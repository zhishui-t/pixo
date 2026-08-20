"""engine.enhance —— 观感增强纯函数 (clarity / dehaze), 解决"发灰/发暗/没质感"。

原理:
  - clarity (局部对比/质感): 中频带通 (大尺度高斯 - 小尺度高斯) 在亮度上做
    带增益的增强, 边缘区增益受限防晕边。发灰照片的"油润/立体感"主要来自
    中频对比 —— 这是 Capture One "Clarity" / LR "纹理" 的核心。
  - dehaze (通透/去雾): 暗通道先验 (He et al. 2009) 简化版 —— 暗通道估计
    大气光 A 与透射率 t, 恢复 J=(I-A)/t+A; t 经引导滤波 (box 版) 细化防晕;
    strength 线性混合。发灰的雾霾感/空气感由此消除。
"""
from __future__ import annotations

import cv2
import numpy as np

from .skin import guided_filter  # box 版引导滤波 (无 ximgproc 依赖)

_RGB_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _gray(rgb: np.ndarray) -> np.ndarray:
    return (rgb @ _RGB_WEIGHTS).astype(np.float32)


def clarity(rgb01: np.ndarray, strength: float = 0.5,
            small_sigma: float = 0.8, large_sigma: float = 3.0) -> np.ndarray:
    """中频局部对比增强 (float RGB 0..1 → 0..1, strength 0..1)。

    mid = gauss(gray, small) - gauss(gray, large)  (中频带通)
    gain = (gray + strength*3*mid) / gray          (亮度增益比, 色相近似保持)
    增益钳位 [1-2s, 1+2s] 防晕边。
    """
    s = float(strength)
    if s <= 0.0:
        return rgb01
    img = np.clip(np.asarray(rgb01, dtype=np.float32), 0.0, 1.0)
    g = _gray(img)
    small = cv2.GaussianBlur(g, (0, 0), small_sigma)
    large = cv2.GaussianBlur(g, (0, 0), large_sigma)
    mid = small - large
    gain = (g + s * 3.0 * mid) / np.maximum(g, 1e-4)
    gain = np.clip(gain, 1.0 - 2.0 * s, 1.0 + 2.0 * s)
    out = img * gain[:, :, None]
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def dehaze(rgb01: np.ndarray, strength: float = 0.5,
           radius: int = 15, omega: float = 0.95,
           t0: float = 0.1) -> np.ndarray:
    """暗通道先验去雾 (float RGB 0..1 → 0..1, strength 0..1)。

    dark = min_c RGB; 大气光 A = dark 前 0.1% 亮点的中位 RGB;
    t = 1 - omega*dark/A; 引导滤波细化 t; J = (I-A)/max(t,t0)+A;
    输出 = I*(1-s) + J*s。
    """
    s = float(strength)
    if s <= 0.0:
        return rgb01
    img = np.clip(np.asarray(rgb01, dtype=np.float32), 0.0, 1.0)
    h, w = img.shape[:2]

    dark = img.min(axis=2)
    k = max(1, int(radius))
    kernel = np.ones((2 * k + 1, 2 * k + 1), np.uint8)
    dark_er = cv2.erode(dark, kernel)

    # 大气光: 暗通道最亮的前 0.1% 像素对应原图中位 RGB
    flat = dark_er.ravel()
    thr = np.quantile(flat, 0.999)
    mask = dark_er >= thr
    if int(mask.sum()) < 3:
        return img
    A = np.median(img[mask], axis=0).astype(np.float32)  # (3,)
    A = np.maximum(A, 1e-3)
    a_scalar = float(np.max(A))

    # 透射率: t = 1 - omega*dark/A。亮区/天空保护: 暗通道 ≥ 大气光的像素
    # (太阳/天空/明亮晴天) 会被暗通道先验误判为浓雾并过度恢复 —— 这类
    # 像素 t 强制为 1 (不恢复)。这是 DCP 对非雾亮场景的经典失效保护。
    t = 1.0 - omega * dark_er / max(a_scalar, 1e-6)
    t = np.clip(t, 0.05, 1.0)
    t = np.where(dark_er >= a_scalar, 1.0, t)
    # 引导滤波细化 (guide=灰, r=2k, eps=1e-3)
    guide = _gray(img)
    t = guided_filter(guide, t.astype(np.float32), r=2 * k, eps=1e-3)
    t = np.clip(t, 0.05, 1.0)

    J = (img - A) / np.maximum(t[:, :, None], t0) + A
    J = np.clip(J, 0.0, 1.0)
    out = img * (1.0 - s) + J * s
    return np.clip(out, 0.0, 1.0).astype(np.float32)

__all__ = ["dehaze", "clarity"]
