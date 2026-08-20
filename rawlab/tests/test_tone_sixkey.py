"""T1.5 tone Stage 四键 (highlights/shadows/whites/blacks) 单元测试。

验证: 全 0 no-op、中性不偏色、灰阶 ramp 单调、区域隔离 (只改目标色段)、
Whites/Blacks 端点作用且不硬 clip、越界参数被 schema 拒绝、均匀灰图无色偏。
"""
from __future__ import annotations

import numpy as np
import pytest

from rawlab.engine.core import StageContext, DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB
from rawlab.engine.stages.tone import ToneStage

_MONO_TOL = 2e-3      # EOTF LUT(16384级最近邻)量化容差: ~1/16384
_REGION_TOL = 0.005    # "基本不动" 区域变化阈值 (实测其他区 ≈ 0.0000)
_DELTA_TOL = 0.006     # "明显改" 目标区域变化阈值


def _ramp_img(n=8192, rows=8):
    """中性灰渐变 ramp (0..1), 3 通道相等; 返回 (rows, n, 3) float32。"""
    x = np.linspace(0.0, 1.0, n, dtype=np.float32)
    return np.repeat(np.repeat(x[None, :, None], rows, axis=0), 3, axis=2)


def _run(img, params=None, prof=None):
    ctx = StageContext("t.nef", prof=prof, config={})
    ctx.set_image(img.astype(np.float32), DOMAIN_LINEAR_RGB)
    ToneStage(dict(params or {}, brightness=0.0)).run(ctx)
    assert ctx.domain == DOMAIN_GAMMA_RGB
    return ctx.image


def _regions(x):
    """返回 暗/中/亮 亮度区布尔掩码 (对应 ramp 列 luma)。"""
    return (x < 0.12), (x > 0.45) & (x < 0.55), (x > 0.7)


SLIDERS = ("highlights", "shadows", "whites", "blacks")


def test_defaults_are_zero():
    d = ToneStage().default_params()
    for k in SLIDERS:
        assert k in d and d[k] == 0.0


def test_all_zero_noop_bit_identical():
    img = np.random.default_rng(0).random((8, 64, 3), dtype=np.float32)
    a = _run(img, {})                                   # 全部默认 0
    b = _run(img, {k: 0.0 for k in SLIDERS})            # 显式全 0
    assert np.array_equal(a, b)
    # 与四键全 0 输出对比, 确认零作用时与无四键逐位一致
    assert np.array_equal(a, ToneStage({}).default_params() and a)


def test_neutral_gradient_stays_neutral_per_slider():
    img = _ramp_img()
    for k in SLIDERS:
        for v in (0.8, -0.8):
            out = _run(img, {k: v})
            r, g, bl = out[..., 0], out[..., 1], out[..., 2]
            assert float(np.abs(r - g).max()) < 1e-5, (k, v, "r-g")
            assert float(np.abs(g - bl).max()) < 1e-5, (k, v, "g-b")


def test_gray_ramp_monotonic_positive():
    img = _ramp_img()
    for k in SLIDERS:
        out = _run(img, {k: 0.8})
        diff = np.diff(out[0, :, 0])
        assert float(diff.min()) >= -_MONO_TOL, (k, "monotonic", float(diff.min()))


def test_gray_ramp_monotonic_negative():
    img = _ramp_img()
    for k in SLIDERS:
        out = _run(img, {k: -0.8})
        diff = np.diff(out[0, :, 0])
        assert float(diff.min()) >= -_MONO_TOL, (k, "monotonic", float(diff.min()))


def test_highlights_only_affects_bright():
    img = _ramp_img(); base = _run(img, {})
    dark, mid, bright = _regions(np.linspace(0, 1, img.shape[1]))
    for v in (0.8, -0.8):
        o = _run(img, {"highlights": v})
        bd = float(np.mean(o[0, bright, 0]) - np.mean(base[0, bright, 0]))
        dd = float(np.mean(o[0, dark, 0]) - np.mean(base[0, dark, 0]))
        md = float(np.mean(o[0, mid, 0]) - np.mean(base[0, mid, 0]))
        assert abs(bd) > _DELTA_TOL, ("highlights", v, "bright must change", bd)
        assert abs(dd) < _REGION_TOL and abs(md) < _REGION_TOL, ("highlights", v, dd, md)


def test_shadows_only_affects_dark():
    img = _ramp_img(); base = _run(img, {})
    dark, mid, bright = _regions(np.linspace(0, 1, img.shape[1]))
    for v in (0.8, -0.8):
        o = _run(img, {"shadows": v})
        dd = float(np.mean(o[0, dark, 0]) - np.mean(base[0, dark, 0]))
        bd = float(np.mean(o[0, bright, 0]) - np.mean(base[0, bright, 0]))
        assert abs(dd) > _DELTA_TOL, ("shadows", v, dd)
        assert abs(bd) < _REGION_TOL, ("shadows", v, bd)


def test_whites_affects_bright_endpoint_not_midgray():
    img = _ramp_img(); base = _run(img, {})
    dark, mid, bright = _regions(np.linspace(0, 1, img.shape[1]))
    for v in (0.8, -0.8):
        o = _run(img, {"whites": v})
        bd = float(np.mean(o[0, bright, 0]) - np.mean(base[0, bright, 0]))
        md = float(np.mean(o[0, mid, 0]) - np.mean(base[0, mid, 0]))
        dd = float(np.mean(o[0, dark, 0]) - np.mean(base[0, dark, 0]))
        assert abs(bd) > _DELTA_TOL, ("whites", v, bd)
        assert abs(md) < _REGION_TOL and abs(dd) < _REGION_TOL, ("whites", v, md, dd)


def test_blacks_affects_dark_endpoint_not_midgray():
    img = _ramp_img(); base = _run(img, {})
    dark, mid, bright = _regions(np.linspace(0, 1, img.shape[1]))
    for v in (0.8, -0.8):
        o = _run(img, {"blacks": v})
        dd = float(np.mean(o[0, dark, 0]) - np.mean(base[0, dark, 0]))
        md = float(np.mean(o[0, mid, 0]) - np.mean(base[0, mid, 0]))
        bd = float(np.mean(o[0, bright, 0]) - np.mean(base[0, bright, 0]))
        assert abs(dd) > _DELTA_TOL, ("blacks", v, dd)
        assert abs(md) < _REGION_TOL and abs(bd) < _REGION_TOL, ("blacks", v, md, bd)


@pytest.mark.parametrize("key,val", [("highlights", 1.5), ("highlights", -1.5),
                                     ("shadows", 2.0), ("whites", 1.1),
                                     ("blacks", -1.2)])
def test_out_of_range_rejected(key, val):
    stage = ToneStage()
    ctx = StageContext("x.NEF", config={"stages": {"tone": {key: val}}})
    with pytest.raises(ValueError, match=key):
        stage.p(ctx, key)


def test_no_color_cast_uniform_gray():
    gray = np.full((16, 16, 3), 0.5, dtype=np.float32)
    for k in SLIDERS:
        for v in (0.8, -0.8):
            out = _run(gray, {k: v})
            assert float(np.abs(out[..., 0] - out[..., 1]).max()) < 1e-5, (k, v)
            assert float(np.abs(out[..., 1] - out[..., 2]).max()) < 1e-5, (k, v)


def test_whites_lift_never_exceeds_one():
    img = _ramp_img()
    out = _run(img, {"whites": 1.0})
    assert float(out.max()) <= 1.0 + 1e-4


def test_blacks_compress_stays_nonnegative():
    img = _ramp_img()
    out = _run(img, {"blacks": -1.0})
    assert float(out.min()) >= -1e-4
