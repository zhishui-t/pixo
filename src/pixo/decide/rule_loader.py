"""pixo.decide.rule_loader —— 规则加载兼容入口。"""
from __future__ import annotations

from .engine import RuleEngine, load_rules

__all__ = ["RuleEngine", "load_rules"]
