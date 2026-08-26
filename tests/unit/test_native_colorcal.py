"""T3: M2 colorcal 原生内核数值等价测试。

覆盖:
  - PixoRenderColorCalApplyLab 与 Python 参考全量 Lab 路径逐像素等价 (uint8 完全一致)
  - PixoRenderGamutSoft 与 NumPy 参考等价
  - ColorCalStage 原生路径与强制回退路径输出一致
"""
from __future__ import annotations

import ctypes

import cv2
import numpy as np
import pytest

from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext
from pixo.render import _native as native
from pixo.render.core.skin import skin_mask

_NEUTRAL_CENTERS = np.array([8, 32, 72, 128, 184, 224, 248], dtype=np.float32)


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 colorcal 原生测试")


def _reference_lab(u8, sat, vib, hue, na, nb, sigma, skin,
                   skin_trim_da, skin_trim_db, curve_a=None, curve_b=None):
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
    C = np.sqrt((a - 128.0) ** 2 + (b - 128.0) ** 2)
    if na != 0.0 or nb != 0.0 or curve_a is not None or curve_b is not None:
        w = np.exp(-(C ** 2) / (2.0 * sigma * sigma))
        if curve_a is not None or curve_b is not None:
            a_off = (np.interp(L, _NEUTRAL_CENTERS, curve_a).astype(np.float32)
                     if curve_a is not None else 0.0)
            b_off = (np.interp(L, _NEUTRAL_CENTERS, curve_b).astype(np.float32)
                     if curve_b is not None else 0.0)
            a = a + (na + a_off) * w
            b = b + (nb + b_off) * w
        else:
            a = a + na * w
            b = b + nb * w
    mask = None
    if skin_trim_da != 0.0 or skin_trim_db != 0.0 or skin > 0.0:
        mask = skin_mask(u8).astype(np.float32)
    if skin_trim_da != 0.0 or skin_trim_db != 0.0:
        a = a + skin_trim_da * mask
        b = b + skin_trim_db * mask
    if hue != 0.0:
        rad = np.deg2rad(hue)
        ca, cb = a - 128.0, b - 128.0
        a = 128.0 + ca * np.cos(rad) - cb * np.sin(rad)
        b = 128.0 + ca * np.sin(rad) + cb * np.cos(rad)
    gain = 1.0 + sat
    if vib != 0.0:
        gain = gain + vib * np.clip(1.0 - C / 128.0, 0.0, 1.0)
    if skin > 0.0:
        gain = 1.0 + (gain - 1.0) * (1.0 - skin * mask)
    a = 128.0 + (a - 128.0) * gain
    b = 128.0 + (b - 128.0) * gain
    lab2 = np.stack([L, a, b], axis=-1)
    return np.clip(lab2, 0, 255).astype(np.uint8)


def _make_params(sat, vib, hue, na, nb, sigma, skin, skin_trim_da, skin_trim_db,
                 curve_a=None, curve_b=None):
    ca = np.asarray(curve_a, dtype=np.float32) if curve_a is not None else None
    cb = np.asarray(curve_b, dtype=np.float32) if curve_b is not None else None
    return native.PixoRenderColorCalParams(
        saturation=sat, vibrance=vib, hueDeg=hue,
        neutralA=na, neutralB=nb, neutralSigma=sigma,
        skinProtect=skin, skinTrimA=skin_trim_da, skinTrimB=skin_trim_db,
        curveA=(ca.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) if ca is not None else None),
        curveB=(cb.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) if cb is not None else None),
    )


def test_colorcal_apply_lab_matches_reference(native_required):
    rng = np.random.default_rng(20260820)
    for trial in range(20):
        u8 = rng.integers(0, 256, size=(24, 24, 3), dtype=np.uint8)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        curve_a = [0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5] if trial % 2 == 0 else None
        curve_b = [1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5] if trial % 3 == 0 else None
        args = dict(
            sat=float(rng.uniform(-0.5, 0.5)),
            vib=float(rng.uniform(-0.5, 0.5)),
            hue=float(rng.uniform(-15.0, 15.0)),
            na=float(rng.uniform(-3.0, 3.0)),
            nb=float(rng.uniform(-3.0, 3.0)),
            sigma=float(rng.uniform(5.0, 20.0)),
            skin=float(rng.uniform(0.0, 1.0)),
            skin_trim_da=float(rng.uniform(-4.0, 4.0)),
            skin_trim_db=float(rng.uniform(-4.0, 4.0)),
            curve_a=curve_a,
            curve_b=curve_b,
        )
        expected = _reference_lab(u8, **args)
        params = _make_params(**args)
        actual = native.colorcal_apply_lab(lab, params)
        assert actual.dtype == np.uint8
        assert np.array_equal(actual, expected), f"trial {trial} mismatch"


def test_gamut_soft_matches_reference(native_required):
    rng = np.random.default_rng(1)
    for gs in (0.0, 0.1, 0.5, 1.0):
        rgb = rng.uniform(0.8, 1.3, size=(16, 16, 3)).astype(np.float32)
        if gs > 0.0:
            over = np.maximum(rgb - 1.0, 0.0)
            scale = 1.0 / (1.0 + gs * over.sum(axis=-1, keepdims=True))
            expected = np.clip(rgb * scale, 0.0, 1.0).astype(np.float32)
        else:
            expected = np.clip(rgb, 0.0, 1.0).astype(np.float32)
        actual = native.gamut_soft(rgb, gs)
        assert np.array_equal(actual, expected), f"gamut_soft {gs} mismatch"


def test_colorcal_stage_native_matches_fallback(native_required, monkeypatch):
    rng = np.random.default_rng(20260820)
    img = rng.uniform(0.0, 1.0, size=(32, 32, 3)).astype(np.float32)
    # S5 后 Python 全量回退的中性权重是"平台+高斯尾", native 仍是纯高斯:
    # 中性偏移非零时两者已知分歧 (待 native 重编对齐, 有界性由
    # tests/regression/test_gate_colorcal.py 的分歧上界测试把守), 故本测试
    # 的严格等价只覆盖中性偏移为零的组合。
    cfg = {"stages": {"colorcal": {
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 0.0, "neutral_b": 0.0, "neutral_mode": "static",
        "skin_protect": 0.7, "gamut_soft": 0.5,
    }}}
    stage = ColorCalStage()

    ctx = StageContext("x.NEF", config=cfg)
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx)
    native_out = ctx.image.copy()

    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    ctx2 = StageContext("x.NEF", config=cfg)
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx2)
    fallback_out = ctx2.image

    assert np.array_equal(native_out, fallback_out)
