"""Gate: 用户 RGB 校准功能性质。"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.usercal import apply_usercal_rgb

pytestmark = pytest.mark.gate


def test_zero_noop(neutral_gray):
    out = apply_usercal_rgb(neutral_gray)
    assert np.array_equal(out, neutral_gray.astype(np.float32))


def test_shadow_tint_affects_dark_only():
    img = np.zeros((8, 8, 3), dtype=np.float32)
    img[0:4, :, :] = 0.05
    img[4:8, :, :] = 0.8
    out = apply_usercal_rgb(img, shadow_tint=50.0)
    assert np.abs(out[4:8] - img[4:8]).max() <= 1e-3
    assert np.abs(out[0:4] - img[0:4]).max() > 1e-3


def test_invalid_raises():
    with pytest.raises(ValueError):
        apply_usercal_rgb(np.zeros((4, 4, 3), np.float32), shadow_tint=200.0)
