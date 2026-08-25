"""t44 —— 公式带通守卫护栏①③单测。

护栏①：load_rules 公式标识符 lint（严格/注册表/宽松三模式）；
护栏③：evaluate_rules no-op 计数可见（RuleResults.noop_count + item["noop"]）。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from pixo.decide.engine import (
    DecideError,
    evaluate_rules,
    load_rules,
    register_metric_keys,
    registered_metric_keys,
    reset_metric_keys,
)
from pixo.decide import (
    register_metric_keys as pkg_register,
    reset_metric_keys as pkg_reset,
)

TPL = """
rule_id: r1
condition:
  metric: contrast
  op: ">"
  value: 0.5
action:
  param: exposure_ev
  mode: delta
  formula: "__EXPR__"
"""


def _load_yaml(expr, **kw):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TPL.replace("__EXPR__", expr))
    try:
        return load_rules(path, **kw)
    finally:
        os.remove(path)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_metric_keys()
    yield
    reset_metric_keys()


def test_unknown_identifier_raises_at_load():
    """笔误指标名在加载期报 DecideError，而非运行期静默吞。"""
    with pytest.raises(DecideError) as exc_info:
        _load_yaml("haz_proxy * 0.5", metric_keys=["haze_proxy"])
    assert "haz_proxy" in str(exc_info.value)


def test_known_metric_and_builtin_pass():
    """合法指标 + 内置函数 + 运行时变量全部通过白名单。"""
    rules = _load_yaml(
        "min(haze_proxy, current) * 0.5 + param_current",
        metric_keys=["haze_proxy"],
    )
    assert len(rules) == 1


def test_registry_backed_strict_mode():
    """register_metric_keys 注册键宇宙后，无显式 metric_keys 也走严格模式。"""
    register_metric_keys({"tonal_range"})
    assert registered_metric_keys() == {"tonal_range"}
    assert len(_load_yaml("tonal_range * 2")) == 1

    with pytest.raises(DecideError):
        _load_yaml("tanal_range * 2")


def test_legacy_callers_stay_lenient_without_key_universe():
    """未提供任何键宇宙的旧调用方保持兼容，不做加载期报错。"""
    assert len(_load_yaml("some_future_metric + 1")) == 1


def test_direct_dict_source_also_linted():
    """dict 直传分支同样执行标识符校验。"""
    with pytest.raises(DecideError):
        load_rules(
            {"rule_id": "d", "action": {"formula": "bad_name*2"}},
            metric_keys=["x"],
        )
    ok = load_rules(
        {"rule_id": "d", "action": {"formula": "x * 2"}}, metric_keys=["x"]
    )
    assert len(ok) == 1


def test_package_level_reexport():
    """decide 包出口转发注册表 API（pkg_register 即 engine 同一实现）。"""
    pkg_register({"warmth_db"})
    assert "warmth_db" in registered_metric_keys()


def test_noop_formula_counted():
    """护栏③：公式返回 0.0 的建议标记 noop 并聚合 noop_count。"""
    metrics = {"contrast": 0.9}
    params = {"exposure_ev": 0.2}
    results = evaluate_rules(
        _load_yaml("current * 0", metric_keys=["contrast"]),
        metrics,
        params=params,
    )
    assert isinstance(results, list)  # 向后兼容
    assert len(results) == 1
    assert results[0]["noop"] is True
    assert results.noop_count == 1


def test_nonzero_formula_not_noop():
    """正常公式不计 no-op；非公式规则不参与该统计。"""
    metrics = {"contrast": 0.9}
    params = {"exposure_ev": 0.2}

    results = evaluate_rules(
        _load_yaml("current + 0.3", metric_keys=["contrast"]),
        metrics,
        params=params,
    )
    assert results[0]["noop"] is False
    assert results.noop_count == 0

    set_rules = load_rules(
        {
            "rule_id": "s",
            "condition": {"metric": "contrast", "op": ">", "value": 0.5},
            "action": {"param": "saturation", "mode": "set", "value": 0},
        }
    )
    res_set = evaluate_rules(set_rules, metrics, params=params)
    assert res_set[0]["noop"] is False
    assert res_set.noop_count == 0


def test_mixed_results_aggregate_count():
    """多规则混合时只统计公式为 0.0 的子集。"""
    rules = [
        {
            "rule_id": "hit_noop",
            "condition": {"metric": "contrast", "op": ">", "value": 0.5},
            "action": {"param": "a_param", "mode": "delta", "formula": "current * 0"},
        },
        {
            "rule_id": "hit_real",
            "condition": {"metric": "contrast", "op": ">", "value": 0.5},
            "action": {"param": "b_param", "mode": "delta", "formula": "current + 0.4"},
        },
    ]
    loaded = load_rules(rules, metric_keys=["contrast"])
    results = evaluate_rules(
        loaded, {"contrast": 0.9}, params={"a_param": 0.1, "b_param": 0.1}
    )
    flags = {r["rule_id"]: r["noop"] for r in results}
    assert flags == {"hit_noop": True, "hit_real": False}
    assert results.noop_count == 1
