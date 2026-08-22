"""T4 单元测试: 影调曲线原语 (render/core/curves.py)。

覆盖 (验收: 曲线单调、端点 0/1、线性插值精度、锚定≈117、无死代码):
  - 各曲线 LUT 单调 + 端点 0/1 (sRGB EOTF / power / profile curve / filmic)
  - apply_lut1d 线性插值精度 (替代最近邻 floor)
  - curve_anchor_target 锚点 (回退 log2(0.18) / 中灰 ≈117)

运行: python -m pytest tests/test_curves.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pixo.render.core.calibration import DcpProfile
from pixo.render.core.curves import (
    MID_GRAY_GAMMA,
    apply_lut1d,
    apply_lut1d_fast,
    curve_anchor_target,
    curve_lut_from_points,
    make_base_curve_lut,
    make_filmic_lut,
    make_power_lut,
    make_srgb_eotf_lut,
    parse_profile_curve,
    srgb_encode,
)


def _assert_monotonic_endpoints(lut: np.ndarray) -> None:
    assert np.all(np.diff(lut.astype(np.float64)) >= -1e-7), "曲线非单调"
    assert float(lut[0]) == 0.0, f"左端点 {lut[0]} != 0"
    assert abs(float(lut[-1]) - 1.0) < 1e-6, f"右端点 {lut[-1]} != 1"


def _interleaved(xs, ys) -> list:
    return np.column_stack([xs, ys]).ravel().tolist()


def _curve_profile(xs, ys) -> DcpProfile:
    return DcpProfile(path=Path("test.dcp"), profile_tone_curve=_interleaved(xs, ys))


# ---------------------------------------------------------------------------
# 曲线单调 + 端点 (AC-03)
# ---------------------------------------------------------------------------

def test_srgb_eotf_lut_monotonic_endpoints():
    _assert_monotonic_endpoints(make_srgb_eotf_lut(4096))


def test_power_lut_monotonic_endpoints():
    _assert_monotonic_endpoints(make_power_lut(2.2, 4096))
    _assert_monotonic_endpoints(make_power_lut(1.8, 4096))


def test_base_curve_lut_default_is_srgb():
    srgb = make_srgb_eotf_lut(4096)
    assert np.allclose(make_base_curve_lut("srgb", 4096), srgb)
    assert np.allclose(make_base_curve_lut("bogus", 4096), srgb)  # 未知 eotf 回退 srgb


def test_base_curve_lut_power22():
    power = make_power_lut(2.2, 4096)
    assert np.allclose(make_base_curve_lut("power22", gamma=2.2, n=4096), power)
    # 端点仍精确 0/1
    _assert_monotonic_endpoints(make_base_curve_lut("power22", 4096))


def test_profile_curve_lut_monotonic_endpoints():
    xs = np.linspace(0.0, 1.0, 65)
    ys = np.power(xs, 1.0 / 2.2)
    prof = _curve_profile(xs, ys)
    parsed = parse_profile_curve(prof.profile_tone_curve)
    assert parsed is not None
    lut = curve_lut_from_points(*parsed, 4096)
    _assert_monotonic_endpoints(lut)


def test_parse_profile_curve_rejects_non_monotonic():
    xs = np.linspace(0.0, 1.0, 16)
    ys = 1.0 - 4.0 * (xs - 0.5) ** 2  # 先升后降, 非单调, 值域 [0,1]
    assert ys.min() >= -1e-6 and ys.max() <= 1.0 + 1e-6
    prof = _curve_profile(xs, ys)
    assert parse_profile_curve(prof.profile_tone_curve) is None


def test_parse_profile_curve_rejects_garbage():
    assert parse_profile_curve(None) is None
    assert parse_profile_curve([0.0, 0.0, 1.0]) is None  # 奇数长度
    assert parse_profile_curve([0.0] * 8) is None       # 过短


# ---------------------------------------------------------------------------
# 线性插值精度 (apply_lut1d)
# ---------------------------------------------------------------------------

def test_apply_lut1d_matches_np_interp():
    lut = np.power(np.linspace(0.0, 1.0, 4096, dtype=np.float64), 2.2).astype(np.float32)
    rng = np.random.default_rng(1)
    x = rng.random((50, 50)).astype(np.float32)
    y = apply_lut1d(x, lut)
    grid = np.linspace(0.0, 1.0, 4096, dtype=np.float64)
    expected = np.interp(x, grid, lut)
    assert float(np.abs(y - expected).max()) < 1e-5, "线性插值结果偏离 np.interp"


def test_apply_lut1d_linear_more_accurate_than_nearest():
    n = 4096
    lut = np.power(np.linspace(0.0, 1.0, n, dtype=np.float64), 2.2).astype(np.float32)
    # 采样点落在两格正中 (最近邻误差最大处)
    x = (np.arange(512, dtype=np.float64) + 0.5) / (n - 1)
    true = np.power(x, 2.2)
    y_lin = apply_lut1d(x.astype(np.float32), lut)
    i = np.floor(x * (n - 1)).astype(np.int32)
    y_near = lut[i]
    err_lin = float(np.abs(y_lin - true).max())
    err_near = float(np.abs(y_near - true).max())
    assert err_lin < err_near, f"线性插值 {err_lin:.3e} 未优于最近邻 {err_near:.3e}"
    assert err_lin < 1e-3


def test_apply_lut1d_clamps_out_of_range():
    lut = make_power_lut(2.2, 4096)
    out = apply_lut1d(np.array([-1.0, 0.0, 0.5, 1.0, 3.0], dtype=np.float32), lut)
    assert float(out[0]) == float(lut[0]) == 0.0     # x<0 → 左端点
    assert float(out[1]) == float(lut[0]) == 0.0     # x=0 → 左端点
    assert float(out[3]) == float(lut[-1]) == 1.0    # x=1 → 右端点
    assert float(out[4]) == float(lut[-1]) == 1.0    # x>1 → 右端点 (截断)


def test_apply_lut1d_identity_lut_roundtrip():
    lut = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
    x = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    assert float(np.abs(apply_lut1d(x, lut) - x).max()) < 1e-6


# ---------------------------------------------------------------------------
# filmic 无死代码 (仍单调、有限、端点精确)
# ---------------------------------------------------------------------------

def test_filmic_lut_monotonic_endpoints_no_dead_code():
    for kw in ({}, {"contrast": 0.2}, {"toe": 0.5, "contrast": 0.3},
               {"shoulder": 0.4, "contrast": 0.2, "toe": 0.3}):
        lut = make_filmic_lut(4096, **kw)
        assert np.all(np.isfinite(lut)), f"filmic 出现非有限值: {kw}"
        _assert_monotonic_endpoints(lut)


# ---------------------------------------------------------------------------
# 曝光锚点 (curve_anchor_target) + 中灰 ≈117
# ---------------------------------------------------------------------------

def test_mid_gray_gamma_is_117():
    assert abs(MID_GRAY_GAMMA - 0.18 ** (1.0 / 2.2)) < 1e-9
    assert abs(MID_GRAY_GAMMA * 255.0 - 117.0) < 0.5


def test_curve_anchor_target_fallback():
    assert abs(curve_anchor_target(None) - np.log2(0.18)) < 1e-9


def test_curve_anchor_target_power_curve():
    # 曲线恰为 x^(1/2.2) → curve(0.18)=MID_GRAY_GAMMA, 反演锚点 = log2(0.18)
    xs = np.linspace(0.0, 1.0, 4097)
    ys = np.power(xs, 1.0 / 2.2)
    prof = _curve_profile(xs, ys)
    anchor = curve_anchor_target(prof)
    assert abs(anchor - np.log2(0.18)) < 1e-6


def test_curve_anchor_target_outputs_mid_gray():
    # 反演锚点后经曲线应输出中灰 (≈117)
    xs = np.linspace(0.0, 1.0, 65)
    ys = np.power(xs, 1.0 / 2.2)
    prof = _curve_profile(xs, ys)
    x = 2.0 ** curve_anchor_target(prof)
    # 锚定后的线性值经 power 曲线 → 中灰 gamma → ≈117
    lut = make_power_lut(2.2, 4096)
    gamma = apply_lut1d(np.array([x], dtype=np.float32), lut)
    assert abs(float(gamma[0]) * 255.0 - 117.0) < 1.0


def test_curve_anchor_target_clamped():
    # 陡峭曲线 (x^0.1) 把中灰输出压到极小线性输入 → 锚点钳位到下限 0.02
    xs = np.linspace(0.0, 1.0, 2049)
    ys = np.power(xs, 0.1)
    prof = _curve_profile(xs, ys)
    anchor = curve_anchor_target(prof)
    assert abs(anchor - np.log2(0.02)) < 1e-12


# ---------------------------------------------------------------------------
# tone Stage: profile_curve 默认关闭 (基座 sRGB EOTF) + Adobe look 开关 + 回退曲线基
# ---------------------------------------------------------------------------

def test_tone_stage_default_profile_curve_disabled():
    from pixo.render.modules.tone_map import ToneStage
    defaults = ToneStage().default_params()
    # 基座影调 = sRGB EOTF; ProfileToneCurve 默认关闭 (保留为 Adobe look 开关, 见 tone.py)
    assert defaults["profile_curve"] is False
    assert defaults["eotf"] == "srgb"
    assert defaults["use_filmic"] is False


def test_tone_stage_applies_profile_curve():
    from pixo.render.modules.tone_map import ToneStage
    from pixo.render.pipeline.graph import StageContext, DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB

    xs = np.linspace(0.0, 1.0, 65)
    ys = np.power(xs, 1.0 / 2.2)
    prof = _curve_profile(xs, ys)
    x = np.linspace(0.0, 1.0, 64, dtype=np.float32)
    img = np.repeat(np.repeat(x[None, :, None], 16, axis=0), 3, axis=2)
    ctx = StageContext("t.nef", prof=prof, config={})
    ctx.set_image(img, DOMAIN_LINEAR_RGB)
    # profile_curve=True 显式开启 Adobe look (默认关闭); brightness 钉 0 以测曲线本体
    ToneStage({"profile_curve": True, "brightness": 0.0}).run(ctx)
    assert ctx.domain == DOMAIN_GAMMA_RGB
    assert ctx.state["tone_profile_curve"] is True
    # 热路径用 16384 级最近邻快查表 (apply_lut1d_fast, 量化误差 <1/16384)
    expected = apply_lut1d_fast(img, curve_lut_from_points(xs, ys, 16384))
    assert float(np.abs(ctx.image - expected).max()) < 1e-5


def test_tone_stage_fallback_srgb_when_no_curve():
    from pixo.render.modules.tone_map import ToneStage
    from pixo.render.pipeline.graph import StageContext, DOMAIN_LINEAR_RGB

    x = np.linspace(0.0, 1.0, 64, dtype=np.float32)
    img = np.repeat(np.repeat(x[None, :, None], 16, axis=0), 3, axis=2)
    ctx = StageContext("t.nef", prof=None, config={})
    ctx.set_image(img, DOMAIN_LINEAR_RGB)
    ToneStage({"brightness": 0.0}).run(ctx)  # 默认 profile_curve=False → sRGB EOTF 曲线基; brightness 钉 0 测曲线本体
    assert ctx.state["tone_profile_curve"] is False
    assert ctx.state["tone_eotf"] == "srgb"
    expected = apply_lut1d_fast(img, make_srgb_eotf_lut(16384))
    assert float(np.abs(ctx.image - expected).max()) < 1e-5
