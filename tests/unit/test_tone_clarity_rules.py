"""tone_clarity_rules 阈值重推验证 + 带通守卫双分支单测 (t42)。

阈值来源: docs/metrics/proxy_distribution.md (t41, 12 样张实测分布)。
护栏② (t40 裁定): 公式带通守卫必须真/假两侧路径均有用例并钉死边界 ——
t40 的 tonal_range<=0.35 恒假漏网正因缺假侧断言。
"""
from __future__ import annotations

import pytest

from pixo.decide.engine import evaluate_rules, load_rules
from pixo.decide.rules import DEFAULT_RULES

# 分布表分位数 (docs/metrics/proxy_distribution.md)
HAZE_P25, HAZE_P50, HAZE_P75 = 0.1202, 0.1633, 0.2260
TONAL_P25, TONAL_P50 = 0.4636, 0.5218
DEHAZE_LINE = 0.22      # p75 取整
CLARITY_ENTRY = 0.12    # p25 取整
TONAL_GUARD = 0.46      # p25 取整


@pytest.fixture(scope="module")
def tone_rules():
    rules = {}
    for p in DEFAULT_RULES:
        for r in load_rules(str(p)):
            rules[r["rule_id"]] = r
    assert {"dehaze_rule_030", "clarity_flat_rule_031"} <= set(rules)
    return rules


def _eval(tone_rules, metrics, params):
    out = evaluate_rules(list(tone_rules.values()), metrics, params=dict(params))
    return {x["param"]: x for x in out}


def test_thresholds_come_from_distribution(tone_rules):
    """yaml 阈值必须与分布表引用值一致 (防手滑改数)。t60 起 all 原生形态。"""
    assert tone_rules["dehaze_rule_030"]["condition"]["value"] == DEHAZE_LINE
    subs = tone_rules["clarity_flat_rule_031"]["condition"]["all"]
    got = {(s["metric"], s["op"], s["value"]) for s in subs}
    assert got == {
        ("haze_proxy", "gte", CLARITY_ENTRY),
        ("haze_proxy", "lt", DEHAZE_LINE),
        ("tonal_range", "le", TONAL_GUARD),
    }
    assert tone_rules["clarity_flat_rule_031"]["action"]["formula"] == "0.04"


@pytest.mark.parametrize("haze", [0.2226, 0.2258, 0.2267, 0.2445, 0.2477])
def test_dehaze_fires_on_hazy_cluster(tone_rules, haze):
    """浓雾簇样张值 (0352/5238/5239/0353/5237) 全触发, 正向且上钳。"""
    res = _eval(tone_rules, {"haze_proxy": haze}, {"dehaze.strength": 0.20})
    v = res["dehaze.strength"]["value"]
    assert 0.20 < v <= 0.45


def test_p50_composite_does_not_fire(tone_rules):
    """p50 复合向量 (haze=p50, tonal=p50) 不触发 dehaze/clarity。"""
    res = _eval(tone_rules,
                {"haze_proxy": HAZE_P50, "tonal_range": TONAL_P50},
                {"dehaze.strength": 0.10, "clarity.strength": 0.15})
    # t60 迁移后原生 all 整条不命中 -> 无条目(旧公式守卫时代的
    # no-op 留痕条目随日落条款消失, 属预期演进)
    assert "dehaze.strength" not in res
    assert "clarity.strength" not in res


def test_clarity_guard_true_path_fires(tone_rules):
    res = _eval(tone_rules,
                {"haze_proxy": 0.15, "tonal_range": 0.40},
                {"clarity.strength": 0.12})
    assert abs(res["clarity.strength"]["value"] - 0.16) < 1e-9


@pytest.mark.parametrize("metrics", [
    {"haze_proxy": 0.25, "tonal_range": 0.40},   # 重雾越上界 -> 让位 dehaze
    {"haze_proxy": 0.15, "tonal_range": 0.60},   # 高对比不平 -> 不加清晰度
    {"haze_proxy": 0.30, "tonal_range": 0.60},   # 双越界
])
def test_clarity_guard_false_paths_are_exact_noop(tone_rules, metrics):
    cur = 0.18
    res = _eval(tone_rules, metrics, {"clarity.strength": cur})
    # t60 迁移后：守卫假 = all 条件不命中 = 直接无条目(不再有留痕条目)
    assert "clarity.strength" not in res


@pytest.mark.parametrize("haze,tonal,fires", [
    (DEHAZE_LINE, TONAL_GUARD, False),   # 上界开区间: 恰等于线让位 dehaze
    (CLARITY_ENTRY, TONAL_GUARD, True),  # 入口闭区间: 恰等于 p25 即入带
])
def test_clarity_band_boundaries(tone_rules, haze, tonal, fires):
    cur = 0.14
    res = _eval(tone_rules,
                {"haze_proxy": haze, "tonal_range": tonal},
                {"clarity.strength": cur})
    if fires:
        assert abs(res["clarity.strength"]["value"] - (cur + 0.04)) < 1e-9
    else:
        assert "clarity.strength" not in res


def test_missing_metrics_stay_silent(tone_rules):
    assert _eval(tone_rules, {}, {}) == {}
