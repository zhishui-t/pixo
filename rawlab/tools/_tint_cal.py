"""测量: 每张照片的理想线性增益 g* 与 warm 公式的实际效果 f, 为 tint 相关校正标定。

数据点:
  - 0376: LR As Shot 3300K / tint +27 → LR 渲染 a+6 b+12 (暖)
  - 5236: LR As Shot 3450K / tint  0  → LR 渲染 a=0  b=-1 (中性)
结论验证: 校正必须含 tint 轴, 不能是常量 warm。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"K:\work\project\RawFlow")))
import cv2
import numpy as np
from rawlab.dcp import load_dcp
from rawlab.engine import stages as _  # noqa
from rawlab.engine.core import StageContext, STAGE_REGISTRY, DOMAIN_LINEAR_CAM
from rawlab.engine.decode import decode_raw
from rawlab.tools.lr_wb import lr_temp_tint_to_wb

DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
       r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")
PHOTOS = [(r"K:\data\photo\2026春节\DSC_0376.NEF",
           r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_0376.jpg"),
          (r"K:\data\photo\0711\raw\DSC_5236.NEF",
           r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_5236.jpg")]
PROF = load_dcp(DCP)


def srgb_inv(x):
    x = np.clip(np.asarray(x, np.float64), 0, 1)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear(raw_path, warmth):
    im, r = decode_raw(raw_path)
    ctx = StageContext(raw_path, raw=r, prof=PROF, config={"stages": {
        "exposure": {"mode": "baseline"},
        "whitebalance": {"warmth": warmth}}})
    ctx.set_image(im, DOMAIN_LINEAR_CAM)
    ctx.state["half_size"] = False
    STAGE_REGISTRY["exposure"]().run(ctx)
    STAGE_REGISTRY["whitebalance"]().run(ctx)
    wb = ctx.state["wb"]
    r.close()
    return ctx.image.astype(np.float32), wb


def wb_to_temp_tint(wb):
    """相机 WB 系数 → (temp_k, tint), 反解 lr_temp_tint_to_wb。"""
    from scipy.optimize import least_squares
    wb = np.asarray(wb, np.float64)

    def resid(p):
        t, ti = p
        out = lr_temp_tint_to_wb(PROF, t, ti).astype(np.float64)
        return np.array([(out[0] - wb[0]) / wb[0], (out[2] - wb[2]) / wb[2]]) * 100

    best = None
    for t0 in (2800.0, 3500.0, 4500.0, 5500.0):
        for ti0 in (-30.0, 0.0, 30.0):
            r = least_squares(resid, [t0, ti0], bounds=([1500, -150], [50000, 150]))
            if best is None or r.cost < best.cost:
                best = r
    return float(best.x[0]), float(best.x[1])


print("== 1) 相机 WB → temp/tint 反解 (对照 LR 显示: 0376=3300/+27, 5236=3450/0) ==")
wbs = {}
for raw_path, _ in PHOTOS:
    im, raw = decode_raw(raw_path)
    wb = np.array(raw.camera_whitebalance[:3], np.float64)
    wb = wb / wb[1]
    t, ti = wb_to_temp_tint(wb)
    print(f"  {Path(raw_path).name}: wb={np.round(wb,3)} → {t:.0f}K / tint {ti:+.0f}")
    wbs[Path(raw_path).name] = wb
    raw.close()

print("\n== 2) 理想线性增益 g* = median(LR_lin / ours(warmth0)) ==")
for raw_path, lr_path in PHOTOS:
    L, wb = linear(raw_path, 0.0)
    lr8 = cv2.cvtColor(cv2.imread(lr_path), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    lr8 = cv2.resize(lr8, (L.shape[1], L.shape[0]), interpolation=cv2.INTER_AREA)
    lr_lin = srgb_inv(lr8)
    g = np.median(lr_lin / np.maximum(L, 1e-9), axis=(0, 1))
    print(f"  {Path(raw_path).name}: g* = {np.round(g,3)}")

print("\n== 3) warm 公式在 linear RGB 的实际效果 f = ours(warmth1)/ours(warmth0) ==")
for raw_path, _ in PHOTOS:
    L1, _ = linear(raw_path, 1.0)
    L0, _ = linear(raw_path, 0.0)
    f = np.median(L1 / np.maximum(L0, 1e-9), axis=(0, 1))
    print(f"  {Path(raw_path).name}: f = {np.round(f,3)}")

print("\n== 4) 求解: k = g*_5236 / f_5236; tint_gain(+27) = g*_0376/(k*f_0376) ==")
L, _ = linear(PHOTOS[0][0], 0.0)
lr8 = cv2.cvtColor(cv2.imread(PHOTOS[0][1]), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
lr8 = cv2.resize(lr8, (L.shape[1], L.shape[0]), interpolation=cv2.INTER_AREA)
g0376 = np.median(srgb_inv(lr8) / np.maximum(L, 1e-9), axis=(0, 1))
L2, _ = linear(PHOTOS[1][0], 0.0)
lr82 = cv2.cvtColor(cv2.imread(PHOTOS[1][1]), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
lr82 = cv2.resize(lr82, (L2.shape[1], L2.shape[0]), interpolation=cv2.INTER_AREA)
g5236 = np.median(srgb_inv(lr82) / np.maximum(L2, 1e-9), axis=(0, 1))
f0376 = np.median(linear(PHOTOS[0][0], 1.0)[0] / np.maximum(L, 1e-9), axis=(0, 1))
f5236 = np.median(linear(PHOTOS[1][0], 1.0)[0] / np.maximum(L2, 1e-9), axis=(0, 1))
k = g5236 / f5236
tg27 = g0376 / (k * f0376)
print(f"  k (固定部分) = {np.round(k,3)}")
print(f"  tint_gain(tint=+27) = {np.round(tg27,3)}   (tint=0 应为 [1,1,1])")
