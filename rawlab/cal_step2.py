"""阶段2: 影调重塑 (干净/通透/透亮/锐一点), 叠加在阶段1之上。

全部在 Lab 空间操作, 与色彩解耦:
  透亮: 中位亮度抬升 + 中调对比微增
  通透: 大半径局部对比 (clarity, USM 低通)
  干净: 暗部轻微提纯 (黑点上抬一点点) + 高光软滚降
  锐:   小半径 USM (仅 L 通道)
"""
from __future__ import annotations

import cv2
import numpy as np

# 阶段2 参数 (v1 默认, 批量迭代后校准)
STEP2_PARAMS = {
    "bright": 6.0,        # 整体亮度抬升 (Lab L)
    "contrast": 1.06,     # 中调对比 (绕 128)
    "shadow_lift": 8.0,   # 暗部抬升量 (L<50 区间)
    "clarity": 0.25,      # 通透: 大半径局部对比强度
    "clarity_radius": 25.0,
    "sharpen": 0.6,       # 锐化强度
    "sharpen_radius": 1.8,
    "highlight_roll": 0.5,  # 高光软滚降 (L>235)
}


def apply_tone_step2(rgb8: np.ndarray, p: dict | None = None) -> np.ndarray:
    if p is None:
        p = STEP2_PARAMS
    lab = cv2.cvtColor(rgb8, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]

    # 1) 透亮: 亮度抬升 + 中调对比
    L = 128 + (L - 128) * p["contrast"] + p["bright"]

    # 2) 暗部抬升 (干净不发灰: 只抬最深部, 保持中间调)
    w = np.clip((50 - L) / 50, 0, 1)
    L = L + p["shadow_lift"] * w * (1 - w) * 4  # 峰值在 L=25

    # 3) 高光软滚降
    w = np.clip((L - 235) / 20, 0, 1)
    L = np.where(L > 235, L - p["highlight_roll"] * w * (L - 235), L)

    # 4) 通透 (clarity): 大半径 USM 加回局部对比
    if p["clarity"] > 0:
        blur = cv2.GaussianBlur(L, (0, 0), p["clarity_radius"])
        detail = L - blur
        L = L + p["clarity"] * detail

    L = np.clip(L, 0, 255)

    # 5) 锐化: 小半径 USM 仅 L
    if p["sharpen"] > 0:
        blur = cv2.GaussianBlur(L, (0, 0), p["sharpen_radius"])
        L = L + p["sharpen"] * (L - blur)

    L = np.clip(L, 0, 255)
    out = cv2.cvtColor(np.stack([L, a, b], axis=-1).astype(np.uint8), cv2.COLOR_LAB2RGB)
    return out


def render_step2(raw_path, prof, half_size: bool = False,
                 params: dict | None = None) -> np.ndarray:
    from .cal_step1 import render_step1
    rgb8 = render_step1(raw_path, prof, half_size=half_size)
    return apply_tone_step2(rgb8, params)
