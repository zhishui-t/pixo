"""T2.3 分离色调 (split toning) —— split_tone_rgb 纯函数 + SplitToneStage。

测试: no-op (enabled False / 全 0 饱和 / strength 0)、纯黑/纯白隔离、HSV 换算、
      balance 移动分界、strength 缩放、hue360≡0、sat=0 时 hue 无差异、
      [0,1] 无 NaN、分界附近 C1 连续、stage 默认 wants False。
"""
from __future__ import annotations

import numpy as np
import pytest

import rawlab.engine.stages  # noqa: F401  (触发 split_tone 注册)
from rawlab.engine.core import StageContext, DOMAIN_GAMMA_RGB, available_stages
from rawlab.engine.split_tone import split_tone_rgb


def hsv_ref(hue, s, v):
    """标准 HSV->RGB 参考 (标量 hue/sat, 标量亮度 v)。"""
    h = (float(hue) % 360.0) / 60.0
    c = v * s
    x = c * (1.0 - abs((h % 2.0) - 1.0))
    m = v - c
    i = int(h)
    tbl = [(c, x, 0.0), (x, c, 0.0), (0.0, c, x), (0.0, x, c), (x, 0.0, c), (c, 0.0, x)]
    r, g, b = tbl[i % 6]
    return np.array([r + m, g + m, b + m], dtype=np.float32)


# ---- no-op ----
def test_enabled_false_noop_stage():
    """enabled=False → wants()=False → 管线跳过该 Stage (no-op)。"""
    img = np.random.default_rng(0).random((8, 8, 3)).astype(np.float32)
    ctx = StageContext("x.NEF", config={"stages": {"split_tone": {"enabled": False,
                                     "shadows_sat": 80.0, "highlights_sat": 80.0}}})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    sg = available_stages()["split_tone"]()
    assert sg.wants(ctx) is False          # 管线据此跳过 process → 输出不变


def test_all_zero_sat_noop():
    img = np.random.default_rng(0).random((8, 8, 3)).astype(np.float32)
    out = split_tone_rgb(img, 45.0, 0.0, 210.0, 0.0)
    assert np.array_equal(out, img)


def test_strength_zero_noop():
    img = np.random.default_rng(0).random((8, 8, 3)).astype(np.float32)
    out = split_tone_rgb(img, 45.0, 80.0, 210.0, 80.0, strength=0.0)
    assert np.array_equal(out, img)


# ---- 纯黑/纯白隔离 ----
def test_pure_black_only_shadow():
    """纯黑不受 highlights 影响 (shadow 权重≈1)；改 highlights 不改变输出。"""
    black = np.array([[[0.0, 0.0, 0.0]]], np.float32)
    a = split_tone_rgb(black, 45.0, 80.0, 210.0, 80.0)
    b = split_tone_rgb(black, 45.0, 80.0, 0.0, 90.0)   # 改 highlights
    assert np.array_equal(a, b)                        # 仅 shadows 侧作用
    assert np.allclose(a[0, 0], 0.0, atol=1e-6)        # 纯黑保持黑 (V=0)


def test_pure_white_only_highlight():
    """纯白不受 shadows 影响 (highlight 权重≈1)；改 shadows 不改变输出。"""
    white = np.array([[[1.0, 1.0, 1.0]]], np.float32)
    a = split_tone_rgb(white, 45.0, 80.0, 210.0, 80.0)
    b = split_tone_rgb(white, 30.0, 90.0, 210.0, 80.0)  # 改 shadows
    assert np.array_equal(a, b)                        # 仅 highlights 侧作用
    # 纯白应染成 highlights HSV(210, 0.8, v=1)
    ref = hsv_ref(210.0, 0.8, 1.0)
    assert np.allclose(a[0, 0], ref, atol=1e-3)


# ---- HSV 换算 ----
@pytest.mark.parametrize("hue,sat", [(45.0, 80.0), (210.0, 60.0), (340.0, 100.0)])
def test_neutral_gray_hue_matches_hsv(hue, sat):
    """全阴影 (balance=1.0) 下中灰输出 = HSV(hue, sat/100, v)。"""
    v = 0.3
    img = np.array([[[v, v, v]]], np.float32)
    out = split_tone_rgb(img, hue, sat, 0.0, 0.0, balance=1.0)
    ref = hsv_ref(hue, sat / 100.0, v)
    assert np.allclose(out[0, 0], ref, atol=1e-3)


# ---- balance 移动分界 ----
def test_balance_moves_partition():
    """固定 luma 像素: balance 增大 → 更偏 shadows (染色效果增强)。"""
    v = 0.3
    img = np.array([[[v, v, v]]], np.float32)
    low = split_tone_rgb(img, 45.0, 100.0, 0.0, 0.0, balance=0.2)
    high = split_tone_rgb(img, 45.0, 100.0, 0.0, 0.0, balance=0.8)
    # balance 高 → 该 luma 更偏 shadows → 更接近 HSV(45,1,v) 染色 (绿色下降)
    assert abs(high[0, 0, 1] - v) > abs(low[0, 0, 1] - v)
    assert high[0, 0, 1] < low[0, 0, 1]


# ---- strength 缩放 ----
def test_strength_scale_halfway():
    """strength=0.5 应在原图与全染之间线性插值 (全阴影区)。"""
    v = 0.4
    img = np.array([[[v, v, v]]], np.float32)
    ref = hsv_ref(45.0, 0.8, v)
    f0 = split_tone_rgb(img, 45.0, 80.0, 0.0, 0.0, balance=1.0, strength=0.0)
    f1 = split_tone_rgb(img, 45.0, 80.0, 0.0, 0.0, balance=1.0, strength=1.0)
    f05 = split_tone_rgb(img, 45.0, 80.0, 0.0, 0.0, balance=1.0, strength=0.5)
    assert np.array_equal(f0, img)
    assert np.allclose(f1[0, 0], ref, atol=1e-3)
    expect = img[0, 0] + 0.5 * (ref - img[0, 0])
    assert np.allclose(f05[0, 0], expect, atol=1e-3)


# ---- hue 360 ≡ 0 ----
def test_hue_360_equiv_0():
    img = np.array([[[0.5, 0.5, 0.5]]], np.float32)
    a = split_tone_rgb(img, 0.0, 60.0, 0.0, 0.0, balance=0.0)
    b = split_tone_rgb(img, 360.0, 60.0, 0.0, 0.0, balance=0.0)
    assert np.allclose(a, b, atol=1e-6)


# ---- sat=0 时 hue 无差异 ----
def test_zero_sat_hue_no_effect():
    img = np.array([[[0.4, 0.5, 0.6]]], np.float32)
    a = split_tone_rgb(img, 10.0, 0.0, 200.0, 0.0)
    b = split_tone_rgb(img, 100.0, 0.0, 20.0, 0.0)
    assert np.array_equal(a, img)
    assert np.array_equal(b, img)


# ---- 输出范围 / NaN ----
def test_output_range_no_nan():
    rng = np.random.default_rng(3)
    img = rng.random((16, 16, 3)).astype(np.float32)
    for args in [(45, 80, 210, 100, 0.5, 1.0), (300, 50, 30, 90, 0.3, 0.7),
                 (0, 100, 360, 100, 1.0, 1.0)]:
        out = split_tone_rgb(img, *args)
        assert np.isfinite(out).all()
        assert out.min() >= 0.0 and out.max() <= 1.0 + 1e-6


# ---- C1 连续 ----
def test_c1_continuity_near_balance():
    """分界附近相邻亮度输出差有界 (C1 光滑权重)。"""
    ys = np.linspace(0.4, 0.6, 41)
    outs = np.array([split_tone_rgb(np.array([[[y, y, y]]], np.float32),
                                    45.0, 100.0, 180.0, 90.0, balance=0.5)[0, 0]
                     for y in ys])
    diff = float(np.max(np.abs(np.diff(outs, axis=0))))
    assert diff < 0.02


# ---- stage 默认 ----
def test_alphabet_stage_defaults_and_wants():
    sg = available_stages()["split_tone"]()
    d = sg.default_params()
    assert d["enabled"] is False
    assert d["balance"] == 0.5 and d["strength"] == 1.0
    ctx = StageContext("x.NEF")
    ctx.set_image(np.full((4, 4, 3), 0.5, np.float32), DOMAIN_GAMMA_RGB)
    assert sg.wants(ctx) is False


def test_stage_enabled_runs_metrics():
    sg = available_stages()["split_tone"]()
    ctx = StageContext("x.NEF", config={"stages": {"split_tone": {
        "enabled": True, "shadows_sat": 80.0, "highlights_sat": 50.0}}})
    ctx.set_image(np.full((8, 8, 3), 0.5, np.float32), DOMAIN_GAMMA_RGB)
    sg.run(ctx)
    assert ctx.results[-1].metrics.get("split_tone_enabled") is True
    assert ctx.results[-1].metrics.get("split_tone_balance") == 0.5
