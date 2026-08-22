"""Gate: huesat（HueSatMap 域 + 局部暖高光饱和）功能性质 + native 等价。"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render import _native as native
from pixo.render.core.huesat import apply_local_warm_sat

pytestmark = pytest.mark.gate


def test_noop_when_scales_one(neutral_gray):
    out = apply_local_warm_sat(neutral_gray, sat_scale=1.0, spot_sat_scale=1.0)
    assert np.array_equal(out, neutral_gray)


def test_neutral_gray_unchanged(neutral_gray):
    out = apply_local_warm_sat(neutral_gray, sat_scale=3.0, spot_sat_scale=3.0,
                               hue_center=22.5, hue_halfwidth=17.5,
                               sat_min=0.05, val_min=0.6, coverage_max=0.0015)
    assert np.array_equal(out, neutral_gray)


def test_warm_highlight_enhanced_dark_background_untouched(warm_highlight):
    out = apply_local_warm_sat(warm_highlight, sat_scale=2.0,
                               spot_sat_scale=2.0, hue_center=22.5,
                               hue_halfwidth=17.5, sat_min=0.05, val_min=0.6,
                               coverage_max=0.0015)
    patch = out[28:36, 28:36]
    bg = out.copy()
    bg[28:36, 28:36] = warm_highlight[28:36, 28:36]
    assert float(patch.max()) > float(warm_highlight[28:36, 28:36].max())
    assert np.abs(bg - warm_highlight).max() <= 1e-6


def test_native_warm_sat_matches_fallback(monkeypatch, random_small):
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    img = random_small.copy()
    img[8:12, 8:12] = (0.9, 0.3, 0.05)
    kwargs = dict(sat_scale=2.0, spot_sat_scale=2.0, hue_center=22.5,
                  hue_halfwidth=17.5, sat_min=0.05, val_min=0.6,
                  coverage_max=0.0015)
    out_native = apply_local_warm_sat(img, **kwargs)

    old_lib, old_error = native._lib, native._load_error
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated fallback")
    out_python = apply_local_warm_sat(img, **kwargs)
    monkeypatch.setattr(native, "_lib", old_lib)
    monkeypatch.setattr(native, "_load_error", old_error)
    assert np.abs(out_native - out_python).max() <= 1e-6
