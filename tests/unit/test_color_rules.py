"""t43：色彩规则阈值按 t41 实测分布重推后的双分支门禁。

数据源 docs/metrics/proxy_distribution.md（12 样本）：
  colorfulness_proxy min 3.39 / p25 4.7795 / p75 6.1292 / max 11.21。
护栏②（t40 复盘）：每条规则触发/不触发两侧都必须有断言，
并锁死指标归一域——阈值必须落在实测语料 [min, max] 之内。
"""
from __future__ import annotations

import pytest

from pixo.decide.engine import evaluate_rules, load_rules
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules(str(ROOT / "configs" / "rules" / "color_rules.yaml"))

# 12 样本实测 colorfulness（t41 分布表，样本名 -> 值）
CORPUS = {
    "DSC_5236": 5.86, "DSC_5237": 5.66, "DSC_5238": 6.16, "DSC_5239": 6.12,
    "DSC_6006": 3.39, "DSC_6007": 3.40, "DSC_0352": 5.19, "DSC_0353": 6.75,
    "DSC_0354": 4.51, "DSC_0355": 11.21, "DSC_0606": 4.87, "DSC_0607": 4.96,
}
VIB_THR = 4.78   # p25
SAT_THR = 6.13   # p75


def _fire(metric_value: float) -> list[str]:
    return [r["rule_id"] for r in evaluate_rules(RULES, {"colorfulness_proxy": metric_value})]


def test_thresholds_inside_corpus_domain() -> None:
    """域回归断言：阈值必须落在实测语料值域内（防归一口径回退成死码）。"""
    lo, hi = min(CORPUS.values()), max(CORPUS.values())
    assert lo < VIB_THR < hi and lo < SAT_THR < hi


def test_vibrance_low_both_branches() -> None:
    """触发侧给 vibrance 且 clamp 生效；不触发侧静默。"""
    fired = _fire(3.39)
    assert fired == ["vibrance_low_rule"]
    val = evaluate_rules(RULES, {"colorfulness_proxy": 3.39})[0]["value"]
    assert 0.15 <= val <= 0.4
    assert _fire(VIB_THR) == ["vibrance_low_rule"]          # le 含边界
    assert _fire(VIB_THR + 0.01) == []                       # 紧邻上侧不触发


def test_saturation_high_both_branches() -> None:
    """触发侧负向 saturation 且 clamp 生效；不触发侧静默。"""
    fired = _fire(11.21)
    assert fired == ["saturation_high_rule"]
    val = evaluate_rules(RULES, {"colorfulness_proxy": 11.21})[0]["value"]
    assert -0.25 <= val <= -0.1
    assert _fire(SAT_THR) == ["saturation_high_rule"]        # ge 含边界
    assert _fire(SAT_THR - 0.01) == []                       # 紧邻下侧不触发


def test_middle_band_silent() -> None:
    """p25-p75 中间带六张实测样本对两条规则均静默。"""
    middle = {k: v for k, v in CORPUS.items() if VIB_THR < v < SAT_THR}
    assert len(middle) == 6
    for v in middle.values():
        assert _fire(v) == []


def test_full_corpus_distribution_gate() -> None:
    """12 样张逐一驱动：触发集与分布表严格一致、两规则互斥。"""
    for name, v in CORPUS.items():
        expect = []
        if v <= VIB_THR:
            expect.append("vibrance_low_rule")
        if v >= SAT_THR:
            expect.append("saturation_high_rule")
        assert _fire(v) == expect, (name, v)


def test_mirror_in_sync() -> None:
    """双镜像字节一致。"""
    a = (ROOT / "configs/rules/color_rules.yaml").read_bytes()
    b = (ROOT / "src/pixo/decide/rules/color_rules.yaml").read_bytes()
    assert a == b
