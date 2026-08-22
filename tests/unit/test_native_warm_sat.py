"""M5: apply_local_warm_sat 原生完整内核（broad + spot）/ Python 回退数值等价测试。

覆盖:
  - 低覆盖率暖点: C++ broad 分支处理, 与纯 Python 参考 max|Δ| ≤ 1e-6
  - 高覆盖率平滑暖场: C++ spot 分支处理（GaussianBlur 反差门）,
    开启/关闭 native 的输出差异 ≤ 1e-6
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.huesat import apply_local_warm_sat
from pixo.render import _native as native

TOL = 1e-6


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 warm_sat 数值等价测试")


def _low_coverage_img(size=256, spot=8, rgb=(0.9, 0.3, 0.05)):
    """深灰底 + 小暖斑, 覆盖率远低于 coverage_max=0.0015。"""
    img = np.full((size, size, 3), 0.05, dtype=np.float32)
    c = size // 2
    half = spot // 2
    img[c - half:c + half, c - half:c + half] = rgb
    return img


def _high_coverage_img(size=64, rgb=(0.7, 0.2, 0.05)):
    """整片暖色平滑场, 覆盖率 100% > coverage_max, 触发 spot/Gaussian 分支。"""
    return np.full((size, size, 3), rgb, dtype=np.float32)


def _fallback_call(img, **kwargs):
    """强制 native 不可用后调用 apply_local_warm_sat。"""
    old_lib = native._lib
    old_error = native._load_error
    try:
        native._lib = None
        native._load_error = "simulated fallback"
        return apply_local_warm_sat(img, **kwargs)
    finally:
        native._lib = old_lib
        native._load_error = old_error


def test_low_coverage_native_broad_handled(native_required):
    img = _low_coverage_img()
    params = native.PixoRenderWarmSatParams(
        satScale=2.0, spotSatScale=2.0, hueCenter=22.5,
        hueHalfwidth=17.5, satMin=0.05, valMin=0.6,
        coverageMax=0.0015, contrastSigmaFrac=0.006,
        contrastThr=0.03, contrastSoft=0.08)
    out, handled = native.apply_local_warm_sat_native(img, params)
    assert handled is True
    assert out.shape == img.shape and out.dtype == np.float32


def test_low_coverage_native_matches_fallback(native_required):
    img = _low_coverage_img()
    out_native = apply_local_warm_sat(
        img, sat_scale=2.0, spot_sat_scale=2.0,
        hue_center=22.5, hue_halfwidth=17.5,
        sat_min=0.05, val_min=0.6, coverage_max=0.0015)
    out_fallback = _fallback_call(
        img, sat_scale=2.0, spot_sat_scale=2.0,
        hue_center=22.5, hue_halfwidth=17.5,
        sat_min=0.05, val_min=0.6, coverage_max=0.0015)
    err = float(np.abs(out_native - out_fallback).max())
    assert err <= TOL, f"低覆盖 warm_sat max|Δ|={err:.3e} > {TOL}"


def test_high_coverage_native_spot_handled(native_required):
    img = _high_coverage_img()
    params = native.PixoRenderWarmSatParams(
        satScale=2.0, spotSatScale=2.0, hueCenter=22.5,
        hueHalfwidth=17.5, satMin=0.05, valMin=0.6,
        coverageMax=0.0015, contrastSigmaFrac=0.006,
        contrastThr=0.03, contrastSoft=0.08)
    out, handled = native.apply_local_warm_sat_native(img, params)
    assert handled is True
    assert out.shape == img.shape and out.dtype == np.float32


def test_high_coverage_native_enabled_matches_fallback(native_required):
    img = _high_coverage_img()
    out_native = apply_local_warm_sat(
        img, sat_scale=2.0, spot_sat_scale=2.0,
        hue_center=22.5, hue_halfwidth=17.5,
        sat_min=0.05, val_min=0.6, coverage_max=0.0015)
    out_fallback = _fallback_call(
        img, sat_scale=2.0, spot_sat_scale=2.0,
        hue_center=22.5, hue_halfwidth=17.5,
        sat_min=0.05, val_min=0.6, coverage_max=0.0015)
    err = float(np.abs(out_native - out_fallback).max())
    assert err <= TOL, f"高覆盖 warm_sat max|Δ|={err:.3e} > {TOL}"
