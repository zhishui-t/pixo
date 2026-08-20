"""T2 单元测试: HueSatMap 域修复 —— 线性 ProPhoto(D50)、tone 之前。

覆盖对象:
  - rawlab.engine.color.linear_srgb_to_linear_prophoto / linear_prophoto_to_linear_srgb
  - rawlab.engine.huesat.apply_hue_sat_map / apply_look_table (线性域输入)
  - rawlab.engine.huesat._rgb_to_hsv / _hsv_to_rgb (float64 HSV 往返)
  - rawlab.engine.stages.huesat.HueSatStage (order=25 < tone=30, domain=linear_rgb, 默认关)
  - 默认全链 (huesat 关) 输出不变

验收标准 (03-specification §3 AC / 任务 T2):
  - 恒等表精确往返: max|Δ| ≤ 1e-6 (encoding 0/1, HueSatMap 与 LookTable 同验)
  - ProPhoto 转换往返: max|Δ| ≤ 1e-5
  - 端点断言: 黑→黑、白→白、灰→灰; 单调性: 灰阶斜坡单调、S/V 表应用单调
  - 全链默认 (huesat 关) 输出不变; stage order=25 < tone=30; domain=linear_rgb

运行: python -m pytest rawlab/tests/test_huesat_domain.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from rawlab.engine.color import (
    linear_prophoto_to_linear_srgb,
    linear_srgb_to_linear_prophoto,
)
from rawlab.engine.huesat import (
    _hsv_to_rgb,
    _rgb_to_hsv,
    apply_hue_sat_map,
    apply_look_table,
    apply_table_to_hsv,
)

_H, _S, _V = 90, 16, 16  # Adobe Camera 系列联合形态 HueSatMap dims
IDENTITY_TOL = 1e-6       # 恒等表精确往返上限 (规格 AC)
PROPHOTO_TOL = 1e-5       # ProPhoto 转换往返上限 (规格 AC)


class MockProf:
    """最小 DcpProfile 替身: 恒等 ColorMatrix (白平衡链路) + HSM/LookTable 字段。"""

    def __init__(self, hue_sat_map=None, hue_sat_dims=None, hue_sat_encoding=None,
                 look_table=None, look_table_dims=None):
        self.hue_sat_map = hue_sat_map
        self.hue_sat_map1 = hue_sat_map
        self.hue_sat_dims = hue_sat_dims
        self.hue_sat_encoding = hue_sat_encoding
        self.look_table = look_table
        self.look_table_dims = look_table_dims
        # 白平衡链路 (identity ColorMatrix, 与 test_pipeline.MockProf 一致)
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


def _identity_table(H=_H, S=_S, V=_V):
    """(H,S,V,3) 恒等表: 每格 (hue_shift=0, sat_scale=1, val_scale=1)。"""
    t = np.zeros((H, S, V, 3), dtype=np.float32)
    t[..., 0] = 0.0
    t[..., 1] = 1.0
    t[..., 2] = 1.0
    return t


def _flatten(table):
    """(H,S,V,3) 表 → DCP 平面布局: index = ((v*H)+h)*S+s。"""
    return table.transpose(2, 0, 1, 3).reshape(-1).tolist()


def _sample_inputs(n=3000):
    """随机 + 结构化采样: 端点/灰/基色/高饱和/近黑近白, 覆盖 HSV 边界情形。"""
    rng = np.random.default_rng(20260816)
    x = rng.random((n, 3)).astype(np.float32)
    extra = np.array([
        [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.5, 0.5, 0.5],
        [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
        [1.0, 1.0, 0.0], [0.0, 1.0, 1.0], [1.0, 0.0, 1.0],
        [0.1, 0.2, 0.3], [0.9, 0.1, 0.5], [0.05, 0.5, 0.95],
        [0.99, 0.99, 0.01], [0.001, 0.002, 0.003],
        [0.5, 0.1, 0.05], [0.3, 0.7, 0.2], [0.8, 0.8, 0.2],
    ], dtype=np.float32)
    return np.concatenate([x, extra])


# ---------------------------------------------------------------------------
# 1) ProPhoto 域转换: 往返精度 / 端点 / 单调性
# ---------------------------------------------------------------------------

def test_prophoto_roundtrip():
    """线性 sRGB ↔ 线性 ProPhoto 往返 (含 >1 高光值) ≤ 1e-5。"""
    x = _sample_inputs(2000)
    pp = linear_srgb_to_linear_prophoto(x)
    back = linear_prophoto_to_linear_srgb(pp)
    err = float(np.abs(back - x).max())
    assert err <= PROPHOTO_TOL, f"sRGB→ProPhoto→sRGB 往返误差 {err:.3e} ≥ {PROPHOTO_TOL}"
    # 反向 (ProPhoto → sRGB → ProPhoto)
    pp2 = linear_srgb_to_linear_prophoto(back)
    assert float(np.abs(pp2 - pp).max()) <= PROPHOTO_TOL
    # >1 线性高光值: 线性变换应精确往返
    hi = np.array([[1.5, 1.2, 0.8], [0.0, 2.0, 0.5], [3.0, 0.1, 1.7]], dtype=np.float32)
    back_hi = linear_prophoto_to_linear_srgb(linear_srgb_to_linear_prophoto(hi))
    assert float(np.abs(back_hi - hi).max()) <= PROPHOTO_TOL


def test_prophoto_endpoints():
    """端点断言: 黑→黑, 白→白, 灰→灰 (中性保持)。"""
    black = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    assert np.array_equal(linear_srgb_to_linear_prophoto(black), black)
    assert np.array_equal(linear_prophoto_to_linear_srgb(black), black)

    white = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    pw = linear_srgb_to_linear_prophoto(white)
    assert float(np.abs(pw - white).max()) <= PROPHOTO_TOL, f"白→白误差 {np.abs(pw - white).max():.3e}"
    sw = linear_prophoto_to_linear_srgb(white)
    assert float(np.abs(sw - white).max()) <= PROPHOTO_TOL

    gray = np.full((1, 3), 0.5, dtype=np.float32)
    pg = linear_srgb_to_linear_prophoto(gray)
    sg = linear_prophoto_to_linear_srgb(gray)
    assert float(np.ptp(pg)) <= PROPHOTO_TOL, "灰经转换后通道不等 (非中性)"
    assert float(np.ptp(sg)) <= PROPHOTO_TOL


def test_prophoto_gray_ramp_monotonic():
    """单调性: 灰阶斜坡 (t,t,t) 转换后每通道单调不减 (行和为正 ⇒ 单调)。"""
    t = np.linspace(0.0, 1.0, 257, dtype=np.float32)
    g = np.stack([t, t, t], axis=-1)
    for name, out in (("fwd", linear_srgb_to_linear_prophoto(g)),
                      ("back", linear_prophoto_to_linear_srgb(g))):
        for c in range(3):
            ch = out[:, c].astype(np.float64)
            assert np.all(np.diff(ch) >= -1e-6), f"{name} 通道 {c} 灰阶非单调"


def test_hsv_float64_roundtrip():
    """HSV 自实现 (float64) 往返精度 ≪ 1e-6 (恒等表预算不在此消耗)。"""
    x = _sample_inputs(2000).astype(np.float64)
    h, s, v = _rgb_to_hsv(x)
    y = _hsv_to_rgb(h, s, v)
    err = float(np.abs(y - x).max())
    assert err <= 1e-10, f"HSV 往返误差 {err:.3e} 过大"


# ---------------------------------------------------------------------------
# 2) 恒等表精确往返 (域修复核心验收: max|Δ| ≤ 1e-6)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("encoding", [0, 1])
def test_identity_table_roundtrip(encoding):
    """恒等表 (线性域输入) 精确往返: max|Δ| ≤ 1e-6, encoding 0/1 同验。"""
    prof = MockProf(hue_sat_map=_flatten(_identity_table()), hue_sat_dims=[_H, _S, _V],
                    hue_sat_encoding=encoding)
    x = _sample_inputs()
    y = apply_hue_sat_map(x, prof, strength=1.0)
    assert y.shape == x.shape and y.dtype == np.float32
    err = float(np.abs(y - x).max())
    assert err <= IDENTITY_TOL, \
        f"恒等表往返 (encoding={encoding}) max|Δ| {err:.3e} ≥ {IDENTITY_TOL}"


def test_identity_table_roundtrip_look_table():
    """LookTable 恒等表同域往返 ≤ 1e-6 (与 HueSatMap 同一色彩空间)。"""
    prof = MockProf(look_table=_flatten(_identity_table()), look_table_dims=[_H, _S, _V])
    x = _sample_inputs(1500)
    y = apply_look_table(x, prof, strength=1.0)
    err = float(np.abs(y - x).max())
    assert err <= IDENTITY_TOL, f"LookTable 恒等往返 max|Δ| {err:.3e} ≥ {IDENTITY_TOL}"


def test_identity_table_roundtrip_small_dims():
    """小表 (16×8×8) 恒等往返 ≤ 1e-6 —— 三线性插值路径 (非退化为格点直读)。"""
    H, S, V = 16, 8, 8
    prof = MockProf(hue_sat_map=_flatten(_identity_table(H, S, V)), hue_sat_dims=[H, S, V],
                    hue_sat_encoding=1)
    x = _sample_inputs(2000)
    err = float(np.abs(apply_hue_sat_map(x, prof) - x).max())
    assert err <= IDENTITY_TOL, f"小表恒等往返 max|Δ| {err:.3e} ≥ {IDENTITY_TOL}"


def test_identity_table_roundtrip_above_one():
    """线性域高光 (>1) 恒等表往返 ≤ 1e-6: 高光不截顶 (查表坐标钳到 V 边界行)。"""
    prof = MockProf(hue_sat_map=_flatten(_identity_table()), hue_sat_dims=[_H, _S, _V],
                    hue_sat_encoding=1)
    x = np.array([[1.5, 1.2, 0.8], [0.0, 2.0, 0.5], [3.0, 0.1, 1.7],
                  [0.9, 0.3, 1.4], [2.84, 0.0, 0.12]], dtype=np.float32)
    y = apply_hue_sat_map(x, prof)
    assert y.shape == x.shape and y.dtype == np.float32
    assert np.isfinite(y).all() and float(y.min()) >= 0.0
    err = float(np.abs(y - x).max())
    assert err <= IDENTITY_TOL, f"高光恒等往返 max|Δ| {err:.3e} ≥ {IDENTITY_TOL}"


# ---------------------------------------------------------------------------
# 3) 单调性断言 (表应用路径)
# ---------------------------------------------------------------------------

def test_sat_val_monotonicity():
    """sat_scale/val_scale ≥ 1 的常数表: 输出 S/V 随输入 S/V 斜坡单调不减。"""
    H, S, V = 16, 8, 8
    table = np.zeros((H, S, V, 3), dtype=np.float32)
    table[..., 0] = 0.0
    table[..., 1] = 2.0   # sat_scale 恒 2
    table[..., 2] = 1.5   # val_scale 恒 1.5
    n = 513

    s_ramp = np.linspace(0.0, 1.0, n, dtype=np.float64)
    h_fix = np.zeros_like(s_ramp)
    v_fix = np.full_like(s_ramp, 0.8)
    _, s_out, _ = apply_table_to_hsv(h_fix, s_ramp, v_fix, table, (H, S, V), strength=1.0)
    assert np.all(np.diff(s_out) >= -1e-6), "输出 S 随输入 S 非单调"

    v_ramp = np.linspace(0.0, 1.0, n, dtype=np.float64)
    h_fix = np.zeros_like(v_ramp)
    s_fix = np.full_like(v_ramp, 0.5)
    _, _, v_out = apply_table_to_hsv(h_fix, s_fix, v_ramp, table, (H, S, V), strength=1.0)
    assert np.all(np.diff(v_out) >= -1e-6), "输出 V 随输入 V 非单调"
    # V 只钳下界 (线性域语义): val_scale=1.5 不再截顶到 1.0
    assert float(v_out[-1]) == pytest.approx(1.5, abs=1e-6)


# ---------------------------------------------------------------------------
# 4) Stage 注册: order=25 < tone=30, domain=linear_rgb, 默认关
# ---------------------------------------------------------------------------

def test_stage_order_domain():
    from rawlab.engine.core import DOMAIN_LINEAR_RGB
    from rawlab.engine.stages.huesat import HueSatStage
    from rawlab.engine.stages.tone import ToneStage

    hs = HueSatStage()
    assert hs.order == 25
    assert hs.order < ToneStage().order == 30          # tone 之前
    assert hs.domain_in == DOMAIN_LINEAR_RGB
    assert hs.domain_out == DOMAIN_LINEAR_RGB
    assert hs.default_params() == {"enabled": False, "strength": 1.0}


# ---------------------------------------------------------------------------
# 5) 全链默认 (huesat 关) 输出不变 + 启用时域/顺序正确
# ---------------------------------------------------------------------------

def _run_default_chain(prof, img, params):
    from rawlab.engine import build_default_pipeline
    from rawlab.engine.core import DOMAIN_LINEAR_CAM, StageContext

    pipe = build_default_pipeline(prof=prof, params=params)
    ctx = StageContext("x.NEF", prof=prof, config={"stages": params})
    ctx.set_image(img.copy(), DOMAIN_LINEAR_CAM)
    out = pipe.run(ctx)
    return ctx, out


def test_default_chain_output_unchanged_with_huesat_disabled():
    """默认全链 (huesat 关): 有无 HSM 表的 profile 输出逐位一致。"""
    params = {"exposure": {"mode": "off"}, "whitebalance": {"mode": "off"},
              "skin": {"enabled": False}}
    H, S, V = 16, 8, 8
    table = np.zeros((H, S, V, 3), dtype=np.float32)
    table[..., 0] = 15.0   # hue_shift 15° (非恒等: 若被应用必改变输出)
    table[..., 1] = 1.0
    table[..., 2] = 1.0
    prof_with = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=[H, S, V])
    prof_without = MockProf()
    img = np.random.default_rng(7).random((16, 16, 3)).astype(np.float32)

    ctx1, out1 = _run_default_chain(prof_with, img, params)
    ctx2, out2 = _run_default_chain(prof_without, img, params)

    assert ctx1.domain == "gamma_rgb"
    assert [r.name for r in ctx1.results] == [r.name for r in ctx2.results]
    assert "huesat" not in [r.name for r in ctx1.results]   # 默认关 → 未执行
    assert np.array_equal(out1, out2), "huesat 默认关时全链输出应逐位不变"


def test_huesat_enabled_identity_chain_before_tone():
    """启用 huesat (恒等表): 在 tone 之前执行, 线性域接线无域错位, 输出有限。"""
    params = {"exposure": {"mode": "off"}, "whitebalance": {"mode": "off"},
              "skin": {"enabled": False}, "huesat": {"enabled": True}}
    prof = MockProf(hue_sat_map=_flatten(_identity_table(16, 8, 8)),
                    hue_sat_dims=[16, 8, 8], hue_sat_encoding=1)
    img = np.random.default_rng(3).random((16, 16, 3)).astype(np.float32)

    ctx, out = _run_default_chain(prof, img, params)

    assert ctx.domain == "gamma_rgb"                        # 终态域正确 (tone 收口)
    names = [r.name for r in ctx.results]
    assert "huesat" in names and "tone" in names
    assert names.index("huesat") < names.index("tone")      # tone 之前执行
    assert out.shape == img.shape and out.dtype == np.float32
    assert np.isfinite(out).all()
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0

    # 恒等表全链 ≈ 关闭 huesat 的基线 (误差经 tone/colorcal 放大后仍很小)
    params_off = dict(params, huesat={"enabled": False})
    _, out_off = _run_default_chain(prof, img, params_off)
    diff = float(np.abs(out.astype(np.float64) - out_off.astype(np.float64)).max())
    assert diff <= 1e-4, f"恒等表全链与基线偏差 {diff:.3e} 过大"
