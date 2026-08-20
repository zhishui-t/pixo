"""拟合 Z5 II 中性轴校正曲线 (每机标定, 30 张拟合 / 10 张留出验证)。

流程:
  1. 拟合集 (--n_fit 张) 渲染 (当前默认管线), 统计每亮度层中性区 a/b 中位。
  2. 校正曲线 = -每层中位 (中位数稳健, 抗个别极端场景)。
  3. 写 engine/z5ii_neutral_trim.json (colorcal 自动加载)。
  4. 验证集: 套曲线渲染, 报告分层 worst |a|/|b| (目标 <3)。
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rawlab.dcp import load_dcp
from rawlab.engine import build_default_pipeline
from rawlab.tools.verify_l1 import l1_metrics, BANDS

DEFAULT_DCP = r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp"
DEFAULT_RAW_DIRS = [r"K:\data\photo\0711\raw", r"K:\data\photo\2026春节"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_fit", type=int, default=30)
    ap.add_argument("--n_val", type=int, default=10)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--dcp", default=os.environ.get("RAWLAB_DCP", DEFAULT_DCP))
    ap.add_argument("--raw-dir", action="append", default=None, help="RAW 目录, 可多次指定")
    args = ap.parse_args()

    prof = load_dcp(args.dcp)
    raw_dirs = args.raw_dir
    if not raw_dirs:
        env = os.environ.get("RAWLAB_RAW_DIRS")
        raw_dirs = [d for d in env.split(";") if d] if env else DEFAULT_RAW_DIRS
    # 各目录各取一半, 保证拟合/验证覆盖不同光照分布
    files = []
    for d in raw_dirs:
        files.extend(sorted(glob.glob(os.path.join(d, "*.NEF"))))
    n_half = (args.n_fit + args.n_val + 1) // 2
    files = files[: n_half * len(raw_dirs)]
    files = files[args.start: args.start + args.n_fit + args.n_val]
    fit_files, val_files = files[: args.n_fit], files[args.n_fit:]

    # 1) 拟合集: **关闭 colorcal** 渲染 (测真实未校正漂移; 若带旧校正拟合
    #    测的是"旧校正后的残差", 新曲线会失效)。逐层中性 → 校正曲线 = -中位。
    from rawlab.engine.core import Pipeline
    from rawlab.engine import stages as _stages  # noqa: F401 触发注册
    pipe = Pipeline(stages=["exposure", "whitebalance", "tone", "stylize", "refine"])
    pipe.prof = prof
    band_a, band_b = [[] for _ in BANDS], [[] for _ in BANDS]
    for i, f in enumerate(fit_files):
        try:
            m = l1_metrics(pipe.run_file(f, half_size=True))
            for j, (lo, hi) in enumerate(BANDS):
                v = m["bands"].get(f"{lo}-{hi}")
                if v:
                    band_a[j].append(v["a"])
                    band_b[j].append(v["b"])
        except Exception as e:
            print(f"  fit skip {os.path.basename(f)}: {e}")
        if (i + 1) % 10 == 0:
            print(f"  fit {i+1}/{len(fit_files)}")

    a_curve = [-float(np.median(v)) if v else 0.0 for v in band_a]
    b_curve = [-float(np.median(v)) if v else 0.0 for v in band_b]
    # 稳健: 曲线值过大 (>8) 说明该层样本少/场景混杂, 收缩 50%
    a_curve = [v if abs(v) <= 8 else v * 0.5 for v in a_curve]
    b_curve = [v if abs(v) <= 8 else v * 0.5 for v in b_curve]
    a_curve = [round(v, 2) for v in a_curve]
    b_curve = [round(v, 2) for v in b_curve]
    print(f"拟合曲线 a: {a_curve}")
    print(f"拟合曲线 b: {b_curve}")

    cal_file = (os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                             "engine", "z5ii_neutral_trim.json")))
    cal = {prof.name: {"neutral_a_curve": a_curve, "neutral_b_curve": b_curve}}
    with open(cal_file, "w", encoding="utf-8") as fh:
        json.dump(cal, fh, ensure_ascii=False, indent=1)
    print(f"标定写入: {cal_file}")

    # 2) 验证集: 用**固定掩码** (校正前的中性像素) 测真实校正位移:
    #    pre = 无 colorcal 管线; post = 默认管线 (标定已加载)。
    pipe2 = build_default_pipeline(prof=prof)
    worst_a, worst_b = [], []
    for i, f in enumerate(val_files):
        try:
            pre = pipe.run_file(f, half_size=True)      # 无 colorcal (未校正)
            post = pipe2.run_file(f, half_size=True)    # 有 colorcal (标定已加载)
            pre_lab = cv2.cvtColor(pre, cv2.COLOR_RGB2LAB).astype(np.float32)
            c0 = np.sqrt((pre_lab[:, :, 1] - 128) ** 2 + (pre_lab[:, :, 2] - 128) ** 2)
            fix_mask = c0 < 12
            post_lab = cv2.cvtColor(post, cv2.COLOR_RGB2LAB).astype(np.float32)
            L, A, B = post_lab[:, :, 0], post_lab[:, :, 1], post_lab[:, :, 2]
            worstA, worstB = 0.0, 0.0
            for lo, hi in BANDS:
                m = fix_mask & (L >= lo) & (L < hi)
                if m.sum() > 200:
                    worstA = max(worstA, abs(float(np.median(A[m] - 128))))
                    worstB = max(worstB, abs(float(np.median(B[m] - 128))))
            worst_a.append(worstA)
            worst_b.append(worstB)
            print(f"  val {os.path.basename(f)}: worst_a={worstA:.1f} worst_b={worstB:.1f}")
        except Exception as e:
            print(f"  val skip {os.path.basename(f)}: {e}")
    if worst_a:
        print(f"\n=== 留出验证(固定掩码) n={len(worst_a)} ===")
        print(f"  worst_a: mean={np.mean(worst_a):.1f} max={np.max(worst_a):.1f} (目标<3)")
        print(f"  worst_b: mean={np.mean(worst_b):.1f} max={np.max(worst_b):.1f} (目标<3)")


if __name__ == "__main__":
    main()
