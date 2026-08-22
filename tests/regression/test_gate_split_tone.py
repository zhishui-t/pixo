"""Gate: 分离色调功能性质。"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.split_tone import split_tone_rgb

pytestmark = pytest.mark.gate


def test_zero_sat_noop(neutral_gray):
    out = split_tone_rgb(neutral_gray, 45, 0, 210, 0)
    assert np.array_equal(out, neutral_gray.astype(np.float32))


def test_strength_zero_noop(neutral_gray):
    out = split_tone_rgb(neutral_gray, 45, 50, 210, 50, strength=0.0)
    assert np.array_equal(out, neutral_gray.astype(np.float32))


def test_black_highlight_untouched():
    img = np.zeros((4, 4, 3), dtype=np.float32)
    out = split_tone_rgb(img, 45, 50, 210, 50, balance=0.5, strength=1.0)
    assert np.abs(out).max() <= 1e-6


def test_white_highlight_tints():
    img = np.ones((4, 4, 3), dtype=np.float32)
    out = split_tone_rgb(img, 45, 50, 210, 50, balance=0.5, strength=1.0)
    # 高光染色会作用于纯白，输出应偏离白色；同时仍保持在 [0,1]。
    assert np.abs(out - 1.0).max() > 1e-3
    assert out.min() >= 0.0 and out.max() <= 1.0
