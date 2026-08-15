"""L1 客观验收 —— 不依赖相机预览, 只验收"中性正确打底"的硬指标:

  1. 灰中性 (分层): 低色度像素 (C*<12) 按亮度分 7 层, 每层 a/b 中位;
     报告各层 max |a|/|b| —— 旧管线"每通道 tone LUT"会在这里暴露亮度分层偏色。
  2. 高光/暗部裁切: >250 / <5 占比 (目标均 <2%)。
  3. 亮度稳定性: 输出中位亮度 (目标 ≈117, 灰点 0.18 的 gamma 值) 的跨照片 std。

用法: python rawlab/tools/verify_l1.py --mode {baseline,engine} --n 60
"""
import argparse
import glob
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rawlab.dcp import load_dcp

DEFAULT_DCP = r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp"
DEFAULT_RAW_DIRS = [r"K:\data\photo\0711\raw", r"K:\data\photo\2026春节"]
BANDS = [(0, 16), (16, 48), (48, 96), (96, 160), (160, 208), (208, 240), (240, 256)]


def l1_metrics(rgb8):
    lab = cv2.cvtColor(rgb8, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
    c = np.sqrt((a - 128) ** 2 + (b - 128) ** 2)
    neutral = c < 12
    bands = {}
    for lo, hi in BANDS:
        m = neutral & (L >= lo) & (L < hi)
        if m.sum() > 200:
            bands[f"{lo}-{hi}"] = {
                "a": round(float(np.median(a[m] - 128)), 1),
                "b": round(float(np.median(b[m] - 128)), 1),
            }
    worst_a = max((abs(v["a"]) for v in bands.values()), default=0.0)
    worst_b = max((abs(v["b"]) for v in bands.values()), default=0.0)
    gray = cv2.cvtColor(rgb8, cv2.COLOR_RGB2GRAY)
    return {
        "luma_med": round(float(np.median(gray)), 1),
        "hi_clip": round(float((gray > 250).mean()) * 100, 2),
        "lo_clip": round(float((gray < 5).mean()) * 100, 2),
        "band_worst_a": worst_a,
        "band_worst_b": worst_b,
        "bands": bands,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="engine", choices=["baseline", "engine"])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--dcp", default=os.environ.get("RAWLAB_DCP", DEFAULT_DCP))
    ap.add_argument("--raw-dir", action="append", default=None, help="RAW 目录, 可多次指定")
    args = ap.parse_args()

    prof = load_dcp(args.dcp)
    if args.mode == "engine":
        from rawlab.engine import build_default_pipeline
        pipe = build_default_pipeline(prof=prof)

    raw_dirs = args.raw_dir
    if not raw_dirs:
        env = os.environ.get("RAWLAB_RAW_DIRS")
        raw_dirs = [d for d in env.split(";") if d] if env else DEFAULT_RAW_DIRS
    files = []
    for d in raw_dirs:
        files.extend(glob.glob(os.path.join(d, "*.NEF")))
    files = sorted(files)[args.start: args.start + args.n]

    rows, t0 = [], time.time()
    for i, f in enumerate(files):
        name = os.path.basename(f)
        try:
            if args.mode == "baseline":
                from rawlab.render import render
                rgb8 = render(f, prof, half_size=True)
            else:
                rgb8 = pipe.run_file(f, half_size=True)
            m = l1_metrics(rgb8)
            m["file"] = name
            rows.append(m)
            print(f"  [{i+1:3d}/{len(files)}] {name}: L={m['luma_med']:5.1f} "
                  f"hi={m['hi_clip']:4.2f}% lo={m['lo_clip']:4.2f}% "
                  f"wa={m['band_worst_a']:4.1f} wb={m['band_worst_b']:4.1f}")
        except Exception as e:
            print(f"  [{i+1:3d}] {name}: ERROR {e}")

    print(f"\n=== L1 {args.mode} n={len(rows)} ({time.time()-t0:.0f}s) ===")
    if not rows:
        return
    lm = np.array([r["luma_med"] for r in rows])
    hi = np.array([r["hi_clip"] for r in rows])
    lo = np.array([r["lo_clip"] for r in rows])
    wa = np.array([r["band_worst_a"] for r in rows])
    wb = np.array([r["band_worst_b"] for r in rows])
    print(f"  亮度中位: mean={lm.mean():.1f} std={lm.std():.1f} (目标≈117)")
    print(f"  高光裁切%: mean={hi.mean():.2f} p90={np.percentile(hi,90):.2f} (目标<2)")
    print(f"  暗部裁切%: mean={lo.mean():.2f} p90={np.percentile(lo,90):.2f} (目标<2)")
    print(f"  分层中性 worst_a: mean={wa.mean():.1f} p90={np.percentile(wa,90):.1f} (目标<3)")
    print(f"  分层中性 worst_b: mean={wb.mean():.1f} p90={np.percentile(wb,90):.1f} (目标<3)")

    import json
    out = Path(__file__).resolve().parent.parent / "out" / "engine_verify" / f"l1_{args.mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report -> {out}")


if __name__ == "__main__":
    main()
