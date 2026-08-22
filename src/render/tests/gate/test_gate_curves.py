"""Gate: 曲线/影调性质 + LUT native 等价。"""
from __future__ import annotations

import numpy as np
import pytest

from render import _native as native
from render.core.curves import (apply_lut1d, apply_lut1d_fast,
                                make_base_curve_lut, parse_profile_curve)

pytestmark = pytest.mark.gate


def test_apply_lut1d_matches_interp(random_small):
    lut = np.linspace(0.0, 1.0, 1024, dtype=np.float32)
    out = apply_lut1d(random_small, lut)
    ref = np.interp(random_small, np.linspace(0.0, 1.0, len(lut)), lut)
    assert np.abs(out - ref).max() <= 1e-6


def test_base_lut_monotonic_endpoints():
    for eotf in ("srgb", "power22"):
        lut = make_base_curve_lut(eotf=eotf, gamma=2.2, n=4096)
        assert np.all(np.diff(lut) >= -1e-6)
        assert abs(lut[0]) <= 1e-6
        assert abs(lut[-1] - 1.0) <= 1e-6


def test_non_monotonic_profile_curve_rejected():
    xs = np.array([0.0, 0.5, 0.5, 1.0], dtype=np.float32)
    ys = np.array([0.0, 0.6, 0.4, 1.0], dtype=np.float32)
    assert parse_profile_curve(np.stack([xs, ys], axis=-1).ravel().tolist()) is None


def test_native_tone_lut_matches_fast(random_small):
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    lut = np.linspace(0.0, 1.0, 1024, dtype=np.float32)
    out_n = native.tone_apply_lut1d(random_small, lut)
    out_p = apply_lut1d_fast(random_small, lut)
    assert np.array_equal(out_n, out_p)
