"""Regression tests for exposure param flatten/apply mapping in the loop."""
import numpy as np
import pytest

from pixo.pipeline.loop import (
    SyntheticRenderBackend,
    _apply_decide_params,
    _flatten_decide_params,
)


def test_flatten_exposure_uses_canonical_alias_only():
    params = {"exposure": {"mode": "auto", "target_offset": -0.15}, "style": "portrait"}
    flat = _flatten_decide_params(params)
    assert flat["exposure_ev"] == -0.15
    # The stale duplicate alias must not be carried into Decide results.
    assert "Exposure" not in flat
    assert flat["style"] == "portrait"


def test_apply_decide_params_uses_auto_target_offset_not_manual_absolute():
    params = {"exposure": {"mode": "auto", "target_offset": -0.15}}
    decided = {"exposure_ev": 0.5}
    out = _apply_decide_params(params, decided)
    assert out["exposure"]["mode"] == "auto"
    assert out["exposure"]["target_offset"] == 0.5


def test_manual_numeric_mode_still_flattens():
    params = {"exposure": {"mode": 0.3}}
    flat = _flatten_decide_params(params)
    assert flat["exposure_ev"] == 0.3


def test_flatten_include_exposure_keeps_bucket_for_delta_precheck():
    """include_exposure=True：嵌套 exposure 桶与扁平 exposure_ev 共存。

    run_suggest → review_patches 的 delta 预检按
    current_params["exposure"]["target_offset"] 读现值，默认剥离曝光桶
    会使 exposure.target_offset 的 delta 基线失真回 0。
    """
    params = {"exposure": {"mode": "auto", "target_offset": -0.15},
              "tone": {"shadows": 0.1}}
    flat_default = _flatten_decide_params(params)
    assert "exposure" not in flat_default          # 默认仍剥离（旧行为）
    assert flat_default["exposure_ev"] == -0.15

    flat = _flatten_decide_params(params, include_exposure=True)
    assert flat["exposure_ev"] == -0.15            # 扁平方言仍暴露
    assert flat["exposure"] == {"mode": "auto", "target_offset": -0.15}
    assert flat["tone"] == {"shadows": 0.1}        # 其余桶不受影响


# ---- t51 色彩规则执行位映射桥 (_COLOR_PARAM_ALIASES) ----

def test_color_alias_vibrance_strength_maps_to_colorcal():
    from pixo.pipeline.loop import _COLOR_PARAM_ALIASES
    assert _COLOR_PARAM_ALIASES["vibrance.strength"] == ("colorcal", "vibrance")
    params = {"colorcal": {"saturation": 0.0}}
    out = _apply_decide_params(params, {"vibrance.strength": 0.3})
    assert out["colorcal"]["vibrance"] == 0.3          # 直传, 正向提升
    assert out["colorcal"]["saturation"] == 0.0        # 既有桶不被破坏
    assert "vibrance.strength" not in out              # 悬空键不再残留


def test_color_alias_saturation_adjust_maps_to_colorcal():
    params = {}
    out = _apply_decide_params(params, {"saturation.adjust": -0.15})
    assert out["colorcal"]["saturation"] == -0.15      # 负值=降饱和, 域内直传
    assert "saturation.adjust" not in out


def test_color_alias_bucket_not_dict_falls_back_flat():
    """桶被占成非 dict 时退回原样扁平键 (不静默吞掉)。"""
    params = {"colorcal": "reserved"}
    out = _apply_decide_params(params, {"vibrance.strength": 0.2})
    assert out["vibrance.strength"] == 0.2
    assert out["colorcal"] == "reserved"


def test_exposure_alias_still_wins_over_color_table():
    """曝光别名优先级不受色彩桥影响 (回归锁定)。"""
    out = _apply_decide_params({"exposure": {"mode": "auto"}}, {"exposure_ev": 0.4})
    assert out["exposure"]["target_offset"] == 0.4


# ---- t107 影调/清晰度/去雾执行位注册表 (DOTTED_PARAM_REGISTRY) ----

def test_tone_shadows_maps_to_tone_bucket():
    out = _apply_decide_params({}, {"tone.shadows": 0.2})
    assert out["tone"]["shadows"] == 0.2
    assert "tone.shadows" not in out


def test_tone_highlights_maps_to_tone_bucket():
    out = _apply_decide_params({}, {"tone.highlights": -0.1})
    assert out["tone"]["highlights"] == -0.1


def test_clarity_strength_maps_to_clarity_bucket():
    out = _apply_decide_params({}, {"clarity.strength": 0.3})
    assert out["clarity"]["strength"] == 0.3


def test_dehaze_strength_maps_to_dehaze_bucket():
    out = _apply_decide_params({}, {"dehaze.strength": 0.25})
    assert out["dehaze"]["strength"] == 0.25


def test_unknown_dotted_key_warns_and_keeps_flat(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="pixo.pipeline.loop"):
        out = _apply_decide_params({}, {"ghost.key": 1.0})
    assert out["ghost.key"] == 1.0                       # 不静默吞掉
    msgs = [r.message for r in caplog.records]
    assert any("无执行位" in m for m in msgs)
    # 文案与行为一致：键被保留为顶层 informational，而非"已忽略"
    assert any("保留" in m for m in msgs)
    assert not any("已忽略" in m for m in msgs)


# ---- SyntheticRenderBackend 曝光增益：auto+target_offset 生效 ----

def test_synthetic_backend_auto_target_offset_applies_gain():
    """mode="auto" 时 target_offset 应按 EV 线性增益生效。

    此前 auto 字符串被直接跳过，loop 的 decide 曝光修正写出的正是
    auto+target_offset 形态——合成链路曝光规则整体无效。
    """
    img = np.full((32, 32, 3), 0.2, dtype=np.float32)
    backend = SyntheticRenderBackend(img)
    base = backend._apply_exposure(img, {"exposure": {"mode": "auto"}})
    boosted = backend._apply_exposure(
        img, {"exposure": {"mode": "auto", "target_offset": 0.5}})
    assert float(boosted.mean()) > float(base.mean())
    assert boosted.mean() == pytest.approx(base.mean() * 2 ** 0.5, rel=1e-5)


def test_synthetic_backend_auto_zero_offset_and_numeric_mode_unchanged():
    """auto 无 target_offset 时无增益；数值 mode 手动 EV 行为保持。"""
    img = np.full((32, 32, 3), 0.2, dtype=np.float32)
    backend = SyntheticRenderBackend(img)
    same = backend._apply_exposure(img, {"exposure": {"mode": "auto"}})
    assert same.mean() == pytest.approx(img.mean(), rel=1e-6)
    manual = backend._apply_exposure(img, {"exposure": {"mode": 0.3}})
    assert manual.mean() == pytest.approx(img.mean() * 2 ** 0.3, rel=1e-5)
    # 非法 target_offset：不放大异常，图像原样返回
    bad = backend._apply_exposure(
        img, {"exposure": {"mode": "auto", "target_offset": "x"}})
    assert bad.mean() == pytest.approx(img.mean(), rel=1e-6)


def test_synthetic_backend_render_preview_auto_offset_brightens():
    """端到端：render_preview 消费 auto+target_offset 后亮度单调提升。"""
    img = np.full((48, 48, 3), 0.08, dtype=np.float32)
    backend = SyntheticRenderBackend(img)
    p0 = backend.render_preview({"exposure": {"mode": "auto"}}, long_edge=48)
    p1 = backend.render_preview(
        {"exposure": {"mode": "auto", "target_offset": 1.0}}, long_edge=48)
    assert float(p1.mean()) > float(p0.mean())
