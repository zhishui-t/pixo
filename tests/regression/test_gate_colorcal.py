"""Gate: colorcal（Lab 全量路径, float Lab 域）功能性质 + native 等价。

16bit 精度改造: 生产路径为 float 全链 (cv2 float Lab, L∈[0,100], a/b 中心
0; uint8 Lab 域 L∈[0,255]/a/b 中心 128 为旧链, 已退役为 ABI 兼容导出)。
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from pixo.render import _native as native
from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext

pytestmark = pytest.mark.gate


def _random_img01(seed=20260820):
    return np.random.default_rng(seed).random((24, 24, 3), dtype=np.float32)


def _assert_float_equivalent(a, b, ctx=""):
    """float 全链 native/Python 等价口径: mean ≤ 1e-5 且 max < 半个 8bit 级。

    两实现 Lab 域差 ≤ ~2e-6 (libm/np.exp、np.interp vs InterpCurve 的 ULP
    级差异, uint8 截断不再吸收); cv2 LAB2RGB 阴影膝点 (斜率 ~903) 会把它
    放大到个别极暗像素 ~2e-3。旧 u8 链时代为逐位一致 (截断吸收 ULP 差)。
    """
    diff = np.abs(a.astype(np.float64) - b.astype(np.float64))
    assert float(diff.mean()) <= 1e-5, f"{ctx} native/Python float 分歧 mean"
    assert float(diff.max()) <= 2.5e-3, f"{ctx} native/Python float 分歧 max"


def test_native_zero_params_returns_same_lab():
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    if not hasattr(native._lib, "PixoRenderColorCalApplyLabF32"):
        pytest.fail("native DLL 未导出 F32 内核 (需 ≥1.2.0)")
    img = _random_img01()
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    out = native.colorcal_apply_lab_f32(lab, native.PixoRenderColorCalParams())
    # 零参数 → 恒等 (仅域内限幅 L∈[0,100], a/b∈[-128,127]), 逐位一致
    expected = np.stack([np.clip(lab[..., 0], 0.0, 100.0),
                         np.clip(lab[..., 1], -128.0, 127.0),
                         np.clip(lab[..., 2], -128.0, 127.0)], axis=-1)
    assert np.array_equal(out, expected)


def test_saturation_scales_chroma_only_on_color_pixels():
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    img = np.zeros((16, 16, 3), dtype=np.float32)
    img[:, :8] = (200 / 255.0, 80 / 255.0, 80 / 255.0)     # 高色度块
    img[:, 8:] = (128 / 255.0, 128 / 255.0, 128 / 255.0)   # 中性灰块
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    p = native.PixoRenderColorCalParams(saturation=0.5)
    out = native.colorcal_apply_lab_f32(lab, p)
    chroma_in = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)        # a/b 中心 0
    chroma_out = np.sqrt(out[..., 1] ** 2 + out[..., 2] ** 2)
    assert float(chroma_out[:, :8].mean()) > float(chroma_in[:, :8].mean())
    # 中性块 C==0 (float 域 a=b=0), 饱和增益不动中性色 (u8 域容差 1.0 收紧为 0)
    assert float(np.abs(chroma_out[:, 8:] - chroma_in[:, 8:]).max()) <= 1e-6


def test_stage_native_matches_fallback(monkeypatch):
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    rng = np.random.default_rng(20260820)
    img = rng.uniform(0.0, 1.0, size=(32, 32, 3)).astype(np.float32)
    # float 全链 (native F32 内核 vs 纯 Python 回退) 等价口径见
    # _assert_float_equivalent; 覆盖 na/nb != 0 与曲线路径。
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
    _assert_float_equivalent(native_out, ctx2.image)


def test_stage_neutral_offset_curves_native_strict(monkeypatch):
    """中性偏移 + 分段曲线组合的 native/Python float 路径等价。

    历史: S5 曾因 native (colorcal.cpp) 中性权重仍是纯高斯而与 Python 回退
    (平台+高斯尾) 有已知分歧 (max ~0.05 @na=±1), 当时以 0.1 有界上界把守;
    native 对齐重编后升级为 u8 逐位等价; 16bit 精度改造后 float 出图,
    等价口径见 _assert_float_equivalent (Lab 域差为 libm ULP 级)。
    """
    if not native.available():
        pytest.fail("native DLL 缺失，gate 不允许 skip")
    rng = np.random.default_rng(20260820)
    img = rng.uniform(0.0, 1.0, size=(32, 32, 3)).astype(np.float32)
    cfg = {"stages": {"colorcal": {
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 0.6, "neutral_b": -0.4, "neutral_sigma": 9.0,
        "neutral_mode": "static",
        "neutral_a_curve": [0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5],
        "neutral_b_curve": [1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5],
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
    _assert_float_equivalent(native_out, ctx2.image, "中性偏移+曲线组合")
