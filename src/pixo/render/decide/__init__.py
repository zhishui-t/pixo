"""Pixo Decide —— 量化决策规则引擎 (P1-3)。

当前放在 ``render.decide``，后续 P1-1 完成命名空间迁移后对应 ``pixo.decide``。
"""
from __future__ import annotations

from .engine import (
    DecideError,
    FormulaError,
    RuleEngine,
    apply_rules,
    apply_rules_detailed,
    check_termination,
    decide,
    evaluate_rules,
    load_rules,
    qc_rollback,
    resolve_conflicts,
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
]
