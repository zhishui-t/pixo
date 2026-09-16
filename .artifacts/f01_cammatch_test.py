"""F01 附加实验: 现有"对齐相机"校准路径 (render_camera_matched) 的天花板.

问: 引擎已内置一条 per-photo 迭代求解 (曝光 EV + 白平衡 trim) 使输出贴近相机预览的路径
    (src/pixo/render/api.py:238)。它能消掉 F01 量出来的系统偏色吗?

若不能 -> 说明残差不是「一个全局 WB/曝光错误」, 而是 DCP 矩阵/曲线级的表达力不足,
          必须走矩阵拟合或分区校正, 而非调 trim。

产出: 同一批样本下 默认渲染 vs camera_matched 的配对 A/B/C 对照。
用法: python .artifacts/f01_cammatch_test.py --n 48
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / ".artifacts"))

from f01_batch import (  # noqa: E402
    OUT_JSON, discover, read_thumb, rot_k, sample, to_common, lab_f32,
    de76, block_means, UNDO_ROT,
)

OUT = ROOT / ".artifacts/f01_cammatch_report.md"
PREVIEW_EDGE = 768


def metrics(ours: np.ndarray, thumb: np.ndarray, k: int) -> dict:
    ref = rot_k(thumb, k)
    a, b = to_common(ours, ref)
    la, lb = lab_f32(a), lab_f32(b)
    dv = la.reshape(-1, 3).mean(axis=0) - lb.reshape(-1, 3).mean(axis=0)
    return {
        "A": float(np.linalg.norm(dv)),
        "B": de76(block_means(la), block_means(lb)),
        "C": de76(la, lb),
        "dL": float(dv[0]), "da": float(dv[1]), "db": float(dv[2]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--seed", type=int, default=777)
    args = ap.parse_args()

    groups = discover(None)
    picked = sample(groups, args.n, args.seed)

    from pixo.render.api import Renderer
    from pixo.meta import extract as meta_extract
    dcp = sorted((ROOT / "resources/dcp").glob("*.dcp"))[0]
    r = Renderer(dcp)
    print(f"DCP: {dcp.name}  样本 {len(picked)}", flush=True)

    rows = []
    t0 = time.time()
    for i, (sess, grp, p) in enumerate(picked, 1):
        rec = {"name": p.name, "session": sess, "group": grp}
        try:
            o = int(meta_extract(p)["capture"].get("orientation") or 1)
            k = UNDO_ROT.get(o, 0)
            thumb = read_thumb(p)
            base = r.render_preview_full(p, long_edge=PREVIEW_EDGE)
            rec.update({f"base_{a}": b for a, b in
                        metrics(base, thumb, k).items()})
            # camera_matched 输出为显示态 (api.py:287 已套 EXIF) → 与 thumb 原样比
            cm = r.render_camera_matched(p, long_edge=PREVIEW_EDGE, iters=8)
            rec.update({f"cm_{a}": b for a, b in
                        metrics(cm, thumb, 0).items()})
        except Exception as e:  # noqa: BLE001
            rec["err"] = f"{type(e).__name__}: {e}"
        rows.append(rec)
        if i % 4 == 0 or i == len(picked):
            print(f"  [{i}/{len(picked)}] {time.time() - t0:.0f}s", flush=True)

    ok = [x for x in rows if "err" not in x]
    if not ok:
        raise SystemExit("全部失败")
    md = lambda k: float(np.median([x[k] for x in ok]))  # noqa: E731
    L = ["# F01 附加实验: camera_matched 校准路径的天花板\n",
         f"- 样本 {len(ok)} / {len(rows)} (seed={args.seed})",
         "- 对照: `render_preview_full`(默认) vs `render_camera_matched`(per-photo 迭代解 EV+WB trim)\n",
         "## 配对结果 (median)\n", "| 口径 | 默认 | camera_matched | 变化 |",
         "|---|---:|---:|---:|"]
    for k in ("A", "B", "C"):
        b, c = md(f"base_{k}"), md(f"cm_{k}")
        L.append(f"| {k} | {b:.2f} | {c:.2f} | {c - b:+.2f} "
                 f"({100 * (c - b) / max(b, 1e-6):+.0f}%) |")
    L.append("")
    L.append("| 分量 | 默认 | camera_matched | 变化 |")
    L.append("|---|---:|---:|---:|")
    for k in ("dL", "da", "db"):
        b, c = md(f"base_{k}"), md(f"cm_{k}")
        L.append(f"| {k} | {b:+.2f} | {c:+.2f} | {c - b:+.2f} |")
    L.append("")

    # 逐张胜负
    winA = sum(1 for x in ok if x["cm_A"] < x["base_A"])
    winC = sum(1 for x in ok if x["cm_C"] < x["base_C"])
    L.append(f"- A 变好: {winA}/{len(ok)} ({winA / len(ok) * 100:.0f}%)")
    L.append(f"- C 变好: {winC}/{len(ok)} ({winC / len(ok) * 100:.0f}%)")
    L.append("")
    L.append("## 结论判据\n")
    ba, ca = md("base_A"), md("cm_A")
    if ca < 0.5 * ba:
        L.append(f"→ camera_matched 把 A 从 {ba:.2f} 降到 {ca:.2f}, **偏色主要是一个 WB/曝光级错误**, "
                 "修 trim/EV 即可大幅回收。")
    elif ca < 0.85 * ba:
        L.append(f"→ A 从 {ba:.2f} 降到 {ca:.2f}, **部分可回收**: WB/曝光是主因之一, 但仍有矩阵级残差。")
    else:
        L.append(f"→ A 仅从 {ba:.2f} 到 {ca:.2f}, **WB/曝光不是主因**; 残差在 DCP 矩阵/色调曲线层面, "
                 "需走矩阵拟合或分区校正。")
    L.append("")
    L.append("## 分会话\n")
    L.append("| 会话 | n | base_A | cm_A | base_da | cm_da |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for s in sorted({x["session"] for x in ok}):
        v = [x for x in ok if x["session"] == s]
        L.append(f"| {s} | {len(v)} | {np.median([x['base_A'] for x in v]):.2f} | "
                 f"{np.median([x['cm_A'] for x in v]):.2f} | "
                 f"{np.median([x['base_da'] for x in v]):+.2f} | "
                 f"{np.median([x['cm_da'] for x in v]):+.2f} |")
    L.append("")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    (ROOT / ".artifacts/f01_cammatch_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L))
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
