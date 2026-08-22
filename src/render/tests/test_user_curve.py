"""T1.4 用户控制点曲线 (RGB 主曲线 + 分通道 + 亮度) —— ToneStage user_curve 参数测试。

测试: no-op/恒等、主曲线单调、分通道独立、亮度保色调(无 clip 时)、中性灰保中性、
      校验报错、纯黑不除零、端点保黑白、多结构解析。
"""
from __future__ import annotations

import numpy as np
import pytest

from render.pipeline.graph import StageContext, DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB
from render.core.curves import apply_lut1d_fast, curve_lut_from_points
from render.modules.tone_map import (_apply_user_curve, _parse_user_curve_points,
                                        _RGB_WEIGHTS)
from render.modules.tone_map import ToneStage


def _stage_out(img, user_curve, base="srgb"):
    """跑 ToneStage 全链路 (user_curve 注入), 返回 gamma 输出。"""
    ctx = StageContext("x.NEF", prof=None,
                       config={"stages": {"tone": {"eotf": base, "user_curve": user_curve}}})
    ctx.set_image(np.asarray(img, dtype=np.float32), DOMAIN_LINEAR_RGB)
    ToneStage().run(ctx)
    return ctx.image


def _neut(v, h=4, w=4):
    return np.full((h, w, 3), v, dtype=np.float32)


# ---- no-op / 恒等 ----
def test_none_noop_bitwise():
    img = np.random.default_rng(0).random((8, 8, 3)).astype(np.float32)
    a = _stage_out(img, None)
    b = _stage_out(img, None)
    assert np.array_equal(a, b)          # 运行稳定
    c = _stage_out(img, {"rgb": [[0, 0], [1, 1]]})
    assert np.allclose(a, c, atol=1e-3)  # 恒等曲线 ≈ no-op


def test_empty_noop():
    img = _neut(0.5)
    assert np.array_equal(_apply_user_curve(img, None), img)
    assert np.array_equal(_apply_user_curve(img, []), img)
    assert np.array_equal(_apply_user_curve(img, {}), img)


def test_identity_curve_effectively_noop():
    img = _neut(0.5)
    out = _apply_user_curve(img, [[0, 0], [1, 1]])
    assert np.allclose(out, img, atol=1e-3)


# ---- RGB 主曲线 ----
def test_main_curve_bright_lift_monotonic():
    lift = [[0.0, 0.0], [0.5, 0.6], [1.0, 1.0]]
    g = np.linspace(0.05, 0.95, 10)
    img = np.stack([g, g, g], axis=-1)[np.newaxis].astype(np.float32)  # (1,10,3)
    out = _apply_user_curve(img, lift)
    # 每点三通道仍相等 (主曲线不偏色)
    assert np.allclose(out[..., 0], out[..., 1], atol=1e-6)
    assert np.allclose(out[..., 1], out[..., 2], atol=1e-6)
    # 单调不减
    v = out[0, :, 0]
    assert np.all(np.diff(v) >= -1e-6)
    # 亮部提升: 0.8 -> >0.8
    bright_img = np.array([[[0.8, 0.8, 0.8]]], np.float32)
    bo = _apply_user_curve(bright_img, lift)
    assert bo[0, 0, 0] > 0.8


# ---- 分通道 ----
def test_per_channel_only_affects_channel():
    img = _neut(0.5, 1, 1)
    out = _apply_user_curve(img, {"red": [[0, 0], [1, 1.2]]})
    assert out[0, 0, 0] > 0.5          # red 提升
    assert out[0, 0, 1] == 0.5          # green 不动
    assert out[0, 0, 2] == 0.5          # blue 不动


def test_per_channel_plural():
    img = _neut(0.5, 1, 1)
    out = _apply_user_curve(img, {"red": [[0, 0], [1, 1.2]],
                                  "blue": [[0, 0], [1, 0.8]]})
    assert out[0, 0, 0] > 0.5
    assert out[0, 0, 1] == 0.5
    assert out[0, 0, 2] < 0.5


# ---- 亮度曲线 ----
def test_luminance_preserves_hue_nonclip():
    """非中性色, 亮度曲线在输出未 clip 时 R/G/B 比值不变 (保色调)。"""
    nonneut = np.array([[[0.2, 0.5, 0.9]]], np.float32)
    dim = [[0.0, 0.0], [0.5, 0.35], [1.0, 1.0]]  # 中段压暗, 输出 <1 不 clip
    out = _apply_user_curve(nonneut, {"luminance": dim})
    r_in = nonneut[0, 0] / nonneut[0, 0][1]
    r_out = out[0, 0] / out[0, 0][1]
    assert np.allclose(r_out, r_in, atol=1e-3)  # 排列比值保持


def test_luminance_black_no_division_by_zero():
    black = np.zeros((2, 2, 3), np.float32)
    out = _apply_user_curve(black, {"luminance": [[0.0, 0.2], [1.0, 0.9]]})
    assert out.min() >= 0.0
    assert np.isfinite(out).all()


def test_luminance_changes_brightness_scale():
    img = np.array([[[0.2, 0.5, 0.9]]], np.float32)
    # 中段压暗曲线 → 亮度降低
    dim = [[0.0, 0.0], [0.5, 0.3], [1.0, 1.0]]
    out = _apply_user_curve(img, {"luminance": dim})
    y_in = float((img[0, 0] * _RGB_WEIGHTS).sum())
    y_out = float((out[0, 0] * _RGB_WEIGHTS).sum())
    assert y_out < y_in - 1e-4          # 变暗
    assert y_out > 0.0


# ---- 中性 ----
def test_neutral_gray_stays_neutral_main_curve():
    """中性灰经任意主曲线仍中性 (三通道相等)。"""
    img = _neut(0.6, 8, 8)
    curve = [[0.0, 0.0], [0.4, 0.5], [0.7, 0.65], [1.0, 1.0]]
    out = _apply_user_curve(img, curve)
    spread = float(np.ptp(out, axis=2).max())
    assert spread < 1e-4


# ---- 校验 ----
def test_unsorted_x_raises():
    with pytest.raises(ValueError, match="单调"):
        _apply_user_curve(_neut(0.5), [[0.3, 0.2], [0.1, 0.1]])


def test_out_of_range_x_raises():
    with pytest.raises(ValueError, match=r"\[0,1\]"):
        _apply_user_curve(_neut(0.5), [[-0.1, 0.0], [1.0, 1.0]])


def test_unknown_key_raises():
    with pytest.raises(ValueError, match="未知键|合法键"):
        _apply_user_curve(_neut(0.5), {"foo": [[0, 0], [1, 1]]})


def test_non_list_structure_raises():
    with pytest.raises(ValueError):
        _apply_user_curve(_neut(0.5), 5)


def test_bad_point_shape_raises():
    with pytest.raises(ValueError, match="二元组"):
        _parse_user_curve_points([[0.0], [1.0]], "rgb")


# ---- 端点 ----
def test_endpoints_preserve_black_and_white():
    """控制点 [0,0][1,1] 保黑/白点 (端点映射到端点)。"""
    curve = [[0.0, 0.0], [0.5, 0.6], [1.0, 1.0]]
    img = np.array([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]], np.float32)
    out = _apply_user_curve(img, curve)
    assert np.allclose(out[0, 0], 0.0, atol=1e-6)       # 黑保黑
    assert np.allclose(out[0, 1].min(), 1.0, atol=1e-3)  # 白保白 (钳位到 1)


# ---- 结构解析 ----
def test_rgb_key_equiv_list():
    img = _neut(0.5, 1, 1)
    a = _apply_user_curve(img, [[0, 0], [0.5, 0.6], [1, 1]])
    b = _apply_user_curve(img, {"rgb": [[0, 0], [0.5, 0.6], [1, 1]]})
    assert np.allclose(a, b, atol=1e-6)


def test_rgb_then_perchannel_order():
    """顺序 rgb → per-channel: 先整体 (红蓝同幅度), 再红色修正覆盖红通道。"""
    img = _neut(0.5, 1, 1)
    out = _apply_user_curve(img, {"rgb": [[0, 0], [1, 1.2]],
                                  "red": [[0, 0], [1, 0.5]]})
    # 先 rgb: 全通道 0.5→0.6; 再 red 分通道贴合压暗 → red 单独不同于 green/blue
    assert np.isclose(out[0, 0, 1], 0.6, atol=1e-3)    # green 仅受 rgb 影响
    assert np.isclose(out[0, 0, 2], 0.6, atol=1e-3)    # blue 仅受 rgb 影响
    assert np.isclose(out[0, 0, 0], 0.3, atol=2e-2)    # red 再被分通道压暗 (0.6→0.3)


def test_combined_all_three():
    """rgb + per-channel + luminance 同时: 三阶段都生效, 输出有限且 ≥0。"""
    img = np.random.default_rng(1).random((5, 5, 3)).astype(np.float32)
    out = _apply_user_curve(img, {"rgb": [[0, 0], [1, 1]],
                                  "red": [[0, 0], [1, 0.9]],
                                  "luminance": [[0, 0.1], [1, 0.9]]})
    assert out.shape == img.shape
    assert np.isfinite(out).all()
    assert out.min() >= 0.0


# ---- 参数校验层: 非法 user_curve dict 即报错 (core._validate_param/_curve_dict_check) ----
def test_invalid_user_curve_dict_raises_at_param_layer():
    """非法 user_curve dict 在参数校验层 (self.p) 即抛 ValueError (未知键/非点集)。"""
    from render.pipeline.graph import StageContext, DOMAIN_LINEAR_RGB
    for bad, match in [({"foo": [[0, 0], [1, 1]]}, "未知曲线键"),
                       ({"rgb": 123}, "点集"),
                       ({"red": []}, "点集")]:
        ctx = StageContext("x.NEF", prof=None,
                           config={"stages": {"tone": {"user_curve": bad}}})
        ctx.set_image(np.full((4, 4, 3), 0.5, np.float32), DOMAIN_LINEAR_RGB)
        with pytest.raises(ValueError, match=match):
            ToneStage().run(ctx)
