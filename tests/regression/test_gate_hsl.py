"""Gate: HSL 功能性质。"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.hsl import DEFAULT_BANDS, hsl_adjust_rgb

pytestmark = pytest.mark.gate


def test_default_bands_noop(color_steps):
    out = hsl_adjust_rgb(color_steps, DEFAULT_BANDS)
    assert np.array_equal(out, color_steps.astype(np.float32))


def test_neutral_gray_unchanged(neutral_gray):
    bands = [dict(DEFAULT_BANDS[0], saturation=50.0)]
    out = hsl_adjust_rgb(neutral_gray, bands)
    assert np.abs(out - neutral_gray).max() <= 1e-6


def test_red_sat_affects_red_only():
    # 使用低饱和红，确保 saturation 调整可观测；绿色块应不受影响。
    img = np.zeros((2, 1, 3), dtype=np.float32)
    img[0, 0] = (0.8, 0.2, 0.2)
    img[1, 0] = (0.2, 0.8, 0.2)
    bands = [dict(DEFAULT_BANDS[0], saturation=50.0)]
    out = hsl_adjust_rgb(img, bands)
    assert not np.array_equal(out[0, 0], img[0, 0])
    assert np.array_equal(out[1, 0], img[1, 0])


def test_invalid_band_raises():
    with pytest.raises(ValueError):
        hsl_adjust_rgb(np.zeros((4, 4, 3), np.float32), [{"name": "bad"}])
