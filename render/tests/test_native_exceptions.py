"""T28: warm_sat/colorcal C ABI 异常路径测试。

Python 侧无法直接抛 C++ 异常，这里模拟 C ABI 返回 PixoRenderInternalError(-3)，
验证 ctypes 包装器统一抛 RuntimeError，而不是静默返回或崩溃。
"""
from __future__ import annotations

import numpy as np
import pytest

from render import _native as native


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过异常路径测试")


def test_warm_sat_internal_error_raises(native_required, monkeypatch):
    if not hasattr(native._lib, "PixoRenderApplyLocalWarmSat"):
        pytest.skip("DLL 不含 PixoRenderApplyLocalWarmSat")
    monkeypatch.setattr(native._lib, "PixoRenderApplyLocalWarmSat",
                        lambda *a, **k: -3)
    params = native.PixoRenderWarmSatParams()
    with pytest.raises(RuntimeError, match="native status -3"):
        native.apply_local_warm_sat_native(
            np.zeros((4, 4, 3), dtype=np.float32), params)


def test_colorcal_internal_error_raises(native_required, monkeypatch):
    if not hasattr(native._lib, "PixoRenderColorCalApplyLab"):
        pytest.skip("DLL 不含 PixoRenderColorCalApplyLab")
    monkeypatch.setattr(native._lib, "PixoRenderColorCalApplyLab",
                        lambda *a, **k: -3)
    params = native.PixoRenderColorCalParams()
    with pytest.raises(RuntimeError, match="native status -3"):
        native.colorcal_apply_lab(np.zeros((4, 4, 3), dtype=np.float32), params)


def test_gamut_soft_internal_error_raises(native_required, monkeypatch):
    if not hasattr(native._lib, "PixoRenderGamutSoft"):
        pytest.skip("DLL 不含 PixoRenderGamutSoft")
    monkeypatch.setattr(native._lib, "PixoRenderGamutSoft",
                        lambda *a, **k: -3)
    with pytest.raises(RuntimeError, match="native status -3"):
        native.gamut_soft(np.zeros((4, 4, 3), dtype=np.float32), 1.0)
