"""Regression tests for exposure param flatten/apply mapping in the loop."""
from pixo.pipeline.loop import _apply_decide_params, _flatten_decide_params


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
