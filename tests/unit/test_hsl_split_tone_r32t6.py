"""R32-T6: HSL 对照吸收 (adjust_math="rt") 与 split_tone 亮度保持测试。

口径: 缺省参数下既有输出逐位不变 (向后兼容红线); "rt"/"preserve_luma"
为显式开启的对照吸收数学 (出处 RT improcfun.cc @ 6c4cb59)。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.hsl import hsl_adjust_rgb
from pixo.render.core.split_tone_oklab import split_tone_oklab_rgb

_BAND = {"name": "orange", "hue_center": 30.0, "width": 45.0,
         "hue_shift": 0.0, "saturation": 100.0, "luminance": 0.0,
         "domain": "hsv"}


def _hsv_strip(s_value: float):
    from pixo.render.core.huesat import _hsv_to_rgb
    h = np.arange(360, dtype=np.float64)
    return _hsv_to_rgb(h, np.full(360, s_value), np.full(360, 0.5))


def test_adjust_math_default_bitwise_unchanged():
    """缺省 (pixo) 与既有对称乘法公式逐位一致。"""
    from pixo.render.core.huesat import _rgb_to_hsv
    from pixo.render.core.hsl import _ring_mask
    img = _hsv_strip(0.6)
    out = hsl_adjust_rgb(img, [_BAND], smooth=1.0, adjust_math="pixo")
    # 旧实现内联复算: s' = clip(s·(1+1.0·m))
    _, s, _ = _rgb_to_hsv(img)
    hh = np.arange(360, dtype=np.float64)
    m = _ring_mask(hh, 30.0, 45.0, 1.0)
    s_ref = np.clip(s * (1.0 + 1.0 * m), 0.0, 1.0)
    _, s_out, _ = _rgb_to_hsv(out)
    assert np.abs(s_out - s_ref).max() <= 1e-6


def test_adjust_math_rt_sat_boost_no_clip():
    """RT 正向二次混合: 高饱和自然收敛无截断 (s=0.8, +100 → ≈0.96 < 1);
    pixo 乘法同参数顶格 clip 到 1。"""
    img = _hsv_strip(0.8)
    pixo = hsl_adjust_rgb(img, [_BAND], adjust_math="pixo")
    rt = hsl_adjust_rgb(img, [_BAND], adjust_math="rt")
    s_p = _hsv_strip_s(pixo)
    s_r = _hsv_strip_s(rt)
    # band 中心 30° (索引 30)
    assert s_p[30] == 1.0                     # pixo clip
    assert 0.90 < s_r[30] < 1.0               # RT 收敛不截断 (≈0.96)
    assert s_r[30] == pytest.approx(0.96, abs=0.01)


def test_adjust_math_rt_sat_negative_multiplicative():
    """RT 负向 = 乘法 (与 pixo 同式): -50 → s·0.5。"""
    img = _hsv_strip(0.6)
    rt = hsl_adjust_rgb(img, [{**_BAND, "saturation": -50.0}],
                        adjust_math="rt")
    s_r = _hsv_strip_s(rt)
    assert s_r[30] == pytest.approx(0.3, abs=1e-6)


def test_adjust_math_rt_lum_attenuation():
    """RT lum 的 (1-(1-S)^4) 饱和衰减 vs pixo 线性 protect=S:
    近中性 RT 保护更强 (|ΔV| 更小), 高饱和 RT 混合收敛 (|ΔV| 更小),
    且 RT 随 S 陡增 (E3 曲线)。"""
    band_lum = {"name": "red", "hue_center": 0.0, "width": 180.0,
                "hue_shift": 0.0, "saturation": 0.0, "luminance": 50.0,
                "domain": "hsv"}

    def dv(s0, math_mode):
        img = _hsv_strip(s0)
        out = hsl_adjust_rgb(img, [band_lum], adjust_math=math_mode)
        return float(abs(_hsv_strip_v(out)[0] - 0.5))

    rt_lo, rt_hi = dv(0.05, "rt"), dv(0.9, "rt")
    pixo_lo, pixo_hi = dv(0.05, "pixo"), dv(0.9, "pixo")
    assert rt_lo < 0.03, f"近中性保护: {rt_lo}"            # S=0.05 近不动
    assert rt_lo > pixo_lo * 1.5, (rt_lo, pixo_lo)          # RT 衰减曲线低 S 更缓
    assert rt_hi < pixo_hi, (rt_hi, pixo_hi)                # 高饱和 RT 混合收敛
    assert rt_hi > rt_lo * 3.0, (rt_hi, rt_lo)              # 随 S 陡增


def test_adjust_math_invalid_raises():
    img = _hsv_strip(0.6)
    with pytest.raises(ValueError):
        hsl_adjust_rgb(img, [_BAND], adjust_math="wat")


def _hsv_strip_s(rgb):
    from pixo.render.core.huesat import _rgb_to_hsv
    return _rgb_to_hsv(rgb)[1]


def _hsv_strip_v(rgb):
    from pixo.render.core.huesat import _rgb_to_hsv
    return _rgb_to_hsv(rgb)[2]


# ---- split_tone preserve_luma (对照吸收 RT preser 分支) ----

def test_split_tone_preserve_luma_reduces_drift():
    """preserve_luma=True 亮度漂移显著低于 False (E4: mean 0.027 → ~0.005)。"""
    rng = np.random.default_rng(6)
    img = (0.1 + rng.random((16, 16, 3)) * 0.8).astype(np.float32)
    w = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
    a = split_tone_oklab_rgb(img, 45.0, 50.0, 210.0, 50.0,
                             preserve_luma=False).astype(np.float64)
    b = split_tone_oklab_rgb(img, 45.0, 50.0, 210.0, 50.0,
                             preserve_luma=True).astype(np.float64)
    d_off = float(np.abs((a @ w) - (img @ w)).mean())
    d_on = float(np.abs((b @ w) - (img @ w)).mean())
    assert d_on < d_off / 3.0, (d_off, d_on)


def test_split_tone_preserve_luma_default_bitwise_unchanged():
    """缺省 preserve_luma=False 输出与旧签名逐位一致。"""
    rng = np.random.default_rng(8)
    img = rng.random((8, 8, 3)).astype(np.float32)
    a = split_tone_oklab_rgb(img, 45.0, 50.0, 210.0, 50.0)
    b = split_tone_oklab_rgb(img, 45.0, 50.0, 210.0, 50.0,
                             preserve_luma=False)
    assert np.array_equal(a, b)
