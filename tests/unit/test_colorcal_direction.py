"""t57 —— colorcal 四向方向语义合成小图单测。

固化 t56 复审的四向方向探针：vibrance/saturation 正负增益下，
colorfulness 与 mean_S 的变化方向必须与规则语义一致，
防止 colorcal 未来实现回归时方向翻转（无需 RAW，纯合成图）。
"""
from __future__ import annotations

import numpy as np

from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext


def _synthetic_image() -> np.ndarray:
    """确定性合成图：色相扫掠渐变 + 中等饱和度斑块（float32 [0,1]）。"""
    h, w = 48, 64
    yy, xx = np.mgrid[0:h, 0:w]
    u = xx / max(w - 1, 1)
    v = yy / max(h - 1, 1)
    r = np.clip(0.35 + 0.45 * u, 0.0, 1.0)
    g = np.clip(0.30 + 0.30 * v, 0.0, 1.0)
    b = np.clip(0.55 - 0.35 * u * v, 0.0, 1.0)
    img = np.stack([r, g, b], axis=-1).astype(np.float32)
    noise = np.random.default_rng(20260825).uniform(-0.02, 0.02, img.shape)
    return np.clip(img + noise.astype(np.float32), 0.0, 1.0)


def _apply(params: dict) -> np.ndarray:
    stage = ColorCalStage()
    ctx = StageContext("synthetic.NEF", config={"stages": {"colorcal": dict(params)}})
    ctx.set_image(_synthetic_image(), DOMAIN_GAMMA_RGB)
    stage.run(ctx)
    return ctx.image


def _colorfulness(rgb: np.ndarray) -> float:
    """Hasler-Süsstrunk 彩度指标（域无关的方向性足够）。"""
    rg = rgb[..., 0] - rgb[..., 1]
    yb = 0.5 * (rgb[..., 0] + rgb[..., 1]) - rgb[..., 2]
    return float(
        np.sqrt(rg.std() ** 2 + yb.std() ** 2)
        + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )


def _mean_s(rgb: np.ndarray) -> float:
    """HSV 语义平均饱和度 S=(max-min)/max。"""
    mx = rgb.max(axis=-1)
    mn = rgb.min(axis=-1)
    s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return float(s.mean())


BASELINE_IMG = None
BASELINE_CF = None
BASELINE_MS = None


def _baseline():
    global BASELINE_IMG, BASELINE_CF, BASELINE_MS
    if BASELINE_IMG is None:
        BASELINE_IMG = _apply({})
        BASELINE_CF = _colorfulness(BASELINE_IMG)
        BASELINE_MS = _mean_s(BASELINE_IMG)
    return BASELINE_CF, BASELINE_MS


MARGIN = 1e-4


def test_zero_gain_matches_baseline_identity():
    cf, ms = _baseline()
    out = _apply({"saturation": 0.0, "vibrance": 0.0})
    assert abs(_colorfulness(out) - cf) < MARGIN
    assert abs(_mean_s(out) - ms) < MARGIN


def test_positive_vibrance_raises_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"vibrance": 0.4})
    assert _colorfulness(out) > cf + MARGIN
    assert _mean_s(out) > ms + MARGIN


def test_negative_vibrance_lowers_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"vibrance": -0.4})
    assert _colorfulness(out) < cf - MARGIN
    assert _mean_s(out) < ms - MARGIN


def test_positive_saturation_raises_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"saturation": 0.4})
    assert _colorfulness(out) > cf + MARGIN
    assert _mean_s(out) > ms + MARGIN


def test_negative_saturation_lowers_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"saturation": -0.4})
    assert _colorfulness(out) < cf - MARGIN
    assert _mean_s(out) < ms - MARGIN


# ---------------------------------------------------------------------------
# schema 绕过修复 (neutral_*_curve / scene_skin_trim / scene_hue) + 曲线 7 点校验
# ---------------------------------------------------------------------------

import pytest


def test_process_read_keys_declared_in_param_schema():
    """process 读取的全部参数键必须声明在 param_schema (不得绕过校验)。"""
    schema = ColorCalStage.param_schema
    for key in ("neutral_a_curve", "neutral_b_curve", "scene_skin_trim",
                "scene_hue", "skin_trim", "scene_trim", "saturation",
                "neutral_mode"):
        assert key in schema, f"colorcal param_schema 缺 {key}"


def test_scene_keys_rejected_when_malformed():
    """补声明后, 非法 scene_skin_trim / scene_hue 结构会被 schema/校验拒绝。"""
    with pytest.raises(ValueError, match="scene_skin_trim"):
        _apply({"scene_skin_trim": [[1.0, 2.0, 3.0]]})   # 列数错
    with pytest.raises(ValueError, match="scene_hue"):
        _apply({"scene_hue": [[1.0, 2.0, 90.0]]})        # deg 越界 [-15,15]


def test_neutral_curve_must_be_seven_points():
    """neutral_a/b_curve 必须为 7 点 (native InterpCurve 无条件读 curve[0..6])。"""
    with pytest.raises(ValueError, match="neutral_a_curve"):
        _apply({"neutral_mode": "static", "neutral_a_curve": [0.0] * 6})
    with pytest.raises(ValueError, match="neutral_b_curve"):
        _apply({"neutral_mode": "static", "neutral_b_curve": [0.0] * 8})
    # 7 点放行 (走全量路径, sat=0 才进快路径; 这里给 sat 微量强制全量)
    out = _apply({"saturation": 0.001, "neutral_mode": "static",
                  "neutral_a_curve": [0.0] * 7, "neutral_b_curve": [0.0] * 7})
    assert out.shape == _synthetic_image().shape


def test_stylize_lut_declared_in_param_schema():
    """stylize 的 lut 键 (LUT3D 实例) 也必须声明 (类型 any 宽松放行)。"""
    from pixo.render.modules.style import StylizeStage
    assert "lut" in StylizeStage.param_schema


def test_dehaze_param_schema_maps_to_dehaze_stage():
    """params.py STAGE_CLASSES['dehaze'] 应映射 DehazeStage (radius 不丢)。"""
    from pixo.render.params import STAGE_CLASSES, get_param_schema
    from pixo.render.modules.dehaze import DehazeStage
    assert STAGE_CLASSES["dehaze"] is DehazeStage
    schema = get_param_schema("dehaze")
    assert "radius" in schema, "dehaze schema 误用 clarity (丢 radius)"


# ---------------------------------------------------------------------------
# S5: 全量路径中性权重与快路径同口径 (平台+高斯尾)
# ---------------------------------------------------------------------------

def _near_neutral_img(c_target=10.0):
    """构造 Lab C≈c_target 的近中性均匀图 (RGB uint8 域内往返)。"""
    import cv2
    lab = np.full((16, 16, 3), [128.0, 128.0 + c_target, 128.0],
                  dtype=np.float32)
    rgb = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
    lab_rt = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    c = float(np.sqrt(((lab_rt[..., 1] - 128.0) ** 2
                       + (lab_rt[..., 2] - 128.0) ** 2).mean()))
    return rgb.astype(np.float32) / 255.0, c


def _lab_a(img01):
    import cv2
    u8 = (np.clip(img01, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)[..., 1]


def _disable_native(monkeypatch):
    """模拟 native DLL 缺失, 强制走 Python 全量回退 (S5 修改的路径)。"""
    from pixo.render import _native as native
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")


def _run_colorcal(img, params):
    """在给定图像上跑 ColorCalStage (本文件 _apply 固定用合成图, 这里要自带图)。"""
    ctx = StageContext("synthetic.NEF", config={"stages": {"colorcal": dict(params)}})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    return ctx.image


def test_full_path_neutral_weight_uses_plateau(monkeypatch):
    """S5: 全量路径 (Python 回退) 中性权重 = 平台(C<=12 全量)+高斯尾。

    旧实现为纯高斯 w=exp(-C²/2σ²): C=10, σ=14 → w≈0.775, 中性校正被缩水
    ~22%; 平台口径应为 w=1.0。用 Δa 直接钉死口径。
    注: native (colorcal.cpp) 仍为纯高斯 —— 已知分歧, 待 native 重编对齐,
    故本测试禁用 native 只验证 Python 回退。
    """
    na = 20.0
    img, c = _near_neutral_img(10.0)
    assert 8.0 <= c <= 12.0, f"构造 C 超出平台内测区: C={c}"
    a_before = float(_lab_a(img).mean())

    _disable_native(monkeypatch)
    # 全量路径: sat 微量非零强制不进快路径 (0.1% 饱和增益对近中性影响 <0.01)
    out_full = _run_colorcal(img, {"saturation": 0.001, "neutral_mode": "static",
                                   "neutral_a": na, "neutral_sigma": 14.0})
    da_full = float(_lab_a(out_full).mean()) - a_before

    w_plateau = 1.0                                   # C<=12 平台内
    w_gauss = float(np.exp(-(c ** 2) / (2.0 * 14.0 ** 2)))
    assert abs(da_full - na * w_plateau) <= 1.5, (
        f"全量路径未用平台口径: Δa={da_full:.2f}, 平台期望 {na * w_plateau:.2f}, "
        f"纯高斯期望 {na * w_gauss:.2f}")
    assert abs(da_full - na * w_plateau) < abs(da_full - na * w_gauss), (
        "Δa 更接近纯高斯口径而非平台口径")


def test_full_path_matches_fast_path_neutral_shift(monkeypatch):
    """同参数下全量路径 (Python 回退) 与快路径的中性校正量一致 (S5 的目的)。"""
    na = 20.0
    img, c = _near_neutral_img(10.0)
    assert 8.0 <= c <= 12.0
    a_before = float(_lab_a(img).mean())

    out_fast = _run_colorcal(img, {"neutral_mode": "static", "neutral_a": na,
                                   "neutral_sigma": 14.0})   # sat=0 → 快路径
    _disable_native(monkeypatch)
    out_full = _run_colorcal(img, {"saturation": 0.001, "neutral_mode": "static",
                                   "neutral_a": na, "neutral_sigma": 14.0})
    da_fast = float(_lab_a(out_fast).mean()) - a_before
    da_full = float(_lab_a(out_full).mean()) - a_before
    assert abs(da_fast - da_full) <= 1.5, (
        f"快/慢路径中性校正分歧: fast={da_fast:.2f} full={da_full:.2f}")
