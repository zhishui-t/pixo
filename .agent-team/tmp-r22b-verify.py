# R22 Wave1 收口 —— A10 镜像/日落护栏 手工核验探针（dev-1，一次性）
# 用法: python .agent-team/tmp-r22b-verify.py
from __future__ import annotations

import hashlib
from pathlib import Path

from pixo.decide.engine import (
    load_rules,
    register_metric_keys,
    registered_metric_keys,
    reset_metric_keys,
)
from pixo.decide.rules import DEFAULT_RULES, RULES_DIR
from pixo.pipeline.metrics import metric_universe

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs" / "rules"
SRC = RULES_DIR / "noise_rules.yaml"
CFG = CONFIG_DIR / "noise_rules.yaml"

print("[1] 镜像存在:", CFG.exists(), "| src:", SRC.exists())
print("[2] 字节数: src=%d cfg=%d | 相等=%s" % (SRC.stat().st_size, CFG.stat().st_size,
                                                SRC.read_bytes() == CFG.read_bytes()))
print("[3] sha256 src=%s" % hashlib.sha256(SRC.read_bytes()).hexdigest())
print("    sha256 cfg=%s" % hashlib.sha256(CFG.read_bytes()).hexdigest())

names = sorted(p.name for p in CONFIG_DIR.glob("*.yaml"))
print("[4] configs/rules/*.yaml 盘点 (n=%d): %s" % (len(names), names))
print("[5] noise_rules.yaml 已被日落护栏枚举:", "noise_rules.yaml" in names)
print("[6] 镜像全部为 src 侧同名文件:",
      all((RULES_DIR / n).exists() for n in names))

# 日落护栏两种模式都要能过：宽松（空注册表）与严格（loop 注册键宇宙后）
reset_metric_keys()
rules = load_rules(str(CFG))
print("[7] 宽松模式 load_rules(configs 镜像) -> n=%d, enabled=%s"
      % (len(rules), rules[0].get("enabled")))
register_metric_keys(metric_universe(("face", "sky", "plant")))
print("    严格模式注册集 n=%d（含 noise_ratio=%s）"
      % (len(registered_metric_keys()), "noise_ratio" in registered_metric_keys()))
rules_strict = load_rules(str(CFG))
print("[8] 严格模式 load_rules(configs 镜像) -> n=%d, rule_id=%s"
      % (len(rules_strict), rules_strict[0]["rule_id"]))

# 日落条款 GUARD_TOKENS 预检（与 test_formula_guard_sunset 同一口径）
GUARD_TOKENS = (" if ", " and ", " or ", "<=", ">=", "==", "!=", "<", ">")
expr = rules[0]["action"]["formula"]
print("[9] action.formula=%r" % expr)
print("    命中守卫 token:", [t for t in GUARD_TOKENS if t in expr] or "无")
print("[10] condition 无 formula 键:", "formula" not in rules[0]["condition"])
reset_metric_keys()

print("[11] DEFAULT_RULES n=%d -> %s"
      % (len(DEFAULT_RULES), [Path(p).name for p in DEFAULT_RULES]))
