"""engine.usercal —— 用户可调 RGB 校准 (shadow tint + 三原色 hue/sat)。

与 ColorCalStage (场景自适应中性轴校准) 解耦的**独立用户校准**:
  - shadow_tint: 按暗部亮度掩码调 R/B 相对增益 (G 不动)。
  - red/green/blue hue/sat: 对三原色色段用环状掩码做 HSV 色相/饱和调整
    (复用 engine.hsl 的掩码/HSV 机制; 本模块只暴露三原色参数)。
域: gamma RGB [0,1]。全 0 → 逐位 no-op; 中性灰 (S≈0 / 中调) 不变。
"""
from __future__ import annotations

import numpy as np

from .hsl import hsl_adjust_rgb

_RGB_W = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)  # Rec.709 亮度

# 边界
_TINT_LO, _TINT_HI = -100.0, 100.0
_HUE_LO, _HUE_HI = -180.0, 180.0
_SAT_LO, _SAT_HI = -100.0, 100.0
# shadow_tint 增益幅度: 满载(±100)时暗部 R/B 相对偏移比例
_TINT_K = 0.6
# 三原色段带宽 (度, 可选自选; 60 使相邻色段平滑重叠)
_PRIMARY_WIDTH = 60.0


def _check(v, lo, hi, name):
    v = float(v)
    if not (lo <= v <= hi):
        raise ValueError(f"usercal 参数 '{name}' 越界: {v} 不在 [{lo}, {hi}]")
    return v


def _shadow_mask(y_luma: np.ndarray) -> np.ndarray:
    """暗部 smoothstep 掩码 [0,1]: 深暗部=1, 中灰(≈0.30)归 0, 平滑无硬边。"""
    t = np.clip((0.30 - y_luma) / 0.28, 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def apply_usercal_rgb(img01, shadow_tint: float = 0.0,
                      red_hue: float = 0.0, red_sat: float = 0.0,
                      green_hue: float = 0.0, green_sat: float = 0.0,
                      blue_hue: float = 0.0, blue_sat: float = 0.0):
    """对 gamma RGB [0,1] 应用用户 RGB 校准。

    shadow_tint∈[-100,100]: 正=偏品红/暖 (暗部 R↑ B↓, G 不动); 负=偏绿 (R↓ B↑)。
    red/green/blue_hue∈[-180,180], _sat∈[-100,100]: 三原色独立色相旋转/饱和。
    全 0 → 原样返回 (逐位 no-op)。返回 float32 [0,1]。
    """
    t = _check(shadow_tint, _TINT_LO, _TINT_HI, "shadow_tint")
    rh = _check(red_hue, _HUE_LO, _HUE_HI, "red_hue")
    rs = _check(red_sat, _SAT_LO, _SAT_HI, "red_sat")
    gh = _check(green_hue, _HUE_LO, _HUE_HI, "green_hue")
    gs = _check(green_sat, _SAT_LO, _SAT_HI, "green_sat")
    bh = _check(blue_hue, _HUE_LO, _HUE_HI, "blue_hue")
    bs = _check(blue_sat, _SAT_LO, _SAT_HI, "blue_sat")

    img01 = np.asarray(img01, dtype=np.float32)
    out = img01

    # ---- shadow_tint: 暗部 R/B 相对增益 (G 不动), 中灰掩码=0 不受影响 ----
    if t != 0.0:
        Y = np.asarray(img01 @ _RGB_W, dtype=np.float32)
        m = _shadow_mask(Y)
        k = t / 100.0 * _TINT_K
        r_gain = (1.0 + k * m)[..., None]
        b_gain = (1.0 - k * m)[..., None]
        out = img01.copy()
        out[..., 0] = out[..., 0] * r_gain[..., 0]
        out[..., 2] = out[..., 2] * b_gain[..., 0]

    # ---- 三原色 hue/sat: 复用 hsl_adjust_rgb 的环状掩码 + HSV 调整 ----
    if any(v != 0.0 for v in (rh, rs, gh, gs, bh, bs)):
        bands = [
            {"name": "red",   "hue_center": 0,   "width": _PRIMARY_WIDTH,
             "hue_shift": rh, "saturation": rs, "luminance": 0.0},
            {"name": "green", "hue_center": 120, "width": _PRIMARY_WIDTH,
             "hue_shift": gh, "saturation": gs, "luminance": 0.0},
            {"name": "blue",  "hue_center": 240, "width": _PRIMARY_WIDTH,
             "hue_shift": bh, "saturation": bs, "luminance": 0.0},
        ]
        out = hsl_adjust_rgb(out, bands, smooth=1.0)

    return np.clip(out, 0.0, 1.0).astype(np.float32)

__all__ = ["apply_usercal_rgb"]
