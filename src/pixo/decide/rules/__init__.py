"""pixo.decide.rules —— 内置规则 YAML 镜像 + 引擎符号转发。

规则源文件同时维护在仓库顶层 ``configs/rules/``；本目录保存镜像副本，
便于安装后按包内路径加载。

历史上引擎符号 (load_rules/decide/...) 由同级 ``rules.py`` 转发，但
Python 导入系统中包 ``rules/`` 优先于同名模块 ``rules.py``，导致
``from pixo.decide.rules import load_rules`` ImportError（包遮蔽）。
修复：转发职责并入本 ``__init__.py``，``rules.py`` 已删除。
"""
from pathlib import Path

from ..engine import (
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

RULES_DIR = Path(__file__).resolve().parent
DEFAULT_RULES = [
    RULES_DIR / "exposure_rule_001.yaml",
    RULES_DIR / "highlight_protect_rule_002.yaml",
    RULES_DIR / "crop_suggest_rule_003.yaml",
    RULES_DIR / "tone_clarity_rules.yaml",
    RULES_DIR / "color_rules.yaml",
]

__all__ = [
    "RULES_DIR",
    "DEFAULT_RULES",
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
