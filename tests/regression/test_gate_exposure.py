"""Gate: 曝光功能性质 + native 等价。"""
from __future__ import annotations

import numpy as np
import pytest

from render import _native as native
from render.modules.exposure import soft_highlight_rolloff

pytestmark = pytest.mark.gate


def test_noop_when_ev_zero(gray_ramp):
    img = np.repeat(gray_ramp, 3, axis=1).reshape(256, 1, 3).astype(np.float32)
    out = soft_highlight_rolloff(img * 1.0, knee=1.0)
    assert np.array_equal(out, img)


def test_ev_positive_monotonic(gray_ramp):
    img = np.repeat(gray_ramp, 3, axis=1).reshape(256, 1, 3).astype(np.float32)
    out = soft_highlight_rolloff(img * 2.0, knee=0.9)
    gray = out[..., 0]
    assert np.all(np.diff(gray) >= -1e-6)


def test_native_exposure_matches_python(random_small):
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    ev, knee = 0.7, 0.9
    out_n = native.exposure_apply(random_small, ev=ev, rolloff_knee=knee)
    out_p = soft_highlight_rolloff(random_small * (2.0 ** ev), knee=knee)
    assert np.abs(out_n - out_p).max() <= 1e-6
