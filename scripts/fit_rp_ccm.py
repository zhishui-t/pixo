"""RP-CCM 语料拟合 (弱监督) —— pixo DCP 渲染 → 相机 JPEG 参考 (设计 §4 / M-O3)。

弱监督参考对齐 scripts/calibrate_to_camera.py 既有基础:
  - 语料: exports/auto/full_scan/full_scan_*.json 的 photos[].raw (--raw 可显式指定);
  - 参考: rawpy 抽 RAW 内嵌相机 JPEG 缩略图 (相机自身 look, 非 ColorChecker 真值,
    故称"弱监督"), 缩放到渲染尺寸 INTER_AREA (gamma 域, 与既有脚本一致);
  - 基座: Renderer.render_preview_full 中性参数渲染 (exposure mode 0.0 /
    wb trim [1,1,1], 同 calibrate_to_camera 的 base 渲染口径)。

拟合目标: 线性 sRGB 域上 pixo 渲染 (src) → 相机参考 (dst) 的根多项式映射
(core.rp_ccm.fit_rp_ccm, 纯 numpy; 根多项式保曝光不变, 每张照片的 EV 差异
不污染系数)。弱监督噪声 (视差/遮挡/JPEG 压缩) 用残差分位裁剪 (--robust,
默认开) 两轮再拟合抑制。

产出: configs/color/rp_ccm_<camera>.json (camera 取自 pixo.meta make/model)。
本脚本只产系数与报告, 不切运行时默认 (设计 §4 纪律)。

用法:
  python scripts/fit_rp_ccm.py                       # 全语料
  python scripts/fit_rp_ccm.py --limit 3 --degree 2  # 前 3 张, 6 项根多项式
  python scripts/fit_rp_ccm.py --raw K:/path/a.NEF   # 显式指定 RAW
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rawpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.render.api import Renderer
from pixo.render.core.rp_ccm import RPCCM, fit_rp_ccm, rp_features, save_rp_ccm
from pixo.render.core.tone import srgb_decode

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"

# 线性域有效样本窗: 避开相机 JPEG 高光裁剪与深阴影噪声 (任一侧出窗即弃样)
SAMPLE_LIN_LO = 0.01
SAMPLE_LIN_HI = 0.90


# ---------------------------------------------------------------------------
# 语料 / 相机 / 参考图 (eval_rp_ccm_ab.py 复用)
# ---------------------------------------------------------------------------

def json_load(path: str) -> dict:
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def iter_corpus(corpus_dir: str, raws: list[str] | None,
                limit: int) -> list[tuple[str, str]]:
    """语料 → 去重 (photo_id, raw_path) 列表 (对齐 calibrate_to_camera 口径)。"""
    raw_map: dict[str, str] = {}
    if raws:
        for p in raws:
            raw_map[Path(p).stem] = p
    else:
        for f in sorted(glob.glob(str(Path(corpus_dir) / "full_scan_*.json"))):
            d = json_load(f)
            for p in d.get("photos", []):
                raw_map.setdefault(p["photo_id"], p["raw"])
    items = list(raw_map.items())
    if limit:
        items = items[:limit]
    return items


def camera_slug(raw_path: str | Path) -> str:
    """pixo.meta make/model → 文件安全标识 (如 nikon_z_5); 取不到回退 unknown。"""
    try:
        from pixo.meta import extract as meta_extract
        cam = meta_extract(raw_path).get("camera") or {}
        name = cam.get("model") or cam.get("make") or ""
    except Exception:
        name = ""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return slug or "unknown"


def camera_thumb_rgb(raw_path: str | Path) -> np.ndarray:
    """RAW 内嵌缩略图 → RGB gamma float64 [0,1] (JPEG 解码 / 位图直取)。"""
    with rawpy.imread(str(raw_path)) as rr:
        th = rr.extract_thumb()
        if th.format == rawpy.ThumbFormat.JPEG:
            bgr = cv2.imdecode(np.frombuffer(th.data, np.uint8), cv2.IMREAD_COLOR)
            img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:
            img = np.asarray(th.data)[..., ::-1]  # 位图缩略图为 BGR 布线
    return img.astype(np.float64) / 255.0


# 相机缩略图存储方向 → 传感器方向的逆显示旋转表 (np.rot90 第二参数, 1/4 圈)。
# 实证 (Nikon Z5_2 语料, 2026-08): orientation=8 照片 thumb 顺时针 90° 后与
# pixo 渲染亮度相关 0.970 (as-is 仅 -0.06); orientation=6 逆时针 90° 后 0.884
# (as-is 0.14); 横拍 (orientation=1) as-is 即对齐 (0.96+)。注意 pixo
# render_preview_full 对竖拍 RAW 输出传感器尺寸横幅画布、内容为显示取向,
# 故此表恢复的是"与 pixo 渲染画布同构"的朝向, 尺寸差异由调用方 resize 兜底。
_THUMB_UNDO_ROT = {3: 2, 6: 1, 8: -1}


def align_thumb_to_sensor(thumb: np.ndarray, orientation: int,
                          thumb_rot: str = "auto") -> tuple[np.ndarray, str]:
    """相机缩略图 → 与 pixo 渲染画布同构的朝向。

    thumb_rot="auto": 按 _THUMB_UNDO_ROT 依 EXIF orientation 逆旋转 (本语料
    Nikon 实证规则); "off": 原样返回 (供未预旋转缩略图的机型/排查使用)。
    返回 (图, 处理说明)。
    """
    if thumb_rot == "auto":
        k = _THUMB_UNDO_ROT.get(int(orientation), 0)
        if k:
            return np.ascontiguousarray(np.rot90(thumb, k)), f"rot90×{k}"
    return thumb, "as_is"


def aligned_pair(renderer: Renderer, raw_path: str | Path, preview_edge: int,
                 thumb_rot: str = "auto") -> tuple[np.ndarray, np.ndarray] | None:
    """(pixo 中性渲染 gamma [0,1], 相机参考 gamma [0,1]) 同尺寸对; 失败 None。"""
    try:
        from pixo.meta import extract as meta_extract
        orientation = int(meta_extract(raw_path)["capture"].get("orientation") or 1)
    except Exception:
        orientation = 1
    base = renderer.render_preview_full(
        raw_path, long_edge=preview_edge,
        params={"exposure": {"mode": 0.0}, "whitebalance": {"trim": [1, 1, 1]}})
    if base.dtype == np.uint8:
        base = base.astype(np.float64) / 255.0
    else:
        base = np.asarray(base, dtype=np.float64)
    ref = camera_thumb_rgb(raw_path)
    ref, _note = align_thumb_to_sensor(ref, orientation, thumb_rot)
    if ref.shape[:2] != base.shape[:2]:
        ref = cv2.resize(ref, (base.shape[1], base.shape[0]),
                         interpolation=cv2.INTER_AREA)
    if ref.shape[:2] != base.shape[:2]:
        return None
    return base, ref


def sample_linear_pairs(base: np.ndarray, ref: np.ndarray,
                        stride: int) -> tuple[np.ndarray, np.ndarray]:
    """gamma 对 → 线性域有效样本 (src, dst) (网格抽样 + 裁剪区剔除)。"""
    b = srgb_decode(np.ascontiguousarray(base[::stride, ::stride]).astype(np.float32))
    r = srgb_decode(np.ascontiguousarray(ref[::stride, ::stride]).astype(np.float32))
    bf, rf = b.reshape(-1, 3).astype(np.float64), r.reshape(-1, 3).astype(np.float64)
    ok = np.all((bf >= SAMPLE_LIN_LO) & (bf <= SAMPLE_LIN_HI), axis=1) & \
         np.all((rf >= SAMPLE_LIN_LO) & (rf <= SAMPLE_LIN_HI), axis=1)
    return bf[ok], rf[ok]


# ---------------------------------------------------------------------------
# 拟合主流程
# ---------------------------------------------------------------------------

def robust_fit(src: np.ndarray, dst: np.ndarray, degree: int,
               robust: bool) -> tuple[RPCCM, dict]:
    """极端离群裁剪 (残差 >99 分位, 1 轮) 抑制错位/遮挡样本后最小二乘拟合。

    注意: 裁剪分位取 99% 而非 95% —— 残差最大的样本往往是高饱和色 (相机
    JPEG 与 pixo 渲染分歧最大处), 过激裁剪会抽掉色彩多样性, 使样本整体
    更中性化、√项与线性项共线加剧 (实测系数幅值 ±23 → ±62), 拟合反而病态。
    """
    coeff = fit_rp_ccm(src, dst, degree=degree)
    stats = {"outliers_trimmed": 0, "rounds": 0}
    if not robust:
        return coeff, stats
    pred = rp_features(src, degree) @ coeff.matrix.T
    resid = np.linalg.norm(pred - dst, axis=1)
    keep = resid <= np.quantile(resid, 0.99)
    if not bool(keep.all()) and int(keep.sum()) > degree * 8:
        stats["outliers_trimmed"] = int((~keep).sum())
        stats["rounds"] = 1
        coeff = fit_rp_ccm(src[keep], dst[keep], degree=degree)
    resid = np.linalg.norm(rp_features(src, degree) @ coeff.matrix.T - dst, axis=1)
    stats["residual_median"] = float(np.median(resid))
    stats["residual_p95"] = float(np.quantile(resid, 0.95))
    return coeff, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None, help="显式 RAW (可多次)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--degree", type=int, default=2, choices=(1, 2))
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--preview-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--out-dir", default="configs/color")
    ap.add_argument("--camera", default="", help="覆盖输出文件名中的相机标识")
    ap.add_argument("--thumb-rot", default="auto", choices=("auto", "off"),
                    help="缩略图朝向复原 (auto=按 EXIF 逆旋转, off=原样)")
    ap.add_argument("--no-robust", action="store_true", help="关闭离群裁剪再拟合")
    args = ap.parse_args()

    items = iter_corpus(args.corpus, args.raw, args.limit)
    if not items:
        print("语料为空: 检查 --corpus/--raw", file=sys.stderr)
        sys.exit(2)
    renderer = Renderer(args.dcp)

    by_camera: dict[str, dict[str, list]] = {}
    errors: list[str] = []
    t0 = time.time()
    for i, (pid, raw) in enumerate(items, 1):
        try:
            pair = aligned_pair(renderer, raw, args.preview_edge,
                                thumb_rot=args.thumb_rot)
            if pair is None:
                raise RuntimeError("对齐失败")
            src, dst = sample_linear_pairs(*pair, stride=args.stride)
            if src.shape[0] < 1000:
                raise RuntimeError(f"有效样本过少 {src.shape[0]}")
            # 逐照片标量曝光增益对齐 (口径同 calibrate_to_camera 的均值 EV):
            # 中性渲染与相机 JPEG 差 ~2EV 且逐张不同, 不对齐会让矩阵被迫吸收
            # 逐张增益污染色度系数; 根多项式曝光不变 → src×k 仅等比缩放特征,
            # 矩阵只学"像素曝光下的色度校正", EV 由曝光阶段管 (正交关注点)。
            gain = float(dst.mean() / max(src.mean(), 1e-9))
            src = src * gain
            slug = args.camera or camera_slug(raw)
            acc = by_camera.setdefault(slug, {"src": [], "dst": [], "photos": [],
                                              "gains": []})
            acc["src"].append(src)
            acc["dst"].append(dst)
            acc["photos"].append(pid)
            acc["gains"].append(gain)
            print(f"[{i}/{len(items)}] {pid} camera={slug} "
                  f"samples={src.shape[0]} ev={np.log2(gain):+.2f}", flush=True)
        except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
            errors.append(f"{pid}: {exc}")
            print(f"[{i}/{len(items)}] {pid} 跳过: {exc}", flush=True)

    if not by_camera:
        print("所有照片均失败, 无拟合产出", file=sys.stderr)
        sys.exit(1)

    for slug, acc in by_camera.items():
        src = np.vstack(acc["src"])
        dst = np.vstack(acc["dst"])
        coeff, stats = robust_fit(src, dst, args.degree, robust=not args.no_robust)
        gains = acc["gains"]
        coeff = RPCCM(matrix=coeff.matrix, degree=coeff.degree, camera=slug,
                      source=f"fit_rp_ccm.py dcp={Path(args.dcp).name}",
                      meta={"n_samples": int(src.shape[0]),
                            "n_photos": len(acc["photos"]),
                            "photos": acc["photos"],
                            "exposure_gain_ev": [round(float(np.log2(g)), 3)
                                                 for g in gains],
                            "stride": args.stride,
                            "preview_edge": args.preview_edge,
                            "thumb_rot": args.thumb_rot,
                            "robust": not args.no_robust,
                            "fit_stats": stats,
                            "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
        out = save_rp_ccm(coeff, Path(args.out_dir) / f"rp_ccm_{slug}.json")
        rs = stats.get("residual_median", float("nan"))
        print(f"== {slug}: n={coeff.meta['n_samples']} "
              f"photos={coeff.meta['n_photos']} "
              f"trimmed={stats['outliers_trimmed']} "
              f"resid_median={rs:.4f} -> {out}", flush=True)

    if errors:
        print(f"跳过 {len(errors)} 张 (详见上方日志)", flush=True)
    print(f"DONE {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
