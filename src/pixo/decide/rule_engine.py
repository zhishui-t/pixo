"""兼容入口：``render.decide.rule_engine`` / ``pixo.decide.rule_engine``。"""
from .engine import (
    DecideError,
    FormulaError,
    RuleEngine,
    decide,
    evaluate_rules,
    load_rules,
    resolve_conflicts,
)

__all__ = [
    "DecideError",
    "FormulaError",
    "RuleEngine",
    "decide",
    "evaluate_rules",
    "load_rules",
    "resolve_conflicts",
]
