"""pixo.know —— Pixo 知识层 v1（混合知识库）。

包含:
  - graph.KnowledgeGraph: 结构化知识图谱（场景/光场/策略、风格/影调/副作用等）。
  - cards.StyleCard / load_style_cards / style_card_to_decide_rules: 风格卡片。
  - rag.RagIndex: 轻量关键词/RAG 检索。
  - query.hybrid_query: 图谱 + RAG 聚合查询。
  - registry.KnowledgeRegistry: 默认知识包加载/登记。
"""
from __future__ import annotations

from .cards import (
    DEFAULT_STYLE_CARDS,
    StyleCard,
    build_style_card_rules,
    load_style_card_dicts,
    load_style_cards,
    style_card_from_dict,
    style_card_to_decide_rules,
    style_card_to_dict,
)
from .graph import DEFAULT_GRAPH, KnowledgeGraph, load_default_graph
from .query import (
    build_agent_message,
    format_agent_message,
    hybrid_query,
)
from .rag import DEFAULT_RAG_DOCUMENTS, RagIndex, load_default_rag
from .registry import (
    KnowledgeRegistry,
    default_registry,
    load_default_registry,
    load_registry_from_files,
)

__all__ = [
    "KnowledgeGraph",
    "load_default_graph",
    "DEFAULT_GRAPH",
    "StyleCard",
    "load_style_cards",
    "load_style_card_dicts",
    "style_card_from_dict",
    "style_card_to_dict",
    "style_card_to_decide_rules",
    "build_style_card_rules",
    "DEFAULT_STYLE_CARDS",
    "RagIndex",
    "load_default_rag",
    "DEFAULT_RAG_DOCUMENTS",
    "hybrid_query",
    "format_agent_message",
    "build_agent_message",
    "KnowledgeRegistry",
    "default_registry",
    "load_default_registry",
    "load_registry_from_files",
]
