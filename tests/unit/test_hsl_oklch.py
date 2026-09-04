"""M-O1 OKLCh 域 8 带调整单元测试 (OWN_PIPELINE_STAGE1_DESIGN §2.2)。

验证: 全 0/空 bands/全掩码零 no-op 逐位、掩码外像素逐位不变 (touch 直通)、
中性灰任何参数不变、单 band 只动目标色相扇区、h 环绕 348°+20° 无跳变、
饱和软限幅严格单调无平台 (C_max(L) tanh 渐近)、luminance 只动 L、
HslStage color_domain 分派 (缺省 hsv 与旧内核逐位一致 = 存量卡零迁移 A1)、
band 级 domain 键混用、非法 domain/色域报错。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from pixo.render.pipeline.graph import StageContext, DOMAIN_GAMMA_RGB
from pixo.render.core.hsl import hsl_adjust_rgb
from pixo.render.core.hsl_oklch import (C_NEUTRAL, DEFAULT_BANDS_OKLCH,
                                        oklch_adjust_rgb)
from pixo.render.core.oklab import (oklab_to_oklch, oklab_to_srgb,
                                    oklch_to_oklab, srgb_to_oklab)
from pixo.render.modules.hsl import HslStage


def _band(**kw):
    base = {"name": "x", "hue_center": 0, "width": 45,
            "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0}
    base.update(kw)
    return base


def _run_stage(params, img):
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    st = HslStage(params={**params, "enabled": True})
    st.run(ctx)
    return ctx.image


def _hue_dist(h, center):
    """到 center 的环状角距 [0,180]。"""
    return np.abs((h - center + 180.0) % 360.0 - 180.0)


# ---------------------------------------------------------------------------
# no-op 逐位纪律
# ---------------------------------------------------------------------------

def test_all_zero_bands_noop_bitwise():
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out = oklch_adjust_rgb(img, DEFAULT_BANDS_OKLCH)   # 全 0 → 快路径逐位一致
    assert out.dtype == np.float32
    assert np.array_equal(out, img)


def test_empty_bands_noop():
    rng = np.random.default_rng(1)
    img = rng.random((8, 8, 3), dtype=np.float32)
    assert np.array_equal(oklch_adjust_rgb(img, []), img)
    assert np.array_equal(oklch_adjust_rgb(img, None), img)


def test_out_of_mask_pixels_bitwise_unchanged():
    """掩码外 (角距 > width) 像素逐位不变——touch 直通, 绕过非逐位可逆的域重建。"""
    rng = np.random.default_rng(0)
    img = rng.random((32, 32, 3), dtype=np.float32)
    band = _band(name="blue", hue_center=264, width=45,
                 hue_shift=-40, saturation=80, luminance=30)
    out = oklch_adjust_rgb(img, [band])
    h = oklab_to_oklch(srgb_to_oklab(img.astype(np.float64)))[..., 2]
    outside = _hue_dist(h, 264) > 45
    assert int(outside.sum()) > 0
    assert np.array_equal(out[outside], img[outside]), "掩码外像素必须逐位不变"
    assert float(np.abs(out[~outside].astype(np.float64)
                        - img[~outside].astype(np.float64)).max()) > 0.05


def test_all_masks_zero_bitwise_passthrough():
    """所有 band 掩码全零 → 原值直通逐位 (即使参数非 0)。"""
    v = np.linspace(0.1, 0.9, 12)
    gray_img = np.stack([v, v, v], axis=-1).astype(np.float32)   # (12,3) 纯灰
    hues = oklab_to_oklch(srgb_to_oklab(gray_img.astype(np.float64)))[..., 2].ravel()
    # 最大环状空档取中点为带中心, 保证所有像素角距 > width
    order = np.sort(hues)
    gaps = np.diff(np.concatenate([order, [order[0] + 360.0]]))
    k = int(gaps.argmax())
    center = float((order[k] + gaps[k] / 2.0) % 360.0)
    band = _band(hue_center=center, width=6, hue_shift=-40, saturation=80, luminance=30)
    dist = _hue_dist(hues, center)
    assert float(dist.min()) > 6.0
    out = oklch_adjust_rgb(gray_img, [band])
    assert np.array_equal(out, gray_img)


def test_neutral_gray_unchanged_any_param():
    """中性灰 (C≈0, protect≈0) 任何强参数逐位不变。"""
    gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
    band = _band(name="red", hue_center=29, width=120,
                 hue_shift=60, saturation=100, luminance=100)
    out = oklch_adjust_rgb(gray, [band])
    assert np.array_equal(out, gray)


# ---------------------------------------------------------------------------
# 单 band 语义
# ---------------------------------------------------------------------------

def test_saturation_only_moves_target_sector():
    """红段 sat 只影响红像素 (C 增), 蓝像素逐位不变。"""
    red = np.array([[[0.8, 0.2, 0.2]]], dtype=np.float32)    # OKLCh h≈29
    blue = np.array([[[0.2, 0.2, 0.8]]], dtype=np.float32)   # OKLCh h≈264
    band = _band(name="red", hue_center=29, width=45, saturation=50)
    h_red = float(oklab_to_oklch(srgb_to_oklab(red.astype(np.float64)))[0, 0, 2])
    assert _hue_dist(np.array([h_red]), 29).item() < 22.5, "红像素应落在红带内"
    out_red = oklch_adjust_rgb(red, [band])
    out_blue = oklch_adjust_rgb(blue, [band])
    assert float(np.abs(out_red - red).max()) > 0.02, "红段应改红像素"
    assert np.array_equal(out_blue, blue), "红段不应改蓝像素"
    c_before = float(oklab_to_oklch(srgb_to_oklab(red.astype(np.float64)))[0, 0, 1])
    c_after = float(oklab_to_oklch(srgb_to_oklab(out_red.astype(np.float64)))[0, 0, 1])
    assert c_after > c_before + 0.01, "sat>0 应提升色度 C"


def test_hue_wrap_348_plus_20_no_jump():
    """h 环绕: 348°+20° → 8° 无跳变 (跨 0/360), L/C 保持。"""
    px = oklab_to_srgb(oklch_to_oklab(np.array([[0.55, 0.08, 348.0]])))   # (1,3) f32
    band = _band(hue_center=348, width=60, hue_shift=20.0)
    out = oklch_adjust_rgb(px, [band])
    lch = oklab_to_oklch(srgb_to_oklab(out.astype(np.float64)))[0]
    assert np.isfinite(out).all()
    assert abs(float(lch[2]) - 8.0) < 0.5, f"h 应环绕到 ≈8° (实际 {lch[2]:.3f})"
    assert abs(float(lch[0]) - 0.55) < 1e-2 and abs(float(lch[1]) - 0.08) < 1e-2


def test_saturation_soft_limit_monotone_no_plateau():
    """sat=100 拉满: C' 严格单调、无硬截断平台、渐近不超 C_max(L)。"""
    from pixo.render.core.hsl_oklch import _cmax_of_l
    cs = [0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    pxs = oklab_to_srgb(oklch_to_oklab(np.array([[0.5, c, 264.0] for c in cs])))
    band = _band(name="blue", hue_center=264, width=90, saturation=100.0)
    out = oklch_adjust_rgb(pxs, [band])
    c_out = oklab_to_oklch(srgb_to_oklab(out.astype(np.float64)))[:, 1]
    assert np.isfinite(c_out).all()
    diffs = np.diff(c_out)
    assert bool((diffs > 1e-3).all()), f"应严格单调无平台 (实际 {c_out.tolist()})"
    assert float(c_out.max()) <= float(_cmax_of_l(np.array([0.5]))[0]) + 1e-6, \
        "软限幅渐近不得超过 C_max(L)"


def test_luminance_scales_l_only():
    """lum>0 只抬 L, hue/色度近似不变; 输出始终 [0,1]。"""
    px = oklab_to_srgb(oklch_to_oklab(np.array([[0.4, 0.08, 264.0]])))   # (1,3) f32
    band = _band(hue_center=264, width=60, luminance=40.0)
    out = oklch_adjust_rgb(px, [band])
    lch = oklab_to_oklch(srgb_to_oklab(out.astype(np.float64)))[0]
    assert float(lch[0]) > 0.45, "lum=+40 应显著抬升 L"
    assert abs(float(lch[2]) - 264.0) < 1.0, "lum 不应改 h"
    assert abs(float(lch[1]) - 0.08) < 2e-3, "lum 不应改 C"
    assert bool((out >= 0.0).all() and (out <= 1.0).all())


def test_output_dtype_range_finite():
    rng = np.random.default_rng(3)
    img = rng.random((16, 16, 3), dtype=np.float32)
    bands = [_band(name="blue", hue_center=264, width=45,
                   hue_shift=-40, saturation=80, luminance=30)]
    out = oklch_adjust_rgb(img, bands)
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert bool((out >= 0.0).all() and (out <= 1.0).all())


# ---------------------------------------------------------------------------
# HslStage color_domain 分派 (band schema v2 / A1)
# ---------------------------------------------------------------------------

_B2 = [{"name": "red", "hue_center": 0, "width": 45,
        "hue_shift": 25, "saturation": 40, "luminance": -20}]


def test_stage_default_hsv_bitwise_identical_to_old_kernel():
    """缺省 color_domain=hsv: Stage 输出与旧 hsl_adjust_rgb 逐位一致 (A1 硬约束)。"""
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out = _run_stage({"bands": json.dumps(_B2)}, img)
    ref = hsl_adjust_rgb(img.astype(np.float64), _B2, smooth=1.0)
    assert np.array_equal(out, ref)


def test_stage_color_domain_oklch_dispatch():
    """color_domain=oklch: 分派到 oklch_adjust_rgb (逐位一致), 且与 hsv 结果不同。"""
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out_hsv = _run_stage({"bands": json.dumps(_B2)}, img)
    out_oklch = _run_stage({"bands": json.dumps(_B2), "color_domain": "oklch"}, img)
    ref = oklch_adjust_rgb(img.astype(np.float64), _B2, smooth=1.0)
    assert np.array_equal(out_oklch, ref)
    assert not np.array_equal(out_oklch, out_hsv), "两域结果应可区分"


def test_stage_band_domain_key_mixed():
    """band 级 domain 键逐段覆盖 Stage 缺省: hsv 段走旧内核 + oklch 段走新内核。"""
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    mixed = [{"name": "r", "hue_center": 0, "width": 45,
              "hue_shift": 25, "saturation": 40, "luminance": 0.0, "domain": "hsv"},
             {"name": "b", "hue_center": 264, "width": 45,
              "hue_shift": 0.0, "saturation": 50, "luminance": 0.0, "domain": "oklch"}]
    out = _run_stage({"bands": json.dumps(mixed)}, img)
    manual = oklch_adjust_rgb(
        hsl_adjust_rgb(img.astype(np.float64), [mixed[0]]).astype(np.float32),
        [mixed[1]])
    assert np.array_equal(out, manual)


def test_stage_bands_none_oklch_uses_default_bands():
    """bands=None + color_domain=oklch → DEFAULT_BANDS_OKLCH (全 0 → no-op 逐位)。"""
    rng = np.random.default_rng(2)
    img = rng.random((8, 8, 3), dtype=np.float32)
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    st = HslStage(params={"enabled": True, "color_domain": "oklch"})
    st.run(ctx)
    assert np.array_equal(ctx.image, img)
    assert ctx.results[-1].metrics["hsl_bands"] == len(DEFAULT_BANDS_OKLCH)


def test_stage_disabled_noop():
    img = np.full((8, 8, 3), 0.5, dtype=np.float32)
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img, DOMAIN_GAMMA_RGB)
    st = HslStage()
    assert st.wants(ctx) is False
    ctx2 = StageContext("t", prof=None, config={})
    ctx2.set_image(img, DOMAIN_GAMMA_RGB)
    st.run(ctx2)
    assert np.array_equal(ctx2.image, img)


@pytest.mark.parametrize("bad_params", [
    {"bands": json.dumps([dict(_band(hue_shift=1.0), domain="lab")])},   # band 级非法
    {"bands": json.dumps(_B2), "color_domain": "lab"},                   # Stage 级非法
])
def test_stage_invalid_domain_raises(bad_params):
    rng = np.random.default_rng(4)
    img = rng.random((4, 4, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        _run_stage(bad_params, img)


def test_kernel_rejects_out_of_range_band():
    """内核复用 hsl 的 band 校验 (width/hue_shift 界)。"""
    img = np.full((2, 2, 3), 0.5, dtype=np.float32)
    with pytest.raises(ValueError):
        oklch_adjust_rgb(img, [_band(width=3, saturation=10)])
    with pytest.raises(ValueError):
        oklch_adjust_rgb(img, [_band(hue_shift=200)])
