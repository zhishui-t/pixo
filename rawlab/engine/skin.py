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
