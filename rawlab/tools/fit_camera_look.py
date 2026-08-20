"""tools.fit_camera_look —— 每机"相机观感"标定 (基座 = 渲染≈相机预览)。

原理 (相对 fit_neutral_trim 的修正):
  CM 色彩链路是 colorimetric (中性≈0), 但相机预览是尼康"观感" (其中性区
  有特征偏移, 如偏暖)。基座目标 = 复现相机预览, 因此静态校正曲线应拟合
  **我方渲染 vs 相机预览**的中性区偏移 (而非"我方 vs 纯中性")。

  1. 校准子集: 无 colorcal 渲染 (base chain), 与相机预览对齐尺寸。
  2. 在相机预览的中性像素 (C*<12) 上, 按 L 分 7 带统计
     (mine_a - cam_a) / (mine_b - cam_b) 的中位。
  3. 校正曲线 = -跨图中位 (稳健中位)。按 CCT 分 3 桶 (<3500 / 3500-5500 / >5500)
     各拟合 a/b 曲线, 写回 engine/z5ii_neutral_trim.json 新格式:
       {"default": {"neutral_a_curve": [...], "neutral_b_curve": [...]},
        "by_cct": [[cct_center, {"neutral_a_curve": [...], "neutral_b_curve": [...]}], ...]}
     (default = 全集中位; colorcal neutral_mode=static 按渲染时 CCT 自动插值)。
  4. 验证子集: 带 colorcal (static) 渲染, 固定掩码复测 neu_a/neu_b 应≈0。

用法: python rawlab/tools/fit_camera_look.py --n_fit 30 --n_val 10
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np
import rawpy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rawlab.dcp import load_dcp
from rawlab.engine import build_default_pipeline
from rawlab.engine.core import Pipeline
from rawlab.engine import stages as _stages  # noqa: F401
from rawlab.engine.color import cct_from_wb
from rawlab.engine.decode import camera_neutral_wb
from rawlab.tools.batch_iter import camera_preview

DEFAULT_DCP = r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp"
DEFAULT_RAW_DIRS = [r"K:\data\photo\0711\raw", r"K:\data\photo\2026春节"]
BANDS = [(0, 16), (16, 48), (48, 96), (96, 160), (160, 208), (208, 240), (240, 256)]

# CCT 分段标定: 3 桶 (中心按桶内 CCT 中位回填, 见 compose 前处理)
CCT_BOUNDS = (3500.0, 5500.0)     # 桶: <3500 / 3500-5500 / >5500
MIN_BUCKET_SAMPLES = 15           # 每桶至少样本数, 不足跳过该桶 (回退 default)


def band_offsets_vs_cam(mine: np.ndarray, cam: np.ndarray):
    """在相机预览中性像素 (C*<12) 上按 L 带统计 (mine-cam) 的 a/b 中位。"""
    cam_s = cv2.resize(cam, (mine.shape[1], mine.shape[0]),
                       interpolation=cv2.INTER_AREA)
    lm = cv2.cvtColor(mine, cv2.COLOR_RGB2LAB).astype(np.float32)
    lc = cv2.cvtColor(cam_s, cv2.COLOR_RGB2LAB).astype(np.float32)
    chroma = np.sqrt((lc[..., 1] - 128) ** 2 + (lc[..., 2] - 128) ** 2)
    neu = (chroma < 12) & (lc[..., 0] > 8) & (lc[..., 0] < 250)
    da, db = [], []
    for lo, hi in BANDS:
        m = neu & (lc[..., 0] >= lo) & (lc[..., 0] < hi)
        if m.sum() < 200:
            da.append(None)
            db.append(None)
        else:
            da.append(float(np.median(lm[..., 1][m] - lc[..., 1][m])))
            db.append(float(np.median(lm[..., 2][m] - lc[..., 2][m])))
    return da, db


def cct_of_file(f, prof) -> float:
    """单张 RAW 的 CCT: 读 AsShot WB → engine.color.cct_from_wb 反演。"""
    with rawpy.imread(f) as raw:
        wb = camera_neutral_wb(raw)
    return float(cct_from_wb(wb, prof))


def offsets_to_curve(band_a, band_b):
    """每带偏移中位列表 (7×list) → (a_curve, b_curve): 取负、钳幅、舍入。

    band_a/band_b: 7 个 list, 每项为该带跨图 (mine-cam) 偏移集合; 空→0。
    """
    a = [-float(np.median(v)) if v else 0.0 for v in band_a]
    b = [-float(np.median(v)) if v else 0.0 for v in band_b]
    a = [v if abs(v) <= 8 else v * 0.5 for v in a]
    b = [v if abs(v) <= 8 else v * 0.5 for v in b]
    return [round(v, 2) for v in a], [round(v, 2) for v in b]


def cct_bucket_index(cct: float) -> int:
    """CCT → 桶下标: 0=<3500, 1=3500-5500, 2=>5500。"""
    if cct < CCT_BOUNDS[0]:
        return 0
    if cct < CCT_BOUNDS[1]:
        return 1
    return 2


def compose_cct_cal(default_curves, bucket_rows):
    """组装新格式标定 JSON (纯函数, 供单测)。

    default_curves: (a_curve, b_curve) 全集中位。
    bucket_rows: [(cct_center, (a_curve, b_curve)), ...]; 输出按 cct 升序。
    返回 {"default": {...}, "by_cct": [[cct, {...}], ...]}。
    """
    default_a, default_b = default_curves
    by_cct = []
    for center, (a, b) in sorted(bucket_rows, key=lambda r: r[0]):
        by_cct.append([round(float(center), 1),
                       {"neutral_a_curve": list(a), "neutral_b_curve": list(b)}])
    return {
        "default": {"neutral_a_curve": list(default_a), "neutral_b_curve": list(default_b)},
        "by_cct": by_cct,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_fit", type=int, default=30)
    ap.add_argument("--n_val", type=int, default=10)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--min-bucket", type=int, default=MIN_BUCKET_SAMPLES,
                    help="每桶至少样本数 (不足跳过该桶, 回退 default)")
    ap.add_argument("--dcp", default=os.environ.get("RAWLAB_DCP", DEFAULT_DCP))
    ap.add_argument("--raw-dir", action="append", default=None)
    args = ap.parse_args()

    prof = load_dcp(args.dcp)
    raw_dirs = args.raw_dir
    if not raw_dirs:
        env = os.environ.get("RAWLAB_RAW_DIRS")
        raw_dirs = [d for d in env.split(";") if d] if env else DEFAULT_RAW_DIRS
    files = []
    for d in raw_dirs:
        files.extend(sorted(glob.glob(os.path.join(d, "*.NEF"))))
    files = files[args.start: args.start + args.n_fit + args.n_val]
    fit_files, val_files = files[: args.n_fit], files[args.n_fit:]

    # 拟合: 无 colorcal 渲染 → vs 相机预览中性区偏移, 按 CCT 分桶
    pipe_no = Pipeline(stages=["exposure", "whitebalance", "tone", "stylize", "refine"])
    pipe_no.prof = prof
    band_a = [[] for _ in BANDS]              # 全集 (default)
    band_b = [[] for _ in BANDS]
    buckets = [{"ccts": [], "band_a": [[] for _ in BANDS],
                "band_b": [[] for _ in BANDS]} for _ in range(3)]
    for i, f in enumerate(fit_files):
        try:
            mine = pipe_no.run_file(f, half_size=True)
            cam = camera_preview(f)
            if cam is None:
                continue
            cct = cct_of_file(f, prof)
            da, db = band_offsets_vs_cam(mine, cam)
            bi = cct_bucket_index(cct)
            buckets[bi]["ccts"].append(cct)
            for j in range(7):
                if da[j] is not None:
                    band_a[j].append(da[j])
                    band_b[j].append(db[j])
                    buckets[bi]["band_a"][j].append(da[j])
                    buckets[bi]["band_b"][j].append(db[j])
        except Exception as e:
            print(f"  fit skip {os.path.basename(f)}: {e}")
        if (i + 1) % 10 == 0:
            print(f"  fit {i+1}/{len(fit_files)}")

    default_a, default_b = offsets_to_curve(band_a, band_b)
    print(f"相机观感曲线 (default) a: {default_a}")
    print(f"相机观感曲线 (default) b: {default_b}")

    # 每桶拟合 (样本不足跳过)
    by_cct = []
    for bi, bkt in enumerate(buckets):
        n = len(bkt["ccts"])
        if n < args.min_bucket:
            print(f"  CCT 桶 {bi} (n={n}) 样本不足 {args.min_bucket}, 跳过 (回退 default)")
            continue
        a, b = offsets_to_curve(bkt["band_a"], bkt["band_b"])
        center = float(np.median(bkt["ccts"]))
        by_cct.append((center, (a, b)))
        print(f"  CCT 桶 {bi} n={n} center={center:.0f}K: a={a} b={b}")

    cal = compose_cct_cal((default_a, default_b), by_cct)
    cal_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                            "engine", "z5ii_neutral_trim.json"))
    with open(cal_file, "w", encoding="utf-8") as fh:
        json.dump(cal, fh, ensure_ascii=False, indent=1)
    print(f"标定写入: {cal_file}")
    print("新格式标定 JSON:")
    print(json.dumps(cal, ensure_ascii=False, indent=1))

    # 验证: 带 colorcal (static) vs 无, 固定掩码 (相机中性像素) 复测
    pipe_with = build_default_pipeline(prof=prof, params={"colorcal": {"neutral_mode": "static"}})
    na_all, nb_all = [], []
    for i, f in enumerate(val_files):
        try:
            mine = pipe_with.run_file(f, half_size=True)
            cam = camera_preview(f)
            if cam is None:
                continue
            cam_s = cv2.resize(cam, (mine.shape[1], mine.shape[0]),
                               interpolation=cv2.INTER_AREA)
            lm = cv2.cvtColor(mine, cv2.COLOR_RGB2LAB).astype(np.float32)
            lc = cv2.cvtColor(cam_s, cv2.COLOR_RGB2LAB).astype(np.float32)
            chroma = np.sqrt((lc[..., 1] - 128) ** 2 + (lc[..., 2] - 128) ** 2)
            neu = (chroma < 12) & (lc[..., 0] > 8) & (lc[..., 0] < 250)
            da = float(np.median(lm[..., 1][neu] - 128))
            db = float(np.median(lm[..., 2][neu] - 128))
            na_all.append(da)
            nb_all.append(db)
            print(f"  val {os.path.basename(f)}: neu_a={da:+.1f} neu_b={db:+.1f}")
        except Exception as e:
            print(f"  val skip {os.path.basename(f)}: {e}")
    if na_all:
        print(f"\n=== 验证 (相机中性区) n={len(na_all)} ===")
        print(f"  neu_a: |mean|={abs(np.mean(na_all)):.1f}  neu_b: |mean|={abs(np.mean(nb_all)):.1f}")


if __name__ == "__main__":
    main()
