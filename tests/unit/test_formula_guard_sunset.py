"""护栏④日落条款哨兵（t64）：configs/rules/*.yaml 全面盘点后的持续约束。

盘点结论（t64，程序化扫描全部 5 个规则文件 9 条活跃规则）：
- 迁移清单为空 —— clarity 首例(t60)之后不存在任何以 formula 表达的
  条件守卫；全部 condition 均为原生 metric/op/value 或 all(≥2 子件 AND)。
- 保留清单恰一项 —— exposure_rule_001 的 action.formula =
  "2.2 * log2(target / current)"，是曝光增量的算术计算（除法+对数），
  不属于区间/组合语义，all/between 无法表达，按日落条款③登记保留。

本文件把上述结论变成可持续约束：任何新写的 formula 条件守卫或带
比较逻辑的动作公式都会在此被 CI 拦下。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from pixo.decide.engine import load_rules

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs" / "rules"
MIRROR_DIR = ROOT / "src" / "pixo" / "decide" / "rules"

# 日落条款允许的动作公式形态：纯常量或已登记的纯算术（不得含比较/布尔守卫）
GUARD_TOKENS = (" if ", " and ", " or ", "<=", ">=", "==", "!=", "<", ">")


def _iter_rules() -> list[tuple[str, dict]]:
    out = []
    for fp in sorted(CONFIG_DIR.glob("*.yaml")):
        data = yaml.safe_load(fp.read_text(encoding="utf-8"))
        for r in (data if isinstance(data, list) else [data]):
            if isinstance(r, dict):
                out.append((fp.name, r))
    return out


def _flat_conditions(rule: dict) -> list[dict]:
    cond = rule.get("condition") or {}
    return [cond] + [c for c in (cond.get("all") or []) if c]


def test_no_condition_level_formula_guards() -> None:
    """任何规则的 condition（含 all 子件）都不得携带 formula 键。"""
    offenders = [
        (fname, r.get("rule_id"))
        for fname, r in _iter_rules()
        for c in _flat_conditions(r)
        if "formula" in c
    ]
    assert offenders == [], f"发现 formula 条件守卫，应迁移 all/between: {offenders}"


def test_no_conditional_logic_in_action_formulas() -> None:
    """动作公式只许常量或已登记纯算术；比较/布尔守卫一律拦截。"""
    offenders = [
        (fname, r.get("rule_id"), r["action"]["formula"])
        for fname, r in _iter_rules()
        if any(tok in str((r.get("action") or {}).get("formula", "")) for tok in GUARD_TOKENS)
    ]
    assert offenders == [], f"动作公式含守卫逻辑，应迁原生条件: {offenders}"


def test_clarity_first_migration_stays_native() -> None:
    """首例迁移不回退：clarity 必须保持原生 all 三子件。"""
    rule = next(r for _, r in _iter_rules() if r.get("rule_id") == "clarity_flat_rule_031")
    subs = rule["condition"]["all"]
    assert len(subs) == 3 and all("formula" not in c for c in subs)


def test_exposure_arithmetic_is_registered_retention() -> None:
    """唯一在册保留项：曝光公式是纯算术（含除法），且不含任何守卫 token。"""
    rule = next(r for _, r in _iter_rules() if r.get("rule_id") == "exposure_rule_001")
    expr = rule["action"]["formula"]
    assert expr == "2.2 * log2(target / current)"
    assert "/" in expr and "log2" in expr          # 真算术，非区间守卫
    assert not any(tok in expr for tok in GUARD_TOKENS)


def test_all_packs_load_via_engine_and_mirrors_in_sync() -> None:
    """引擎可加载每个规则文件，且双镜像逐文件字节一致。"""
    names = sorted(p.name for p in CONFIG_DIR.glob("*.yaml"))
    assert names, "规则目录为空？"
    for name in names:
        load_rules(str(CONFIG_DIR / name))         # 引擎侧可解析
        cfg = (CONFIG_DIR / name).read_bytes().replace(b"", b"\r\n")
        mir = (MIRROR_DIR / name).read_bytes().replace(b"", b"\r\n")
        assert cfg == mir, name

