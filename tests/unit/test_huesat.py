"""T3 单元测试: DCP HueSatMap / LookTable 解码 + huesat Stage 门控 (R11 后)。

覆盖对象:
  - pixo.render.core.huesat.decode_table / get_hue_sat_table / get_look_table
    (数据访问; R11 起 HSV 三线性应用链 apply_table_to_hsv/apply_hue_sat_map/
    apply_look_table 已删 —— B 轨应用见 test_huesat_oklch.py, 底座 prophoto
    路径见 test_native_colorcal/tone 相关)
  - pixo.render.modules.huesat.HueSatStage (oklch-or-no-op 门控/分派;
    "hsv" 为退役取值 → warn-once + no-op)
  - make_hue_sat_map (T5 表构造) / _sat_rolloff / apply_local_warm_sat (自研, 保留)

运行: python -m pytest tests/unit/test_huesat.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.huesat import (
    _rgb_to_hsv,
    apply_local_warm_sat,
    decode_table, get_hue_sat_table, get_look_table,
)
from pixo.render.core.color import (linear_prophoto_to_linear_srgb,
                                 linear_srgb_to_linear_prophoto)


class MockProf:
    """最小 DcpProfile 替身 (只用 huesat 需要的字段)。"""

    def __init__(self, hue_sat_map=None, hue_sat_dims=None,
                 look_table=None, look_table_dims=None,
                 hue_sat_encoding=None, look_table_encoding=None,
                 name=""):
        self.hue_sat_map = hue_sat_map
        self.hue_sat_map1 = hue_sat_map
        self.hue_sat_dims = hue_sat_dims
        self.look_table = look_table
        self.look_table_dims = look_table_dims
        self.hue_sat_encoding = hue_sat_encoding
        self.look_table_encoding = look_table_encoding
        self.name = name


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------

def _make_table(H, S, V, hue_fn=None, sat_fn=None, val_fn=None):
    """构造 (H, S, V, 3) 表。默认: hue=0, sat=1, val=1 (恒等)。"""
    table = np.zeros((H, S, V, 3), dtype=np.float32)
    table[..., 0] = 0.0
    table[..., 1] = 1.0
    table[..., 2] = 1.0
    if hue_fn is not None:
        table[..., 0] = np.asarray(hue_fn(np.mgrid[0:H, 0:S, 0:V][0]), np.float32)
    if sat_fn is not None:
        table[..., 1] = np.asarray(sat_fn(np.mgrid[0:H, 0:S, 0:V][1]), np.float32)
    if val_fn is not None:
        table[..., 2] = np.asarray(val_fn(np.mgrid[0:H, 0:S, 0:V][2]), np.float32)
    return table


def _flatten(table):
    """(H,S,V,3) 表 → DCP 平面布局: index = ((v*H)+h)*S+s。"""
    flat = table.transpose(2, 0, 1, 3)  # (V,H,S,3)
    return flat.reshape(-1).tolist()


# ---------------------------------------------------------------------------
# 1) decode_table: 布局正确性 (数据访问, 保留)
# ---------------------------------------------------------------------------

def test_decode_table_layout():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V,
                        hue_fn=lambda h: 10.0 + h,       # 10,11,12,13
                        sat_fn=lambda s: 1.0,
                        val_fn=lambda v: 1.0)
    flat = _flatten(table)
    decoded = decode_table(flat, (H, S, V))
    assert decoded is not None and decoded.shape == (H, S, V, 3)
    assert np.allclose(decoded[..., 0], table[..., 0])
    assert np.allclose(decoded[..., 1], 1.0)
    assert np.allclose(decoded[..., 2], 1.0)


def test_decode_table_insufficient_data():
    assert decode_table([1.0, 2.0], (4, 2, 2)) is None
    assert decode_table(None, (4, 2, 2)) is None


def test_hue_dims_do_not_fallback_to_look_dims():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    prof = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=None, look_table_dims=[H, S, V])
    t, dims, enc = get_hue_sat_table(prof)
    # HueSatMap 必须用 ProfileHueSatMapDims, 不得误用 LookTableDims
    assert dims is None and t is None


def test_sat_rolloff_full_smoothstep():
    """low#1: S 近中性保护区滚降跨 [0, 0.05] 完整 smoothstep (幂 6 压陡底部):
    S=0 → 0 (恒等), S=0.03 → 权重 < 0.1 (不误伤近中性亮部), S≥0.05 → 1 (全效)。"""
    from pixo.render.core.huesat import _sat_rolloff
    assert _sat_rolloff(0.0) == 0.0
    assert _sat_rolloff(0.05) == 1.0
    assert _sat_rolloff(0.1) == 1.0
    assert _sat_rolloff(0.03) < 0.1
    # 单调: S 越小权重越低
    assert _sat_rolloff(0.02) < _sat_rolloff(0.03) < _sat_rolloff(0.04)


# ---------------------------------------------------------------------------
# 2) HueSatStage 门控 (R11: oklch-or-no-op; "hsv" 退役 → warn-once + no-op)
# ---------------------------------------------------------------------------

def test_stage_wants_gating():
    from pixo.render.pipeline.graph import StageContext
    from pixo.render.modules.huesat import HueSatStage

    stage = HueSatStage()
    ctx = StageContext("x.NEF", prof=None)
    assert stage.wants(ctx) is False

    # DCP 无表 (如 Preview 系): 静默 no-op (无 HSM 数据可形变)
    prof_empty = MockProf(name="Nikon Z 5 2 RawLab Preview Baseline")
    ctx2 = StageContext("x.NEF", prof=prof_empty)
    assert stage.wants(ctx2) is False

    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    # 含表 DCP + 名字命中仓库点云 (hsm_oklch_nikon_z_5_2_rawlab_lr_baseline.json)
    prof_hit = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=[H, S, V],
                        name="Nikon Z 5 2 RawLab LR Baseline")
    ctx3 = StageContext("x.NEF", prof=prof_hit,
                        config={"stages": {"huesat": {"enabled": True}}})
    assert stage.wants(ctx3) is True

    ctx4 = StageContext("x.NEF", prof=prof_hit,
                        config={"stages": {"huesat": {"enabled": False}}})
    assert stage.wants(ctx4) is False


def test_stage_wants_no_spec_is_noop():
    """R11 防御语义: oklch 域但点云缺失 → warn-once + no-op (不回退旧链)。"""
    from pixo.render.pipeline.graph import StageContext
    from pixo.render.modules.huesat import HueSatStage, _OKLCH_MISSING_WARNED

    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    prof_miss = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=[H, S, V],
                         name="No Such DCP Profile 12345")
    _OKLCH_MISSING_WARNED.discard("No Such DCP Profile 12345")
    stage = HueSatStage()
    ctx = StageContext("x.NEF", prof=prof_miss,
                       config={"stages": {"huesat": {"enabled": True}}})
    assert stage.wants(ctx) is False


def test_stage_wants_retired_hsv_domain_is_noop():
    """R11: color_domain="hsv" (退役域) → warn-once + no-op。"""
    from pixo.render.pipeline.graph import StageContext
    from pixo.render.modules.huesat import HueSatStage, _OKLCH_MISSING_WARNED

    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    prof_hit = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=[H, S, V],
                        name="Nikon Z 5 2 RawLab LR Baseline")
    _OKLCH_MISSING_WARNED.discard("hsv")
    stage = HueSatStage()
    ctx = StageContext("x.NEF", prof=prof_hit,
                       config={"stages": {"huesat": {"enabled": True,
                                                     "color_domain": "hsv"}}})
    assert stage.wants(ctx) is False


def test_stage_process_dispatch_oklch_vs_noop():
    """分派钉死: oklch+点云 → 形变应用 (metrics.color_domain=oklch);
    退役域/点云缺失 → no-op (metrics.color_domain=none)。"""
    from pixo.render.pipeline.graph import StageContext
    from pixo.render.modules.huesat import HueSatStage, _OKLCH_MISSING_WARNED

    stage = HueSatStage()
    img = np.random.default_rng(5).random((32, 32, 3)).astype(np.float32) * 0.8

    # oklch + 仓库点云命中 → 应用
    ctx = StageContext("x.NEF", prof=MockProf(name="Nikon Z 5 2 RawLab LR Baseline"),
                       config={"stages": {"huesat": {"enabled": True}}})
    ctx.set_image(img.copy(), "linear_rgb")
    stage.run(ctx)
    assert ctx.results[-1].metrics["color_domain"] == "oklch"
    assert not np.array_equal(ctx.image, img)

    # 退役域 → no-op
    _OKLCH_MISSING_WARNED.discard("hsv")
    ctx2 = StageContext("x.NEF", prof=MockProf(name="Nikon Z 5 2 RawLab LR Baseline"),
                        config={"stages": {"huesat": {"enabled": True,
                                                      "color_domain": "hsv"}}})
    ctx2.set_image(img.copy(), "linear_rgb")
    stage.run(ctx2)
    assert ctx2.results[-1].metrics["color_domain"] == "none"
    assert np.array_equal(ctx2.image, img)

    # oklch 但点云缺失 → no-op
    _OKLCH_MISSING_WARNED.discard("No Such DCP Profile 12345")
    ctx3 = StageContext("x.NEF", prof=MockProf(name="No Such DCP Profile 12345"),
                        config={"stages": {"huesat": {"enabled": True}}})
    ctx3.set_image(img.copy(), "linear_rgb")
    stage.run(ctx3)
    assert ctx3.results[-1].metrics["color_domain"] == "none"
    assert np.array_equal(ctx3.image, img)


def test_stage_invalid_domain_raises():
    from pixo.render.pipeline.graph import StageContext
    from pixo.render.modules.huesat import HueSatStage
    stage = HueSatStage()
    ctx = StageContext("x.NEF", prof=MockProf(name="x"),
                       config={"stages": {"huesat": {"enabled": True,
                                                     "color_domain": "lab"}}})
    with pytest.raises(ValueError):
        stage.wants(ctx)


def test_make_hue_sat_map_per_band_val_min():
    """make_hue_sat_map 支持 4 元组 (center, halfwidth, sat, val_min):
    不同 band 可指定不同 V 窗口, 互不改变其他 band 的 V 权重。"""
    from pixo.render.core.huesat import make_hue_sat_map
    flat = make_hue_sat_map([(272.5, 37.5, 0.5, 0.6), (22.5, 17.5, 2.0, 0.8)])
    arr = np.asarray(flat, np.float32).reshape(16, 90, 16, 3).transpose(1, 2, 0, 3)
    # 品红带 (val_min=0.6): V=0.8 行被压缩; V=0.533 行在窗口起点 → 不变
    assert arr[int(272 / 360 * 90), 8, 12, 1] < 1.0
    assert arr[int(272 / 360 * 90), 8, 8, 1] == 1.0
    # 暖带 (val_min=0.8): V 低行不受影响 (窗口从 ~0.733 才开始), V 高行被提升
    assert arr[int(22.5 / 360 * 90), 8, 7, 1] == 1.0
    assert arr[int(22.5 / 360 * 90), 8, 15, 1] > 1.0


# ---------------------------------------------------------------------------
# 3) apply_local_warm_sat: 问题清单 A1 局部暖色高光饱和 (自研, 保留)
# ---------------------------------------------------------------------------

def _pp_saturation(rgb01: np.ndarray) -> np.ndarray:
    """线性 sRGB → 线性 ProPhoto → HSV S (0..1)。"""
    pp = linear_srgb_to_linear_prophoto(np.asarray(rgb01, dtype=np.float64))
    return _rgb_to_hsv(np.clip(pp, 0.0, None))[1]


def test_local_warm_sat_identity():
    x = np.random.default_rng(3).random((16, 16, 3)).astype(np.float32)
    assert np.array_equal(apply_local_warm_sat(x, 1.0), x)
    assert np.array_equal(apply_local_warm_sat(x, 0.5), x)


def test_local_warm_sat_sparse_warm_spot_only():
    """低覆盖率暖色高光 (烟花/暖灯): 暖斑补饱和, 背景/中性不动。"""
    img = np.full((256, 256, 3), 0.05, np.float32)
    img[120:128, 120:128] = (0.9, 0.3, 0.05)   # 覆盖率 ~0.1%, 低于 coverage_max
    out = apply_local_warm_sat(img, 2.0)
    s0 = float(_pp_saturation(img[124, 124]))
    s1 = float(_pp_saturation(out[124, 124]))
    assert s1 > s0 * 1.08, f"暖斑未补饱和: {s0:.3f} -> {s1:.3f}"
    assert np.array_equal(out[:100, :100], img[:100, :100])  # 背景严格不变
    assert np.array_equal(out[100:, 140:], img[100:, 140:])


def test_local_warm_sat_high_coverage_smooth_field_untouched():
    """大范围平滑暖色区 (暖光室内/日落天空) 不整片加饱和 (锚点安全)。"""
    img = np.full((64, 64, 3), (0.7, 0.2, 0.05), np.float32)
    out = apply_local_warm_sat(img, 3.0)
    assert float(np.abs(out - img).max()) < 1e-5


def test_local_warm_sat_high_coverage_spot_contrast_gets_boost():
    """高覆盖率场景只增强与局部背景有 V 反差的火点, 周围暖场不动。"""
    img = np.full((128, 128, 3), (0.7, 0.2, 0.05), np.float32)
    img[60:68, 60:68] = (1.0, 0.45, 0.05)       # 亮橙火点
    out = apply_local_warm_sat(img, 2.0)
    s0_spot = float(_pp_saturation(img[64, 64]))
    s1_spot = float(_pp_saturation(out[64, 64]))
    s0_field = float(_pp_saturation(img[30, 30]))
    s1_field = float(_pp_saturation(out[30, 30]))
    assert s1_spot > s0_spot, "局部反差火点未被增强"
    assert abs(s1_field - s0_field) < 1e-4, "平滑暖场被误增强"


def test_stage_warm_highlight_wants_and_metrics():
    """warm_highlight_sat>1 时: 无 DCP HSM 数据也要执行; 恒等 scale 仍走旧门控。"""
    from pixo.render.pipeline.graph import StageContext
    from pixo.render.modules.huesat import HueSatStage

    prof = MockProf()
    ctx = StageContext("x.NEF", prof=prof,
                       config={"stages": {"huesat": {"warm_highlight_sat": 2.0}}})
    stage = HueSatStage()
    assert stage.wants(ctx) is True          # 局部暖色高光独立于 DCP HSM 数据
    ctx.set_image(np.zeros((16, 16, 3), np.float32), "linear_rgb")
    stage.run(ctx)
    assert ctx.results[-1].metrics["local_warm_sat"] == 2.0
    assert ctx.results[-1].metrics["hue_sat"] is False

    ctx2 = StageContext("x.NEF", prof=prof,
                        config={"stages": {"huesat": {"warm_highlight_sat": 1.0}}})
    assert stage.wants(ctx2) is False
