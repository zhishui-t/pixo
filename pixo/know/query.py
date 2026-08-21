"""pixo.know.query —— 混合查询：知识图谱 + RAG 聚合。

hybrid_query 返回：
  {
    "query": str,
    "items": [{source_type, confidence, knowledge_ref, content, ...}],
    "recommendation": str,
    "agent_output": str,
  }
"""
from __future__ import annotations

from typing import Any

from .graph import KnowledgeGraph, load_default_graph
from .rag import RagIndex, load_default_rag


def _merge_items(
    graph_items: list[dict[str, Any]],
    rag_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """合并图谱与 RAG 条目，按置信度降序；同一引用可标记 both。"""
    merged: dict[str, dict[str, Any]] = {}

    for item in graph_items:
        ref = item.get("knowledge_ref") or item.get("title")
        key = f"graph:{ref}"
        merged[key] = dict(item)
        merged[key]["source_type"] = "graph"

    for item in rag_items:
        ref = item.get("knowledge_ref") or item.get("title")
        # 若与图谱内容高度重合，提升为 both
        graph_key = None
        for key, exists in merged.items():
            if exists.get("content") == item.get("content"):
                graph_key = key
                break
        if graph_key is not None:
            merged[graph_key]["source_type"] = "both"
            merged[graph_key]["rag_confidence"] = item.get("confidence")
            merged[graph_key]["confidence"] = round(
                min(0.95, float(merged[graph_key].get("confidence", 0.0))
                    + float(item.get("confidence", 0.0)) / 2.0),
                4,
            )
        else:
            merged[f"rag:{ref}"] = dict(item)

    for item in merged.values():
        item.setdefault("source", item.get("source_type", "unknown"))
    items = sorted(
        merged.values(),
        key=lambda x: float(x.get("confidence", 0.0)),
        reverse=True,
    )
    return items


def _build_recommendation(items: list[dict[str, Any]]) -> str:
    """根据 top 条目构造一句话建议。"""
    if not items:
        return "没有找到足够相关知识，建议参考通用修图流程或人工复核。"
    top = items[0]
    content = str(top.get("content", ""))[:120]
    source = top.get("source_type", "unknown")
    ref = top.get("knowledge_ref", "")
    return f"综合建议（来源 {source} / {ref}）：{content}"


def _build_agent_message(
    query: str,
    items: list[dict[str, Any]],
) -> str:
    """生成给 Agent 的可读建议/解释。"""
    if not items:
        return f"关于“{query}”暂无高置信知识，建议走通用规则或人工复核。"
    lines = [f"关于“{query}”的知识建议："]
    for idx, item in enumerate(items[:3], start=1):
        source = item.get("source_type", "unknown")
        confidence = item.get("confidence", 0.0)
        content = str(item.get("content", ""))
        ref = item.get("knowledge_ref", "")
        lines.append(
            f"{idx}. [{source}] conf={confidence:.2f} {ref} — {content}"
        )
    return "\n".join(lines)


def format_agent_message(result: dict[str, Any]) -> str:
    """从 hybrid_query 结果生成 Agent 消息。"""
    return str(result.get("agent_output") or result.get("recommendation") or "")


def build_agent_message(
    query: str,
    items: list[dict[str, Any]] | None = None,
) -> str:
    """直接由 query/items 生成 Agent 消息。"""
    return _build_agent_message(query, items or [])


def hybrid_query(
    query: str,
    graph: KnowledgeGraph | None = None,
    rag: RagIndex | None = None,
    registry: Any | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """执行混合查询。

    Args:
        query: 查询文本，支持中文/英文关键词。
        graph: 知识图谱；缺省加载默认内置图谱。
        rag: RAG 索引；缺省加载默认内置文档。
        top_k: 每个来源最多返回条数。

    Returns:
        含 items / recommendation / agent_output 的 dict。
    """
    if registry is not None:
        graph = getattr(registry, "graph", graph)
        rag = getattr(registry, "rag", rag)
    if graph is None:
        graph = load_default_graph()
    if rag is None:
        rag = load_default_rag()

    graph_items = graph.query(query, max_results=top_k)
    rag_items = rag.search(query, top_k=top_k)
    items = _merge_items(graph_items, rag_items)
    recommendation = _build_recommendation(items)
    agent_output = _build_agent_message(query, items)

    return {
        "query": query,
        "items": items,
        "recommendation": recommendation,
        "agent_output": agent_output,
        "agent": agent_output,
        "suggestions": [str(item.get("content", "")) for item in items[:3]],
    }


__all__ = [
    "hybrid_query",
    "format_agent_message",
    "build_agent_message",
]
