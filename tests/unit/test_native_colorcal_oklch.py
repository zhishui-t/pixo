"""T9: colorcal oklch 域原生内核对齐测试 (v1.5.0, F11 15x 性能鸿沟回收)。

对象: PixoRenderColorCalApplyLabF32Oklch —— 与 PixoRenderColorCalApplyLabF32
(float Lab 域 hsv 内核) 逐式对应, 唯一差异 = 肤色掩码源:
OKLab 椭圆 (core/skin.py::skin_mask_oklab 同式, 掩码取校正前原始 gamma sRGB)。

对齐口径 (分层):
  - **掩码隔离路径 (bitwise)**: 仅 skin_trim/skin_protect 激活 (无中性权重
    exp/曲线插值等 libm ULP 源) 时, 内核输出与 numpy 参考 (skin_mask_oklab)
    **逐位一致** —— 掩码链 (sRGB EOTF pow + msun 复刻 cbrt + 椭圆 +
    smoothstep) 的 f64->f32 舍入后等价 (cbrt 与 ucrt/np.cbrt 差 <=1 ULP f64,
    实测随机+越界+边界语料 0 差异, 见 .agent-team/streams/r10-hard-problems.md)。
  - **全参数路径 (紧容差)**: |Δ| <= 4e-5 Lab 单位 (实测 2.3e-5 = 1 ULP f32
    @|a|~128)。该地板与 hsv 内核**同源同量级** (np.exp/np.interp vs
    std::exp/InterpCurveF32 的 libm ULP, 同语料 A/B 实测 hsv 内核
    max 2.289e-5 / oklch 内核 2.289e-5) —— oklch 掩码不新增分歧,
    非 oklch 特有误差。
  - **stage 级 (native vs Python 回退)**: RGB 域 mean <= 1e-5 / max <= 2.5e-3
    (口径同 test_native_colorcal 的 _assert_stage_close_u8_strict: ULP 级
    Lab 差被 cv2 LAB2RGB 阴影膝点条件数放大)。
"""
from __future__ import annotations

import ctypes

import cv2
import numpy as np
import pytest

from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext
from pixo.render import _native as native
from pixo.render.core.skin import skin_mask_oklab

_NEUTRAL_CENTERS = np.array([8, 32, 72, 128, 184, 224, 248], dtype=np.float32)
_NEUTRAL_CENTERS_F = _NEUTRAL_CENTERS.astype(np.float64) * (100.0 / 255.0)


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 colorcal oklch 原生测试")


def _oklch_kernel_exported() -> bool:
    return native.available() and hasattr(native._lib, "PixoRenderColorCalApplyLabF32Oklch")


@pytest.fixture()
def oklch_kernel_required(native_required):
    if not _oklch_kernel_exported():
        pytest.skip("native DLL < 1.5.0 未导出 oklch 内核 (旧 DLL 兼容路径, 见回退测试)")


# ---------------------------------------------------------------------------
# 参考实现 (与 modules/color_cal.py ② 纯 Python float oklch 分支同式)
# ---------------------------------------------------------------------------
def _reference_lab_f32_oklch(img01, sat, vib, hue, na, nb, sigma, skin,
                             skin_trim_da, skin_trim_db, curve_a=None, curve_b=None):
    """float RGB [0,1] → 校正后 float Lab; 掩码 = skin_mask_oklab(原始 img)。

    与 test_native_colorcal._reference_lab_f32 同算法, 仅掩码源换
    OKLab 椭圆 (对应 _skin_region_mask 的 oklch 分支)。
    """
    lab = cv2.cvtColor(np.asarray(img01, np.float32), cv2.COLOR_RGB2LAB)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
    C = np.sqrt(a * a + b * b)
    if na != 0.0 or nb != 0.0 or curve_a is not None or curve_b is not None:
        plateau = 12.0
        tail = np.maximum(C - plateau, 0.0)
        w = np.exp(-(tail ** 2) / (2.0 * sigma * sigma))
        if curve_a is not None or curve_b is not None:
            a_off = (np.interp(L, _NEUTRAL_CENTERS_F, curve_a).astype(np.float32)
                     if curve_a is not None else 0.0)
            b_off = (np.interp(L, _NEUTRAL_CENTERS_F, curve_b).astype(np.float32)
                     if curve_b is not None else 0.0)
            a = a + (na + a_off) * w
            b = b + (nb + b_off) * w
        else:
            a = a + na * w
            b = b + nb * w
    mask = None
    if skin_trim_da != 0.0 or skin_trim_db != 0.0 or skin > 0.0:
        mask = skin_mask_oklab(img01)     # 掩码取原始像素 (native rgb 口径)
    if skin_trim_da != 0.0 or skin_trim_db != 0.0:
        a = a + skin_trim_da * mask
        b = b + skin_trim_db * mask
    if hue != 0.0:
        rad = np.deg2rad(hue)
        ca64, cb64 = a.astype(np.float64), b.astype(np.float64)
        a = ca64 * np.cos(rad) - cb64 * np.sin(rad)
        b = ca64 * np.sin(rad) + cb64 * np.cos(rad)
    gain = np.float32(1.0 + sat)
    if vib != 0.0:
        gain = gain + np.float32(vib) * np.clip(
            np.float32(1.0) - C / np.float32(128.0), np.float32(0.0), np.float32(1.0))
    if skin > 0.0:
        gain = np.float32(1.0) + (gain - np.float32(1.0)) * (
            np.float32(1.0) - np.float32(skin) * mask)
    a = a * gain
    b = b * gain
    return np.stack([np.clip(L, 0.0, 100.0),
                     np.clip(a, -128.0, 127.0),
                     np.clip(b, -128.0, 127.0)], axis=-1).astype(np.float32)


def _make_params(**kw):
    curve_a = kw.pop("curve_a", None)
    curve_b = kw.pop("curve_b", None)
    ca = np.asarray(curve_a, dtype=np.float32) if curve_a is not None else None
    cb = np.asarray(curve_b, dtype=np.float32) if curve_b is not None else None
    return native.PixoRenderColorCalParams(
        curveA=(ca.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) if ca is not None else None),
        curveB=(cb.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) if cb is not None else None),
        **kw)


def _structured_img(rng) -> np.ndarray:
    """结构化语料: EOTF 分支边界 0.04045 邻域 / 椭圆软边 / 越界极值 + 随机。"""
    h = w = 32
    img = rng.uniform(0.0, 1.0, size=(h, w, 3)).astype(np.float32)
    # EOTF 阈值邻域 (sRGB decode pow 分支切换)
    for k, d in enumerate((-1e-6, -1e-7, 0.0, 1e-7, 1e-6, 1e-3)):
        v = np.float32(0.04045 + d)
        img[k, 0] = [v, v, v]
        img[k, 1] = [v, 0.5, 0.5]
        img[k, 2] = [0.5, v, 0.5]
        img[k, 3] = [0.5, 0.5, v]
    # 肤色三角扫描 + 越界 (入参清洗 clip [0,1])
    for k, t in enumerate(np.linspace(0.0, 1.0, 16)):
        img[10 + k // 4, k % 4] = [0.35 + 0.4 * t, 0.2 + 0.35 * t, 0.15 + 0.3 * t]
    img[31, 0] = [-0.5, 0.2, 0.2]
    img[31, 1] = [1.5, 0.2, 0.2]
    img[31, 2] = [0.2, -0.5, 1.5]
    img[31, 3] = [2.0, -1.0, 2.0]
    return img


# ---------------------------------------------------------------------------
# 1) 掩码隔离路径: 逐位一致 (新增对齐面 = OKLab 掩码链)
# ---------------------------------------------------------------------------
def test_oklch_mask_isolated_bitwise(oklch_kernel_required):
    """仅 skin_trim/skin_protect 激活 (无 exp/interp libm 源) → 与
    skin_mask_oklab 参考逐位一致; 含随机 + 越界 + EOTF 边界语料。"""
    rng = np.random.default_rng(20260907)
    total_miss = 0
    for trial in range(40):
        if trial % 4 == 0:
            img = _structured_img(rng)
        elif trial % 4 == 1:
            img = rng.uniform(-0.1, 1.1, size=(24, 24, 3)).astype(np.float32)
        else:
            img = rng.uniform(0.0, 1.0, size=(24, 24, 3)).astype(np.float32)
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)   # 与 stage 同口径 (无 clip)
        skin = float(rng.uniform(0.0, 1.0))
        tda = float(rng.uniform(-4.0, 4.0))
        tdb = float(rng.uniform(-4.0, 4.0))
        expected = _reference_lab_f32_oklch(
            img, sat=0.0, vib=0.0, hue=0.0, na=0.0, nb=0.0, sigma=14.0,
            skin=skin, skin_trim_da=tda, skin_trim_db=tdb)
        params = _make_params(
            saturation=0.0, vibrance=0.0, hueDeg=0.0,
            neutralA=0.0, neutralB=0.0, neutralSigma=14.0,
            skinProtect=skin, skinTrimA=tda, skinTrimB=tdb)
        got = native.colorcal_apply_lab_f32_oklch(lab, img, params)
        miss = int(np.count_nonzero(got.view(np.int32) != expected.view(np.int32)))
        total_miss += miss
        if miss:
            d = np.abs(got.astype(np.float64) - expected.astype(np.float64))
            assert d.max() <= 1.2e-7, f"trial {trial} mask 路径非逐位且超 1 ULP: {d.max()}"
    assert total_miss == 0, f"掩码隔离路径应逐位一致 (总差异像素 {total_miss})"


# ---------------------------------------------------------------------------
# 2) 全参数路径: 紧容差 (地板 = hsv 内核同源 libm ULP, 非掩码分歧)
# ---------------------------------------------------------------------------
def test_oklch_kernel_matches_reference(oklch_kernel_required):
    rng = np.random.default_rng(20260907)
    for trial in range(20):
        img = rng.uniform(0.0, 1.0, size=(24, 24, 3)).astype(np.float32)
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        curve_a = [0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5] if trial % 2 == 0 else None
        curve_b = [1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5] if trial % 3 == 0 else None
        args = dict(sat=float(rng.uniform(-0.5, 0.5)),
                    vib=float(rng.uniform(-0.5, 0.5)),
                    hue=float(rng.uniform(-15.0, 15.0)),
                    na=float(rng.uniform(-3.0, 3.0)),
                    nb=float(rng.uniform(-3.0, 3.0)),
                    sigma=float(rng.uniform(5.0, 20.0)),
                    skin=float(rng.uniform(0.0, 1.0)),
                    skin_trim_da=float(rng.uniform(-4.0, 4.0)),
                    skin_trim_db=float(rng.uniform(-4.0, 4.0)),
                    curve_a=curve_a, curve_b=curve_b)
        expected = _reference_lab_f32_oklch(img, **args)
        params = _make_params(saturation=args["sat"], vibrance=args["vib"],
                              hueDeg=args["hue"], neutralA=args["na"],
                              neutralB=args["nb"], neutralSigma=args["sigma"],
                              skinProtect=args["skin"],
                              skinTrimA=args["skin_trim_da"],
                              skinTrimB=args["skin_trim_db"],
                              curve_a=curve_a, curve_b=curve_b)
        got = native.colorcal_apply_lab_f32_oklch(lab, img, params)
        maxdiff = float(np.abs(got.astype(np.float64) - expected.astype(np.float64)).max())
        # 地板 = 1 ULP f32 @|a|~128 (2.3e-5, 实测), 与 hsv 内核同语料同值
        # (np.exp/np.interp libm ULP); 4e-5 为 1 ULP + 舍入余量
        assert maxdiff <= 4e-5, f"trial {trial} maxdiff={maxdiff}"


def test_oklch_kernel_zero_params_identity(oklch_kernel_required):
    """零参数 → 恒等 (仅域内限幅), bit 一致 (掩码不激活)。"""
    rng = np.random.default_rng(7)
    img = rng.uniform(0.0, 1.0, size=(16, 16, 3)).astype(np.float32)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    out = native.colorcal_apply_lab_f32_oklch(
        lab, img, native.PixoRenderColorCalParams())
    expected = np.stack([np.clip(lab[..., 0], 0.0, 100.0),
                         np.clip(lab[..., 1], -128.0, 127.0),
                         np.clip(lab[..., 2], -128.0, 127.0)], axis=-1)
    assert np.array_equal(out, expected)


# ---------------------------------------------------------------------------
# 3) stage 级: native oklch vs Python 回退 (分层回退链守卫)
# ---------------------------------------------------------------------------
def _disable_native(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")


def _oklch_cfg():
    return {"stages": {"colorcal": {
        "color_domain": "oklch",
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 0.6, "neutral_b": -0.4, "neutral_sigma": 9.0,
        "neutral_mode": "static",
        "neutral_a_curve": [0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5],
        "neutral_b_curve": [1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5],
        "skin_protect": 0.7, "skin_trim": [-2.0, -4.0], "gamut_soft": 0.5,
    }}}


def test_oklch_stage_native_matches_fallback(oklch_kernel_required, monkeypatch):
    rng = np.random.default_rng(20260907)
    img = rng.uniform(0.0, 1.0, size=(32, 32, 3)).astype(np.float32)
    stage = ColorCalStage()

    ctx = StageContext("x.NEF", config=_oklch_cfg())
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx)
    native_out = ctx.image.copy()

    _disable_native(monkeypatch)
    ctx2 = StageContext("x.NEF", config=_oklch_cfg())
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx2)
    fallback_out = ctx2.image

    diff = np.abs(native_out.astype(np.float64) - fallback_out.astype(np.float64))
    assert float(diff.mean()) <= 1e-5, f"oklch native/Python 分歧 mean={diff.mean()}"
    assert float(diff.max()) <= 2.5e-3, f"oklch native/Python 分歧 max={diff.max()}"


def test_oklch_stage_fallback_when_kernel_missing(native_required, monkeypatch):
    """DLL 未导出 oklch 内核 (旧 v1.4) → 包装函数抛 RuntimeError → stage
    回退纯 Python oklch 路径, 输出与禁 native 直跑一致。"""
    def _raise(*_a, **_kw):
        raise RuntimeError("native colorcal oklch F32 kernel unavailable (DLL 未导出)")

    monkeypatch.setattr(native, "colorcal_apply_lab_f32_oklch", _raise)
    rng = np.random.default_rng(20260907)
    img = rng.uniform(0.0, 1.0, size=(24, 24, 3)).astype(np.float32)

    ctx = StageContext("x.NEF", config=_oklch_cfg())
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    fallback_via_exception = ctx.image.copy()

    _disable_native(monkeypatch)
    ctx2 = StageContext("x.NEF", config=_oklch_cfg())
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx2)

    assert np.array_equal(fallback_via_exception, ctx2.image), (
        "oklch 内核缺失时 stage 应回退纯 Python oklch 路径且输出一致")


def test_oklch_kernel_version_gate(native_required):
    """DLL >= 1.5.0 必须导出 oklch 内核 (版本-符号一致性)。"""
    if not _oklch_kernel_exported():
        ver = native.version()
        assert ver is None or ver < (1, 5, 0), (
            f"DLL 版本 {ver} >= 1.5.0 但未导出 PixoRenderColorCalApplyLabF32Oklch")
    else:
        assert native.version() is not None and native.version() >= (1, 5, 0)
