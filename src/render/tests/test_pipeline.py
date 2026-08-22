"""T6 单元测试: RAW 渲染引擎插件架构整合。

覆盖对象 (任务 T6):
  - Stage param_schema 校验 (类型/范围/枚举, 非法抛 ValueError 含参数名)
  - stage order 统一重排 (10/20/25/30/50/60/70 + 影调重塑层空壳 45..49)
  - Pipeline 域错位校验 (domain_in 不匹配抛 ValueError)
  - 默认全链 (合成小图 + mock DcpProfile, exposure/whitebalance mode=off)
  - probe 逐级落盘
  - preset JSON 加载 (pipeline_from_config, 顺序含 huesat)
  - Phase 1.5 reshape 空壳注册 (wants 恒 False)

运行: python -m pytest src/render/tests/test_pipeline.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import render.modules as _stages  # noqa: F401  触发全部插件注册 (含 reshape)

from render.pipeline import (
    DEFAULT_STAGES,
    available_stages,
    build_default_pipeline,
    pipeline_from_config,
)
from render.pipeline.graph import (
    DOMAIN_GAMMA_RGB,
    DOMAIN_LINEAR_CAM,
    DOMAIN_LINEAR_RGB,
    Pipeline,
    Stage,
    StageContext,
)
from render.modules.exposure import ExposureStage
from render.modules.tone_map import ToneStage, _check_highlight_compress_curve
from render.modules.white_balance import (
    WARMTH_SLOPE_BOUNDS,
    WhiteBalanceStage,
    apply_warmth,
)
from render.modules.reshape import (
    ClarityStage,
    DehazeStage,
    DenoiseStage,
    SharpenStage,
    VibranceStage,
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

class MockProf:
    """最小 DcpProfile 替身: 只带基座色彩链路所需字段 (恒等 ColorMatrix)。"""

    def __init__(self):
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


class _FakeLinearCamStage(Stage):
    """domain_in=linear_cam 的假 Stage, 用于制造域错位。"""

    name = "fake_linear_cam"
    domain_in = DOMAIN_LINEAR_CAM
    domain_out = DOMAIN_LINEAR_CAM

    def process(self, ctx: StageContext) -> None:
        pass


# ---------------------------------------------------------------------------
# 1) 域错位校验
# ---------------------------------------------------------------------------

def test_domain_mismatch_raises():
    ctx = StageContext("x.NEF")
    rng = np.random.default_rng(0)
    ctx.set_image(rng.random((8, 8, 3)).astype(np.float32), DOMAIN_LINEAR_RGB)
    # tone 输出 gamma_rgb, 但接在后面的假 Stage 期望 linear_cam → 域错位
    pipe = Pipeline(stages=[ToneStage(), _FakeLinearCamStage()])
    with pytest.raises(ValueError, match="域不匹配"):
        pipe.run(ctx)


# ---------------------------------------------------------------------------
# 2) param_schema 校验
# ---------------------------------------------------------------------------

def test_param_invalid_max_ev_raises():
    stage = ExposureStage()
    ctx = StageContext("x.NEF", config={"stages": {"exposure": {"max_ev": 99}}})
    with pytest.raises(ValueError, match="max_ev"):
        stage.p(ctx, "max_ev")


def test_param_invalid_type_raises():
    stage = ExposureStage()
    ctx = StageContext("x.NEF", config={"stages": {"exposure": {"clip_p": "98"}}})
    with pytest.raises(ValueError, match="clip_p"):
        stage.p(ctx, "clip_p")


def test_param_valid_clip_p_and_contrast():
    # clip_p=90 (int 也放行 float 类型), contrast=0.2 (tone 0..1 范围内) 均不抛
    exp = ExposureStage()
    ctx1 = StageContext("x.NEF", config={"stages": {"exposure": {"clip_p": 90}}})
    assert exp.p(ctx1, "clip_p") == 90

    tone = ToneStage()
    ctx2 = StageContext("x.NEF", config={"stages": {"tone": {"contrast": 0.2}}})
    assert tone.p(ctx2, "contrast") == 0.2


def test_param_choices_and_enum():
    exp = ExposureStage()
    ctx = StageContext("x.NEF", config={"stages": {"exposure": {"subject_mode": "bogus"}}})
    with pytest.raises(ValueError, match="subject_mode"):
        exp.p(ctx, "subject_mode")


# ---------------------------------------------------------------------------
# 3) 默认全链 (合成图, exposure/whitebalance 关闭)
# ---------------------------------------------------------------------------

def test_default_full_chain():
    prof = MockProf()
    params = {"exposure": {"mode": "off"}, "whitebalance": {"mode": "off"}}
    pipe = build_default_pipeline(prof=prof, params=params)
    ctx = StageContext("x.NEF", prof=prof, config={"stages": params})
    rng = np.random.default_rng(0)
    ctx.set_image(rng.random((16, 16, 3)).astype(np.float32), DOMAIN_LINEAR_CAM)

    out = pipe.run(ctx)

    assert ctx.domain == DOMAIN_GAMMA_RGB
    assert out.shape == (16, 16, 3)
    assert out.dtype == np.float32
    assert float(out.min()) >= 0.0
    assert float(out.max()) <= 1.0


# ---------------------------------------------------------------------------
# 4) probe 逐级落盘
# ---------------------------------------------------------------------------

def test_probe_files_written(tmp_path):
    prof = MockProf()
    params = {"exposure": {"mode": "off"}, "whitebalance": {"mode": "off"},
              "skin": {"enabled": False}}  # 关磨皮: 随机图不触发人像门控
    pipe = build_default_pipeline(prof=prof, params=params)
    ctx = StageContext("x.NEF", prof=prof, config={"stages": params})
    rng = np.random.default_rng(1)
    ctx.set_image(rng.random((16, 16, 3)).astype(np.float32), DOMAIN_LINEAR_CAM)

    pipe.run(ctx, probe_dir=tmp_path)

    # 实际执行链: exposure → whitebalance → compose → tone → clarity → colorcal
    # → refine (huesat/stylize/skin 被 wants 跳过, 不落盘)
    for fname in ("01_exposure.jpg", "02_whitebalance.jpg", "03_compose.jpg",
                  "04_tone.jpg", "05_clarity.jpg", "06_colorcal.jpg",
                  "07_refine.jpg"):
        assert (tmp_path / fname).exists(), f"缺少 probe 文件 {fname}"


# ---------------------------------------------------------------------------
# 5) preset 加载 + describe 顺序
# ---------------------------------------------------------------------------

def test_preset_loads_and_describe_order():
    presets = (Path(__file__).resolve().parents[2] / "pixo" / "render"
                     / "presets")
    cfg = json.loads((presets / "neutral.json").read_text(encoding="utf-8"))
    pipe = pipeline_from_config(cfg)
    names = [s["name"] for s in pipe.describe()]
    assert names == ["exposure", "whitebalance", "huesat", "tone",
                     "colorcal", "stylize", "refine"]
    assert "huesat" in names


def test_default_stages_contains_huesat():
    # P0-1 集成: 默认链扩为 13 段 (compose 插在 whitebalance 后; calibration/hsl/split_tone 默认 no-op)
    assert DEFAULT_STAGES == ["exposure", "whitebalance", "compose", "huesat",
                              "tone", "clarity", "colorcal", "calibration",
                              "hsl", "split_tone", "skin", "stylize", "refine"]


def test_stage_orders_renumbered():
    orders = {s: cls.order for s, cls in available_stages().items()}
    assert orders["exposure"] == 10
    assert orders["whitebalance"] == 20
    assert orders["compose"] == 22
    assert orders["huesat"] == 25
    assert orders["tone"] == 30
    assert orders["colorcal"] == 50
    assert orders["stylize"] == 60
    assert orders["refine"] == 70


# ---------------------------------------------------------------------------
# 6) Phase 1.5 影调重塑层空壳
# ---------------------------------------------------------------------------

def test_reshape_stubs_registered_and_inert():
    stages = available_stages()
    for name in ("dehaze", "clarity", "denoise", "sharpen", "vibrance"):
        assert name in stages, f"reshape 空壳 {name} 未注册"
    # order 45..49, 位于 huesat(25) 之后、colorcal(50) 之前
    assert stages["dehaze"].order == 45
    assert stages["clarity"].order == 46
    assert stages["denoise"].order == 47
    assert stages["sharpen"].order == 48
    assert stages["vibrance"].order == 49

    ctx = StageContext("x.NEF")
    for cls in (DehazeStage, DenoiseStage, SharpenStage, VibranceStage):
        s = cls()
        assert s.wants(ctx) is False
        assert s.domain_in == DOMAIN_GAMMA_RGB
        assert s.domain_out == DOMAIN_GAMMA_RGB


# ---------------------------------------------------------------------------
# 7) 暖度模型约束 (方案 A): 冻结锚点 + 斜率带界 + 删死参数 cct_orig
# ---------------------------------------------------------------------------

class _FakeRawWB:
    """带 As Shot 白平衡的 raw 替身 (0376 暖锚点 wb=[1.291,1,2.287])。"""

    def __init__(self, wb=(1.291, 1.0, 2.287)):
        self.camera_whitebalance = [wb[0], wb[1], wb[2], 1.0]


def test_warmth_slope_bounds_stage_validation():
    """Stage 参数校验层: 斜率越界抛 ValueError (含参数名), 带内 (含边界) 放行。"""
    stage = WhiteBalanceStage()
    for pkey, bad in (("warmth_r_slope", 0.3), ("warmth_r_slope", -0.2),
                      ("warmth_g_slope", 0.2), ("warmth_g_slope", -0.2),
                      ("warmth_b_slope", 0.0), ("warmth_b_slope", 0.9)):
        ctx = StageContext("x.NEF", config={"stages": {"whitebalance": {pkey: bad}}})
        with pytest.raises(ValueError, match=pkey):
            stage.p(ctx, pkey)

    for pkey, good in (("warmth_r_slope", -0.05), ("warmth_r_slope", 0.25),
                       ("warmth_g_slope", -0.05), ("warmth_g_slope", 0.15),
                       ("warmth_b_slope", 0.05), ("warmth_b_slope", 0.35)):
        ctx = StageContext("x.NEF", config={"stages": {"whitebalance": {pkey: good}}})
        assert stage.p(ctx, pkey) == good


def test_warmth_slope_bounds_apply_warmth_direct():
    """apply_warmth 直接 cal 覆盖: 越界斜率抛 ValueError; 默认/预设值均在界内。"""
    wb = np.array([1.291, 1.0, 2.287], dtype=np.float32)
    for key, bad in (("r_slope", 0.3), ("g_slope", 0.2), ("b_slope", 0.0)):
        with pytest.raises(ValueError, match=key):
            apply_warmth(wb, None, 1.0, {key: bad})
    # 默认斜率 (0.0/0.10/0.26) 与预设注入值一致
    out_default = apply_warmth(wb, None, 1.0)
    out_preset = apply_warmth(wb, None, 1.0,
                              {"r_slope": 0.0, "g_slope": 0.10, "b_slope": 0.26})
    assert np.allclose(out_default, out_preset)


def test_warmth_frozen_anchors_override_allowed():
    """b0/b1 冻结锚点 1.79/2.287: 缺省与显式一致; 覆盖仍放行且实际生效 (向前兼容)。"""
    wb = np.array([1.0, 1.0, 2.0], dtype=np.float32)   # 带内 wb_B=2.0
    default = apply_warmth(wb, None, 1.0)
    explicit = apply_warmth(wb, None, 1.0, {"b0": 1.79, "b1": 2.287})
    assert np.allclose(default, explicit)              # 冻结值 == 显式注入
    # 覆盖锚点 (冻结 ≠ 禁覆盖): 允许且改变插值强度
    overridden = apply_warmth(wb, None, 1.0, {"b0": 1.80, "b1": 2.20})
    assert not np.allclose(overridden, default)
    assert overridden.dtype == np.float32


def test_warmth_slope_bounds_constant_matches_schema():
    """带界常量与 Stage 参数校验 schema 一致 (单一事实源防漂移)。"""
    assert WARMTH_SLOPE_BOUNDS == {"r_slope": (-0.05, 0.25),
                                   "g_slope": (-0.05, 0.15),
                                   "b_slope": (0.05, 0.35),
                                   "r_day": (0.0, 0.5)}
    for key, (lo, hi) in WARMTH_SLOPE_BOUNDS.items():
        schema = WhiteBalanceStage.param_schema["warmth_" + key]
        assert schema["min"] == lo and schema["max"] == hi


def test_warmth_curve_validation_and_apply():
    """warmth_curve: 结点校验 (≥2/严格递增/增益带界) + 分段线性插值应用。"""
    wb = np.array([1.0, 1.0, 2.1], dtype=np.float32)   # wb_B=2.1, 带内
    curve = [[1.5, 1.10, 1.00, 0.95],
             [2.0, 1.00, 0.95, 0.90],
             [2.5, 0.95, 0.90, 0.85]]
    # warmth=1.0, wb_B=2.1 → 在 2.0/2.5 间 t=0.2 线性插值 (输出 = wb × 增益)
    out = apply_warmth(wb, None, 1.0, {"curve": curve})
    exp_r = 1.00 + 0.2 * (0.95 - 1.00)      # 0.99
    exp_g = 0.95 + 0.2 * (0.90 - 0.95)      # 0.94
    exp_b = 0.90 + 0.2 * (0.85 - 0.90)      # 0.89
    assert np.allclose(out, np.asarray(wb) * np.array([exp_r, exp_g, exp_b],
                                                      dtype=np.float32),
                       atol=1e-6)
    # warmth=0 → 恒等 (曲线不生效)
    assert np.allclose(apply_warmth(wb, None, 0.0, {"curve": curve}), wb)
    # 端点钳位: wb_B 超上限 → 取末结点
    wb_hi = np.array([1.0, 1.0, 3.0], dtype=np.float32)
    out_hi = apply_warmth(wb_hi, None, 1.0, {"curve": curve})
    assert np.allclose(out_hi, np.asarray(wb_hi) * np.array([0.95, 0.90, 0.85],
                                                            dtype=np.float32),
                       atol=1e-6)
    # 校验错误: 结点 <2 / 非递增 / 增益越界
    for bad in ([[1.0, 1.0, 1.0, 1.0]],
                [[2.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]],
                [[1.0, 1.0, 1.0, 2.0], [2.0, 1.0, 1.0, 1.0]]):
        with pytest.raises(ValueError):
            apply_warmth(wb, None, 1.0, {"curve": bad})


def test_warmth_curve_via_stage_param():
    """Stage 参数层 warmth_curve 透传: 与直接 cal 注入结果一致。"""
    curve = [[1.5, 1.05, 1.00, 0.95], [2.5, 0.95, 0.95, 0.85]]
    prof = MockProf()
    params = {"whitebalance": {"mode": "as_shot", "warmth": 1.0,
                               "warmth_curve": curve}}
    ctx = StageContext("x.NEF", raw=_FakeRawWB(), prof=prof,
                       config={"stages": params})
    ctx.set_image(np.full((8, 8, 3), 0.3, dtype=np.float32), DOMAIN_LINEAR_CAM)
    WhiteBalanceStage().run(ctx)
    wb_in = np.array([1.291, 1.0, 2.287], dtype=np.float32)
    expected = apply_warmth(wb_in, None, 1.0, {"curve": curve})
    # stage 内 wb 已按相机 as_shot 处理, 与直接调用同曲线
    assert np.allclose(ctx.state["wb"], expected, atol=1e-5)


def test_exposure_vignette_linear_lift():
    """exposure vignette: 线性域径向增益, 角落亮于中心, 中心不动, k=0 恒等。"""
    from render.modules.exposure import _vignette_lift_linear
    img = np.full((60, 80, 3), 0.5, dtype=np.float32)
    out = _vignette_lift_linear(img, 0.0)
    assert np.array_equal(out, img)
    out2 = _vignette_lift_linear(img, 0.2)
    h, w = img.shape[:2]
    center = float(out2[h // 2, w // 2, 0])
    corner = float(out2[0, 0, 0])
    assert abs(center - 0.5) < 1e-3          # 中心 (像素偏移) 近似不动
    assert corner > 0.5                       # 角落提亮
    assert corner <= 0.5 * (1.0 + 0.2) + 1e-6  # 不超过 1+k
    # 空间单调: 半径越大增益越大
    assert out2[0, w // 2, 0] >= center
    # stage 全链路: baseline 模式 + vignette 参数生效
    prof = MockProf()
    ctx = StageContext("x.NEF", prof=prof, config={"stages": {
        "exposure": {"mode": "baseline", "vignette": 0.3}}})
    ctx.set_image(np.full((40, 40, 3), 0.4, dtype=np.float32), DOMAIN_LINEAR_CAM)
    ExposureStage().run(ctx)
    assert ctx.image[0, 0, 0] > 0.4
    assert abs(ctx.image[20, 20, 0] - 0.4) < 1e-3


def test_apply_warmth_no_cct_orig():
    """死参数 cct_orig 已从 apply_warmth 签名移除 (第 4 位置参数现为 cal)。"""
    import inspect
    import render.modules.white_balance as wb_mod
    sig = inspect.signature(wb_mod.apply_warmth)
    assert "cct_orig" not in sig.parameters
    assert list(sig.parameters) == ["wb", "prof", "warmth", "cal"]
    # 新 4 位置参数调用 (旧签名第 4 位是 cct_orig, 现已删除)
    wb = np.array([1.244, 1.0, 1.791], dtype=np.float32)  # 5236 冷锚点
    out = wb_mod.apply_warmth(wb, None, 1.0, {"g_slope": 0.10})
    assert out.shape == (3,) and out.dtype == np.float32


def test_whitebalance_stage_warmth_path_full_process():
    """Stage 全链路 (as_shot + warmth): 新签名下 process 正常; 越界斜率在参数校验层抛错。"""
    prof = MockProf()
    params = {"whitebalance": {"mode": "as_shot", "warmth": 1.0}}
    ctx = StageContext("x.NEF", raw=_FakeRawWB(), prof=prof,
                       config={"stages": params})
    ctx.set_image(np.full((8, 8, 3), 0.3, dtype=np.float32), DOMAIN_LINEAR_CAM)
    result = WhiteBalanceStage().run(ctx)
    assert ctx.domain == DOMAIN_LINEAR_RGB
    assert ctx.state["cct_k"] > 0
    assert result.metrics["cct_k"] == ctx.state["cct_k"]

    # 越界斜率经 Stage 参数校验层 (process 内 p() 触发) 抛 ValueError
    bad = {"whitebalance": {"mode": "as_shot", "warmth_b_slope": 0.9}}
    ctx_bad = StageContext("x.NEF", raw=_FakeRawWB(), prof=prof,
                           config={"stages": bad})
    ctx_bad.set_image(np.full((8, 8, 3), 0.3, dtype=np.float32), DOMAIN_LINEAR_CAM)
    with pytest.raises(ValueError, match="warmth_b_slope"):
        WhiteBalanceStage().run(ctx_bad)


def test_highlight_compress_curve_validation():
    curve = _check_highlight_compress_curve([[1.0, 0.0], [1.4, 0.06], [2.0, 0.0]])
    assert curve.shape == (3, 2)
    import pytest as _pytest
    with _pytest.raises(ValueError):
        _check_highlight_compress_curve([[2.0, 0.0], [1.0, 0.0]])
    with _pytest.raises(ValueError):
        _check_highlight_compress_curve([[1.0, 0.0], [2.0, 0.6]])
