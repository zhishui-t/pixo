"""阶段3: 色彩校准 (肤色/灰阶) — Lab 空间选择性肤色修正。

基线 (80 张, mine-cam):
  肤色 Δa=-0.21 Δb=-7.29 (偏蓝/苍白) ΔL=-2.27 (略暗)
  灰阶 Δa=-1.15 Δb=+1.09 (已近中性, 不能动)

策略: 仅对肤色概率高的像素修正 b/a/L, 权重按 (a,b) 到肤色中心的距离平滑衰减。
"""
from __future__ import annotations

import cv2
import numpy as np

# 肤色中心 (Lab, 实测 25 张: 我们 a=11.1 b=15.8, 相机 a=11.3 b=19.8)
SKIN_CENTER_A = 11.0
SKIN_CENTER_B = 16.0
SKIN_SIGMA = 16.0          # 高斯衰减半径 (肤色 b std≈4, 留裕量)
CAL_DB = 4.5               # 肤色 Δb 修正 (locus 差 -4.0, 略保守)
CAL_DA = 0.2
CAL_DL = 2.0


def skin_weight(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """按 Lab (a,b) 到肤色中心的距离给 0~1 权重 (仅暖色一侧)。

    cv2 Lab 通道以 128 为零点, 先减 128。
    """
    a = a - 128.0
    b = b - 128.0
    da = a - SKIN_CENTER_A
    db = b - SKIN_CENTER_B
    dist2 = da * da + db * db
    w = np.exp(-dist2 / (2 * SKIN_SIGMA ** 2))
    # 仅暖色调 (a>0 且 b>0 方向)
    warm = (a > 2) & (b > 2)
    return w * warm


def apply_color_cal(rgb8: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(rgb8, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
    w = skin_weight(a, b)
    if w.max() < 0.1:
        return rgb8
    L = np.clip(L + CAL_DL * w, 0, 255)
    a = np.clip(a + CAL_DA * w, 0, 255)
    b = np.clip(b + CAL_DB * w, 0, 255)
    return cv2.cvtColor(np.stack([L, a, b], axis=-1).astype(np.uint8), cv2.COLOR_LAB2RGB)


def render_step3(raw_path, prof, half_size: bool = False,
                 step2_params: dict | None = None) -> np.ndarray:
    from .cal_step1 import render_step1
    from .cal_step2 import apply_tone_step2
    rgb8 = render_step1(raw_path, prof, half_size=half_size)
    if step2_params is not None:
        rgb8 = apply_tone_step2(rgb8, step2_params)
    return apply_color_cal(rgb8)
