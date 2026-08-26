"""T3 单元测试: DCP HueSatMap / LookTable 解码与应用。

覆盖对象:
  - pixo.render.core.huesat.decode_table / apply_table_to_hsv / apply_hue_sat_map / apply_look_table
  - pixo.render.modules.huesat.HueSatStage (wants 门控 / 直通)

验收标准 (规格 AC-09 / 任务 T3):
  - 已知偏移合成数据应用正确 (色相偏移/饱和乘数/明度乘数)
  - 色相角环绕正确 (350°+15° → 5°)
  - 无数据直通; strength=0 恒等; strength 线性混合
  - dims 回退: hue_sat_dims 缺失时用 look_table_dims (0xC725)

运行: python -m pytest tests/test_huesat.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.huesat import (
    _hsv_to_rgb,
    _rgb_to_hsv,
    _srgb_encode_v,
    apply_hue_sat_map, apply_look_table, apply_local_warm_sat,
    apply_table_to_hsv,
    decode_table, get_hue_sat_table, get_look_table,
)
from pixo.render.core.color import (linear_prophoto_to_linear_srgb,
                                 linear_srgb_to_linear_prophoto)


class MockProf:
    """最小 DcpProfile 替身 (只用 huesat 需要的字段)。"""

    def __init__(self, hue_sat_map=None, hue_sat_dims=None,
                 look_table=None, look_table_dims=None,
                 hue_sat_encoding=None, look_table_encoding=None):
        self.hue_sat_map = hue_sat_map
        self.hue_sat_map1 = hue_sat_map
        self.hue_sat_dims = hue_sat_dims
        self.look_table = look_table
        self.look_table_dims = look_table_dims
        self.hue_sat_encoding = hue_sat_encoding
        self.look_table_encoding = look_table_encoding


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
    H, S, V, _ = table.shape
    flat = np.zeros((V, H, S, 3), dtype=np.float32)
    flat = table.transpose(2, 0, 1, 3)  # (V,H,S,3)
    return flat.reshape(-1).tolist()


# ---------------------------------------------------------------------------
# 1) decode_table: 布局正确性
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


# ---------------------------------------------------------------------------
# 2) apply_table_to_hsv: 已知偏移精确应用
# ---------------------------------------------------------------------------

def test_apply_constant_hue_shift():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    h = np.array([0.0, 90.0, 180.0, 270.0], dtype=np.float32)
    s = np.ones(4, dtype=np.float32)
    v = np.ones(4, dtype=np.float32)
    h2, s2, v2 = apply_table_to_hsv(h, s, v, table, (H, S, V), strength=1.0)
    assert np.allclose(h2, (h + 15.0) % 360.0, atol=1e-4)
    assert np.allclose(s2, 1.0)
    assert np.allclose(v2, 1.0)


def test_apply_hue_wraparound():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    h = np.array([350.0], dtype=np.float32)  # 350+15 = 365 → 5
    h2, _, _ = apply_table_to_hsv(h, np.ones(1, np.float32), np.ones(1, np.float32),
                                  table, (H, S, V), strength=1.0)
    assert np.allclose(h2, [5.0], atol=1e-3)


def test_apply_sat_val_scales():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 0.0, sat_fn=lambda s: 0.5, val_fn=lambda v: 1.5)
    h = np.zeros(4, dtype=np.float32)
    s = np.array([0.0, 0.25, 0.5, 1.0], dtype=np.float32)
    v = np.array([0.0, 0.3, 0.7, 1.0], dtype=np.float32)
    h2, s2, v2 = apply_table_to_hsv(h, s, v, table, (H, S, V), strength=1.0)
    assert np.allclose(h2, 0.0)
    assert np.allclose(s2, s * 0.5, atol=1e-4)
    # V 只钳下界 (线性域语义, 2026-08 域修复): 不再截顶到 1.0
    assert np.allclose(v2, v * 1.5, atol=1e-4)


def test_apply_strength_blend():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 20.0, sat_fn=lambda s: 0.5, val_fn=lambda v: 1.0)
    h = np.zeros(4, dtype=np.float32)
    s = np.ones(4, dtype=np.float32)
    v = np.ones(4, dtype=np.float32)
    # strength=0 → 恒等
    h0, s0, v0 = apply_table_to_hsv(h, s, v, table, (H, S, V), strength=0.0)
    assert np.array_equal(h0, h) and np.array_equal(s0, s) and np.array_equal(v0, v)
    # strength=0.5 → 线性混合
    h5, s5, v5 = apply_table_to_hsv(h, s, v, table, (H, S, V), strength=0.5)
    assert np.allclose(h5, 10.0, atol=1e-3)
    assert np.allclose(s5, 0.75, atol=1e-4)


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
# 3) apply_hue_sat_map / apply_look_table: 直通与 dims 回退
# ---------------------------------------------------------------------------

def test_apply_hue_sat_map_passthrough_without_data():
    prof = MockProf()
    x = np.random.default_rng(0).random((8, 8, 3)).astype(np.float32)
    assert np.array_equal(apply_hue_sat_map(x, prof), x)
    assert np.array_equal(apply_look_table(x, prof), x)


def test_hue_dims_do_not_fallback_to_look_dims():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    prof = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=None, look_table_dims=[H, S, V])
    t, dims, enc = get_hue_sat_table(prof)
    # HueSatMap 必须用 ProfileHueSatMapDims, 不得误用 LookTableDims
    assert dims is None and t is None


def test_apply_hue_sat_map_rgb_roundtrip_shape():
    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    prof = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=[H, S, V])
    x = np.random.default_rng(1).random((16, 16, 3)).astype(np.float32)
    y = apply_hue_sat_map(x, prof, strength=1.0)
    assert y.shape == x.shape and y.dtype == np.float32
    # 线性域: 只钳下界; 色相旋转可能把颜色推出 sRGB 色域 (线性分量 >1),
    # 理论上界 = ProPhoto 单位立方经逆矩阵的最大分量 ≈2.04 (tone 后收口)
    assert float(y.min()) >= 0.0 and np.isfinite(y).all()
    assert float(y.max()) <= 2.1
    # 纯灰 (S=0) 不应被色相偏移改变 (S=0 时 HSV→RGB 与 H 无关)
    gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
    yg = apply_hue_sat_map(gray, prof, strength=1.0)
    assert np.allclose(yg, gray, atol=1e-4)


def test_look_table_passthrough_without_data():
    prof = MockProf(hue_sat_map=None, look_table=None,
                    look_table_dims=[90, 16, 16])
    x = np.random.default_rng(2).random((8, 8, 3)).astype(np.float32)
    assert np.array_equal(apply_look_table(x, prof), x)


# ---------------------------------------------------------------------------
# 4) HueSatStage 门控
# ---------------------------------------------------------------------------

def test_stage_wants_gating():
    from pixo.render.pipeline.graph import StageContext
    from pixo.render.modules.huesat import HueSatStage

    stage = HueSatStage()
    ctx = StageContext("x.NEF", prof=None)
    assert stage.wants(ctx) is False

    prof_empty = MockProf()
    ctx2 = StageContext("x.NEF", prof=prof_empty)
    assert stage.wants(ctx2) is False

    H, S, V = 4, 2, 2
    table = _make_table(H, S, V, hue_fn=lambda h: 15.0, sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)
    prof_with = MockProf(hue_sat_map=_flatten(table), hue_sat_dims=[H, S, V])
    ctx3 = StageContext("x.NEF", prof=prof_with, config={"stages": {"huesat": {"enabled": True}}})
    assert stage.wants(ctx3) is True

    ctx4 = StageContext("x.NEF", prof=prof_with, config={"stages": {"huesat": {"enabled": False}}})
    assert stage.wants(ctx4) is False

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
# 5) apply_local_warm_sat: 问题清单 A1 局部暖色高光饱和
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


# ---------------------------------------------------------------------------
# 6) DNG SDK 复刻路径 (use_dng_huesat_path): E1 死 import 回归
# ---------------------------------------------------------------------------

def test_dng_huesat_path_no_dead_import():
    """E1 回归: 启用 DNG 复刻路径 (state.use_dng_huesat_path=True) 不得 ImportError。

    旧实现在该分支 import 了不存在的 dng_linear_prophoto_to_srgb
    (迁移改名后旧名残留, 真名 linear_prophoto_to_srgb) —— 路径一启用即崩。
    FM 缺失/表格缺失均走既有回退 (直通), 只需证明链路可走通。
    """
    from pathlib import Path

    from pixo.render.core.calibration import DcpProfile
    from pixo.render.modules.huesat import HueSatStage
    from pixo.render.pipeline.graph import StageContext

    # 真实 Nikon Z 5 II 矩阵 (与 test_wb_temp_tint.py 一致, 确定性)
    prof = DcpProfile(
        path=Path("test.dcp"),
        color_matrix1=[1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449,
                       -0.0231, 0.0811, 0.7571],
        color_matrix2=[0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286,
                       -0.0648, 0.1513, 0.6375],
        forward_matrix1=[0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001,
                         0.0, 0.0, 0.8251],
        forward_matrix2=[0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001,
                         0.0, 0.0, 0.8251],
        hue_sat_map=_flatten(_make_table(
            4, 2, 2, hue_fn=lambda h: 15.0,
            sat_fn=lambda s: 1.0, val_fn=lambda v: 1.0)),
        hue_sat_dims=[4, 2, 2])

    img = np.random.default_rng(4).random((16, 16, 3)).astype(np.float32) * 0.8
    cam_raw = (img * np.array([1.3, 1.0, 1.7], dtype=np.float32)).astype(np.float32)
    ctx = StageContext("x.NEF", prof=prof,
                       config={"stages": {"huesat": {"enabled": True}}})
    ctx.set_image(img.copy(), "linear_rgb")
    ctx.state["use_dng_huesat_path"] = True
    ctx.state["cam_raw"] = cam_raw
    ctx.state["wb"] = np.array([1.3, 1.0, 1.7], dtype=np.float32)

    stage = HueSatStage()
    assert stage.wants(ctx) is True
    stage.run(ctx)          # 旧代码在此抛 ImportError: dng_linear_prophoto_to_srgb
    assert ctx.domain == "linear_rgb"
    assert ctx.image.shape == img.shape
    assert np.isfinite(ctx.image).all()
    assert float(ctx.image.min()) >= 0.0
    assert "dng_prophoto_pre_tone" in ctx.state
