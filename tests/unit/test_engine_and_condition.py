"""t59 —— 引擎原生 AND(condition.all) 与 between 条件单测。

覆盖：旧单条件行为逐位回归、all 双条件真/假两侧、between 含端点边界、
load_rules lint 对 all 子项未知指标在 strict 模式报错。
"""
from __future__ import annotations

import pytest

from pixo.decide.engine import (
    DecideError,
    _condition_met,
    evaluate_rules,
    load_rules,
)

METRICS = {"contrast": 0.9, "sharpness": 12.0}


def _rule(cond: dict) -> dict:
    return {
        "rule_id": "r1",
        "enabled": True,
        "condition": cond,
        "action": {"param": "exposure_ev", "mode": "delta",
                   "formula": "current + 0.1"},
    }


# ---- ① 旧单条件行为回归（逐位一致） ----


def test_legacy_single_condition_regression():
    cases = [
        ({"metric": "contrast", "op": ">", "value": 0.5}, True),
        ({"metric": "contrast", "op": "<", "value": 0.5}, False),
        ({"metric": "contrast", "op": "between", "value": [0.8, 1.0]}, True),
        ({"metric": "missing_metric", "op": ">", "value": 0}, False),
        ({"metric": "contrast", "op": "in", "value": [0.9, 1.0]}, True),
    ]
    for cond, expected in cases:
        assert _condition_met(cond, METRICS) is expected, cond
    # 缺失条件视为满足
    assert _condition_met(None, METRICS) is True
    assert _condition_met({}, METRICS) is True


def test_legacy_results_carry_no_matched_key():
    """向后兼容：非 all 型结果不得出现 matched 键。"""
    results = evaluate_rules(
        [_rule({"metric": "contrast", "op": ">", "value": 0.5})],
        METRICS,
        params={},
    )
    assert len(results) == 1
    assert "matched" not in results[0]


# ---- ② all 原生 AND ----


def test_all_dual_condition_true_side():
    results = evaluate_rules(
        [_rule({"all": [
            {"metric": "contrast", "op": ">", "value": 0.5},
            {"metric": "sharpness", "op": "between", "value": [10, 15]},
        ]})],
        METRICS,
        params={},
    )
    assert len(results) == 1
    matched = results[0]["matched"]
    assert len(matched) == 2
    assert all(d["passed"] for d in matched)
    assert {d["metric"] for d in matched} == {"contrast", "sharpness"}


def test_all_dual_condition_false_side():
    results = evaluate_rules(
        [_rule({"all": [
            {"metric": "contrast", "op": ">", "value": 0.5},
            {"metric": "sharpness", "op": "<", "value": 5},
        ]})],
        METRICS,
        params={},
    )
    assert results == []


def test_all_requires_at_least_two_subconditions():
    with pytest.raises(DecideError):
        evaluate_rules(
            [_rule({"all": [{"metric": "contrast", "op": ">", "value": 0.5}]})],
            METRICS,
            params={},
        )


# ---- ③ between 含端点边界（独立使用） ----


@pytest.mark.parametrize("mv,expected", [
    (0.2, True),   # 下端点含
    (0.8, True),   # 上端点含
    (0.19, False),
    (0.81, False),
])
def test_between_inclusive_endpoints(mv, expected):
    assert (
        _condition_met({"metric": "contrast", "op": "between",
                        "value": [0.2, 0.8]}, {"contrast": mv})
        is expected
    )


# ---- ④ lint 同步覆盖 all 子项指标名 ----


def test_lint_flags_unknown_metric_inside_all():
    with pytest.raises(DecideError) as exc_info:
        load_rules(
            {
                "rule_id": "lint_bad",
                "condition": {"all": [
                    {"metric": "haz_typo", "op": ">", "value": 0.1},
                    {"metric": "c2", "op": "<", "value": 9},
                ]},
                "action": {"param": "p", "mode": "delta",
                           "formula": "current * 1"},
            },
            metric_keys=["c2"],
        )
    assert "haz_typo" in str(exc_info.value)


def test_lint_passes_known_metrics_inside_all():
    rules = load_rules(
        {
            "rule_id": "lint_ok",
            "condition": {"all": [
                {"metric": "c1", "op": ">", "value": 0.1},
                {"metric": "c2", "op": "<", "value": 9},
            ]},
            "action": {"param": "p", "mode": "delta",
                       "formula": "current * 1"},
        },
        metric_keys=["c1", "c2"],
    )
    assert len(rules) == 1
