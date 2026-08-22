"""Regression tests for exposure param flatten/apply mapping in the loop."""
from pixo.pipeline.loop import _apply_decide_params, _flatten_decide_params


def test_flatten_exposure_uses_canonical_alias_only():
    params = {"exposure": {"mode": -0.15}, "style": "portrait"}
    flat = _flatten_decide_params(params)
    assert flat["exposure_ev"] == -0.15
    # The stale duplicate alias must not be carried into Decide results.
    assert "Exposure" not in flat
    assert flat["style"] == "portrait"


def test_apply_decide_params_does_not_overwrite_with_stale_alias():
    params = {"exposure": {"mode": -0.15}}
    decided = {"exposure_ev": 0.5}
    out = _apply_decide_params(params, decided)
    assert out["exposure"]["mode"] == 0.5
