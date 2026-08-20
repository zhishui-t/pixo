"""T2.1 人工 HSL 八色段 Stage/纯函数 单元测试。

验证: 全 0/禁用 no-op、中性灰不变、饱和度只影响所选色段、hue_shift 不改 V、
luminance 不改 H、掩码环状 0/360 连续、缺省结构、越界报错、smooth 0/1 差异且
无 NaN、随机图 clip [0,1]。
"""
from __future__ import annotations

import numpy as np
import pytest

from rawlab.engine.core import StageContext, DOMAIN_GAMMA_RGB, DOMAIN_LINEAR_RGB
from rawlab.engine.hsl import hsl_adjust_rgb, DEFAULT_BANDS, _ring_mask
from rawlab.engine.huesat import _rgb_to_hsv
from rawlab.engine.stages.hsl import HslStage


def _band(**kw):
    base = {"name": "x", "hue_center": 0, "width": 45,
            "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0}
    base.update(kw)
    return base


def test_disabled_stage_noop():
    img = np.full((8, 8, 3), 0.5, dtype=np.float32)
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img, DOMAIN_GAMMA_RGB)
    # 默认 enabled=False → wants False, process 不执行
    st = HslStage()
    assert st.wants(ctx) is False
    ctx2 = StageContext("t", prof=None, config={})
    ctx2.set_image(img, DOMAIN_GAMMA_RGB)
    st.run(ctx2)
    assert np.array_equal(ctx2.image, img)


def test_all_zero_bands_noop():
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out = hsl_adjust_rgb(img, DEFAULT_BANDS)      # 全 0 → 快路径逐位一致
    assert out.dtype == np.float32
    assert np.array_equal(out, img)


def test_bands_none_noop():
    rng = np.random.default_rng(1)
    img = rng.random((8, 8, 3), dtype=np.float32)
    out = hsl_adjust_rgb(img, [])
    assert np.array_equal(out, img)


def test_neutral_gray_unchanged_any_param():
    gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
    # 红段拉满(色相/饱和/明度都动, 但中性灰 S=0 → 不变)
    bands = [{"name": "red", "hue_center": 0, "width": 90,
              "hue_shift": 60, "saturation": 100, "luminance": 100}]
    out = hsl_adjust_rgb(gray, bands)
    assert np.array_equal(out, gray.astype(np.float32))


def test_sat_only_affects_selected_segment():
    # 红像素 (H≈0) 与 蓝像素 (H≈240): 红段 sat 只影响红
    red = np.array([[[0.8, 0.2, 0.2]]], dtype=np.float32)   # H≈0
    blue = np.array([[[0.2, 0.2, 0.8]]], dtype=np.float32)  # H≈240
    bands = [_band(name="red", hue_center=0, saturation=100)]
    out_red = hsl_adjust_rgb(red, bands)[0, 0]
    out_blue = hsl_adjust_rgb(blue, bands)[0, 0]
    assert float(np.abs(out_red - red[0, 0]).max()) > 0.05, "红段应改红像素"
    assert float(np.abs(out_blue - blue[0, 0]).max()) < 1e-2, "红段不应改蓝像素"
    # 红像素饱和上升
    _, s_before, _ = _rgb_to_hsv(red.astype(np.float64))
    _, s_after, _ = _rgb_to_hsv(out_red[None, None].astype(np.float64))
    assert float(s_after[0, 0]) > float(s_before[0, 0]) + 0.05


def test_hue_shift_preserves_value():
    rgb = np.array([[[0.8, 0.2, 0.2]]], dtype=np.float32)   # V=0.8
    bands = [_band(name="red", hue_center=0, hue_shift=30)]
    out = hsl_adjust_rgb(rgb, bands)[0, 0]
    # hue_shift 不改 V ⇒ 输出最大通道 ≈ 输入 V = 0.8
    assert float(out.max()) == pytest.approx(0.8, abs=1e-4)


def test_luminance_preserves_hue():
    rgb = np.array([[[0.6, 0.3, 0.2]]], dtype=np.float32)
    bands = [_band(name="orange", hue_center=30, width=90, luminance=60)]
    out = hsl_adjust_rgb(rgb, bands)[0, 0]
    h_in = float(_rgb_to_hsv(rgb.astype(np.float64))[0][0, 0])
    h_out = float(_rgb_to_hsv(out[None, None].astype(np.float64))[0][0, 0])
    # luminance 只改 V ⇒ H 不变
    assert abs(h_out - h_in) < 1e-3 or abs((h_out - h_in) % 360.0) < 1e-3


def test_ring_mask_wraparound():
    h = np.array([1.0, 359.0, 180.0], dtype=np.float64)
    m = _ring_mask(h, center=0.0, width=45.0, smooth=1.0)
    assert float(m[0] - m[1]) < 1e-6, "0/360 环绕掩码应一致"
    assert float(m[0]) > 0.9, "center 掩码应≈1"
    assert float(m[2]) < 1e-6, "对侧(180°)掩码应≈0"


def test_default_bands_structure():
    assert len(DEFAULT_BANDS) == 8
    centers = [0, 30, 60, 120, 180, 240, 270, 300]
    for b, c in zip(DEFAULT_BANDS, centers):
        assert set(("height_center",))  # no-op
        for k in ("hue_center", "width", "hue_shift", "saturation", "luminance"):
            assert k in b
        assert float(b["hue_center"]) == c, c
        assert 5.0 <= float(b["width"]) <= 180.0
        # 默认全 0
        assert b["hue_shift"] == 0.0 and b["saturation"] == 0.0 and b["luminance"] == 0.0


def test_out_of_range_width_raises():
    with pytest.raises(ValueError, match="width"):
        hsl_adjust_rgb(np.zeros((1, 1, 3), np.float32),
                       [_band(name="x", width=300.0)])


def test_out_of_range_hue_shift_raises():
    with pytest.raises(ValueError, match="hue_shift"):
        hsl_adjust_rgb(np.zeros((1, 1, 3), np.float32),
                       [_band(name="x", hue_shift=200.0)])


def test_out_of_range_saturation_luminance_raises():
    with pytest.raises(ValueError, match="saturation"):
        hsl_adjust_rgb(np.zeros((1, 1, 3), np.float32), [_band(name="x", saturation=150)])
    with pytest.raises(ValueError, match="luminance"):
        hsl_adjust_rgb(np.zeros((1, 1, 3), np.float32), [_band(name="x", luminance=-120)])


def test_missing_band_key_raises():
    with pytest.raises(ValueError, match="必填键"):
        hsl_adjust_rgb(np.zeros((1, 1, 3), np.float32), [{"name": "x"}])


def test_smooth_0_vs_1_differs_no_nan():
    # 彩色图 (各色相不同饱和): smooth 影响掩码边界锐度, 0/1 应有差异且无 NaN
    rng = np.random.default_rng(3)
    img = rng.random((16, 16, 3), dtype=np.float32)
    bands = [_band(name="red", hue_center=0, saturation=60)]
    o0 = hsl_adjust_rgb(img, bands, smooth=0.0)
    o1 = hsl_adjust_rgb(img, bands, smooth=1.0)
    assert np.isfinite(o0).all() and np.isfinite(o1).all()
    assert not np.array_equal(o0, o1), "smooth 0/1 应有差异"


def test_random_image_output_in_unit():
    rng = np.random.default_rng(7)
    img = rng.random((32, 32, 3), dtype=np.float32)
    bands = [_band(name="red", hue_center=0, hue_shift=20, saturation=40, luminance=30)]
    out = hsl_adjust_rgb(img, bands, smooth=1.0)
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0


def test_stage_wants_only_enabled():
    img = np.zeros((4, 4, 3), np.float32)
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img, DOMAIN_GAMMA_RGB)
    off = HslStage({"enabled": False})
    on = HslStage({"enabled": True})
    assert off.wants(ctx) is False
    assert on.wants(ctx) is True


def test_stage_process_with_bands():
    import json
    # 红 tensor 图: 用红像素 (非灰) 确认 stage 真的改了
    red = np.zeros((4, 4, 3), np.float32)
    red[..., 0], red[..., 1], red[..., 2] = 0.9, 0.1, 0.1
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(red, DOMAIN_GAMMA_RGB)
    # bands 走 float_or_str: 用 JSON 字符串传结构化 band 列表
    bands_json = json.dumps([_band(name="red", hue_center=0, saturation=60)])
    HslStage({"enabled": True, "bands": bands_json}).run(ctx)
    assert ctx.domain == DOMAIN_GAMMA_RGB
    # stage 真正执行: 饱和提升改变输出 (且有限)
    assert not np.array_equal(ctx.image, red)
    assert np.isfinite(ctx.image).all()
