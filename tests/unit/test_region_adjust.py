"""F12 单元测试: region_adjust stage (掩码驱动的分区曝光/饱和度调整)。

覆盖 (设计 §2 完成标准: 合成掩码数值断言 + enabled=False 零影响 +
wants 门控 + 注册全链冒烟):
  - 注册: order=57 (56-59 空槽, skin=55/stylize=60 之间), gamma_rgb 双向域,
    params.STAGE_CLASSES/PARAM_SCHEMAS/DEFAULT_PARAMS 登记
  - 进链: DEFAULT_STAGES 在 skin 后 stylize 前; 默认参数下全链逐位零影响
    (t108 dehaze 先例口径)
  - wants 门控: enabled/regions 缺失/掩码 state 缺失/prompt 无掩码/零效果参数
  - 曝光内核 (gamma 域增益近似): 常数掩码下逐像素精确断言 gain=2^(ev/2.2);
    线性域等效增益 ≈ 2^ev (sRGB EOTF 往返, 中间调相对误差 <4%); 正向单调;
    高光 clip
  - 饱和度内核 (HSV S 缩放): 中性像素不变; 方向性 (增/减); clip 上限
  - 软掩码合成: 半透明掩码线性混合; 掩码外像素逐位不变; 分辨率不一致自动缩放;
    羽化禁硬边 (二值掩码边界无 1px 跳变); 多区域顺序确定性
  - 参数校验: 非法结构/未知键/越界 → ValueError
  - ctx.state 掩码缺失 → 静默直通 (不 set_image, 不报错)

运行: python -m pytest tests/unit/test_region_adjust.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pixo.render.pipeline.graph import (
    DOMAIN_GAMMA_RGB,
    DOMAIN_LINEAR_CAM,
    STAGE_REGISTRY,
    StageContext,
)
from pixo.render.pipeline.presets import DEFAULT_STAGES, Pipeline
from pixo.render.params import (
    DEFAULT_PARAMS,
    DEFAULT_STAGES as PARAMS_DEFAULT_STAGES,
    PARAM_SCHEMAS,
    STAGE_CLASSES,
)
from pixo.render.modules.region_adjust import RegionAdjustStage
from pixo.render.core.calibration import DcpProfile

# 真实 Nikon Z 5 II Camera Standard 矩阵 (test_phase1_chain.py 同款, 确定性)
_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]


class _FakeRaw:
    camera_whitebalance = [1.291, 1.0, 2.287, 1.0]


def _profile() -> DcpProfile:
    return DcpProfile(path=Path("test.dcp"),
                      color_matrix1=_NIKON_CM1, color_matrix2=_NIKON_CM2,
                      forward_matrix1=_NIKON_FM1, forward_matrix2=_NIKON_FM1)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _ctx(img, masks=None, params=None, mode="export"):
    """gamma 域图像 + 可选 region_masks state 的最小 StageContext。"""
    ctx = StageContext("test.nef", config={"stages": {"region_adjust": params or {}}},
                       mode=mode)
    ctx.set_image(np.asarray(img, dtype=np.float32), DOMAIN_GAMMA_RGB)
    if masks is not None:
        ctx.state["region_masks"] = masks
    return ctx


def _uniform(h, w, val):
    return np.full((h, w, 3), val, dtype=np.float32)


def _srgb_decode(x):
    """精确 sRGB EOTF 解码 (gamma → 线性), 测试侧独立实现 (core.curves 只有编码)。"""
    x = np.asarray(x, dtype=np.float64)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


# ---------------------------------------------------------------------------
# 注册 / 进链 / 默认零影响
# ---------------------------------------------------------------------------

def test_registration_order_domain():
    assert "region_adjust" in STAGE_REGISTRY
    cls = STAGE_REGISTRY["region_adjust"]
    assert cls is RegionAdjustStage
    assert cls.order == 57
    assert cls.domain_in == DOMAIN_GAMMA_RGB
    assert cls.domain_out == DOMAIN_GAMMA_RGB
    # 56-59 空槽契约: skin=55 / stylize=60 之间无其他 stage
    neighbors = {n: s.order for n, s in STAGE_REGISTRY.items()
                 if n in ("skin", "region_adjust", "stylize")}
    assert neighbors == {"skin": 55, "region_adjust": 57, "stylize": 60}


def test_params_registry_entries():
    assert STAGE_CLASSES["region_adjust"] is RegionAdjustStage
    assert "region_adjust" in PARAM_SCHEMAS
    assert "enabled" in PARAM_SCHEMAS["region_adjust"]
    assert "regions" in PARAM_SCHEMAS["region_adjust"]
    assert DEFAULT_PARAMS["region_adjust"] == {"enabled": False, "regions": {}}
    # params 模块再导出的 DEFAULT_STAGES 与 presets 一致 (防两处漂移)
    assert PARAMS_DEFAULT_STAGES is DEFAULT_STAGES


def test_default_chain_insertion_between_skin_and_stylize():
    assert "region_adjust" in DEFAULT_STAGES
    i_skin = DEFAULT_STAGES.index("skin")
    i_ra = DEFAULT_STAGES.index("region_adjust")
    i_styl = DEFAULT_STAGES.index("stylize")
    assert i_skin < i_ra < i_styl


def test_default_off_full_chain_bit_identical():
    """默认参数 (enabled=False) 下, 默认链多一个 stage 输出逐位不变
    (dehaze t108 先例口径 —— 金样本/gate 零影响的链级证据)。"""
    rng = np.random.default_rng(7)
    img = rng.random((48, 48, 3)).astype(np.float32) * 0.9
    prof = _profile()

    ctx_a = StageContext("t.nef", raw=_FakeRaw(), prof=prof)
    ctx_a.set_image(img.copy(), DOMAIN_LINEAR_CAM)
    Pipeline(stages=[s for s in DEFAULT_STAGES if s != "region_adjust"]).run(ctx_a)

    ctx_b = StageContext("t.nef", raw=_FakeRaw(), prof=prof)
    ctx_b.set_image(img.copy(), DOMAIN_LINEAR_CAM)
    Pipeline(stages=list(DEFAULT_STAGES)).run(ctx_b)

    assert ctx_b.image.shape == ctx_a.image.shape
    assert float(np.abs(ctx_a.image - ctx_b.image).max()) == 0.0


# ---------------------------------------------------------------------------
# wants 门控
# ---------------------------------------------------------------------------

def test_wants_disabled_by_default():
    img = _uniform(16, 16, 0.5)
    masks = {"sky": np.full((16, 16), 1.0, dtype=np.float32)}
    # 未传 params → 走 default_params (enabled=False)
    assert RegionAdjustStage().wants(_ctx(img, masks)) is False
    # 显式 enabled=False, 其余齐备 → False
    p = {"enabled": False, "regions": {"sky": {"exposure": 1.0}}}
    assert RegionAdjustStage(params=p).wants(_ctx(img, masks, p)) is False


def test_wants_regions_missing_or_empty():
    img = _uniform(16, 16, 0.5)
    masks = {"sky": np.full((16, 16), 1.0, dtype=np.float32)}
    p_no_regions = {"enabled": True}
    assert RegionAdjustStage(params=p_no_regions).wants(
        _ctx(img, masks, p_no_regions)) is False
    p_empty = {"enabled": True, "regions": {}}
    assert RegionAdjustStage(params=p_empty).wants(
        _ctx(img, masks, p_empty)) is False


def test_wants_masks_state_missing():
    """ctx.state 无 region_masks → False (静默, 不报错)。"""
    img = _uniform(16, 16, 0.5)
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.0}}}
    assert RegionAdjustStage(params=p).wants(_ctx(img, masks=None, params=p)) is False
    # 空 dict 同样视为无掩码通道
    assert RegionAdjustStage(params=p).wants(_ctx(img, {}, p)) is False


def test_wants_prompt_without_mask():
    """区域 prompt 在掩码 dict 中无对应键 → False。"""
    img = _uniform(16, 16, 0.5)
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.0}}}
    masks = {"face": np.full((16, 16), 1.0, dtype=np.float32)}
    assert RegionAdjustStage(params=p).wants(_ctx(img, masks, p)) is False
    # 命中任一区域即可
    masks2 = {"face": masks["face"], "sky": np.zeros((16, 16), np.float32)}
    assert RegionAdjustStage(params=p).wants(_ctx(img, masks2, p)) is True


def test_wants_zero_effect_regions():
    """全零参数 (exposure=0 且 saturation=0) 视为无效果 → False。"""
    img = _uniform(16, 16, 0.5)
    masks = {"sky": np.full((16, 16), 1.0, dtype=np.float32)}
    p = {"enabled": True, "regions": {"sky": {"exposure": 0.0}}}
    assert RegionAdjustStage(params=p).wants(_ctx(img, masks, p)) is False
    p2 = {"enabled": True,
          "regions": {"sky": {"exposure": 0.0, "saturation": 0.0}}}
    assert RegionAdjustStage(params=p2).wants(_ctx(img, masks, p2)) is False


def test_wants_true_when_ready():
    img = _uniform(16, 16, 0.5)
    masks = {"sky": np.full((16, 16), 0.8, dtype=np.float32)}
    p = {"enabled": True, "regions": {"sky": {"saturation": -0.5}}}
    assert RegionAdjustStage(params=p).wants(_ctx(img, masks, p)) is True


# ---------------------------------------------------------------------------
# 曝光内核: gamma 域增益近似 (路线 a, 单测钉死)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ev", [-2.0, -1.0, -0.3, 0.3, 1.0, 2.0])
def test_exposure_gamma_gain_exact(ev):
    """常数掩码=1.0 下逐像素精确: out = in * 2^(ev/2.2) (clip 前)。"""
    img = _uniform(8, 8, 0.5)
    p = {"enabled": True, "regions": {"sky": {"exposure": ev}}}
    masks = {"sky": np.ones((8, 8), dtype=np.float32)}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    assert stage.wants(ctx) is True
    stage.process(ctx)
    gain = 2.0 ** (ev / 2.2)
    expected = np.clip(0.5 * gain, 0.0, 1.0)
    assert np.allclose(ctx.image, expected, atol=1e-6), (
        f"ev={ev}: 期望 {expected}, 实际 {ctx.image.flat[0]}")


def test_exposure_linear_equivalence_midtones():
    """数值合理性: gamma 域乘 2^(ev/2.2) 的线性域等效增益 ≈ 2^ev (中间调)。

    未 clip 的中间调 (gamma 0.3..0.6) 相对误差 <4%; 深阴影偏差增大
    (sRGB 分段幂 2.4 段 vs 纯幂 2.2), 高光由 clip 兜底 —— 均为路线 a 的
    设计内取舍 (设计 §2, 意图级软区域)。
    """
    ramp = np.linspace(0.30, 0.60, 64, dtype=np.float32).reshape(8, 8, 1)
    img = np.repeat(ramp, 3, axis=2)
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.0}}}
    masks = {"sky": np.ones((8, 8), dtype=np.float32)}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    stage.process(ctx)
    assert float(ctx.image.max()) < 1.0          # 本测试区间无 clip 干扰
    lin_in = _srgb_decode(img[..., 0])
    lin_out = _srgb_decode(ctx.image[..., 0])
    rel = lin_out / (lin_in * 2.0)
    assert float(np.abs(rel - 1.0).max()) < 0.04, f"线性等效增益偏差: {rel}"


def test_exposure_monotonic_and_clips():
    """曝光方向单调 (亮者愈亮) 且高光 clip 到 ≤1。"""
    img = np.zeros((4, 4, 3), dtype=np.float32)
    img[..., 0] = np.linspace(0.1, 0.95, 16).reshape(4, 4)
    img[..., 1] = img[..., 0]
    img[..., 2] = img[..., 0]
    p = {"enabled": True, "regions": {"sky": {"exposure": 2.0}}}
    masks = {"sky": np.ones((4, 4), dtype=np.float32)}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    stage.process(ctx)
    out = ctx.image[..., 0]
    assert np.all(np.diff(out, axis=0) >= -1e-6)   # 单调非降
    assert float(out.max()) <= 1.0
    gain = 2.0 ** (2.0 / 2.2)
    assert float(out[0, 0]) == pytest.approx(min(0.1 * gain, 1.0), abs=1e-6)


def test_zero_ev_zero_sat_identity():
    """exposure=0 且 saturation=0 的区域: 完全不触碰像素 (逐位恒等)。"""
    rng = np.random.default_rng(3)
    img = rng.random((16, 16, 3)).astype(np.float32)
    masks = {"sky": np.full((16, 16), 1.0, dtype=np.float32)}
    p = {"enabled": True, "regions": {"sky": {"exposure": 0.0, "saturation": 0.0}}}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    writes_before = ctx.image_writes          # _ctx 的 set_image 已计 1 次
    stage.process(ctx)
    assert ctx.image_writes == writes_before  # "未写即未变"
    assert np.array_equal(ctx.image, img)


# ---------------------------------------------------------------------------
# 饱和度内核: HSV S 缩放
# ---------------------------------------------------------------------------

def test_saturation_neutral_unchanged():
    """中性灰 S=0 → 任何饱和度缩放不影响 (HSV S 缩放的关键性质)。"""
    img = _uniform(8, 8, 0.5)
    p = {"enabled": True, "regions": {"sky": {"saturation": 1.0}}}
    masks = {"sky": np.ones((8, 8), dtype=np.float32)}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    stage.process(ctx)
    assert np.allclose(ctx.image, img, atol=1e-6)


def test_saturation_direction_and_clip():
    """红底色 (0.8,0.4,0.4): sat=+1 → S 翻倍到 clip(1.0) ≈ (0.8,0,0);
    sat=-1 → S 归零 ≈ (V,V,V)=(0.8,0.8,0.8)。"""
    base = np.array([0.8, 0.4, 0.4], dtype=np.float32)
    img = np.tile(base, (8, 8, 1))
    masks = {"sky": np.ones((8, 8), dtype=np.float32)}

    p_up = {"enabled": True, "regions": {"sky": {"saturation": 1.0}}}
    ctx_up = _ctx(img.copy(), masks, p_up)
    RegionAdjustStage(params=p_up).process(ctx_up)
    assert float(ctx_up.image[..., 1].max()) == pytest.approx(0.0, abs=1e-3)
    assert float(ctx_up.image[..., 0].max()) == pytest.approx(0.8, abs=1e-3)

    p_down = {"enabled": True, "regions": {"sky": {"saturation": -1.0}}}
    ctx_down = _ctx(img.copy(), masks, p_down)
    RegionAdjustStage(params=p_down).process(ctx_down)
    assert np.allclose(ctx_down.image, 0.8, atol=1e-3)


# ---------------------------------------------------------------------------
# 掩码纪律: 软混合 / 羽化 / 形状
# ---------------------------------------------------------------------------

def test_soft_mask_linear_blend():
    """常数掩码 m=0.5: out = img*(1-m) + img*gain*m (线性混合钉死)。"""
    img = _uniform(8, 8, 0.5)
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.0}}}
    masks = {"sky": np.full((8, 8), 0.5, dtype=np.float32)}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    stage.process(ctx)
    gain = 2.0 ** (1.0 / 2.2)
    expected = 0.5 * (1.0 - 0.5) + min(0.5 * gain, 1.0) * 0.5
    assert np.allclose(ctx.image, expected, atol=1e-6)


def test_mask_zero_region_bit_identical():
    """掩码为 0 的像素逐位不变 (软混合在 m=0 处严格回原值)。"""
    rng = np.random.default_rng(11)
    img = rng.random((16, 16, 3)).astype(np.float32)
    mask = np.zeros((16, 16), dtype=np.float32)
    mask[:, :8] = 1.0
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.5}}}
    ctx = _ctx(img, {"sky": mask}, p)
    RegionAdjustStage(params=p).process(ctx)
    # 掩码羽化会把 m=0 的紧邻列略微抬起, 但最右列 (远离边界) 严格为 0
    assert np.array_equal(ctx.image[:, 12:], img[:, 12:])
    # 掩码内远离边界的列有提升
    assert float(ctx.image[:, :4].mean()) > float(img[:, :4].mean())


def test_exposure_then_saturation_combined_path():
    """组合路径单测 (M1 评审数值探针): exposure 先、saturation 后、区域末尾
    一次 clip —— 增益不经中间 clip 直入饱和度核 (色相比/v 比保持, 限幅只
    在区域边界一次), 公式级钉死。"""
    from pixo.render.modules.region_adjust import _apply_saturation

    rng = np.random.default_rng(9)
    img = (rng.random((12, 12, 3)).astype(np.float32) * 0.7 + 0.15)
    p = {"enabled": True,
         "regions": {"sky": {"exposure": 0.8, "saturation": 0.35}}}
    masks = {"sky": np.ones((12, 12), dtype=np.float32)}
    ctx = _ctx(img, masks, p)
    RegionAdjustStage(params=p).process(ctx)
    gain = np.float32(2.0 ** (0.8 / 2.2))
    expected = np.clip(
        _apply_saturation(np.clip(img * gain, 0.0, None).astype(np.float32),
                          0.35).astype(np.float32), 0.0, 1.0)
    assert np.allclose(ctx.image, expected, atol=1e-6)


def test_nan_mask_degrades_to_skip_without_pollution():
    """I-3 (M1 评审): 单点 NaN 掩码 → 该区域 warn+跳过, 输出无 NaN
    (修复前 NaN 经 clip/GaussianBlur/max<=0 三重穿透污染整帧)。"""
    import logging

    img = _uniform(16, 16, 0.5)
    bad = np.zeros((16, 16), dtype=np.float32)
    bad[4:12, 4:12] = 1.0
    bad[8, 8] = np.nan                       # 单点 NaN
    good = np.full((16, 16), 1.0, dtype=np.float32)
    p = {"enabled": True, "regions": {
        "bad_region": {"exposure": 1.0}, "ok_region": {"exposure": 1.0}}}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, {"bad_region": bad, "ok_region": good}, p)
    writes_before = ctx.image_writes
    with caplog_at_warning():
        stage.process(ctx)
    assert ctx.image_writes == writes_before + 1   # ok_region 仍施加
    assert np.isfinite(ctx.image).all(), "NaN 穿透到输出"
    # ok 区域增益生效; bad 区域无任何作用
    gain = 2.0 ** (1.0 / 2.2)
    assert float(ctx.image[0, 0, 0]) == pytest.approx(min(0.5 * gain, 1.0),
                                                      abs=1e-6)


def caplog_at_warning():
    """小助手: 返回捕获 region_adjust warning 的 contextmanager。"""
    import contextlib
    import logging

    @contextlib.contextmanager
    def _cm():
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger("pixo.render.modules.region_adjust")
        logger.addHandler(handler)
        old = logger.level
        logger.setLevel(logging.WARNING)
        try:
            yield records
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old)
    return _cm()


def test_mask_resolution_mismatch_resized():
    """掩码分辨率与图不同 (预览/导出双线口径) → 自动缩放后施加, 形状保持。"""
    img = _uniform(32, 32, 0.5)
    small_mask = np.ones((8, 8), dtype=np.float32)   # 1/4 分辨率全 1
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.0}}}
    ctx = _ctx(img, {"sky": small_mask}, p)
    RegionAdjustStage(params=p).process(ctx)
    gain = 2.0 ** (1.0 / 2.2)
    assert ctx.image.shape == img.shape
    # 全 1 掩码羽化后中心区域仍≈1 → 中心像素应接近增益后值
    assert float(ctx.image[8:24, 8:24].mean()) > 0.5 * gain * 0.95


def test_feather_no_hard_edge_on_binary_mask():
    """羽化纪律 (禁硬边): 二值阶跃掩码的施加效果无 1px 全幅跳变。"""
    img = _uniform(64, 64, 0.5)
    mask = np.zeros((64, 64), dtype=np.float32)
    mask[:, :32] = 1.0                       # 竖直硬边界在 col 31/32 之间
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.0}}}
    ctx = _ctx(img, {"sky": mask}, p)
    RegionAdjustStage(params=p).process(ctx)
    out = ctx.image[..., 0]
    step = abs(0.5 * (2.0 ** (1.0 / 2.2)) - 0.5)   # 硬边情形的全幅跳变
    max_adj = float(np.abs(np.diff(out, axis=1)).max())
    assert max_adj < 0.5 * step, (
        f"边界存在硬跳变: max|Δcol|={max_adj:.4f} ≥ 0.5*step={0.5 * step:.4f}")


def test_overlapping_regions_sequential_semantics():
    """I-4 (M1 评审) 顺序合成语义钉死: 多区域按 regions 声明序软合成。

    三重断言:
      a) 两次运行逐位一致 (确定性);
      b) 声明序反转 (ground 先、sky 后) → 结果不同 —— 合成顺序真实生效
         (B 的调整施加在 A 的输出上, 含 A 的 clip 后值, 不可交换);
      c) 公式级: 仅 A 区 (mB=0) = clip(img*gA); 重叠内区 (mA=mB=1) =
         clip(sat(clip(img*gA), -0.6)) —— B 明确作用于 A 的输出而非原图。
    """
    import cv2

    rng = np.random.default_rng(5)
    img = rng.random((32, 32, 3)).astype(np.float32) * 0.8 + 0.1
    m_a = np.zeros((32, 32), dtype=np.float32)
    m_a[:, :20] = 1.0
    m_b = np.zeros((32, 32), dtype=np.float32)
    m_b[10:, :] = 1.0
    p = {"enabled": True, "regions": {
        "sky": {"exposure": 0.7}, "ground": {"saturation": -0.6}}}
    masks = {"sky": m_a, "ground": m_b}
    ctx1 = _ctx(img.copy(), masks, p)
    ctx2 = _ctx(img.copy(), masks, p)
    stage = RegionAdjustStage(params=p)
    stage.process(ctx1)
    stage.process(ctx2)
    assert np.array_equal(ctx1.image, ctx2.image)          # (a) 确定性

    p_rev = {"enabled": True, "regions": {
        "ground": {"saturation": -0.6}, "sky": {"exposure": 0.7}}}
    ctx_rev = _ctx(img.copy(), masks, p_rev)
    RegionAdjustStage(params=p_rev).process(ctx_rev)
    assert not np.array_equal(ctx1.image, ctx_rev.image)   # (b) 顺序敏感

    # (c) 公式级钉死 (取远离掩码羽化带的内区: 羽化半径 ~3px, 边界 col 20 /
    # row 10 的安全内区)
    gain = 2.0 ** (0.7 / 2.2)
    blend_a = np.clip(img * np.float32(gain), 0.0, 1.0).astype(np.float32)
    # 仅 A 区 (rows 2:6, cols 2:14: mA=1, mB=0; 避开 m_b 羽化带 row>=7)
    assert np.allclose(ctx1.image[2:6, 2:14],
                       np.clip(img[2:6, 2:14] * np.float32(gain), 0, 1),
                       atol=1e-6)
    # 重叠内区 (rows 15:30, cols 2:14: mA=1, mB=1) = sat(A 输出, -0.6)
    hsv = cv2.cvtColor(blend_a[15:30, 2:14], cv2.COLOR_RGB2HSV)
    h_, s_, v_ = cv2.split(hsv)
    s2 = np.clip(s_ * 0.4, 0.0, 1.0)
    expected = cv2.cvtColor(cv2.merge([h_, s2, v_]), cv2.COLOR_HSV2RGB)
    assert np.allclose(ctx1.image[15:30, 2:14], expected, atol=1e-5)
    # 合成整体有效
    assert float(np.abs(ctx1.image - img).mean()) > 0.0


def test_metrics_written():
    """applied 区域与掩码占比写入 StageResult.metrics (F14 闭环观测位)。"""
    img = _uniform(16, 16, 0.5)
    masks = {"sky": np.full((16, 16), 0.5, dtype=np.float32)}
    p = {"enabled": True, "regions": {"sky": {"exposure": 0.5}}}
    ctx = _ctx(img, masks, p)
    RegionAdjustStage(params=p).run(ctx)     # run(): 先入链 StageResult 再写 metrics
    result = ctx.results[-1]
    assert result.name == "region_adjust"
    assert result.metrics["regions_applied"] == ["sky"]
    assert result.metrics["mask_coverage"]["sky"] == pytest.approx(0.5, abs=1e-5)


# ---------------------------------------------------------------------------
# 参数校验 / 缺失掩码静默
# ---------------------------------------------------------------------------

def test_invalid_regions_raise_value_error():
    img = _uniform(8, 8, 0.5)
    masks = {"sky": np.ones((8, 8), dtype=np.float32)}
    bad_cases = [
        {"enabled": True, "regions": {"sky": {"hue": 30.0}}},          # 未知键
        {"enabled": True, "regions": {"sky": "bright"}},               # 区域值非 dict
        {"enabled": True, "regions": {"sky": {"exposure": "++"}}},     # 非数值
        {"enabled": True, "regions": {"sky": {"exposure": 2.5}}},      # EV 越界
        {"enabled": True, "regions": {"sky": {"saturation": -1.5}}},   # sat 越界
    ]
    for p in bad_cases:
        stage = RegionAdjustStage(params=p)
        ctx = _ctx(img, masks, p)
        with pytest.raises(ValueError):
            stage.wants(ctx)


def test_mask_missing_prompt_in_process_silent():
    """wants 通过后 (多区域其一有掩码), 另一无掩码区域静默跳过不报错。"""
    img = _uniform(16, 16, 0.5)
    masks = {"sky": np.ones((16, 16), dtype=np.float32)}
    p = {"enabled": True, "regions": {
        "sky": {"exposure": 1.0}, "face": {"exposure": -1.0}}}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    stage.run(ctx)                           # face 无掩码 → 只施加 sky
    gain = 2.0 ** (1.0 / 2.2)
    assert np.allclose(ctx.image, min(0.5 * gain, 1.0), atol=1e-5)
    assert ctx.results[-1].metrics["regions_applied"] == ["sky"]


def test_all_zero_mask_no_write():
    """掩码通道存在但全零 → 无效果, 不 set_image。"""
    img = _uniform(8, 8, 0.5)
    masks = {"sky": np.zeros((8, 8), dtype=np.float32)}
    p = {"enabled": True, "regions": {"sky": {"exposure": 1.0}}}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    writes_before = ctx.image_writes          # _ctx 的 set_image 已计 1 次
    stage.process(ctx)
    assert ctx.image_writes == writes_before
    assert np.array_equal(ctx.image, img)


# ---------------------------------------------------------------------------
# 暖色内核 (R13): gamma 域通道增益近似 (白平衡 warmth 标定的暖方向锚定)
# ---------------------------------------------------------------------------

def test_warmth_gains_exact():
    """_warmth_gains 公式级: +1 → [1, 1.10, 0.74] (暖黄向), -1 → [1, 0.90, 1.26]
    (冷向对称), 0 → 恒等; 越界输入钳到 [-1,1]。"""
    from pixo.render.modules.region_adjust import _warmth_gains
    assert np.allclose(_warmth_gains(1.0), [1.0, 1.10, 0.74], atol=1e-6)
    assert np.allclose(_warmth_gains(-1.0), [1.0, 0.90, 1.26], atol=1e-6)
    assert np.allclose(_warmth_gains(0.0), [1.0, 1.0, 1.0], atol=1e-6)
    assert np.allclose(_warmth_gains(5.0), _warmth_gains(1.0), atol=1e-6)
    assert np.allclose(_warmth_gains(-5.0), _warmth_gains(-1.0), atol=1e-6)


@pytest.mark.parametrize("wm", [-1.0, -0.5, 0.5, 1.0])
def test_warmth_gamma_gain_exact(wm):
    """常数掩码=1.0 下逐通道精确: out = in * _warmth_gains(wm) (clip 前)。"""
    from pixo.render.modules.region_adjust import _warmth_gains
    img = _uniform(8, 8, 0.5)
    p = {"enabled": True, "regions": {"sky": {"warmth": wm}}}
    masks = {"sky": np.ones((8, 8), dtype=np.float32)}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    assert stage.wants(ctx) is True
    stage.process(ctx)
    expected = np.clip(img * _warmth_gains(wm), 0.0, 1.0)
    assert np.allclose(ctx.image, expected, atol=1e-6), (
        f"wm={wm}: 期望 {expected.flat[0]}, 实际 {ctx.image.flat[0]}")


def test_warmth_direction_on_blue_sky():
    """方向语义: 蓝天 (B 主导) + warmth>0 → B 降 G 升 (变暖), warmth<0 → 反向;
    R 通道不动 (标定暖方向 r_slope=0)。"""
    img = np.zeros((4, 4, 3), dtype=np.float32)
    img[..., 2] = 0.6                                   # 纯蓝天空
    img[..., 1] = 0.3
    p = {"enabled": True, "regions": {"sky": {"warmth": 0.5}}}
    masks = {"sky": np.ones((4, 4), dtype=np.float32)}
    ctx = _ctx(img, masks, p)
    RegionAdjustStage(params=p).process(ctx)
    assert float(ctx.image[..., 2].mean()) < 0.6        # B 降 (变暖)
    assert float(ctx.image[..., 1].mean()) > 0.3        # G 升
    assert float(ctx.image[..., 0].mean()) == pytest.approx(0.0, abs=1e-6)
    ctx_cold = _ctx(img, masks, {"enabled": True,
                                 "regions": {"sky": {"warmth": -0.5}}})
    RegionAdjustStage(params=ctx_cold.config["stages"]["region_adjust"]).process(ctx_cold)
    assert float(ctx_cold.image[..., 2].mean()) > 0.6   # 冷向 B 升
    assert float(ctx_cold.image[..., 1].mean()) < 0.3


def test_warmth_zero_identity():
    """warmth=0 (含混在其他非零参数外的单warmth区域): 完全不触碰像素。"""
    rng = np.random.default_rng(11)
    img = rng.random((16, 16, 3)).astype(np.float32)
    masks = {"sky": np.full((16, 16), 1.0, dtype=np.float32)}
    p = {"enabled": True, "regions": {"sky": {"warmth": 0.0}}}
    stage = RegionAdjustStage(params=p)
    ctx = _ctx(img, masks, p)
    assert stage.wants(ctx) is False                    # 全零参数 → 无实际效果
    writes_before = ctx.image_writes
    stage.process(ctx)
    assert ctx.image_writes == writes_before
    assert np.array_equal(ctx.image, img)


def test_warmth_clips_highlights():
    """暖向增益把近 1.0 的 B/G 推过 1 → 区域末尾 clip 兜底 ≤1。"""
    img = np.zeros((4, 4, 3), dtype=np.float32)
    img[..., 1] = 0.95
    img[..., 2] = 0.95
    p = {"enabled": True, "regions": {"sky": {"warmth": 1.0}}}
    ctx = _ctx(img, {"sky": np.ones((4, 4), np.float32)}, p)
    RegionAdjustStage(params=p).process(ctx)
    assert float(ctx.image.max()) <= 1.0
    assert float(ctx.image[..., 2].mean()) < 0.95       # B 被压 (未贴 clip)
    assert float(ctx.image[..., 1].mean()) == pytest.approx(1.0, abs=1e-6)


def test_warmth_out_of_range_raises():
    p = {"enabled": True, "regions": {"sky": {"warmth": 1.5}}}
    ctx = _ctx(_uniform(4, 4, 0.5), {"sky": np.ones((4, 4), np.float32)}, p)
    with pytest.raises(ValueError):
        RegionAdjustStage(params=p).wants(ctx)


def test_exposure_warmth_saturation_combined_path():
    """组合路径公式级钉死 (R13): 施加序 = 曝光增益 → 暖色通道增益 →
    饱和度 HSV 核, 区域末尾一次 clip —— 两次增益乘法均不经中间 clip。"""
    from pixo.render.modules.region_adjust import (
        _apply_saturation, _warmth_gains)

    rng = np.random.default_rng(13)
    img = (rng.random((12, 12, 3)).astype(np.float32) * 0.7 + 0.15)
    p = {"enabled": True,
         "regions": {"sky": {"exposure": 0.6, "warmth": -0.4,
                             "saturation": 0.25}}}
    masks = {"sky": np.ones((12, 12), dtype=np.float32)}
    ctx = _ctx(img, masks, p)
    RegionAdjustStage(params=p).process(ctx)
    ev_gain = np.float32(2.0 ** (0.6 / 2.2))
    stepped = np.clip(img * ev_gain, 0.0, None).astype(np.float32)
    stepped = (stepped * _warmth_gains(-0.4)).astype(np.float32)
    expected = np.clip(
        _apply_saturation(np.clip(stepped, 0.0, None).astype(np.float32),
                          0.25).astype(np.float32), 0.0, 1.0)
    assert np.allclose(ctx.image, expected, atol=1e-6)


def test_region_param_limits_single_source_includes_warmth():
    """S-3 单源: warmth 限幅入 REGION_PARAM_LIMITS (loop 映射侧钳制同源)。"""
    from pixo.render.modules.region_adjust import REGION_PARAM_LIMITS
    assert REGION_PARAM_LIMITS["warmth"] == 1.0
    assert set(REGION_PARAM_LIMITS) == {"exposure", "saturation", "warmth"}
