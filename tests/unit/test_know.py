"""P2-6 单元测试：Pixo Know 混合知识库 v1。

覆盖：
  - 知识图谱查询；
  - 风格卡片加载与 schema；
  - RAG 命中/无命中；
  - hybrid_query 聚合/来源/置信度/Agent 输出；
  - 风格卡片规则进入 Decide 且不覆盖用户锁定/软偏好；
  - 默认知识注册表。
"""
from __future__ import annotations

import pytest

from pixo.know import (
    KnowledgeRegistry,
    RagIndex,
    default_registry,
    hybrid_query,
    load_default_graph,
    load_default_rag,
    load_style_cards,
    style_card_to_decide_rules,
)
from pixo.know.cards import build_style_card_rules
from pixo.decide import decide


def test_default_graph_query_hits_scene_and_strategy():
    """知识图谱能按中文关键词返回人像/黄金时刻策略。"""
    graph = load_default_graph()
    items = graph.query("黄金时刻 人像", max_results=5)

    assert items
    for item in items:
        assert item["source_type"] == "graph"
        assert "knowledge_ref" in item
        assert item["content"]
    refs = [i["knowledge_ref"] for i in items]
    assert any("strategy_warm_skin" in r for r in refs)
    # 置信度应在 0-1 之间
    assert all(0.0 <= float(i["confidence"]) <= 1.0 for i in items)


def test_style_cards_load_and_to_dict():
    """默认风格卡片可加载，字段符合 §10.2。"""
    cards = load_style_cards()
    assert len(cards) >= 2
    first = cards[0]
    assert first.style_id
    assert first.name
    assert isinstance(first.tags, dict)
    assert "recommended_adjustments" in first.to_dict()
    # dict 风格访问也支持
    assert first["style_id"] == first.style_id


def test_rag_search_hit_and_no_hit():
    """RAG 按关键词命中，无关联词返回空。"""
    rag = load_default_rag()
    hits = rag.search("ISO 3200 降噪")
    assert hits
    assert hits[0]["source_type"] == "rag"
    assert hits[0]["knowledge_ref"]
    assert hits[0]["content"]

    misses = rag.search("zzzzqqq_not_exist")
    assert misses == []


def test_hybrid_query_aggregates_and_ranks():
    """hybrid_query 聚合 graph+rag，带来源/置信度/建议/Agent 输出。"""
    result = hybrid_query("黄金时刻 人像", top_k=5)

    assert result["query"] == "黄金时刻 人像"
    assert result["items"]
    assert result["recommendation"]
    assert result["agent_output"]
    assert "黄金时刻" in result["agent_output"] or "建议" in result["agent_output"]

    for item in result["items"]:
        assert item["source_type"] in ("graph", "rag", "both")
        assert "confidence" in item
        assert "knowledge_ref" in item
        assert "content" in item

    confidences = [float(i["confidence"]) for i in result["items"]]
    assert confidences == sorted(confidences, reverse=True)


def test_style_card_to_decide_rules_has_style_priority():
    """风格卡片生成的规则使用 style_card 优先级。"""
    card = load_style_cards()[0]
    rules = style_card_to_decide_rules(card)
    assert rules
    for rule in rules:
        assert rule["level"] == "style_card"
        assert rule["source"] == "style_card"
        assert float(rule["priority"]) == 6000.0
        assert rule["rule_id"].startswith(card.style_id)


def test_style_card_rules_do_not_override_user_preference():
    """Decide 冲突时用户软偏好（9000）高于风格卡片（6000）。"""
    style_rule = {
        "rule_id": "style_exposure",
        "priority": 6000,
        "level": "style_card",
        "source": "style_card",
        "action": {"param": "exposure_ev", "value": 0.1},
    }
    user_rule = {
        "rule_id": "user_exposure",
        "priority": 9000,
        "level": "user_preference",
        "source": "user",
        "action": {"param": "exposure_ev", "value": -0.2},
    }
    result = decide({
        "rules": [style_rule, user_rule],
        "params": {"exposure_ev": 0.0},
        "metrics": {},
    })
    assert result["params"]["exposure_ev"] == pytest.approx(-0.2)


def test_style_card_rules_respect_user_locked_params():
    """用户锁定参数时风格卡片规则不得修改该参数。"""
    rules = style_card_to_decide_rules(load_style_cards()[0])
    locked_param = rules[0]["action"]["param"]
    result = decide({
        "rules": rules,
        "params": {locked_param: 1.0},
        "metrics": {},
        "locked_params": [locked_param],
    })
    assert result["params"][locked_param] == pytest.approx(1.0)


def test_decide_reads_style_cards_from_context():
    """Decide 可直接消费 context.style_cards，且锁定参数仍不被覆盖。"""
    from pixo.know import load_style_cards

    card_dict = load_style_cards()[0].to_dict()
    result = decide({
        "style_cards": [card_dict],
        "params": {"hue_orange_shift": 0.0},
        "metrics": {"skin_b": 25},
    })
    assert result["params"]["hue_orange_shift"] == pytest.approx(-3.0)
    assert "kodak_portra_400" in result["rule_ids"][0]

    locked = decide({
        "style_cards": [card_dict],
        "params": {"hue_orange_shift": 0.0},
        "metrics": {"skin_b": 25},
        "locked_params": ["hue_orange_shift"],
    })
    assert locked["params"]["hue_orange_shift"] == pytest.approx(0.0)
    assert locked["rule_ids"] == []


def test_default_registry_aggregates_components():
    """默认注册表同时持有图谱/卡片/RAG，并可输出 Decide 规则。"""
    reg = default_registry()
    assert len(reg.style_cards) >= 2
    assert len(reg.graph.nodes) >= 5
    assert len(reg.rag.documents) >= 3

    result = reg.query("Kodak Portra")
    assert result["items"]

    rules = reg.to_decide_rules()
    assert rules
    assert all(r["level"] == "style_card" for r in rules)

    agent_msg = reg.agent_suggestion("逆光人像")
    assert isinstance(agent_msg, str)
    assert agent_msg


def test_custom_rag_and_registry_merge():
    """自定义 RAG 文档可加入注册表并检索。"""
    rag = RagIndex([{
        "id": "custom_1",
        "title": "自定义案例",
        "content": "自定义内容：夜景灯光保留色彩层次。",
        "tags": ["夜景", "灯光"],
    }])
    reg = KnowledgeRegistry(
        graph=load_default_graph(),
        style_cards=load_style_cards(),
        rag=rag,
    )
    hits = reg.query("夜景 灯光", top_k=3)
    assert any("custom_1" in str(i["knowledge_ref"]) for i in hits["items"])
