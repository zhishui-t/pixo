"""dng_stage3_ablation —— 多照片 DNG SDK 线性渲染逐级消融 (Stage3 输入对齐)。

级别:
  matrix: 只有矩阵/白平衡 (cs_matrix_only.dcp, 无 LookTable/ToneCurve)
  full:   Adobe Camera Standard v2 (矩阵 + LookTable + ProfileToneCurve)

每个级别输出两个残差:
  exact : tools/dng_stage3_replicate.py (DNG SDK dump 矩阵, 纯逐级复刻)
  engine: tools/dng_linear_probe.py --stage3-raw (用我们引擎 color/huesat/tone)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PY = sys.executable
OUT = Path(r"K:\dsh-share\dng_verify\ablation")
OUT.mkdir(parents=True, exist_ok=True)

ADOBE_DCP = r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard v2.dcp"
MATRIX_DCP = r"K:\dsh-share\dng_verify\cs_matrix_only.dcp"
PHOTOS = [
    ("5236_fresh", r"K:\dsh-share\dng_verify\DSC_5236_fresh.dng"),
    ("5607", r"K:\dsh-share\dng_verify\DSC_5607.dng"),
    ("5603", r"K:\dsh-share\dng_verify\DSC_5603.dng"),
    ("0364", r"K:\dsh-share\dng_verify\DSC_0364.dng"),
    ("0479", r"K:\dsh-share\dng_verify\DSC_0479.dng"),
]
LEVELS = [("matrix", MATRIX_DCP), ("full", ADOBE_DCP)]


def run(args, timeout=900):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def scaled_mae(text):
    m = re.search(r"scaled mean abs ([0-9.eE+-]+)", text)
    if m:
        return float(m.group(1))
    tail = text.split("scaled:", 1)
    if len(tail) == 2:
        m = re.search(r"'mae': ([0-9.eE+-]+)", tail[1])
        if m:
            return float(m.group(1))
    return None


def main():
    print(f"{'photo':12s} {'level':7s} {'exact_mae':>11s} {'engine_mae':>12s}")
    for stem, dng in PHOTOS:
        for level, dcp in LEVELS:
            stage_raw = OUT / f"{stem}_{level}.stage3.raw"
            ref = OUT / f"{stem}_{level}.ref_linear.tif"
            tone = OUT / f"{stem}_{level}.tone.table"
            log = OUT / f"{stem}_{level}.engine.log"
            # replicate 工具生成 engine ref/log/tone/stage3, 并给出 exact 残差
            rc, so, se = run([
                PY, str(ROOT / "rawlab/tools/dng_stage3_replicate.py"),
                "--dng", dng, "--dcp", dcp,
                "--out-dir", str(OUT), "--stem", f"{stem}_{level}"])
            if rc:
                print(stem, level, "REPLICATE_FAIL", se[-400:])
                continue
            exact = scaled_mae(so)
            # 用我们引擎函数 + 同一 Stage3 输入
            rc, so, se = run([
                PY, str(ROOT / "rawlab/tools/dng_linear_probe.py"),
                "--dng", dng, "--dcp", dcp,
                "--ref", str(ref),
                "--stage3-raw", str(stage_raw),
                "--engine-log", str(log),
                "--tone-table", str(tone)])
            if rc:
                print(stem, level, "ENGINE_FAIL", se[-400:])
                continue
            eng = scaled_mae(so)
            print(f"{stem:12s} {level:7s} {exact or float('nan'):11.3e} {eng or float('nan'):12.3e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
