"""M5: 原生缺失/不可用时的回退契约 (FR6)。

验收:
  - pixo.render._native 模块保持可导入, available()==False 时不抛 ImportError
  - 调用点自动回退纯 Python, 输出与原生路径等价
  - 原生函数在不可用时抛出 RuntimeError, 由调用方 try/except 捕获
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.pipeline import build_default_pipeline
from pixo.render.pipeline.graph import DOMAIN_LINEAR_CAM, StageContext
from pixo.render.core.huesat import apply_local_warm_sat
from pixo.render import _native as native


@pytest.fixture()
def native_disabled(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    return native


def test_module_importable_and_reports_unavailable(native_disabled):
    assert native.available() is False
    assert native.load_error() is not None


def test_native_function_raises_when_unavailable(native_disabled):
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.rgb_to_hsv(np.zeros((1, 3), dtype=np.float64))


def test_apply_local_warm_sat_fallback_pure_python(native_disabled):
    img = np.full((32, 32, 3), 0.05, dtype=np.float32)
    img[14:18, 14:18] = (0.9, 0.3, 0.05)
    out = apply_local_warm_sat(
        img, sat_scale=2.0, spot_sat_scale=2.0,
        hue_center=22.5, hue_halfwidth=17.5,
        sat_min=0.05, val_min=0.6, coverage_max=0.0015)
    assert out.shape == img.shape
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    # 低覆盖暖点应被增强
    assert float(out[15, 15].max()) > float(img[15, 15].max())


def test_default_pipeline_runs_without_native(native_disabled):
    class MockProf:
        def __init__(self):
            self.color_matrix1 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
            self.color_matrix2 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
            self.forward_matrix1 = None
            self.forward_matrix2 = None
            self.camera_calibration1 = None
            self.camera_calibration2 = None
            self.calibration_illuminant1 = 17
            self.calibration_illuminant2 = 21
            self.baseline_exposure_offset = 0.0
            self.profile_tone_curve = None

    prof = MockProf()
    params = {"exposure": {"mode": "off"},
              "whitebalance": {"mode": "off"},
              "skin": {"enabled": False}}
    pipe = build_default_pipeline(prof=prof, params=params)
    ctx = StageContext("x.NEF", prof=prof, config={"stages": params})
    rng = np.random.default_rng(20260820)
    ctx.set_image(rng.random((16, 16, 3)).astype(np.float32), DOMAIN_LINEAR_CAM)
    out = pipe.run(ctx)
    assert ctx.domain == "gamma_rgb"
    assert out.shape == (16, 16, 3)
    assert np.isfinite(out).all()
