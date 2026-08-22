"""Gate: 白平衡相关性质 + Matrix native 等价。"""
from __future__ import annotations

import numpy as np
import pytest

from render import _native as native
from render.core.color import temp_tint_to_wb

pytestmark = pytest.mark.gate


class _FakeProf:
    color_matrix1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449,
                     -0.0231, 0.0811, 0.7571]
    color_matrix2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286,
                     -0.0648, 0.1513, 0.6375]
    forward_matrix1 = None
    forward_matrix2 = None
    camera_calibration1 = None
    camera_calibration2 = None
    calibration_illuminant1 = 17
    calibration_illuminant2 = 21


def test_temp_tint_to_wb_returns_g1():
    wb = temp_tint_to_wb(_FakeProf(), 5500.0, 0.0)
    assert abs(wb[1] - 1.0) < 1e-6


def test_native_matrix_apply3_matches_python(random_small):
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    m = np.array([[1.1, -0.2, 0.05],
                  [0.1, 0.9, -0.1],
                  [-0.05, 0.2, 1.2]], dtype=np.float32)
    out_n = native.matrix_apply3(random_small, m)
    out_p = (random_small.reshape(-1, 3) @ m.T).reshape(random_small.shape)
    assert np.abs(out_n - out_p).max() <= 1e-6
