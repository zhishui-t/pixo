"""Gate: 肤色掩码/磨皮功能性质。"""
from __future__ import annotations

import numpy as np
import pytest

from render.core.skin import skin_mask, skin_smooth

pytestmark = pytest.mark.gate


def test_mask_range_and_dtype(skin_patch):
    m = skin_mask(skin_patch)
    assert m.dtype == np.float32
    assert m.min() >= 0.0 and m.max() <= 1.0
    assert np.isfinite(m).all()


def test_mask_inside_high_outside_low(skin_patch):
    m = skin_mask(skin_patch)
    assert m[32, 32] >= 0.95
    assert m[2, 2] <= 0.05


def test_smooth_zero_strength_noop(skin_patch):
    out = skin_smooth(skin_patch, np.zeros_like(skin_patch[..., 0], dtype=np.float32), 0.5)
    assert np.array_equal(out, skin_patch)
