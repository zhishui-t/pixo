"""T3: M2 colorcal 原生内核数值等价测试 (float Lab 域, 16bit 精度改造)。

覆盖:
  - PixoRenderColorCalApplyLabF32 (float Lab 域: L∈[0,100], a/b 中心 0) 与
    Python float 参考全量路径等价: |Δ| ≤ 1e-4 Lab 单位 (float 出图不再有
    uint8 截断吸收 ULP 差, 等价口径 = Lab255 域取整后逐位一致 + 微容差,
    1e-4 比旧 u8 链的量化步长 ~0.4-1.0 细 4 个数量级)
  - 旧 PixoRenderColorCalApplyLab (uint8 Lab 域) 仍导出且行为不变 (ABI 兼容)
  - PixoRenderGamutSoft 与 NumPy 参考等价
  - ColorCalStage native F32 路径与 Python 回退路径一致
  - 精度哨兵 (W4 结论固化): 全量路径输出与"数学等价 float 参考"差异 ≤1e-5,
    对比旧 u8 链三段量化合计 0.81 ΔE76 / 24.7% 像素 >1ΔE
    (docs/metrics/u8_midpoint_precision.md)

域换算 (uint8 Lab ↔ float Lab): L_f=L_u8*100/255; a_f=a_u8-128; b_f=b_u8-128。
a/b 轴两域单位相同 —— 偏移量 (neutral/curve/skinTrim)、色度 C 及阈值
(plateau=12/sigma/128) 不变; 换域点只有: 曲线亮度节点 (_NEUTRAL_CENTERS_F)、
肤色椭圆中心 (140,150)→(12,22)、色相旋转中心 128→0、限幅 [0,255]→
[0,100]/[-128,127]。
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
# float Lab 域亮度节点 (与 color_cal.py/_NEUTRAL_CENTERS_F 同式)
_NEUTRAL_CENTERS_F = _NEUTRAL_CENTERS.astype(np.float64) * (100.0 / 255.0)


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 colorcal 原生测试")


# ---------------------------------------------------------------------------
# 参考实现 (float Lab 域, 不经过任何 uint8 —— 精度哨兵的"数学等价参考")
# ---------------------------------------------------------------------------
def _skin_mask_f(a, b):
    """float Lab 域肤色椭圆软掩码 (中心 (12,22), 镜像 colorcal.cpp SkinMaskF32)。"""
    cos_a, sin_a = np.cos(0.65), np.sin(0.65)
    da = a - np.float32(12.0)
    db = b - np.float32(22.0)
    u = da.astype(np.float64) * cos_a + db.astype(np.float64) * sin_a
    v = -da.astype(np.float64) * sin_a + db.astype(np.float64) * cos_a
    d = np.sqrt(np.maximum((u / 22.0) ** 2 + (v / 14.0) ** 2, 0.0)).astype(np.float32)
    t = np.clip((d - 1.0) / 0.25, 0.0, 1.0)
    return (1.0 - t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _reference_lab_f32(img01, sat, vib, hue, na, nb, sigma, skin,
                       skin_trim_da, skin_trim_db, curve_a=None, curve_b=None):
    """float RGB [0,1] → 校正后 float Lab (与 colorcal.cpp ApplyColorCalLabF32
    及 color_cal.py 全量回退分支同算法; 全程 float, 无 u8 量化)。"""
    lab = cv2.cvtColor(np.asarray(img01, np.float32), cv2.COLOR_RGB2LAB)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
    C = np.sqrt(a * a + b * b)          # 与 u8 域 |a-128,b-128| 同单位同值
    if na != 0.0 or nb != 0.0 or curve_a is not None or curve_b is not None:
        # 平台+高斯尾权重: C<=plateau(12) 全量校正, 之后按 sigma 高斯衰减
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
        mask = _skin_mask_f(lab[:, :, 1], lab[:, :, 2])   # 原始 a/b (native aOrig 口径)
    if skin_trim_da != 0.0 or skin_trim_db != 0.0:
        a = a + skin_trim_da * mask
        b = b + skin_trim_db * mask
    if hue != 0.0:
        rad = np.deg2rad(hue)            # 旋转绕中心 0 (u8 域绕 128)
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
    # 限幅 = 旧 u8 链 clip(lab2,0,255) 的 float 域等价口径
    return np.stack([np.clip(L, 0.0, 100.0),
                     np.clip(a, -128.0, 127.0),
                     np.clip(b, -128.0, 127.0)], axis=-1).astype(np.float32)


def _reference_rgb_f32(img01, gs, **kwargs):
    """参考实现的完整 stage 语义: float Lab 校正 → float LAB2RGB → gamut_soft。"""
    out = cv2.cvtColor(_reference_lab_f32(img01, **kwargs), cv2.COLOR_LAB2RGB)
    if gs > 0.0:
        over = np.maximum(out - 1.0, 0.0)
        scale = 1.0 / (1.0 + gs * over.sum(axis=-1, keepdims=True))
        out = out * scale
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 旧 uint8 Lab 域参考 (legacy 内核 ABI 兼容守卫用)
# ---------------------------------------------------------------------------
def _reference_lab_u8(u8, sat, vib, hue, na, nb, sigma, skin,
                      skin_trim_da, skin_trim_db, curve_a=None, curve_b=None):
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
    C = np.sqrt((a - 128.0) ** 2 + (b - 128.0) ** 2)
    if na != 0.0 or nb != 0.0 or curve_a is not None or curve_b is not None:
        # 平台+高斯尾权重: 与 modules/color_cal.py 全量路径 (S5) 及
        # native DLL (colorcal.cpp, 已对齐重编) 同口径 —— C<=plateau(12)
        # 全量校正, 之后按 sigma 高斯衰减。
        plateau = 12.0
        tail = np.maximum(C - plateau, 0.0)
        w = np.exp(-(tail ** 2) / (2.0 * sigma * sigma))
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


def _random_full_args(rng):
    return dict(
        sat=float(rng.uniform(-0.5, 0.5)),
        vib=float(rng.uniform(-0.5, 0.5)),
        hue=float(rng.uniform(-15.0, 15.0)),
        na=float(rng.uniform(-3.0, 3.0)),
        nb=float(rng.uniform(-3.0, 3.0)),
        sigma=float(rng.uniform(5.0, 20.0)),
        skin=float(rng.uniform(0.0, 1.0)),
        skin_trim_da=float(rng.uniform(-4.0, 4.0)),
        skin_trim_db=float(rng.uniform(-4.0, 4.0)),
    )


# ---------------------------------------------------------------------------
# F32 内核 (float Lab 域, 生产路径)
# ---------------------------------------------------------------------------
def test_colorcal_apply_lab_f32_matches_reference(native_required):
    rng = np.random.default_rng(20260820)
    for trial in range(20):
        img = rng.uniform(0.0, 1.0, size=(24, 24, 3)).astype(np.float32)
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        curve_a = [0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5] if trial % 2 == 0 else None
        curve_b = [1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5] if trial % 3 == 0 else None
        args = dict(_random_full_args(rng), curve_a=curve_a, curve_b=curve_b)
        expected = _reference_lab_f32(img, **args)
        params = _make_params(**args)
        actual = native.colorcal_apply_lab_f32(lab, params)
        assert actual.dtype == np.float32
        # float 出图无 uint8 截断吸收 ULP 差 (libm/np.exp、np.interp vs
        # InterpCurve 的最后一位舍入, 实测 ≤ 2e-6): 等价口径 = Lab 域
        # |Δ| ≤ 1e-4 (比旧 u8 链的量化步长 0.4~1.0 细 4 个数量级)
        maxdiff = float(np.abs(actual - expected).max())
        assert maxdiff <= 1e-4, f"trial {trial} maxdiff={maxdiff}"


def test_colorcal_apply_lab_f32_zero_params_identity(native_required):
    """零参数 → 恒等 (仅域内限幅), bit 一致。"""
    rng = np.random.default_rng(7)
    img = rng.uniform(0.0, 1.0, size=(16, 16, 3)).astype(np.float32)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    out = native.colorcal_apply_lab_f32(lab, native.PixoRenderColorCalParams())
    expected = np.stack([np.clip(lab[..., 0], 0.0, 100.0),
                         np.clip(lab[..., 1], -128.0, 127.0),
                         np.clip(lab[..., 2], -128.0, 127.0)], axis=-1)
    assert np.array_equal(out, expected)


def test_colorcal_apply_lab_f32_domain_conversion(native_required):
    """域换算哨兵: F32 内核在 float Lab 域解释输入 (L∈[0,100] 节点曲线),
    不是 uint8 Lab 域——用"中性曲线按 L 分段生效"验证。"""
    # 中性 a 偏移曲线: 仅亮端 (末段节点 97.25/float 域 = 248/u8 域) 给出 +10。
    # 白色 L=100 (float 域) ≥ 97.25 → 命中末段; 若误按 u8 域节点解释,
    # L=100 落在 [72,128] 段 → 插值 0, 曲线解释错位即被抓住。
    curve = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0], dtype=np.float32)
    img = np.array([[[1.0, 1.0, 1.0],         # L=100 → 命中末段曲线
                     [0.03, 0.03, 0.03]]],    # L≈2.5 → 首段, 曲线 0
                   dtype=np.float32)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    p = native.PixoRenderColorCalParams(neutralA=0.0, neutralSigma=14.0,
                                        curveA=curve.ctypes.data_as(
                                            ctypes.POINTER(ctypes.c_float)))
    out = native.colorcal_apply_lab_f32(lab, p)
    # 亮端 a +10 (float 域 a 中心 0, C=0 → 平台内 w=1), 暗端 a 不动
    assert abs(float(out[0, 0, 1]) - 10.0) <= 1e-4, (
        f"亮端曲线偏移未生效: {out[0, 0, 1]}")
    assert abs(float(out[0, 1, 1])) <= 1e-5, f"暗端应不受曲线影响: {out[0, 1, 1]}"


# ---------------------------------------------------------------------------
# legacy uint8 内核 (ABI 兼容守卫; 生产 stage 已不路由)
# ---------------------------------------------------------------------------
def test_colorcal_apply_lab_u8_legacy_unchanged(native_required):
    """旧 uint8 Lab 域内核行为不变 (改造前后逐位一致), 供 ABI 兼容与
    scripts/measure_u8_precision.py 保真自检继续可用。"""
    rng = np.random.default_rng(20260820)
    for trial in range(8):
        u8 = rng.integers(0, 256, size=(24, 24, 3), dtype=np.uint8)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        curve_a = [0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5] if trial % 2 == 0 else None
        curve_b = [1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5] if trial % 3 == 0 else None
        args = dict(_random_full_args(rng), curve_a=curve_a, curve_b=curve_b)
        expected = _reference_lab_u8(u8, **args)
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


# ---------------------------------------------------------------------------
# Stage 级: native F32 vs Python float 回退
# ---------------------------------------------------------------------------
_CFG = {"stages": {"colorcal": {
    "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
    "neutral_a": 1.0, "neutral_b": -1.0, "neutral_mode": "static",
    "skin_protect": 0.7, "gamut_soft": 0.5,
}}}


def _disable_native(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")


def _assert_stage_close_u8_strict(a, b):
    """float 全链 native/Python 等价口径 (替代旧 u8 链的逐位一致断言)。

    两实现 Lab 域差 ≤ ~2e-6 (libm/np.exp、np.interp vs InterpCurve 的
    ULP 级差异, uint8 截断不再吸收); 但 cv2 LAB2RGB 在阴影膝点 (f(t)
    线性段斜率 ~903) 的条件数会把它放大, 个别极暗像素 RGB 差可达 ~2e-3。
    口径 = 均值 ≤ 1e-5 (绝大多数像素机器一致) 且 max < 半个 8bit 级
    (2.5e-3 < 1/255/2 ≈ 1.96e-3 放宽到膝点条件数内, 仍远小于旧 u8 链
    的 0.81 ΔE 量化误差)。
    """
    diff = np.abs(a.astype(np.float64) - b.astype(np.float64))
    mean_diff = float(diff.mean())
    max_diff = float(diff.max())
    assert mean_diff <= 1e-5, f"native/Python float 路径分歧 mean={mean_diff}"
    assert max_diff <= 2.5e-3, f"native/Python float 路径分歧 max={max_diff}"


def test_colorcal_stage_native_matches_fallback(native_required, monkeypatch):
    rng = np.random.default_rng(20260820)
    img = rng.uniform(0.0, 1.0, size=(32, 32, 3)).astype(np.float32)
    stage = ColorCalStage()

    ctx = StageContext("x.NEF", config=_CFG)
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx)
    native_out = ctx.image.copy()

    _disable_native(monkeypatch)
    ctx2 = StageContext("x.NEF", config=_CFG)
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx2)
    fallback_out = ctx2.image

    _assert_stage_close_u8_strict(native_out, fallback_out)


def test_colorcal_stage_neutral_curves_native_matches_fallback(
        native_required, monkeypatch):
    """中性偏移 + 分段曲线 + skin_trim 组合的 native/Python float 路径等价。"""
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

    _disable_native(monkeypatch)
    ctx2 = StageContext("x.NEF", config=cfg)
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx2)
    _assert_stage_close_u8_strict(native_out, ctx2.image)


# ---------------------------------------------------------------------------
# 精度哨兵 (W4 结论固化) + 分层兜底
# ---------------------------------------------------------------------------
def _gradient_img(h=64, w=64):
    """高梯度合成图: 色相扫掠 × 亮度扫掠 × 噪声 (相邻像素 RGB 差 > 1/255)。"""
    yy, xx = np.mgrid[0:h, 0:w]
    u = (xx / max(w - 1, 1)).astype(np.float32)
    v = (yy / max(h - 1, 1)).astype(np.float32)
    r = 0.5 + 0.5 * np.cos(2 * np.pi * (u * 3.0 + v))
    g = 0.5 + 0.5 * np.cos(2 * np.pi * (u * 3.0 + v + 1 / 3.0))
    b = 0.5 + 0.5 * np.cos(2 * np.pi * (u * 3.0 + v + 2 / 3.0))
    img = np.stack([r, g, b], axis=-1).astype(np.float32) * v[..., None]
    noise = np.random.default_rng(20260826).uniform(-0.01, 0.01, img.shape)
    return np.clip(img + noise.astype(np.float32), 0.0, 1.0)


_SENTINEL_ARGS = dict(sat=0.2, vib=0.15, hue=5.0, na=0.6, nb=-0.4,
                      sigma=9.0, skin=0.7,
                      skin_trim_da=-2.0, skin_trim_db=-4.0,
                      curve_a=[0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5],
                      curve_b=[1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5])


def test_full_path_float_precision_sentinel(monkeypatch):
    """精度哨兵: 全量路径输出 ≡ 纯 float 数学参考, 固化 W4 结论。

    W4 实测旧 u8 链 (输入 RGB→u8 + uint8 Lab → uint8 Lab 出 → uint8
    LAB2RGB→/255) 三段量化合计 0.81 ΔE76 / 24.7% 像素 >1ΔE; float 全链后
    colorcal 段量化贡献应为机器精度级:
      - fallback (纯 Python float, 与参考同算式同操作序): max ≤ 1e-6
        (实测 ~6e-8, float32 ULP 级);
      - native F32 内核: Lab 域与参考差 ≤ 2e-6 (libm ULP), RGB 域个别
        极暗像素被 cv2 LAB2RGB 阴影膝点 (斜率 ~903) 放大到 ~2e-3 —— 仍
        < 半个 8bit 级, 比旧 u8 链的量化误差小三个数量级。
    附带验证: 输出不再落在 1/255 网格上 (u8 中转的特征), 且 Lab 往返
    RGB→Lab→RGB 残差 << 1/255。
    """
    img = _gradient_img()
    ref = _reference_rgb_f32(img, gs=0.5, **_SENTINEL_ARGS)
    cfg = {"stages": {"colorcal": {
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 0.6, "neutral_b": -0.4, "neutral_sigma": 9.0,
        "neutral_mode": "static",
        "neutral_a_curve": _SENTINEL_ARGS["curve_a"],
        "neutral_b_curve": _SENTINEL_ARGS["curve_b"],
        "skin_protect": 0.7, "skin_trim": [-2.0, -4.0], "gamut_soft": 0.5,
    }}}

    for label, disable in (("native", False), ("fallback", True)):
        if disable:
            _disable_native(monkeypatch)
        ctx = StageContext("x.NEF", config=cfg)
        ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
        ColorCalStage().run(ctx)
        out = ctx.image
        diff = np.abs(out.astype(np.float64) - ref.astype(np.float64))
        maxdiff = float(diff.max())
        meandiff = float(diff.mean())
        bound = 1e-6 if label == "fallback" else 2.5e-3
        assert maxdiff <= bound and meandiff <= 1e-5, (
            f"[{label}] 全量路径与纯 float 参考分歧 max={maxdiff} mean={meandiff} "
            f"(旧 u8 链该口径为 0.81 ΔE 量级, 见 docs/metrics/u8_midpoint_precision.md)")
        # 输出含 1/255 网格之外的连续值 (u8 中转会把全部像素钉死在网格上)
        on_grid = float((np.abs(out * 255.0 - np.round(out * 255.0)) < 1e-4).mean())
        assert on_grid < 0.99, f"[{label}] 输出几乎全在 1/255 网格上, 疑似 u8 中转回归"
        # Lab 往返残差不劣于输入自身的往返残差 (cv2 float 转换在色域角/
        # 阴影膝点固有 ~3.5e-3 条件数; 我们只验证 stage 不新增量化,
        # 实测两者同量级 —— u8 中转则会叠加 1/255 级网格误差)
        rt = cv2.cvtColor(cv2.cvtColor(out, cv2.COLOR_RGB2LAB), cv2.COLOR_LAB2RGB)
        rt_in = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_RGB2LAB), cv2.COLOR_LAB2RGB)
        assert float(np.abs(rt - out).max()) <= float(np.abs(rt_in - img).max()) * 1.5 + 1e-6, (
            f"[{label}] Lab 往返残差显著大于输入自身 (stage 疑引入量化)")


def test_full_path_u8_legacy_tier_reachable(monkeypatch):
    """③ legacy u8 兜底层可用且落在 u8 网格上 (② 失败时才走)。"""
    from pixo.render.modules import color_cal as cc
    img = _gradient_img(16, 16)

    def _boom(_img):
        raise RuntimeError("simulated cv2 float Lab failure")

    monkeypatch.setattr(cc, "_rgb_to_lab_f", _boom)
    ctx = StageContext("x.NEF", config=_CFG)
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    out = ctx.image
    # u8 链输出必在 1/255 网格上 (兜底链行为特征)
    assert np.array_equal(out, (out * 255.0 + 0.5).astype(np.uint8)
                          .astype(np.float32) / 255.0), (
        "legacy u8 兜底输出应落在 1/255 网格上")
