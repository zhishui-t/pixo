"""M5: 原生 HSV 内核 vs Python 参考实现的数值等价测试。

验收 (PIXO_RENDER_NATIVE_TEST_PLAN §6.3):
  - float64: max|Δ| = 0 (逐位一致)
  - float32: max|Δ| ≤ 1e-6
"""
from __future__ import annotations

import numpy as np
import pytest

from render.core.huesat import _hsv_to_rgb, _rgb_to_hsv
from render import _native as native

F64_TOL = 0.0
F32_TOL = 1e-6


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 HSV 数值等价测试")


def _random_rgb(shape=(64, 64, 3), dtype=np.float64, seed=20260820):
    rng = np.random.default_rng(seed)
    x = rng.random(shape).astype(dtype)
    # 加入 >1 线性高光与边界值, 覆盖 HSV 分支
    x.flat[::97] = np.linspace(0.0, 2.0, x.size // 3, dtype=dtype)[:len(x.flat[::97])]
    return x


def _edge_rgb():
    vals = [0.0, 1.0, 0.5, 0.0031308, 0.04045, 1.5, 2.0]
    arr = np.array([[r, g, b] for r in vals for g in vals for b in vals],
                   dtype=np.float64)
    return arr.reshape(7, 7, 7, 3)


def test_float64_rgb_to_hsv_bitwise(native_required):
    x = _random_rgb(dtype=np.float64)
    h, s, v = native.rgb_to_hsv(x)
    hp, sp, vp = _rgb_to_hsv(x)
    assert np.array_equal(h, hp), f"H max|Δ|={np.abs(h-hp).max():.3e}"
    assert np.array_equal(s, sp), f"S max|Δ|={np.abs(s-sp).max():.3e}"
    assert np.array_equal(v, vp), f"V max|Δ|={np.abs(v-vp).max():.3e}"


def test_float64_hsv_to_rgb_bitwise(native_required):
    x = _random_rgb(dtype=np.float64)
    h, s, v = native.rgb_to_hsv(x)
    y = native.hsv_to_rgb(h, s, v)
    yp = _hsv_to_rgb(h, s, v)
    assert np.array_equal(y, yp), f"RGB max|Δ|={np.abs(y-yp).max():.3e}"


def test_float64_edge_cases_bitwise(native_required):
    x = _edge_rgb()
    h, s, v = native.rgb_to_hsv(x)
    hp, sp, vp = _rgb_to_hsv(x)
    assert np.array_equal(h, hp)
    assert np.array_equal(s, sp)
    assert np.array_equal(v, vp)
    y = native.hsv_to_rgb(h, s, v)
    yp = _hsv_to_rgb(h, s, v)
    assert np.array_equal(y, yp)


def test_float32_rgb_to_hsv_tolerance(native_required):
    x = _random_rgb(dtype=np.float32)
    h, s, v = native.rgb_to_hsv_f32(x)
    hp, sp, vp = _rgb_to_hsv(x)
    assert np.abs(h - hp).max() <= F32_TOL
    assert np.abs(s - sp).max() <= F32_TOL
    assert np.abs(v - vp).max() <= F32_TOL


def test_float32_hsv_to_rgb_tolerance(native_required):
    x = _random_rgb(dtype=np.float32)
    h, s, v = native.rgb_to_hsv_f32(x)
    y = native.hsv_to_rgb_f32(h, s, v)
    yp = _hsv_to_rgb(h, s, v)
    assert np.abs(y - yp).max() <= F32_TOL
