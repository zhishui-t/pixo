"""F01 批量度量台架 v2: 引擎全链 vs 相机内嵌预览.

v2 相对 v1 的三处修正 (均由 2026-09-14 实测驱动)
------------------------------------------------
1. **朝向**: v1 沿用 EXIF 教科书表 {6:CW, 8:CCW}, 实测为错。
   NEF 内嵌缩略图已是"显示态", 而 render_preview_full 输出传感器画布,
   故须把缩略图逆旋到传感器态。正确表见 scripts/fit_rp_ccm.py:100-106
   ({3:2, 6:1, 8:-1} 的 np.rot90 k), 本台架独立四方 ECC 测试复现一致。
   同时记录 C_bug = 按旧(错)朝向算出的逐像素 ΔE, 用于量化历史数字的偏差。
2. **垃圾样本**: 语料含 AppleDouble 文件 ._XXXX.NEF (2026春节 50%、厦门 27.9%,
   全语料 1188 个), rawpy 打不开, 必须剔除。
3. **对齐门**: 新增 ECC 仿射对齐, 得相关系数 cc; C_al = 对齐后逐像素 ΔE。
   表定旋转 cc 仍不达标时, 自动尝试同长宽比类的其它旋转并记录 fallback。

三口径 (ΔE76):
    A     整图 mean Lab        —— 纯系统色偏, 不受错位影响
    B     16x16 分块 mean Lab   —— 对亚块级错位鲁棒
    C_raw 逐像素(表定朝向)      —— 现有脚本口径
    C_al  逐像素(ECC 对齐后)    —— 剥掉错位
    C_bug 逐像素(旧错误朝向)    —— 只对 6/8 有意义, 量化历史偏差

用法
----
  python .artifacts/f01_batch.py --n 1000
  python .artifacts/f01_batch.py --n 0            # 全量 4053 张
  python .artifacts/f01_batch.py --n 300 --sessions 0711,西安
  python .artifacts/f01_batch.py --n 1000 --no-cache
产物
----
  .artifacts/f01_batch_results.json / .csv
  .artifacts/f01_batch_summary.md
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import rawpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CORPUS = Path("K:/data/photo")
CACHE = ROOT / ".artifacts/f01_cache"
OUT_JSON = ROOT / ".artifacts/f01_batch_results.json"
OUT_CSV = ROOT / ".artifacts/f01_batch_results.csv"
OUT_MD = ROOT / ".artifacts/f01_batch_summary.md"

PREVIEW_LONG_EDGE = 1024
COMMON_EDGE = 768         # 度量统一到该长边, 先中心裁到公共长宽比
GRID = 16
ALIGN_EDGE = 384
CC_OK = 0.85
CC_WEAK = 0.60

# 相机缩略图(显示态) → 传感器画布 的逆旋表, np.rot90 的 k 参数。
# 出处: scripts/fit_rp_ccm.py:100-106 (2026-08 实证), 2026-09-14 四方 ECC 复核一致。
UNDO_ROT = {3: 2, 6: 1, 8: -1}
# 旧 scripts/ab_vs_camera_thumb.py 用的 (错的) EXIF 教科书表
BUGGY_ROT = {3: 2, 6: -1, 8: 1}


# ---------------------------------------------------------------- 图像工具
def read_thumb(p: Path) -> np.ndarray:
    """RAW 内嵌 JPEG 预览 (= 相机屏幕所见), 原样不转。"""
    with rawpy.imread(str(p)) as raw:
        t = raw.extract_thumb()
        if t.format == rawpy.ThumbFormat.JPEG:
            bgr = cv2.imdecode(np.frombuffer(t.data, np.uint8), cv2.IMREAD_COLOR)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return np.asarray(t.data)[..., :3].copy()


def rot_k(img: np.ndarray, k: int) -> np.ndarray:
    return img if not k else np.ascontiguousarray(np.rot90(img, k))


def lab_f32(img_u8: np.ndarray) -> np.ndarray:
    l = cv2.cvtColor(img_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    l[..., 0] *= 100.0 / 255.0
    l[..., 1] -= 128.0
    l[..., 2] -= 128.0
    return l


def de76(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.linalg.norm(x - y, axis=-1).mean())


def block_means(img: np.ndarray, g: int = GRID) -> np.ndarray:
    h, w = img.shape[:2]
    bh, bw = h // g, w // g
    if bh < 2 or bw < 2:
        return img.reshape(-1, 3)[:0]
    return img[:bh * g, :bw * g].reshape(g, bh, g, bw, 3).mean(axis=(1, 3)).reshape(-1, 3)


def to_common(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """公共长宽比中心裁切 → 统一到 COMMON_EDGE 长边。"""
    ar = 0.5 * (a.shape[1] / a.shape[0] + b.shape[1] / b.shape[0])
    out = []
    for im in (a, b):
        h, w = im.shape[:2]
        if w / h > ar:
            nw = int(round(h * ar))
            x = (w - nw) // 2
            im = im[:, x:x + nw]
        else:
            nh = int(round(w / ar))
            y = (h - nh) // 2
            im = im[y:y + nh, :]
        s = COMMON_EDGE / max(im.shape[:2])
        out.append(cv2.resize(im, (max(8, int(round(im.shape[1] * s))),
                                   max(8, int(round(im.shape[0] * s)))),
                              interpolation=cv2.INTER_AREA))
    h = min(out[0].shape[0], out[1].shape[0])
    w = min(out[0].shape[1], out[1].shape[1])
    return out[0][:h, :w], out[1][:h, :w]


def gray_small(img: np.ndarray, edge: int = ALIGN_EDGE) -> np.ndarray:
    s = edge / max(img.shape[:2])
    g = cv2.resize(img, (max(8, int(round(img.shape[1] * s))),
                         max(8, int(round(img.shape[0] * s)))),
                   interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(g, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0


def ecc_cc(a: np.ndarray, b: np.ndarray) -> tuple[float, np.ndarray | None]:
    """a 相对 b 的仿射对齐相关系数 + warp 矩阵 (均在 b 的坐标系)。"""
    ga, gb = gray_small(a), gray_small(b)
    h = min(ga.shape[0], gb.shape[0])
    w = min(ga.shape[1], gb.shape[1])
    ga, gb = ga[:h, :w], gb[:h, :w]
    warp = np.eye(2, 3, dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
    try:
        cc, warp = cv2.findTransformECC(gb, ga, warp, cv2.MOTION_AFFINE, crit, None, 5)
        return float(cc), warp
    except cv2.error:
        return float("nan"), None


def dhash64(img: np.ndarray) -> str:
    g = cv2.cvtColor(cv2.resize(img, (9, 8), interpolation=cv2.INTER_AREA),
                     cv2.COLOR_RGB2GRAY)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    v = 0
    for x in bits:
        v = (v << 1) | int(x)
    return f"{v:016x}"


# ---------------------------------------------------------------- 单张度量
def compute_metrics(ours: np.ndarray, thumb: np.ndarray, orientation: int) -> dict:
    k = UNDO_ROT.get(int(orientation), 0)
    ref = rot_k(thumb, k)
    a, b = to_common(ours, ref)
    la, lb = lab_f32(a), lab_f32(b)

    dv = la.reshape(-1, 3).mean(axis=0) - lb.reshape(-1, 3).mean(axis=0)
    A = float(np.linalg.norm(dv))
    B = de76(block_means(la), block_means(lb))
    C_raw = de76(la, lb)
    dv_bug = dv_bug_val = None
    rec: dict = {
        "orient": int(orientation), "rot_k": k,
        "A": round(A, 3), "B": round(B, 3), "C_raw": round(C_raw, 3),
        "dL": round(float(dv[0]), 3), "da": round(float(dv[1]), 3),
        "db": round(float(dv[2]), 3),
    }

    # 旧(错)朝向下的逐像素 ΔE —— 量化历史偏差, 只对 6/8 有别
    if int(orientation) in BUGGY_ROT and BUGGY_ROT[int(orientation)] != k:
        kb = BUGGY_ROT[int(orientation)]
        ref_b = rot_k(thumb, kb)
        a_b, b_b = to_common(ours, ref_b)
        rec["C_bug"] = round(de76(lab_f32(a_b), lab_f32(b_b)), 3)
    else:
        rec["C_bug"] = rec["C_raw"]

    # ECC 对齐 + 门
    cc, warp = ecc_cc(a, b)
    rec["cc"] = round(cc, 4) if cc == cc else None
    rec["orient_fallback"] = False
    if not (cc == cc) or cc < CC_WEAK:
        # 兜底: 同长宽比类的其它逆旋 (0/-1/1/2 中形状匹配者) 取最大 cc
        best = (cc, warp, k)
        for k2 in (-1, 1, 2):
            if k2 == k:
                continue
            ref2 = rot_k(thumb, k2)
            if abs(ref2.shape[0] / ref2.shape[1] - ours.shape[0] / ours.shape[1]) > 0.05:
                continue
            a2, b2 = to_common(ours, ref2)
            c2, w2 = ecc_cc(a2, b2)
            if c2 == c2 and (best[0] != best[0] or c2 > best[0]):
                best = (c2, w2, k2)
        if best[2] != k:
            cc, warp = best[0], best[1]
            k = best[2]
            ref = rot_k(thumb, k)
            a, b = to_common(ours, ref)
            la, lb = lab_f32(a), lab_f32(b)
            rec.update({"rot_k": k, "orient_fallback": True,
                        "cc": round(cc, 4) if cc == cc else None})

    rec["align"] = ("ok" if cc == cc and cc >= CC_OK
                    else "weak" if cc == cc and cc >= CC_WEAK else "fail")
    if warp is not None:
        sc = COMMON_EDGE / max(ALIGN_EDGE, 1)
        wf = warp.copy()
        wf[0, 2] *= a.shape[1] / max(int(gray_small(a).shape[1]), 1)
        wf[1, 2] *= a.shape[0] / max(int(gray_small(a).shape[0]), 1)
        del sc
        aligned = cv2.warpAffine(a, wf, (b.shape[1], b.shape[0]),
                                 flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        rec["C_al"] = round(de76(lab_f32(aligned), lb), 3)
    else:
        rec["C_al"] = None

    # 端点 / 裁切 (不受对齐影响)
    def endpoint(img: np.ndarray):
        y = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        return (float(np.percentile(y, 0.5)), float(np.percentile(y, 99.5)),
                float((img.min(axis=2) <= 5).mean()) * 100.0,
                float((img.max(axis=2) >= 250).mean()) * 100.0)

    o_lo, o_hi, o_cl, o_ch = endpoint(ours)
    r_lo, r_hi, r_cl, r_ch = endpoint(ref)
    rec.update({
        "our_p05": round(o_lo, 2), "our_p995": round(o_hi, 2),
        "cam_p05": round(r_lo, 2), "cam_p995": round(r_hi, 2),
        "our_clip_lo": round(o_cl, 3), "our_clip_hi": round(o_ch, 3),
        "cam_clip_lo": round(r_cl, 3), "cam_clip_hi": round(r_ch, 3),
        "ar": round(ref.shape[1] / max(ref.shape[0], 1), 4),
    })
    rec["dhash"] = dhash64(ref)
    return rec


# ---------------------------------------------------------------- 取样
def discover(sessions: list[str] | None) -> dict[tuple[str, str], list[Path]]:
    groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
    if not CORPUS.exists():
        raise SystemExit(f"语料根不存在: {CORPUS}")
    for sess_dir in sorted(CORPUS.iterdir()):
        if not sess_dir.is_dir() or (sessions and sess_dir.name not in sessions):
            continue
        for p in sess_dir.rglob("*"):
            if p.is_file() and p.suffix.upper() == ".NEF" and not p.name.startswith("._"):
                groups[(sess_dir.name, p.parent.name)].append(p)
    for k in groups:
        groups[k].sort()
    return groups


def sample(groups: dict, n: int, seed: int = 20260914) -> list[tuple[str, str, Path]]:
    rng = random.Random(seed)
    total = sum(len(v) for v in groups.values())
    if n <= 0 or n >= total:
        return [(s, g, p) for (s, g), v in groups.items() for p in v]
    out: list[tuple[str, str, Path]] = []
    for (s, g), v in sorted(groups.items()):
        quota = min(max(1, int(round(len(v) / total * n))), len(v))
        out += [(s, g, p) for p in rng.sample(v, quota)]
    rng.shuffle(out)
    out = out[:n]
    out.sort(key=lambda t: (t[0], t[1], t[2].name))
    return out


# ---------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000, help="取样张数, 0=全量")
    ap.add_argument("--sessions", type=str, default="")
    ap.add_argument("--seed", type=int, default=20260914)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    sessions = [s.strip() for s in args.sessions.split(",") if s.strip()] or None
    groups = discover(sessions)
    total = sum(len(v) for v in groups.values())
    picked = sample(groups, args.n, args.seed)

    print(f"语料(剔除 AppleDouble): {len(groups)} 个子目录 / {total} 张 NEF, 本次取 {len(picked)}")
    for (s, g), v in sorted(groups.items()):
        print(f"    {s}/{g}: {len(v)}")
    CACHE.mkdir(parents=True, exist_ok=True)

    from pixo.render.api import Renderer
    from pixo.meta import extract as meta_extract
    dcp = sorted((ROOT / "resources/dcp").glob("*.dcp"))[0]
    r = Renderer(dcp)
    print(f"DCP: {dcp.name}\n", flush=True)

    rows: list[dict] = []
    t0 = time.time()
    for i, (sess, grp, p) in enumerate(picked, 1):
        key = hashlib.sha1(str(p).encode()).hexdigest()[:16]
        cf = CACHE / f"{key}.json"
        rec = None
        if cf.exists() and not args.no_cache:
            try:
                rec = json.loads(cf.read_text(encoding="utf-8"))
            except Exception:
                rec = None
        if rec is None:
            rec = {"path": str(p), "session": sess, "group": grp, "name": p.name}
            try:
                orientation = int(meta_extract(p)["capture"].get("orientation") or 1)
                thumb = read_thumb(p)
                ours = r.render_preview_full(p, long_edge=PREVIEW_LONG_EDGE)
                rec.update(compute_metrics(ours, thumb, orientation))
            except Exception as e:  # noqa: BLE001
                rec["err"] = f"{type(e).__name__}: {e}"
                rec["tb"] = traceback.format_exc()[-600:]
            cf.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        rows.append(rec)
        if i % 25 == 0 or i == len(picked):
            el = time.time() - t0
            print(f"  [{i}/{len(picked)}] {el:.0f}s 均 {el / i:.2f}s/张 最近 {rec['name']}",
                  flush=True)

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["session", "group", "name", "orient", "rot_k", "orient_fallback", "align",
            "cc", "A", "B", "C_raw", "C_al", "C_bug", "dL", "da", "db",
            "our_p05", "cam_p05", "our_p995", "cam_p995",
            "our_clip_lo", "cam_clip_lo", "our_clip_hi", "cam_clip_hi",
            "ar", "dhash", "err", "path"]
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    write_summary(rows)
    ok = [x for x in rows if "err" not in x]
    print(f"\n完成: 有效 {len(ok)} / {len(rows)}  (总耗时 {time.time() - t0:.0f}s)")
    print(f"→ {OUT_JSON.name} / {OUT_CSV.name} / {OUT_MD.name}")


def med(rows, key):
    v = [x[key] for x in rows if isinstance(x.get(key), (int, float))]
    return float(np.median(v)) if v else float("nan")


def scene_clusters(rows: list[dict], ham_max: int = 10) -> int:
    """按 thumb dHash 汉明距离去近重复 (连拍), 返回独立场景数。"""
    seen: list[int] = []
    n = 0
    for x in sorted(rows, key=lambda r: r.get("name", "")):
        h = x.get("dhash")
        if not isinstance(h, str):
            continue
        v = int(h, 16)
        if any(bin(v ^ s).count("1") <= ham_max for s in seen):
            continue
        seen.append(v)
        n += 1
    return n


def write_summary(rows: list[dict]) -> None:
    ok = [x for x in rows if "err" not in x]
    bad = [x for x in rows if "err" in x]
    if not ok:
        OUT_MD.write_text("# F01 批量度量报告\n\n无有效样本\n", encoding="utf-8")
        return
    by_align: dict[str, list] = defaultdict(list)
    for x in ok:
        by_align[x["align"]].append(x)
    by_sess: dict[str, list] = defaultdict(list)
    for x in ok:
        by_sess[x["session"]].append(x)
    portrait = [x for x in ok if x["orient"] in (6, 8)]
    n_scene = scene_clusters(ok)

    L = ["# F01 批量度量报告 (引擎 vs 相机预览)\n",
         f"- 样本: **{len(rows)}** 张, 有效 {len(ok)}, 失败 {len(bad)}",
         f"- 独立场景 (thumb dHash 去连拍, 汉明<=10): **{n_scene}**",
         f"- 竖拍 (EXIF 6/8): {len(portrait)} ({len(portrait) / len(ok) * 100:.1f}%)",
         f"- 口径: A 整图 / B 16x16 分块 / C_raw 逐像素 / C_al 对齐后 / C_bug 旧错误朝向",
         f"- 朝向: UNDO_ROT={UNDO_ROT} (np.rot90 k), 出处 scripts/fit_rp_ccm.py:100-106\n",
         "## 全体 (median)\n", "| 口径 | median | 说明 |", "|---|---:|---|",
         f"| A 整图系统色偏 | {med(ok, 'A'):.2f} | 不受错位影响 |",
         f"| B 分块色偏 | {med(ok, 'B'):.2f} | 对亚块级错位鲁棒 |",
         f"| C_raw 逐像素 (正确朝向) | {med(ok, 'C_raw'):.2f} | 本台架口径 |",
         f"| C_al 对齐后逐像素 | {med(ok, 'C_al'):.2f} | 剥掉错位 |",
         f"| C_bug 逐像素 (旧错误朝向) | {med(ok, 'C_bug'):.2f} | 历史脚本口径 |",
         f"| cc 对齐相关系数 | {med(ok, 'cc'):.3f} | 1=完美对齐 |", ""]

    if portrait:
        L += ["## 朝向错误的代价 (只看竖拍, n=%d)\n" % len(portrait),
              "| 口径 | median |", "|---|---:|",
              f"| C_raw 正确朝向 | {med(portrait, 'C_raw'):.2f} |",
              f"| C_bug 旧错误朝向 | {med(portrait, 'C_bug'):.2f} |",
              f"| 虚高倍数 | {med(portrait, 'C_bug') / max(med(portrait, 'C_raw'), 1e-6):.2f}x |", ""]

    L += ["## 对齐分级\n", "| 分级 | 张数 | 占比 | A | B | C_raw | C_al |", "|---|---:|---:|---:|---:|---:|---:|"]
    for g in ("ok", "weak", "fail"):
        v = by_align.get(g, [])
        if not v:
            continue
        L.append(f"| {g} | {len(v)} | {len(v) / len(ok) * 100:.1f}% | {med(v, 'A'):.2f} | "
                 f"{med(v, 'B'):.2f} | {med(v, 'C_raw'):.2f} | {med(v, 'C_al'):.2f} |")
    L.append("")

    L += ["## 分会话\n", "| 会话 | n | 场景 | A | B | C_raw | C_al | cc | dL | da | db |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in sorted(by_sess, key=lambda k: -len(by_sess[k])):
        v = by_sess[s]
        L.append(f"| {s} | {len(v)} | {scene_clusters(v)} | {med(v, 'A'):.2f} | {med(v, 'B'):.2f} | "
                 f"{med(v, 'C_raw'):.2f} | {med(v, 'C_al'):.2f} | {med(v, 'cc'):.3f} | "
                 f"{med(v, 'dL'):+.2f} | {med(v, 'da'):+.2f} | {med(v, 'db'):+.2f} |")
    L.append("")

    L += ["## 端点 (median)\n", "| 项 | 我们 | 相机 | 差 |", "|---|---:|---:|---:|"]
    for k, label in (("p05", "黑点 p0.5"), ("p995", "白点 p99.5"),
                     ("clip_lo", "暗部裁切 %"), ("clip_hi", "高光裁切 %")):
        o, c = med(ok, f"our_{k}"), med(ok, f"cam_{k}")
        L.append(f"| {label} | {o:.2f} | {c:.2f} | {o - c:+.2f} |")
    L.append("")

    L += ["## 色偏方向一致性\n", "| 分量 | 正号 | 负号 | 判定 |", "|---|---:|---:|---|"]
    for k in ("dL", "da", "db"):
        pos = sum(1 for x in ok if x.get(k, 0) > 0)
        neg = len(ok) - pos
        verdict = ("方向一致(系统偏差)" if max(pos, neg) / len(ok) > 0.8
                   else "方向混杂(区域性偏差)")
        L.append(f"| {k} | {pos} | {neg} | {verdict} |")
    L.append("")

    if bad:
        L += ["## 失败样本 (前 30)\n", "```"]
        for x in bad[:30]:
            L.append(f"{x['name']}  {x.get('err', '')}")
        L += ["```", f"\n失败合计 {len(bad)} 张。"]

    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
