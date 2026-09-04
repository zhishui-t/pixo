"""engine.skin —— 椭圆肤色掩码 + 引导滤波磨皮 (阶段2, T5)。

职责 (软件设计 §2 / 规格 §1):
  - skin_mask(rgb8) -> ndarray: Lab 椭圆模型软掩码 (float32, 0..1)。
  - skin_smooth(rgb8, mask, strength=0.5) -> ndarray: 引导滤波磨皮 (仅掩码区)。
  - guided_filter(guide, src, r, eps): box-filter 自实现引导滤波 (无 ximgproc 依赖)。

肤色椭圆模型 (规格 §2.2):
  中心 (a=140, b=150), 主轴 22, 副轴 14, 倾角 0.65 rad (OpenCV Lab, a/b ∈ 0..255,
  中性 128)。马氏距离 d = sqrt((u/major)^2 + (v/minor)^2), (u, v) 为旋转变换后的
  椭圆主轴系坐标; 软掩码 = 椭圆内 (d<=1) 全量 1, 边界外 smoothstep 平滑过渡到 0
  (软边界), 供磨皮与 colorcal 肤色保护共用同一掩码。

磨皮 (规格 §2.2): 引导滤波 r=4, eps=0.01 (He et al. 2013, 引导/输入均在 0..1 值域,
  eps 才有意义), 强度默认 0.5。
    out = rgb8*(1 - m*s) + smoothed*(m*s)
  m 为软掩码, s 为强度; m*s=0 的像素严格保持原值 (仅掩码区平滑)。

输入约定:
  - rgb8: 8bit RGB (uint8 HxWx3)。float 0..1 输入会被钳位量化到 0..255。
  - mask: float32 HxW (0..1), 尺寸须与 rgb8 一致 (或 HxWx1)。
"""
from __future__ import annotations

import cv2
import numpy as np

from .oklab import srgb_to_oklab

# 肤色椭圆 (规格 §2.2)
SKIN_LAB_A = 140.0
SKIN_LAB_B = 150.0
SKIN_MAJOR = 22.0
SKIN_MINOR = 14.0
SKIN_ANGLE = 0.65

# 软过渡带: 马氏距离 d 从 1 到 1+SOFT_BAND 平滑衰减到 0 (smoothstep)。
# 取 0.25: 中性灰 (128,128,128) 距椭圆中心 d≈1.27 → 掩码归零 (避免误判中性灰为肤色),
# 又保留足够宽的羽毛边 (软边界, 供磨皮边界无接缝)。
SOFT_BAND = 0.25

# 引导滤波 (规格 §2.2)
GUIDED_R = 4
GUIDED_EPS = 0.01


def _as_uint8_rgb(rgb8) -> np.ndarray:
    """入参清洗 → uint8 RGB HxWx3 (float 图按 0..1 量化; 灰度图扩 3 通道)。"""
    arr = np.asarray(rgb8)
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 1.0)
        arr = (arr * 255.0 + 0.5).astype(np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb8 需为 HxWx3 图, 实际 {arr.shape}")
    return arr


def _ellipse_mahalanobis(lab: np.ndarray) -> np.ndarray:
    """Lab → 椭圆马氏距离 d = sqrt((u/major)^2 + (v/minor)^2) (float32 HxW)。"""
    a = lab[:, :, 1].astype(np.float32)
    b = lab[:, :, 2].astype(np.float32)
    da = a - SKIN_LAB_A
    db = b - SKIN_LAB_B
    cos_a, sin_a = np.cos(SKIN_ANGLE), np.sin(SKIN_ANGLE)
    u = da * cos_a + db * sin_a      # 沿主轴
    v = -da * sin_a + db * cos_a     # 沿副轴
    d2 = (u / SKIN_MAJOR) ** 2 + (v / SKIN_MINOR) ** 2
    return np.sqrt(np.maximum(d2, 0.0)).astype(np.float32)


def skin_mask(rgb8, soft_band: float = SOFT_BAND) -> np.ndarray:
    """Lab 椭圆肤色软掩码 (float32 HxW, 0..1)。

    椭圆内 (马氏距离 d <= 1) → 1.0; 边界外 smoothstep 平滑过渡到 0 (软边界)。
    """
    arr = _as_uint8_rgb(rgb8)
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
    d = _ellipse_mahalanobis(lab)
    band = max(float(soft_band), 1e-6)
    t = np.clip((d - 1.0) / band, 0.0, 1.0)
    # smoothstep: 1 - 3t^2 + 2t^3 (d<=1 → 1; d>=1+band → 0; 边界 C1 连续)
    return (1.0 - t * t * (3.0 - 2.0 * t)).astype(np.float32)


def guided_filter(guide, src, r: int = GUIDED_R, eps: float = GUIDED_EPS) -> np.ndarray:
    """引导滤波 (He et al. 2013) box-filter 自实现, 无 cv2.ximgproc 依赖。

    Args:
        guide: 单通道引导图 float32 (值域 0..1)。
        src:   单通道输入图 float32 (值域 0..1), 与 guide 同尺寸。
        r:     滤波半径 (窗口 2r+1)。
        eps:   正则项 (引导方差 + eps, 值域 0..1 平方)。

    Returns:
        单通道 float32 (值域 0..1)。边缘由 guide 决定 (edge-preserving)。
    """
    guide = np.asarray(guide, dtype=np.float32)
    src = np.asarray(src, dtype=np.float32)
    if guide.shape != src.shape:
        raise ValueError(f"guide {guide.shape} 与 src {src.shape} 尺寸不一致")
    radius = max(int(r), 1)
    ksize = (2 * radius + 1, 2 * radius + 1)
    mean_I = cv2.blur(guide, ksize)
    mean_p = cv2.blur(src, ksize)
    corr_I = cv2.blur(guide * guide, ksize)
    corr_Ip = cv2.blur(guide * src, ksize)
    var_I = corr_I - mean_I * mean_I
    cov_Ip = corr_Ip - mean_I * mean_p
    a = cov_Ip / (var_I + float(eps))
    b = mean_p - a * mean_I
    mean_a = cv2.blur(a, ksize)
    mean_b = cv2.blur(b, ksize)
    return (mean_a * guide + mean_b).astype(np.float32)


def _smooth_rgb_f01(rgb8: np.ndarray) -> np.ndarray:
    """对 RGB 三通道做灰度引导滤波平滑 (返回 float32 HxWx3, 值域 0..1)。

    引导图 = 灰度 (Rec.709 近似由 cvtColor 提供), 对每通道独立引导滤波;
    cv2.ximgproc 可用则用, 否则回退 box-filter 自实现 (规格 §4 兼容性)。
    """
    f = rgb8.astype(np.float32) / 255.0
    gray = cv2.cvtColor(rgb8, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    out = np.empty_like(f)
    use_ximgproc = hasattr(cv2, "ximgproc")
    for c in range(3):
        if use_ximgproc:
            out[:, :, c] = cv2.ximgproc.guidedFilter(
                gray, f[:, :, c], GUIDED_R, GUIDED_EPS)
        else:
            out[:, :, c] = guided_filter(gray, f[:, :, c], GUIDED_R, GUIDED_EPS)
    return out


def skin_smooth(rgb8, mask, strength: float = 0.5, half_res: bool = False) -> np.ndarray:
    """引导滤波磨皮 (uint8 RGB → uint8 RGB, 仅掩码区平滑)。

    out = rgb8*(1 - m*s) + smoothed*(m*s)。m*s=0 的像素严格保持原值;
    强度 s<=0 或掩码全零 → 直通 (原图拷贝)。

    half_res=True: 引导滤波在 1/2 分辨率做 (磨皮是低频操作, 上采样无损
    细节; 全分辨率 ~1.2s → 1/2 分辨率 ~0.3s)。
    """
    arr = _as_uint8_rgb(rgb8)
    m = np.asarray(mask, dtype=np.float32)
    if m.ndim == 3 and m.shape[2] == 1 and m.shape[:2] == arr.shape[:2]:
        m = m[:, :, 0]
    if m.ndim != 2 or m.shape[:2] != arr.shape[:2]:
        raise ValueError(f"mask {m.shape} 需为 HxW (与 rgb8 {arr.shape[:2]} 一致)")
    m = np.clip(m, 0.0, 1.0)
    s = float(strength)
    if s <= 0.0 or float(m.max()) <= 0.0:
        return arr.copy()

    f = arr.astype(np.float32) / 255.0
    if half_res:
        h, w = arr.shape[:2]
        small = cv2.resize(arr, (max(w // 2, 4), max(h // 2, 4)),
                           interpolation=cv2.INTER_AREA)
        smoothed = _smooth_rgb_f01(small)
        smoothed = cv2.resize(smoothed, (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        smoothed = _smooth_rgb_f01(arr)

    w = (m * s)[:, :, None].astype(np.float32)
    out = f * (1.0 - w) + smoothed * w
    return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

# ---------------------------------------------------------------------------
# OKLab 椭圆 (M-O2, 设计 §3) —— 由 scripts/fit_skin_oklch.py 在厦门/春节语料
# (2026-02-10 春节 + 02-14..04-24 厦门, 42 张有效照片, pixo.meta 拍摄日分组)
# 上以 "旧 Lab 椭圆掩码 ∩ person 分割掩码 (RF-DETR)" 为皮肤样本, 取 C>=0.04
# 色度核在 OKLab a-b 平面包围拟合 (coverage=0.96, 2026-09-04):
#   对照 (configs/color/skin_oklab.json): 核内召回 0.955 / 全体 0.832,
#   背景误报 0.258 (旧 0.271); 中性灰 d≈1.43 掩码归零。
# 样本遴选与对照基准均为 cv2.COLOR_RGB2LAB 语义 (白点口径见脚本头 A3)。
# 旧 SKIN_LAB_* 常数与 skin_mask 不动 (hsv 域回退保证, 设计 §1.2)。
# ---------------------------------------------------------------------------

# 椭圆中心 (OKLab a*, b*; 中性 0)
SKIN_OKLAB_A = 0.01516
SKIN_OKLAB_B = 0.06125
# 半轴 (主轴沿 u, 副轴沿 v, 同旧椭圆的旋转变换约定)
SKIN_OKLAB_MAJOR = 0.045692
SKIN_OKLAB_MINOR = 0.045192
# 倾角 (弧度, 同 _ellipse_mahalanobis 的 u/v 旋转约定)
SKIN_OKLAB_ANGLE = 0.191122
# 软过渡带 (马氏距离 d 从 1 到 1+band smoothstep 衰减; 口径同 SOFT_BAND)
SKIN_OKLAB_SOFT_BAND = 0.25


def _ellipse_mahalanobis_ab(a: np.ndarray, b: np.ndarray, cx: float, cy: float,
                            major: float, minor: float,
                            angle: float) -> np.ndarray:
    """a/b 平面 → 椭圆马氏距离 d (float32 HxW)。

    旋转变换约定与旧 Lab 椭圆 (_ellipse_mahalanobis) 完全一致:
    u = da·cosθ + db·sinθ (沿主轴), v = -da·sinθ + db·cosθ (沿副轴)。
    """
    da = a - np.float32(cx)
    db = b - np.float32(cy)
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    u = da * cos_a + db * sin_a
    v = -da * sin_a + db * cos_a
    d2 = (u / major) ** 2 + (v / minor) ** 2
    return np.sqrt(np.maximum(d2, 0.0)).astype(np.float32)


def _soft_band_mask(d: np.ndarray, soft_band: float) -> np.ndarray:
    """马氏距离 → 软掩码: d<=1 全量 1, 1..1+band smoothstep 衰减到 0 (与旧掩码同式)。"""
    band = max(float(soft_band), 1e-6)
    t = np.clip((d - 1.0) / band, 0.0, 1.0)
    return (1.0 - t * t * (3.0 - 2.0 * t)).astype(np.float32)


def skin_mask_oklab(rgb01, soft_band: float = SKIN_OKLAB_SOFT_BAND) -> np.ndarray:
    """OKLab 椭圆肤色软掩码 (float32 HxW, 0..1) —— skin_mask 的 OKLab 域姊妹版。

    输入契约 (设计 §1.3): gamma sRGB float [0,1] (H,W,3), 精度优先不走 uint8
    量化; uint8 输入按 /255 归一 (与旧 skin_mask 的 float 钳位量化方向相反,
    这里是升级而非降级)。内部经 core.oklab (float64) 求 OKLab, a-b 平面按
    SKIN_OKLAB_* 椭圆算马氏距离, 软边界同 skin_mask (d<=1 全量 1, 外带 smoothstep)。

    适用: color_domain="oklch" 时 SkinStage / colorcal 肤色区操作的同一掩码;
    旧 skin_mask (cv2 Lab u8 域) 保持不动, hsv 域路径逐位不变。
    """
    arr = np.asarray(rgb01)
    if arr.dtype == np.uint8:
        arr = arr.astype(np.float64) / 255.0
    elif arr.dtype == np.uint16:
        arr = arr.astype(np.float64) / 65535.0
    else:
        arr = np.clip(np.asarray(arr, dtype=np.float64), 0.0, 1.0)
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb01 需为 HxWx3 图, 实际 {arr.shape}")
    lab = srgb_to_oklab(arr)
    d = _ellipse_mahalanobis_ab(lab[:, :, 1], lab[:, :, 2],
                                SKIN_OKLAB_A, SKIN_OKLAB_B,
                                SKIN_OKLAB_MAJOR, SKIN_OKLAB_MINOR,
                                SKIN_OKLAB_ANGLE)
    return _soft_band_mask(d, soft_band)


__all__ = ["skin_mask", "skin_smooth", "guided_filter",
           "skin_mask_oklab"]
