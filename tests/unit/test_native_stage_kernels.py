"""T21: P1 新增 stage 原生内核数值等价测试。

覆盖:
  - exposure_apply vs Python gain + soft_highlight_rolloff
  - matrix_apply3 vs rgb @ matrix.T
  - tone_apply_lut1d vs apply_lut1d_fast
  - clarity_apply vs core.enhance.clarity（blur 平面由 Python cv2 预计算）
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from render import _native as native
from render.core.curves import apply_lut1d_fast
from render.core.enhance import _gray, clarity
from render.modules.exposure import soft_highlight_rolloff


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 stage kernel 等价测试")


@pytest.fixture()
def native_disabled(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    return native


def _img(shape=(32, 48, 3), seed=20260820):
    rng = np.random.default_rng(seed)
    return rng.random(shape, dtype=np.float32)


def test_exposure_apply_matches_python(native_required):
    img = _img()
    ev = 0.7
    knee = 0.9
    out_n = native.exposure_apply(img, ev=ev, rolloff_knee=knee)
    out_p = soft_highlight_rolloff(img * (2.0 ** ev), knee=knee).astype(np.float32)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_matrix_apply3_matches_python(native_required):
    img = _img()
    m = np.array([[1.1, -0.2, 0.05],
                  [0.1, 0.9, -0.1],
                  [-0.05, 0.2, 1.2]], dtype=np.float32)
    out_n = native.matrix_apply3(img, m)
    out_p = (img.reshape(-1, 3) @ m.T).reshape(img.shape).astype(np.float32)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_tone_apply_lut1d_matches_fast(native_required):
    img = _img()
    lut = np.linspace(0.0, 1.0, 1024, dtype=np.float32)
    out_n = native.tone_apply_lut1d(img, lut)
    out_p = apply_lut1d_fast(img, lut)
    assert np.array_equal(out_n, out_p)


def test_clarity_apply_matches_python(native_required):
    img = _img()
    s = 0.3
    g = _gray(img)
    small = np.asarray(cv2.GaussianBlur(g, (0, 0), 0.8), dtype=np.float32)
    large = np.asarray(cv2.GaussianBlur(g, (0, 0), 3.0), dtype=np.float32)
    out_n = native.clarity_apply(img, s, g, small, large)
    out_p = clarity(img, strength=s)
    assert np.abs(out_n - out_p).max() <= 1e-6


# ---------------------------------------------------------------------------
# 回退契约：native 不可用时包装函数必须抛 RuntimeError，模块层已有 try/except
# 回退纯 Python（test_native_fallback.py 覆盖整条 pipeline）。
# ---------------------------------------------------------------------------


def test_exposure_apply_raises_when_native_disabled(native_disabled):
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.exposure_apply(_img((8, 8, 3)))


def test_matrix_apply3_raises_when_native_disabled(native_disabled):
    m = np.eye(3, dtype=np.float32)
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.matrix_apply3(_img((8, 8, 3)), m)


def test_tone_apply_lut1d_raises_when_native_disabled(native_disabled):
    lut = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.tone_apply_lut1d(_img((8, 8, 3)), lut)


def test_clarity_apply_raises_when_native_disabled(native_disabled):
    img = _img((8, 8, 3))
    g = _gray(img)
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.clarity_apply(img, 0.3, g, g, g)
