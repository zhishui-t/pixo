"""pixo.decide —— 量化决策规则引擎。

公共 API:
  - decide / evaluate_rules / resolve_conflicts / apply_rules
  - check_termination / qc_rollback / load_rules
  - RuleEngine / DecideError / FormulaError
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
