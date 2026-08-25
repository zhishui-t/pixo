"""pixo.know.context —— 知识查询结果 -> LLM prompt 注入段格式器。

输入为 KnowledgeRegistry.query()/hybrid_query() 的返回 dict（items 是
graph/RAG 混合条目：source_type / confidence / knowledge_ref / title /
content）。format_for_prompt() 输出紧凑段落，每条一行
"[label] content (conf=0.xx)"：按 confidence 降序取 top5、按 content 去重、
总长 ≤1200 字符；空结果返回空串。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAX_ITEMS = 5
MAX_CHARS = 1200


def _norm_text(value: Any) -> str:
    """压空白取规范文本。"""
    return " ".join(str(value).split()) if value is not None else ""


def format_for_prompt(query_results: Mapping[str, Any] | None) -> str:
    """把查询结果 dict 格式化为紧凑 prompt 段落。

    - 排序: confidence 降序，截断 top5；
    - 去重: content 归一化（压空白、忽略大小写）后相同视为重复；
    - 限长: 总长 ≤MAX_CHARS，放不下的整行截断并以 … 收尾后停止；
    - 空/非法输入返回 ""。
    """
    if not isinstance(query_results, Mapping):
        return ""
    items = query_results.get("items") or []
    ranked = sorted(
        (it for it in items if isinstance(it, Mapping)),
        key=lambda it: float(it.get("confidence", 0.0) or 0.0),
        reverse=True,
    )
    seen: set[str] = set()
    lines: list[str] = []
    total = 0
    for item in ranked:
        if len(lines) >= MAX_ITEMS:
            break
        content = _norm_text(item.get("content"))
        if not content:
            continue
        dedup_key = content.lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        label = (_norm_text(item.get("label"))
                 or _norm_text(item.get("title"))
                 or _norm_text(item.get("knowledge_ref"))
                 or _norm_text(item.get("source_type"))
                 or "知识")
        try:
            conf = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        line = f"[{label}] {content} (conf={conf:.2f})"
        sep = 1 if lines else 0
        budget = MAX_CHARS - total - sep
        if budget <= 0:
            break
        if len(line) > budget:
            line = line[: max(budget - 1, 0)].rstrip() + "…"
        lines.append(line)
        total += sep + len(line)
    return "\n".join(lines)


__all__ = ["format_for_prompt", "MAX_ITEMS", "MAX_CHARS"]
