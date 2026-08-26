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
    # S5 修复后 Python 全量回退的中性权重为"平台+高斯尾"口径, native
    # (colorcal.cpp) 仍为纯高斯 —— 中性偏移非零时两者已知分歧 (待 native
    # 重编对齐, 见 test_stage_neutral_weight_native_divergence_bounded)。
    # 故严格等价只覆盖中性偏移为零的参数组合。
    cfg = {"stages": {"colorcal": {
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 0.0, "neutral_b": 0.0, "neutral_mode": "static",
        "skin_protect": 0.7, "gamut_soft": 0.5,
    }}}
    ctx = StageContext("x.NEF", config=cfg)
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    native_out = ctx.image.copy()

    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    ctx2 = StageContext("x.NEF", config=cfg)
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx2)
    assert np.array_equal(native_out, ctx2.image)


def test_stage_neutral_weight_native_divergence_bounded(monkeypatch):
    """S5 已知分歧 (有界): Python 回退中性权重=平台+高斯尾, native=纯高斯。

    native 重编对齐前, 两者在中性偏移非零时的差必须有界 (max ≤ 0.1, 实测
    ~0.05 @na=±1); native 对齐后本测试应升级回严格等价并合并进上例。
    """
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

    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    ctx2 = StageContext("x.NEF", config=cfg)
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx2)
    diff = float(np.abs(native_out.astype(np.float64)
                        - ctx2.image.astype(np.float64)).max())
    assert diff <= 0.1, f"native/Python 中性权重分歧越界: max={diff:.4f}"
