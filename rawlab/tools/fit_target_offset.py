"""tools.fit_target_offset —— 每机曝光对齐标定 (基座 = 渲染≈相机预览)。

原理:
  相机预览的曝光策略是场景自适应的 (暗场景保暗、亮场景保护高光), 单个
  常量 target_offset 无法复现 (实测暗场景 d_med +20~+31)。本工具拟合
  **场景自适应表**: (线性中位亮度 log2 → 所需 EV) 分段线性 (5 段),
  写入 engine/target_offset.json 的 cal_table; exposure Stage 查表应用。

  1. 校准子集: exposure.target_offset=0 渲染 (默认管线), 记线性中位 m。
  2. 每张 ev_needed = log2(l_cam / l_mine) (经影调曲线反演, 见文件头)。
  3. 按 m 分 5 个等分桶, 每桶中位 ev → 表结点; 端点外钳位。
  4. --write 写回 JSON: {"cal_table": [[m, ev], ...]}。

用法: python rawlab/tools/fit_target_offset.py --n 40 --write
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rawlab.dcp import load_dcp
from rawlab.engine import build_default_pipeline
from rawlab.tools.batch_iter import camera_preview

DEFAULT_DCP = r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp"
DEFAULT_RAW_DIRS = [r"K:\data\photo\0711\raw", r"K:\data\photo\2026春节"]
_CAL_FILE = Path(__file__).resolve().parent.parent / "engine" / "target_offset.json"


def _srgb_decode(y: float) -> float:
    y = float(np.clip(y, 0.0, 1.0))
    return y / 12.92 if y <= 0.04045 else ((y + 0.055) / 1.055) ** 2.4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--dcp", default=os.environ.get("RAWLAB_DCP", DEFAULT_DCP))
    ap.add_argument("--raw-dir", action="append", default=None)
    ap.add_argument("--write", action="store_true", help="写回 engine/target_offset.json")
    args = ap.parse_args()

    prof = load_dcp(args.dcp)
    # 拟合时禁用场景自适应表加载 (否则渲染带旧表, 测出的是"残差"而非
    # 绝对所需 EV, 形成反馈环)。同时钉 target_offset=0 与 EOTF 基座曲线。
    import rawlab.engine.stages.exposure as _exposure_mod
    _exposure_mod._cached_table = False
    _exposure_mod._cached_offset = None
    pipe = build_default_pipeline(prof=prof, params={
        "tone": {"profile_curve": False}, "exposure": {"target_offset": 0.0}})

    raw_dirs = args.raw_dir
    if not raw_dirs:
        env = os.environ.get("RAWLAB_RAW_DIRS")
        raw_dirs = [d for d in env.split(";") if d] if env else DEFAULT_RAW_DIRS
    files = []
    for d in raw_dirs:
        files.extend(sorted(glob.glob(os.path.join(d, "*.NEF"))))
    files = files[args.start: args.start + args.n]

    pairs = []  # (线性中位 log2, ev_needed)
    for i, f in enumerate(files):
        try:
            mine = pipe.run_file(f, half_size=True)
            cam = camera_preview(f)
            if cam is None:
                continue
            cam_s = cv2.resize(cam, (mine.shape[1], mine.shape[0]),
                               interpolation=cv2.INTER_AREA)
            gm = np.median(cv2.cvtColor(mine, cv2.COLOR_RGB2GRAY).astype(np.float32))
            gc = np.median(cv2.cvtColor(cam_s, cv2.COLOR_RGB2GRAY).astype(np.float32))
            l_mine = max(_srgb_decode(gm / 255.0), 1e-6)
            l_cam = max(_srgb_decode(gc / 255.0), 1e-6)
            ev = float(np.log2(l_cam / l_mine))
            pairs.append((float(np.log2(l_mine)), ev))
            print(f"  [{len(pairs):3d}] {os.path.basename(f)}: m={np.log2(l_mine):+.2f} "
                  f"ev_needed={ev:+.3f} (mine_l={gm:.0f} cam_l={gc:.0f})")
        except Exception as e:
            print(f"  skip {os.path.basename(f)}: {e}")

    if len(pairs) < 10:
        print("样本不足")
        return
    pairs = sorted(pairs, key=lambda p: p[0])
    ms = np.array([p[0] for p in pairs])
    evs = np.array([p[1] for p in pairs])

    # 5 段等分桶 → 结点 (桶中位 m, 桶中位 ev)
    knots_x, knots_y = [], []
    for k in range(5):
        lo = np.percentile(ms, k * 20)
        hi = np.percentile(ms, (k + 1) * 20)
        m = (ms >= lo) & (ms <= hi if k == 4 else ms < hi)
        if not m.any():
            continue
        knots_x.append(round(float(np.median(ms[m])), 4))
        knots_y.append(round(float(np.median(evs[m])), 4))
    # 去重 x (严格递增)
    seen = []
    for x, y in zip(knots_x, knots_y):
        if not seen or x > seen[-1][0] + 1e-6:
            seen.append((x, y))
    knots = seen
    print(f"\n=== 场景自适应表 n={len(pairs)} ===")
    print(f"  cal_table (m→ev): {knots}")
    print(f"  全集中位 ev: {float(np.median(evs)):+.3f} (参考 target_offset)")
    if args.write and len(knots) >= 3:
        _CAL_FILE.write_text(json.dumps({"cal_table": knots}, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        print(f"  已写入 {_CAL_FILE}")
    else:
        print("  (--write 写回 engine/target_offset.json)")


if __name__ == "__main__":
    main()
