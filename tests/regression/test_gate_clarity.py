"""Gate: clarity（中频局部对比）功能性质 + native 等价。"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from render import _native as native
from render.core.enhance import _gray, clarity

pytestmark = pytest.mark.gate


def test_strength_zero_is_identity(random_small):
    out = clarity(random_small, strength=0.0)
    assert np.array_equal(out, random_small)


def test_flat_region_mean_and_range_preserved():
    img = np.full((64, 64, 3), 0.5, dtype=np.float32)
    out = clarity(img, strength=0.5)
    assert abs(float(out.mean()) - 0.5) <= 1.0 / 255.0
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0


def test_native_clarity_matches_python(random_small):
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    s = 0.35
    g = _gray(random_small)
    small = cv2.GaussianBlur(g, (0, 0), 0.8).astype(np.float32)
    large = cv2.GaussianBlur(g, (0, 0), 3.0).astype(np.float32)
    out_native = native.clarity_apply(random_small, s, g, small, large)
    out_python = clarity(random_small, strength=s)
    assert np.abs(out_native - out_python).max() <= 1e-6
