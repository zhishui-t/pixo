"""rawlab.engine.split_tone —— 分离色调 (split toning) 纯函数。

对 gamma RGB [0,1] 图施加阴影/高光双色染色:
  - 用 Rec.709 亮度 Y 与 smoothstep 把像素分成 shadows/highlights 两个权重
    (互补且 C1 光滑, balance 为分界亮度);
  - 把 hue(0..360)/sat(0..100) 按标准 HSV->RGB 转成染色色 (V 取像素亮度以保亮度);
  - out = img*(1-w) + tint*w*strength , 逐区域 (阴影/高光) 顺序施加, clip [0,1]。
全 0 饱和 或 strength=0 时逐位 no-op。
"""
from __future__ import annotations

import numpy as np

_RGB_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def _smoothstep(y, balance: float, width: float = 0.5) -> np.ndarray:
    """0..1 smoothstep (hermite), 以 balance 为中心、宽度 width 的转型带。"""
    x = (y - (balance - width)) / max(width * 2.0, 1e-9)
    t = np.clip(x, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _hsv_to_rgb(hue: float, sat: float, v: np.ndarray) -> np.ndarray:
    """标量 hue(0..360)/sat(0..1) + 亮度数组 v -> RGB 数组 (H,W,3)。

    标准 HSV->RGB 六边形; v 数组逐像素作为 Value (保持各像素亮度)。
    """
    h = float(hue) % 360.0
    s = float(sat)
    c = v * s
    sec = int(h // 60.0)
    f = (h / 60.0) - sec
    # 标准公式: x = c*(1-|h' mod 2 -1|), h'=h/60
    hp = h / 60.0
    x = c * (1.0 - np.abs(np.mod(hp, 2.0) - 1.0))
    m = v - c
    if sec == 0:
        r, g, b = c, x, np.zeros_like(x)
    elif sec == 1:
        r, g, b = x, c, np.zeros_like(x)
    elif sec == 2:
        r, g, b = np.zeros_like(x), c, x
    elif sec == 3:
        r, g, b = np.zeros_like(x), x, c
    elif sec == 4:
        r, g, b = x, np.zeros_like(x), c
    else:
        r, g, b = c, np.zeros_like(x), x
    return np.stack([r + m, g + m, b + m], axis=-1)


def _shadow_weight(y: np.ndarray, balance: float) -> np.ndarray:
    """阴影权重 ws: 暗部(低亮)->1, 亮部(高亮)->0, balance 处 0.5; 互补 wh=1-ws。"""
    return 1.0 - _smoothstep(y, float(balance))


def split_tone_rgb(img01, shadows_hue, shadows_sat,
                   highlights_hue, highlights_sat,
                   balance: float = 0.5, strength: float = 1.0) -> np.ndarray:
    """对 gamma RGB [0,1] 施加分离色调染色, 返回同形状 clip[0,1] 数组。

    参数:
      shadows_hue/shadows_sat    阴影染色 hue(0..360)/饱和(0..100)
      highlights_hue/highlights_sat 高光染色 hue/sat
      balance   分界亮度 (0..1, 默认 0.5); 
      strength  整体强度 (0..1, 默认 1.0)。
    全 0 饱和或 strength=0 → 逐位 no-op。
    """
    img = np.asarray(img01, dtype=np.float64)
    if shadows_sat == 0 and highlights_sat == 0:
        return np.asarray(img01, dtype=np.float32)
    if strength <= 0.0:
        return np.asarray(img01, dtype=np.float32)
    y = np.clip(img @ _RGB_WEIGHTS, 0.0, 1.0)
    ws = _shadow_weight(y, balance)
    wh = 1.0 - ws
    out = img.copy()
    if float(shadows_sat) > 0:
        tint = _hsv_to_rgb(shadows_hue, float(shadows_sat) / 100.0, y)
        w = (ws * float(strength))[..., np.newaxis]
        out = out * (1.0 - w) + tint * w
    if float(highlights_sat) > 0:
        tint = _hsv_to_rgb(highlights_hue, float(highlights_sat) / 100.0, y)
        w = (wh * float(strength))[..., np.newaxis]
        out = out * (1.0 - w) + tint * w
    return np.clip(out, 0.0, 1.0).astype(np.float32)

__all__ = ["split_tone_rgb"]
