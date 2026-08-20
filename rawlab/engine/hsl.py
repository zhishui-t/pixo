"""engine.hsl —— 人工 HSL 八色段调整 (纯函数, 区别于 DCP 自动 HueSatMap)。

8 个默认色段 center/name (度): red 0, orange 30, yellow 60, green 120,
aqua 180, blue 240, purple 270, magenta 300。
每 band 可调 hue_shift / saturation / luminance, 按**环状平滑掩码**逐段作用
(mask 全周连续 C1、0/360 环绕、边界无硬跳):
  - H' = H + hue_shift * mask          (hue_shift 不改 V/S)
  - S' = clip(S * (1 + sat/100*mask))  (sat 只影响所选色段)
  - V' = clip(V * (1 + lum/100*mask*protect))  (lum 不改 H; protect=S 保中性灰)
中性灰 (S≈0) 任何参数不变; 各 band 全 0 → 逐位 no-op。
"""
from __future__ import annotations

import numpy as np

from .huesat import _rgb_to_hsv, _hsv_to_rgb

H_MAX = 360.0

# 8 默认色段 (全部全 0, 作为 bands=None 时的缺省: 运行无效果 / 结构模板)
DEFAULT_BANDS = [
    {"name": "red",     "hue_center": 0,   "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "orange",  "hue_center": 30,  "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "yellow",  "hue_center": 60,  "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "green",   "hue_center": 120, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "aqua",    "hue_center": 180, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "blue",    "hue_center": 240, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "purple",  "hue_center": 270, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "magenta", "hue_center": 300, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
]

# 各字段带界
_W_MIN, _W_MAX = 5.0, 180.0
_HS_MIN, _HS_MAX = -180.0, 180.0
_SAT_MIN, _SAT_MAX = -100.0, 100.0
_LUM_MIN, _LUM_MAX = -100.0, 100.0
_REQUIRED = ("hue_center", "width", "hue_shift", "saturation", "luminance")


def _validate_band(band: dict) -> None:
    """校验单个 band 结构 (必填键齐全 + 各字段带界)。非法 raise ValueError。"""
    if not isinstance(band, dict):
        raise ValueError(f"hsl band 需为 dict (实际 {type(band).__name__})")
    missing = [k for k in _REQUIRED if k not in band]
    if missing:
        raise ValueError(f"hsl band 缺必填键: {missing}")
    w = float(band["width"])
    if not (_W_MIN <= w <= _W_MAX):
        raise ValueError(f"hsl band width 越界: {w} 不在 [{_W_MIN}, {_W_MAX}]")
    hs = float(band["hue_shift"])
    if not (_HS_MIN <= hs <= _HS_MAX):
        raise ValueError(f"hsl band hue_shift 越界: {hs} 不在 [{_HS_MIN}, {_HS_MAX}]")
    for key, lo, hi in (("saturation", _SAT_MIN, _SAT_MAX),
                        ("luminance", _LUM_MIN, _LUM_MAX)):
        v = float(band[key])
        if not (lo <= v <= hi):
            raise ValueError(f"hsl band {key} 越界: {v} 不在 [{lo}, {hi}]")


def _ring_mask(h: np.ndarray, center: float, width: float, smooth: float) -> np.ndarray:
    """环状全周平滑掩码 [0,1]: 以 center 为中心的圆窗, 0/360 环绕连续 C1。

    smooth=1 → 升余弦窗 (软边界); smooth=0 → 硬盒窗; 之间线性混合。
    边界不产生 NaN (width>0, cos 分母常数)。
    """
    diff = (h - center) % 360.0
    d = np.minimum(diff, 360.0 - diff)             # 到中心的环状角距 [0,180]
    u = np.minimum(d / width, 1.0 + 1e-9)          # 归一化角距 [0,1+]
    cos = np.where(u <= 1.0, 0.5 * (1.0 + np.cos(np.pi * u)), 0.0)
    if smooth >= 1.0:
        return cos
    box = (u <= 1.0).astype(np.float64)
    return (1.0 - smooth) * box + smooth * cos


def hsl_adjust_rgb(img01, bands, smooth: float = 1.0):
    """对 gamma RGB [0,1] 应用人工 HSL 各色段调整。

    bands: 8 band dict 列表 (或 None → 不变)。out = 逐段顺序应用后的 float32
    [0,1] 图 (中性灰不变)。smooth ∈ [0,1] 掩码锐度。
    """
    img01 = np.asarray(img01, dtype=np.float64)
    if not bands:
        return img01.astype(np.float32)
    for band in bands:
        _validate_band(band)
    # 全 0 快路径: 逐位 no-op (连掩码都跳过)
    if all(float(b.get("hue_shift", 0.0)) == 0.0
           and float(b.get("saturation", 0.0)) == 0.0
           and float(b.get("luminance", 0.0)) == 0.0 for b in bands):
        return img01.astype(np.float32)

    smooth = float(np.clip(smooth, 0.0, 1.0))
    h, s, v = _rgb_to_hsv(img01)          # H[0,360) S/V[0...]
    protect = np.clip(s, 0.0, 1.0)        # 中性保护: S≈0 的像素任何参数不变
    for band in bands:
        c = float(band["hue_center"]) % 360.0
        w = float(band["width"])
        m = _ring_mask(h, c, w, smooth)
        hs = float(band.get("hue_shift", 0.0))
        sat = float(band.get("saturation", 0.0))
        lum = float(band.get("luminance", 0.0))
        if hs != 0.0:
            h = (h + hs * m * protect) % 360.0
        if sat != 0.0:
            s = np.clip(s * (1.0 + sat / 100.0 * m), 0.0, 1.0)
        if lum != 0.0:
            v = np.clip(v * (1.0 + lum / 100.0 * m * protect), 0.0, None)
    out = _hsv_to_rgb(h, s, v)
    return np.clip(out, 0.0, 1.0).astype(np.float32)
