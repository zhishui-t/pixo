"""M4 Stage3 重采样最小数值验证 (clean-room 回归)。

依据 CLEANROOM_DNG_PLAN.md 交付要求 3:
  从 K:/dsh-share/dng_verify/stage3_5607_noop.raw 生成重采样图,
  与重写前的 dng_resample 基线输出对比, max|Δ| <= 1e-6。

基线参考 (baseline 输出) 保存在
  K:/dsh-share/dng_verify/stage3_5607_noop_refresample.npy
(由重写前的实现生成; 见 CLEANROOM_M4.md)。

用法: python rawlab/tools/verify_stage3_m4.py
"""
from __future__ import annotations

import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from rawlab.tools.dng_stage3_replicate import dng_resample

NOOP_RAW = Path(r"K:/dsh-share/dng_verify/stage3_5607_noop.raw")
REF_NPY = Path(r"K:/dsh-share/dng_verify/stage3_5607_noop_refresample.npy")

SRC_BOUNDS = (1, 1, 673, 1009)   # t,l,b,r (与 5607 engine log 的 srcBounds 一致)
DST_SIZE = (1024, 683)


def load_stage3(path: Path) -> np.ndarray:
    hdr = np.fromfile(path, dtype="<u4", count=2)
    sw, sh = int(hdr[0]), int(hdr[1])
    return np.fromfile(path, dtype="<f4", offset=8,
                       count=sw * sh * 3).reshape(sh, sw, 3)


def main() -> int:
    if not NOOP_RAW.exists() or not REF_NPY.exists():
        print("skipped: baseline 参考 or noop raw 缺失 (见 CLEANROOM_M4.md)")
        return 0
    stage = load_stage3(NOOP_RAW)
    ours = dng_resample(stage, SRC_BOUNDS, DST_SIZE).astype(np.float32)
    ref = np.load(REF_NPY)
    delta = float(np.abs(ours - ref).max())
    ok = delta <= 1e-6
    print(f"M4 resample: max|new - baseline| = {delta:.3e}  (<=1e-6: {ok})")
    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
