"""t48 know.context.format_for_prompt 单测：格式化/去重/截断/空结果。"""
from __future__ import annotations

from pixo.know.context import MAX_CHARS, format_for_prompt


def _item(label, content, conf, ref="r"):
    return {"source_type": "graph", "confidence": conf,
            "knowledge_ref": ref, "content": content, "title": label}


def test_multi_result_formatting():
    """多结果: 每条 '[label] content (conf=0.xx)' 且按 confidence 降序。"""
    res = {"items": [_item("甲规则", "内容一", 0.6),
                     _item("乙规则", "内容二", 0.9)]}
    out = format_for_prompt(res)
    lines = out.split("\n")
    assert len(lines) == 2
    assert lines[0] == "[乙规则] 内容二 (conf=0.90)"
    assert lines[1] == "[甲规则] 内容一 (conf=0.60)"


def test_dedup_by_content():
    """去重: content 相同仅保留 confidence 最高的一条。"""
    res = {"items": [_item("A", "相同内容文本", 0.5, "r1"),
                     _item("B", "相同内容文本", 0.8, "r2"),
                     _item("C", "不同内容文本", 0.4, "r3")]}
    out = format_for_prompt(res)
    lines = [l for l in out.split("\n") if l]
    assert len(lines) == 2
    assert lines[0].startswith("[B]") and "相同内容文本" in lines[0]
    assert any("不同内容文本" in l for l in lines)


def test_truncate_top5_and_total_length():
    """截断: 只保留 top5；超长总段被钳到 ≤1200 字符。"""
    items = [_item(f"规则{i}", f"独特内容编号{i}", 0.10 * i) for i in range(8)]
    out = format_for_prompt({"items": items})
    assert len(out.split("\n")) == 5
    assert "独特内容编号7" in out          # 最高置信在列
    assert "独特内容编号0" not in out      # 最低置信被截
    huge = _item("巨条", "很长" * 1500, 0.99)
    out2 = format_for_prompt({"items": [_item("次", "短内容", 0.5), huge]})
    assert len(out2) <= MAX_CHARS


def test_empty_results():
    """空结果: {} / items=[] / None 一律返回空串。"""
    assert format_for_prompt({}) == ""
    assert format_for_prompt({"items": []}) == ""
    assert format_for_prompt(None) == ""
