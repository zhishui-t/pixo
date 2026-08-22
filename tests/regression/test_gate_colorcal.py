"""Gate: colorcal（Lab 全量路径）功能性质 + native 等价。"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from pixo.render import _native as native
from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext

pytestmark = pytest.mark.gate


def _random_u8(seed=20260820):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(24, 24, 3), dtype=np.uint8)


def test_native_zero_params_returns_same_lab():
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    u8 = _random_u8()
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    out = native.colorcal_apply_lab(lab, native.PixoRenderColorCalParams())
    assert np.array_equal(out, np.clip(lab, 0.0, 255.0).astype(np.uint8))


def test_saturation_scales_chroma_only_on_color_pixels():
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    u8 = np.zeros((16, 16, 3), dtype=np.uint8)
    u8[:, :8] = (200, 80, 80)   # 高色度块
    u8[:, 8:] = (128, 128, 128)  # 中性灰块
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    p = native.PixoRenderColorCalParams(saturation=0.5)
    out = native.colorcal_apply_lab(lab, p)
    chroma_in = np.sqrt(((lab[..., 1] - 128.0) ** 2
                         + (lab[..., 2] - 128.0) ** 2))
    chroma_out = np.sqrt(((out.astype(np.float32)[..., 1] - 128.0) ** 2
                          + (out.astype(np.float32)[..., 2] - 128.0) ** 2))
    assert float(chroma_out[:, :8].mean()) > float(chroma_in[:, :8].mean())
    assert float(np.abs(chroma_out[:, 8:] - chroma_in[:, 8:]).max()) <= 1.0


def test_stage_native_matches_fallback(monkeypatch):
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    rng = np.random.default_rng(20260820)
    img = rng.uniform(0.0, 1.0, size=(32, 32, 3)).astype(np.float32)
    cfg = {"stages": {"colorcal": {
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 1.0, "neutral_b": -1.0, "neutral_mode": "static",
        "skin_protect": 0.7, "gamut_soft": 0.5,
    }}}
    ctx = StageContext("x.NEF", config=cfg)
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    native_out = ctx.image.copy()

    old_lib, old_error = native._lib, native._load_error
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    ctx2 = StageContext("x.NEF", config=cfg)
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx2)
    monkeypatch.setattr(native, "_lib", old_lib)
    monkeypatch.setattr(native, "_load_error", old_error)
    assert np.array_equal(native_out, ctx2.image)
