"""pixo.decide.rules —— 内置规则 YAML 镜像。

规则源文件同时维护在仓库顶层 ``configs/rules/``；本目录保存镜像副本，
便于安装后按包内路径加载。
"""
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent
DEFAULT_RULES = [
    RULES_DIR / "exposure_rule_001.yaml",
    RULES_DIR / "highlight_protect_rule_002.yaml",
]

__all__ = ["RULES_DIR", "DEFAULT_RULES"]
