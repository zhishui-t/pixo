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
