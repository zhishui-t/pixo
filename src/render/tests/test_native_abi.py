"""M5: render._native ctypes ABI / 加载契约测试。

覆盖:
  - DLL 存在时 available()==True, version() 可安全调用
  - 传入非法 shape / 非连续数组的包装行为
  - 原生状态码 <0 时抛 RuntimeError (调用方应回退)
  - 模拟 DLL 缺失时模块仍可导入、available()==False
"""
from __future__ import annotations

import numpy as np
import pytest

from render import _native as native


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 ABI 测试")


def test_available_true(native_required):
    assert native.available() is True
    assert native.load_error() is None


def test_version_callable(native_required):
    # v1.0 旧 DLL 无 PixoRenderVersion 符号时 version() 返回 None; 不抛异常即可
    v = native.version()
    assert v is None or (isinstance(v, tuple) and len(v) == 3)


def test_rgb_to_hsv_wrong_shape_raises(native_required):
    x = np.zeros((4, 4, 4), dtype=np.float64)
    with pytest.raises(ValueError, match="须为"):
        native.rgb_to_hsv(x)


def test_non_contiguous_matches_contiguous(native_required):
    rng = np.random.default_rng(20260820)
    x = rng.random((32, 32, 3)).astype(np.float64)
    h0, s0, v0 = native.rgb_to_hsv(x)
    h1, s1, v1 = native.rgb_to_hsv(x[::2, ::2])
    assert np.array_equal(h0[::2, ::2], h1)
    assert np.array_equal(s0[::2, ::2], s1)
    assert np.array_equal(v0[::2, ::2], v1)


def test_negative_status_raises(native_required, monkeypatch):
    if not hasattr(native._lib, "PixoRenderApplyLocalWarmSat"):
        pytest.skip("DLL 不含 PixoRenderApplyLocalWarmSat")

    def bad_status(*args, **kwargs):
        return -1

    monkeypatch.setattr(native._lib, "PixoRenderApplyLocalWarmSat", bad_status)
    rgb = np.zeros((4, 4, 3), dtype=np.float32)
    params = native.PixoRenderWarmSatParams()
    with pytest.raises(RuntimeError, match="native status"):
        native.apply_local_warm_sat_native(rgb, params)


def test_missing_dll_reports_unavailable(monkeypatch):
    # 模拟 DLL 缺失/加载失败: 模块本身已导入, 只把运行期状态置为不可用。
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    assert native.available() is False
    assert native.load_error() is not None
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.rgb_to_hsv(np.zeros((1, 3), dtype=np.float64))
