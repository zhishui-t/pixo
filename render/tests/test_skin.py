"""T5 单元测试: 人像精修 (render/core/skin.py + stages/skin.py + colorcal 肤色保护)。

覆盖 (验收: 平坦区方差降 ≥30%; 边缘无晕; 掩码软边界; 无肤色直通; 与 colorcal 一致):
  - skin_mask: float32 HxW 0..1; 肤色高 / 中性灰与绿蓝低; float 输入一致
  - skin_mask: 软边界 (椭圆外 smoothstep 过渡, 存在中间值)
  - skin_smooth: 平坦肤色区噪声方差降 ≥30%; 仅掩码区改变; 无肤色/零强度直通
  - skin_smooth: 强边缘无晕 (输出不越界 + 边缘对比度保持)
  - guided_filter: box-filter 自实现平滑 + 保边 (独立于 cv2.ximgproc)
  - SkinStage: 注册 (order=55, gamma_rgb→gamma_rgb); wants 门控 (enabled/scene/掩码占比)
  - SkinStage.process: 磨皮生效且输出合法 float 0..1
  - colorcal: 肤色保护用椭圆掩码 (肤色色度不变, 非肤色色度按增益放大)

运行: python -m pytest render/tests/test_skin.py -q
"""
from __future__ import annotations

import cv2
import numpy as np

from render.pipeline.graph import (
    DOMAIN_GAMMA_RGB,
    STAGE_REGISTRY,
    StageContext,
)
from render.core.skin import (
    GUIDED_EPS,
    GUIDED_R,
    SKIN_ANGLE,
    SKIN_LAB_A,
    SKIN_LAB_B,
    SKIN_MAJOR,
    SKIN_MINOR,
    guided_filter,
    skin_mask,
    skin_smooth,
)
from render.modules.color_cal import ColorCalStage
from render.modules.skin import SkinStage

# 肤色 RGB (test_scenes.py 同款): (210,155,130) → Lab a≈145, b≈149, 椭圆内
_SKIN_RGB = (210, 155, 130)
_GRAY_RGB = (128, 128, 128)
_GREEN_RGB = (60, 160, 80)


def _solid(h, w, rgb):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = rgb
    return img


def _skin_block(h=128, w=128, noise_std=0.0, seed=0):
    """平坦肤色块 + 可选高斯噪声 (uint8)。"""
    base = _solid(h, w, _SKIN_RGB)
    if noise_std <= 0.0:
        return base
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, noise_std, size=(h, w, 3)).astype(np.float32)
    return np.clip(base.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def _noise_var(img, base):
    """逐通道噪声方差 (偏离平坦底色的方差, 避免通道均值差污染)。"""
    return float((img.astype(np.float32) - base.astype(np.float32)).var())


def _chroma(u8):
    """Lab 色度 C = sqrt((a-128)^2 + (b-128)^2) 的均值。"""
    lab = cv2.cvtColor(np.asarray(u8, dtype=np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    a = lab[:, :, 1]
    b = lab[:, :, 2]
    return float(np.sqrt((a - 128.0) ** 2 + (b - 128.0) ** 2).mean())


# ---------------------------------------------------------------------------
# skin_mask: 范围 / dtype / 肤色判别 / 软边界
# ---------------------------------------------------------------------------

def test_skin_mask_range_and_dtype():
    m = skin_mask(_skin_block(32, 32))
    assert m.dtype == np.float32
    assert m.shape == (32, 32)
    assert float(m.min()) >= 0.0
    assert float(m.max()) <= 1.0


def test_skin_mask_skin_high_neutral_low():
    assert float(skin_mask(_skin_block(16, 16)).max()) > 0.9
    assert float(skin_mask(_solid(16, 16, _GRAY_RGB)).max()) < 0.05
    assert float(skin_mask(_solid(16, 16, _GREEN_RGB)).max()) < 0.05


def test_skin_mask_soft_boundary():
    """椭圆外 smoothstep 软过渡: 扫 a 轴应出现 0..1 之间的中间值 (非硬 0/1)。"""
    a_vals = np.linspace(115.0, 165.0, 101)
    lab = np.zeros((1, len(a_vals), 3), dtype=np.uint8)
    lab[:, :, 0] = 150
    lab[:, :, 1] = a_vals.astype(np.uint8)
    lab[:, :, 2] = 150
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    m = skin_mask(rgb)[0]
    # 中心 (a=140) 峰值
    assert float(m[np.argmin(np.abs(a_vals - SKIN_LAB_A))]) > 0.9
    # 存在软过渡中间值
    assert int(((m > 0.01) & (m < 0.99)).sum()) > 0
    # 远端趋于 0
    assert float(m[0]) < 0.05 and float(m[-1]) < 0.05


def test_skin_mask_float_input_consistent():
    u8 = _skin_block(32, 32)
    flt = u8.astype(np.float32) / 255.0
    assert np.array_equal(skin_mask(u8), skin_mask(flt))


def test_skin_mask_ellipse_constants():
    """规格 §2.2 椭圆参数落位 (中心/主轴/副轴/倾角)。"""
    assert (SKIN_LAB_A, SKIN_LAB_B) == (140.0, 150.0)
    assert SKIN_MAJOR == 22.0
    assert SKIN_MINOR == 14.0
    assert abs(SKIN_ANGLE - 0.65) < 1e-9


# ---------------------------------------------------------------------------
# skin_smooth: 磨皮 / 仅掩码区 / 直通 / 无晕
# ---------------------------------------------------------------------------

def test_skin_smooth_reduces_flat_variance():
    base = _skin_block(128, 128)
    noisy = _skin_block(128, 128, noise_std=8.0, seed=0)
    mask = np.ones((128, 128), dtype=np.float32)
    out = skin_smooth(noisy, mask, strength=0.5)

    interior = (slice(20, -20), slice(20, -20))
    var_before = _noise_var(noisy[interior], base[interior])
    var_after = _noise_var(out[interior], base[interior])
    assert var_after <= 0.7 * var_before, \
        f"平坦区方差降不足: {var_before:.2f} → {var_after:.2f}"


def test_skin_smooth_only_mask_region_changes():
    """掩码外的像素严格保持原值 (仅掩码区磨皮)。"""
    h = w = 64
    img = _solid(h, w, _GREEN_RGB)
    img[:, :w // 2] = _SKIN_RGB          # 左半肤色
    mask = np.zeros((h, w), dtype=np.float32)
    mask[:, :w // 2] = 1.0
    out = skin_smooth(img, mask, strength=0.8)
    assert np.array_equal(out[:, w // 2:], img[:, w // 2:])


def test_skin_smooth_no_skin_passthrough():
    """零掩码 → 逐位直通 (无肤色)。"""
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, size=(48, 48, 3), dtype=np.uint8)
    out = skin_smooth(img, np.zeros((48, 48), dtype=np.float32), strength=0.5)
    assert np.array_equal(out, img)


def test_skin_smooth_neutral_image_passthrough_via_mask():
    """中性灰图 → 掩码全零 → 直通 (经 skin_mask 计算)。"""
    img = _solid(48, 48, _GRAY_RGB)
    m = skin_mask(img)
    assert float(m.max()) < 0.05
    assert np.array_equal(skin_smooth(img, m, strength=0.5), img)


def test_skin_smooth_zero_strength_passthrough():
    img = _skin_block(48, 48, noise_std=8.0, seed=2)
    mask = np.ones((48, 48), dtype=np.float32)
    assert np.array_equal(skin_smooth(img, mask, strength=0.0), img)


def test_skin_smooth_no_edge_halo():
    """强边缘图 → 边缘无晕: 输出不越界 (无过冲) 且对比度保持。"""
    h = w = 64
    edge = _solid(h, w, (40, 40, 40))
    edge[:, w // 2:] = (220, 220, 220)
    mask = np.ones((h, w), dtype=np.float32)
    out = skin_smooth(edge, mask, strength=1.0)   # 全强度最严苛

    # 过冲检测: 输出不超出原始 min/max (无晕环/过冲)
    assert int(out.min()) >= int(edge.min())
    assert int(out.max()) <= int(edge.max())
    # 边缘对比度保持 (两侧均值差保留 ≥90%)
    left = float(out[:, 8:24].astype(np.float32).mean())
    right = float(out[:, 40:56].astype(np.float32).mean())
    assert right - left >= 0.9 * (220 - 40)


def test_skin_smooth_guided_filter_constants():
    assert GUIDED_R == 4
    assert abs(GUIDED_EPS - 0.01) < 1e-12


# ---------------------------------------------------------------------------
# guided_filter: box-filter 自实现 (独立于 cv2.ximgproc 可用性)
# ---------------------------------------------------------------------------

def test_guided_filter_smooths_and_preserves_edge():
    rng = np.random.default_rng(0)
    flat = np.clip(0.5 + rng.normal(0.0, 0.06, size=(64, 64)), 0.0, 1.0).astype(np.float32)
    out = guided_filter(flat, flat, r=4, eps=0.01)
    interior = (slice(8, -8), slice(8, -8))
    assert float(out[interior].var()) < 0.5 * float(flat[interior].var())

    edge = np.zeros((64, 64), dtype=np.float32)
    edge[:, :32] = 0.2
    edge[:, 32:] = 0.8
    out2 = guided_filter(edge, edge, r=4, eps=0.01)
    assert float(out2.min()) >= 0.2 - 1e-4
    assert float(out2.max()) <= 0.8 + 1e-4
    assert float(out2[:, 16].mean()) < 0.25
    assert float(out2[:, 48].mean()) > 0.75


def test_guided_filter_mismatched_shape_raises():
    import pytest
    with pytest.raises(ValueError):
        guided_filter(np.zeros((8, 8), np.float32), np.zeros((8, 9), np.float32))


# ---------------------------------------------------------------------------
# SkinStage: 注册 + wants 门控 + process
# ---------------------------------------------------------------------------

def _skin_ctx(image_float01, scene=None, enabled=True, strength=0.5):
    ctx = StageContext("x.NEF", config={"stages": {"skin": {
        "enabled": enabled, "strength": strength}}})
    ctx.set_image(np.clip(np.asarray(image_float01, dtype=np.float32), 0, 1), DOMAIN_GAMMA_RGB)
    if scene is not None:
        ctx.state["scene"] = scene
    return ctx


def test_skin_stage_registered_order_and_domain():
    assert "skin" in STAGE_REGISTRY
    cls = STAGE_REGISTRY["skin"]
    assert cls.order == 55
    assert cls.domain_in == DOMAIN_GAMMA_RGB
    assert cls.domain_out == DOMAIN_GAMMA_RGB
    assert cls().default_params() == {"enabled": True, "strength": 0.5}


def test_skin_stage_wants_disabled():
    img = _skin_block(48, 48)
    assert SkinStage().wants(_skin_ctx(img / 255.0, enabled=False)) is False


def test_skin_stage_wants_non_portrait_scene_false():
    img = _skin_block(48, 48)
    for scene in ("landscape", "night", "street", "food", "mono"):
        assert SkinStage().wants(_skin_ctx(img / 255.0, scene=scene)) is False
    # dict 形式 scene 状态注入
    assert SkinStage().wants(_skin_ctx(img / 255.0, scene={"id": "landscape"})) is False


def test_skin_stage_wants_portrait_true():
    img = _skin_block(48, 48)
    assert SkinStage().wants(_skin_ctx(img / 255.0, scene="portrait")) is True
    assert SkinStage().wants(_skin_ctx(img / 255.0, scene={"id": "portrait"})) is True


def test_skin_stage_wants_no_scene_mask_gate():
    """无 scene 状态 → 掩码占比门限: 肤色图启用, 中性灰图直通。"""
    assert SkinStage().wants(_skin_ctx(_skin_block(48, 48) / 255.0)) is True
    assert SkinStage().wants(_skin_ctx(_solid(48, 48, _GRAY_RGB) / 255.0)) is False


def test_skin_stage_process_smooths():
    base = _skin_block(128, 128)
    noisy = _skin_block(128, 128, noise_std=8.0, seed=3)
    ctx = _skin_ctx(noisy / 255.0, scene="portrait", strength=0.5)
    SkinStage().run(ctx)

    assert ctx.domain == DOMAIN_GAMMA_RGB
    assert ctx.image.dtype == np.float32
    assert float(ctx.image.min()) >= 0.0 and float(ctx.image.max()) <= 1.0

    out8 = (ctx.image * 255.0 + 0.5).astype(np.uint8)
    interior = (slice(20, -20), slice(20, -20))
    var_before = _noise_var(noisy[interior], base[interior])
    var_after = _noise_var(out8[interior], base[interior])
    assert var_after <= 0.7 * var_before


# ---------------------------------------------------------------------------
# colorcal: 肤色保护与 engine.skin.skin_mask 一致
# ---------------------------------------------------------------------------

_COLORCAL_CFG = {
    "saturation": 0.2, "vibrance": 0.0, "hue": 0.0,
    "neutral_a": 0.0, "neutral_b": 0.0, "neutral_mode": "off",
    "skin_protect": 1.0, "gamut_soft": 0.0,
}


def _run_colorcal(u8):
    ctx = StageContext("x.NEF", config={"stages": {"colorcal": _COLORCAL_CFG}})
    ctx.set_image(u8.astype(np.float32) / 255.0, DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    return (np.clip(ctx.image, 0, 1) * 255.0 + 0.5).astype(np.uint8)


def test_colorcal_skin_protection_uses_ellipse_mask():
    """肤色 (椭圆内) 色度不增, 非肤色 (绿) 色度按饱和度增益放大。"""
    skin_before = _chroma(_solid(32, 32, _SKIN_RGB))
    skin_after = _chroma(_run_colorcal(_solid(32, 32, _SKIN_RGB)))
    assert abs(skin_after - skin_before) < 2.0, \
        f"肤色应被保护: {skin_before:.2f} → {skin_after:.2f}"

    green_before = _chroma(_solid(32, 32, _GREEN_RGB))
    green_after = _chroma(_run_colorcal(_solid(32, 32, _GREEN_RGB)))
    assert green_after > 1.15 * green_before, \
        f"非肤色应按增益放大: {green_before:.2f} → {green_after:.2f}"
