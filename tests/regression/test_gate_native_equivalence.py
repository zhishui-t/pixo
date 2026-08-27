"""Gate: L1 native 等价汇总。"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from pixo.render import _native as native
from pixo.render.core.curves import apply_lut1d_fast
from pixo.render.core.enhance import _gray, clarity
from pixo.render.core.lut3d import LUT3D
from pixo.render.modules.exposure import soft_highlight_rolloff

pytestmark = pytest.mark.gate


def test_native_available_is_required():
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")


def test_exposure_native_equiv(random_small):
    ev, knee = 0.5, 0.9
    out_n = native.exposure_apply(random_small, ev=ev, rolloff_knee=knee)
    out_p = soft_highlight_rolloff(random_small * (2.0 ** ev), knee=knee)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_matrix_native_equiv(random_small):
    m = np.eye(3, dtype=np.float32)
    assert np.abs(native.matrix_apply3(random_small, m) - random_small).max() <= 1e-6


def test_tone_native_equiv(random_small):
    lut = np.linspace(0.0, 1.0, 1024, dtype=np.float32)
    assert np.array_equal(native.tone_apply_lut1d(random_small, lut),
                          apply_lut1d_fast(random_small, lut))


def test_clarity_native_equiv(random_small):
    s = 0.3
    g = _gray(random_small)
    small = cv2.GaussianBlur(g, (0, 0), 0.8).astype(np.float32)
    large = cv2.GaussianBlur(g, (0, 0), 3.0).astype(np.float32)
    out_n = native.clarity_apply(random_small, s, g, small, large)
    out_p = clarity(random_small, strength=s)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_lut3d_native_equiv(random_small):
    """v1.3.0 lut3d 四面体内核 vs LUT3D.lookup (numpy 参考)。"""
    n = 17
    rng = np.random.default_rng(20260826)
    data = rng.random((n, n, n, 3), dtype=np.float32) * 1.1 - 0.05
    lut = LUT3D(data, domain_min=0.1, domain_max=0.9)
    img = np.clip(random_small, -0.2, 1.2)   # 覆盖 DOMAIN 窗口外截断
    out_n = lut.apply_f32(img, strength=0.6)
    ref = lut.lookup(img)
    ref = img * (1.0 - 0.6) + ref * 0.6
    assert np.abs(out_n - ref.astype(np.float32)).max() <= 1e-6
