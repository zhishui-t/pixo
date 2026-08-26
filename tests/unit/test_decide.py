"""P1-3 单元测试：Pixo Decide 规则引擎。

覆盖：
  - 基础规则公式求值
  - 优先级链 / 同参数冲突消歧
  - 参数锁定
  - step_decay 幂次衰减
  - 曝光方向限幅
  - 终止条件（目标达标 / 最大轮数 / 改善不足 / 不可靠 / 锁定转人工）
  - FINAL_QC 回退
"""
from __future__ import annotations

import pytest

from pixo.decide import (
    RuleEngine,
    apply_rules,
    check_termination,
    decide,
    evaluate_rules,
    qc_rollback,
)


# ---------------------------------------------------------------------------
# 基础求值
# ---------------------------------------------------------------------------

def test_basic_formula_rule_applies():
    rule = {
        "rule_id": "exposure_rule_001",
        "priority": 10,
        "condition": {"metric": "face_luminance", "op": "lt", "value": 110},
        "action": {
            "param": "exposure_ev",
            "formula": "2.2 * log2(target / current)",
            "clamp": [-0.5, 0.5],
            "step_decay": 0.5,
            "conflict_policy": "high_priority_wins",
        },
    }
    ctx = {
        "metrics": {"face_luminance": 95},
        "targets": {"face_luminance": 115},
        "params": {"exposure_ev": 0.0},
        "rules": [rule],
        "iteration": 1,
    }
    result = decide(ctx)
    assert result["decision"] == "adjust_and_continue"
    assert result["params"]["exposure_ev"] == pytest.approx(0.5, abs=1e-6)
    assert result["rule_ids"] == ["exposure_rule_001"]
    assert result["unreliable_regions"] == []


def test_condition_not_met_skips_rule():
    rule = {
        "rule_id": "r_skip",
        "condition": {"metric": "face_luminance", "op": "gt", "value": 200},
        "action": {"param": "exposure_ev", "value": 0.5},
    }
    result = decide({"metrics": {"face_luminance": 100}, "params": {}, "rules": [rule]})
    assert result["params"] == {}
    assert result["rule_ids"] == []


# ---------------------------------------------------------------------------
# 优先级 / 冲突 / 锁定
# ---------------------------------------------------------------------------

def test_same_param_high_priority_wins():
    rules = [
        {"rule_id": "low", "priority": 10, "action": {"param": "exposure_ev", "value": 0.8}},
        {"rule_id": "high", "priority": 20, "action": {"param": "exposure_ev", "value": 0.2}},
    ]
    ctx = {"rules": rules, "params": {"exposure_ev": 0.0}, "metrics": {}}
    result = decide(ctx)
    assert result["params"]["exposure_ev"] == pytest.approx(0.2)
    assert result["rule_ids"] == ["high"]


def test_different_params_both_apply():
    rules = [
        {"rule_id": "exposure", "priority": 10, "action": {"param": "exposure_ev", "value": 0.3}},
        {"rule_id": "highlight", "priority": 10, "action": {"param": "Highlights", "value": -20}},
    ]
    result = decide({"rules": rules, "params": {}, "metrics": {}})
    assert result["params"]["exposure_ev"] == pytest.approx(0.3)
    assert result["params"]["Highlights"] == pytest.approx(-20)
    assert set(result["rule_ids"]) == {"exposure", "highlight"}


def test_user_locked_param_skips_rule():
    rule = {"rule_id": "r", "priority": 100, "action": {"param": "exposure_ev", "value": 0.5}}
    result = decide({
        "rules": [rule],
        "params": {"exposure_ev": 0.2},
        "metrics": {},
        "locked_params": ["exposure_ev"],
    })
    assert result["params"]["exposure_ev"] == pytest.approx(0.2)
    assert result["rule_ids"] == []


# ---------------------------------------------------------------------------
# step_decay / 曝光限幅
# ---------------------------------------------------------------------------

def test_step_decay_applied_fraction():
    rule = {
        "rule_id": "step",
        "action": {"param": "exposure_ev", "value": 0.1, "mode": "delta", "step_decay": 0.5},
    }
    ctx = {"rules": [rule], "params": {"exposure_ev": 0.0}, "metrics": {}}
    ctx["iteration"] = 1
    result1 = decide(ctx)
    assert result1["params"]["exposure_ev"] == pytest.approx(0.1)
    ctx["iteration"] = 2
    result2 = decide(ctx)
    assert result2["params"]["exposure_ev"] == pytest.approx(0.05)


def test_exposure_limiter_blocks_positive():
    rule = {"rule_id": "up", "action": {"param": "exposure_ev", "value": 0.5}}
    result = decide({
        "rules": [rule],
        "params": {"exposure_ev": 0.0},
        "metrics": {},
        "preview_overflow_ratio": 0.03,
    })
    assert result["params"]["exposure_ev"] == pytest.approx(0.0)


def test_exposure_limiter_allows_negative():
    rule = {"rule_id": "down", "action": {"param": "exposure_ev", "value": -0.5}}
    result = decide({
        "rules": [rule],
        "params": {"exposure_ev": 0.0},
        "metrics": {},
        "preview_overflow_ratio": 0.03,
    })
    assert result["params"]["exposure_ev"] == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# 终止判断
# ---------------------------------------------------------------------------

def test_termination_targets_met():
    term = check_termination({
        "metrics": {"face_luminance": 115},
        "targets": {"face_luminance": 115},
    })
    assert term["should_stop"] is True
    assert term["decision"] == "stopped"
    assert term["reason_code"] == "targets_met"


def test_termination_max_iterations():
    # t107：达到最大轮数时不再继续，但当前轮参数须已计算（last_iteration）
    term = check_termination({"iteration": 3, "max_iterations": 3})
    assert term["should_stop"] is False
    assert term["decision"] == "adjust_and_continue"
    assert term["last_iteration"] is True
    assert term["reason_code"] == "max_iterations"
    # 未达最大轮数时无 last_iteration 标记
    term2 = check_termination({"iteration": 2, "max_iterations": 3})
    assert term2.get("last_iteration") is None


def test_termination_low_improvement():
    term = check_termination({
        "improvement_history": [0.05, 0.04],
        "improvement_threshold": 0.1,
    })
    assert term["should_stop"] is True
    assert term["reason_code"] == "low_improvement"


def test_termination_unreliable_manual():
    term = check_termination({"unreliable_regions": ["face"]})
    assert term["should_stop"] is True
    assert term["decision"] == "manual_review"
    assert term["reason_code"] == "unreliable"


def test_termination_user_locked_manual():
    term = check_termination({
        "metrics": {"face_luminance": 90},
        "targets": {"face_luminance": 115},
        "target_params": ["Exposure"],
        "locked_params": ["Exposure"],
    })
    assert term["should_stop"] is True
    assert term["decision"] == "manual_review"


# ---------------------------------------------------------------------------
# FINAL_QC 回退
# ---------------------------------------------------------------------------

def test_qc_rollback_applies():
    result = qc_rollback({
        "params": {"Exposure": 0.3},
        "qc_overflow_ratio": 0.04,
    })
    assert result["decision"] == "rollback"
    assert result["params"]["Exposure"] == pytest.approx(0.15)
    assert result["rule_ids"] == ["qc_rollback_rule"]


def test_qc_rollback_locked_manual():
    result = qc_rollback({
        "params": {"Exposure": 0.3},
        "qc_overflow_ratio": 0.04,
        "locked_params": ["Exposure"],
    })
    assert result["decision"] == "manual_review"


def test_qc_rollback_second_failure_manual():
    result = qc_rollback({
        "params": {"Exposure": 0.3},
        "qc_overflow_ratio": 0.04,
        "qc_rollback_count": 1,
    })
    assert result["decision"] == "manual_review"


# ---------------------------------------------------------------------------
# 规则引擎门面 / 工具函数
# ---------------------------------------------------------------------------

def test_rule_engine_facade():
    engine = RuleEngine([{"rule_id": "r", "action": {"param": "exposure_ev", "value": 0.2}}])
    result = engine.decide({"params": {}, "metrics": {}})
    assert result["params"]["exposure_ev"] == pytest.approx(0.2)


def test_evaluate_and_apply_helpers():
    rules = [{"rule_id": "r", "action": {"param": "exposure_ev", "value": 0.4}}]
    evaluated = evaluate_rules(rules, {}, params={})
    assert len(evaluated) == 1
    params = apply_rules(rules, {}, {})
    assert params["exposure_ev"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# t107 off-by-one 回归：max_iterations=1 时规则参数必须落地一次
# ---------------------------------------------------------------------------

def test_decide_max_iterations_one_still_applies_rules():
    """max_iterations=1：check_termination 不得截断当前轮规则计算。"""
    rule = {
        "rule_id": "brightness_rule",
        "priority": 10,
        "condition": {"metric": "mean_luminance", "op": "lt", "value": 120},
        "action": {"param": "tone.brightness", "op": "set", "value": 0.5},
    }
    ctx = {
        "metrics": {"mean_luminance": 90},
        "iteration": 1,
        "max_iterations": 1,
    }
    out = decide(ctx, [rule])
    # 参数必须被计算并返回（不被 should_stop 截断）
    assert out["decision"] == "adjust_and_continue"
    assert out["params"].get("tone.brightness") == 0.5


# ---------------------------------------------------------------------------
# last_iteration 死分支修复：decide() 透传 check_termination 的补充信息
# ---------------------------------------------------------------------------

def test_decide_passthrough_last_iteration_extra():
    """末轮 decide 输出须携带 last_iteration/reason_code/reason，否则
    loop 侧 decision.get("last_iteration") 恒 None，break 分支永不生效。"""
    out = decide({
        "metrics": {}, "params": {}, "iteration": 1, "max_iterations": 1,
    })
    assert out["decision"] == "adjust_and_continue"
    assert out["last_iteration"] is True
    assert out["reason_code"] == "max_iterations"
    assert "最大迭代轮数" in out["reason"]


def test_decide_midway_has_no_termination_extra_keys():
    """非末轮输出不得携带终止补充键（保持五键契约干净）。"""
    out = decide({
        "metrics": {}, "params": {}, "iteration": 1, "max_iterations": 3,
    })
    assert out.get("last_iteration") is None
    assert out.get("reason_code") is None
    assert out.get("reason") is None


def test_decide_stopped_carries_reason_and_code():
    """stopped 分支同样透传 reason/reason_code：loop break 时 stop_reason
    直接取 term 的 reason，而非落到通用兜底文案。"""
    out = decide({
        "metrics": {"face_luminance": 115},
        "targets": {"face_luminance": 115},
        "params": {},
    })
    assert out["decision"] == "stopped"
    assert out["reason_code"] == "targets_met"
    assert out["reason"] == "所有目标指标进入容差范围"


# ---------------------------------------------------------------------------
# low_improvement 解锁：停滞判定优先于轮数上限
# ---------------------------------------------------------------------------

def test_low_improvement_beats_max_iterations():
    """max_iterations 末轮若先命中 last_iteration，连续两轮低改善将永不
    触发——停滞判定必须排在轮数上限之前。"""
    term = check_termination({
        "iteration": 3,
        "max_iterations": 3,
        "improvement_history": [0.01, 0.01],
        "improvement_threshold": 0.1,
    })
    assert term["should_stop"] is True
    assert term["decision"] == "stopped"
    assert term["reason_code"] == "low_improvement"
    assert term.get("last_iteration") is None


def test_max_iterations_still_hits_without_stagnation():
    """无停滞历史时末轮仍走 last_iteration（t107 语义不回归）。"""
    term = check_termination({
        "iteration": 3,
        "max_iterations": 3,
        "improvement_history": [0.5, 0.4],
        "improvement_threshold": 0.1,
    })
    assert term["should_stop"] is False
    assert term["decision"] == "adjust_and_continue"
    assert term["last_iteration"] is True
