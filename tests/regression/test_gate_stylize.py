"""Gate: stylize（3D LUT 风格化）功能性质。"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.lut3d import LUT3D

pytestmark = pytest.mark.gate


def _identity_lut(n=2):
    g = np.linspace(0.0, 1.0, n, dtype=np.float32)
    r, gg, b = np.meshgrid(g, g, g, indexing="ij")
    return LUT3D(np.stack([r, gg, b], axis=-1))


def test_identity_lut_is_identity(color_steps):
    u8 = (np.clip(color_steps, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    out = _identity_lut().apply(u8, strength=1.0)
    assert np.abs(out.astype(np.int16) - u8.astype(np.int16)).max() <= 1


def test_zero_strength_returns_input(color_steps):
    u8 = (np.clip(color_steps, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    out = _identity_lut().apply(u8, strength=0.0)
    assert np.array_equal(out, u8)


def test_invalid_lut_shape_rejected():
    with pytest.raises(ValueError):
        LUT3D(np.zeros((2, 2, 3, 3), dtype=np.float32))
