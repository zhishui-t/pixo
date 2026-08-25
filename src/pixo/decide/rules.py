"""兼容入口：``render.decide.rules`` / ``pixo.decide.rules``。

规则引擎核心实现位于 ``engine.py``；本模块仅做显式转发。
"""
from .engine import (
    FormulaError,
    DecideError,
    RuleEngine,
    apply_rules,
    apply_rules_detailed,
    check_termination,
    decide,
    evaluate_rules,
    load_rules,
    qc_rollback,
    resolve_conflicts,
    register_metric_keys,
    registered_metric_keys,
    reset_metric_keys,
)

__all__ = [
    "DecideError",
    "FormulaError",
    "RuleEngine",
    "decide",
    "evaluate_rules",
    "resolve_conflicts",
    "apply_rules",
    "apply_rules_detailed",
    "check_termination",
    "qc_rollback",
    "load_rules",
    "register_metric_keys",
    "registered_metric_keys",
    "reset_metric_keys",
]
