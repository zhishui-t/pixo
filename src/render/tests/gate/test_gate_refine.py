"""Gate: 精修 native 端点/无参性质。"""
from __future__ import annotations

import numpy as np
import pytest

from render import _native as native
from render.modules.refine import apply_warm_sat_gamma

pytestmark = pytest.mark.gate


def test_refine_sat_protection_endpoints():
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    rgb = np.zeros((4, 4, 3), dtype=np.float32)
    rgb[0, 0] = (0.5, 0.5, 0.5)
    rgb[1, 1] = (1.0, 0.0, 0.0)
    sat = native.refine_sat_protection(rgb)
    assert abs(sat[0, 0] - 0.0) <= 1e-6
    assert abs(sat[1, 1] - 1.0) <= 1e-6


def test_warm_sat_gamma_noop():
    img = np.random.default_rng(0).random((8, 8, 3), dtype=np.float32)
    out = apply_warm_sat_gamma(img, np.array([1.0, 1.0, 1.0, 1.0]))
    assert np.array_equal(out, img)
