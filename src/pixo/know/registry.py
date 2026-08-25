"""pixo.know.registry —— 知识包加载/登记。

默认注册内置风格卡片、知识图谱与 RAG 文档；也支持外部注入。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .cards import (
    StyleCard,
    build_style_card_rules,
    load_style_cards,
    style_card_to_decide_rules,
)
from .graph import KnowledgeGraph, load_default_graph
from .query import hybrid_query
from .rag import RagIndex, load_default_rag



def _know_warn(msg: str) -> None:
    """坏包/脏数据告警；不抛错，保持坏包不致命。"""
    print("[pixo.know] warn:", msg)


def _knowledge_pack_dirs() -> list[Path]:
    """外部知识包目录：包内 data/ 与仓库 configs/knowledge/(cwd 相对)。"""
    dirs = [
        Path(__file__).resolve().parent / "data",
        Path.cwd() / "configs" / "knowledge",
    ]
    return [d for d in dirs if d.is_dir()]


def _merge_knowledge_packs(graph: KnowledgeGraph) -> KnowledgeGraph:
    """合并全部外部知识包(*.json) 到图谱。

    - 两阶段：先合并所有节点(first-wins 去重)，再追加所有边；
    - 节点缺 id / 重复 id：跳过并告警；
    - 边端点不在合并后节点集、或 edge id 与已有边重复：跳过该边并告警；
    - 解析失败的坏包直接跳过，均不抛错。
    """
    packs: list[tuple[Path, dict[str, Any]]] = []
    for pack_dir in _knowledge_pack_dirs():
        for pack_path in sorted(pack_dir.glob("*.json")):
            try:
                data = json.loads(pack_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _know_warn("%s: JSON 解析失败，整包跳过" % pack_path.name)
                continue
            if isinstance(data, dict):
                packs.append((pack_path, data))
            else:
                _know_warn("%s: 顶层不是 object，整包跳过" % pack_path.name)

    # 阶段一：节点 first-wins 合并
    for pack_path, data in packs:
        for node in data.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            if not node_id:
                _know_warn("%s: 节点缺 id，跳过 %s" % (pack_path.name, node))
                continue
            if node_id in graph.nodes:
                _know_warn(
                    "%s: 节点 id 重复，保留先到者: %s" % (pack_path.name, node_id)
                )
                continue
            graph.add_node(node)

    # 阶段二：校验后追加边（端点存在 + edge id 唯一）
    edge_ids = {str(e.get("id")) for e in graph.edges}
    for pack_path, data in packs:
        for edge in data.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            eid = str(edge.get("id") or "")
            src = str(edge.get("from") or "")
            dst = str(edge.get("to") or "")
            if src not in graph.nodes or dst not in graph.nodes:
                _know_warn(
                    "%s: 边 %s 端点不存在(%s -> %s)，跳过"
                    % (pack_path.name, eid or "<no-id>", src, dst)
                )
                continue
            if eid and eid in edge_ids:
                _know_warn("%s: 边 id 重复，跳过: %s" % (pack_path.name, eid))
                continue
            record = graph.add_edge(edge)
            edge_ids.add(str(record.get("id")))
    return graph


class KnowledgeRegistry:
    """Pixo Know 知识库注册表。"""

    def __init__(
        self,
        graph: KnowledgeGraph | None = None,
        style_cards: Iterable[StyleCard | Mapping[str, Any]] | None = None,
        rag: RagIndex | None = None,
    ) -> None:
        # 自动合并外部知识包（内置 data/ 与仓库 configs/knowledge/）。
        self.graph = _merge_knowledge_packs(graph or load_default_graph())
        self.style_cards: list[StyleCard] = list(
            load_style_cards(style_cards) if style_cards is not None else load_style_cards()
        )
        self.rag = rag or load_default_rag()

    # ---- 登记 ----
    def register_graph(self, graph: KnowledgeGraph) -> "KnowledgeRegistry":
        """登记/替换知识图谱。"""
        self.graph = graph
        return self

    def register_style_card(
        self,
        card: StyleCard | Mapping[str, Any],
    ) -> "KnowledgeRegistry":
        """新增一张风格卡片。"""
        self.style_cards.append(_as_style_card(card))
        return self

    def register_rag(self, rag: RagIndex) -> "KnowledgeRegistry":
        """登记/替换 RAG 索引。"""
        self.rag = rag
        return self

    def register_documents(
        self,
        documents: Iterable[Mapping[str, Any]],
    ) -> "KnowledgeRegistry":
        """批量追加 RAG 文档。"""
        if self.rag is None:
            self.rag = RagIndex()
        for doc in documents:
            self.rag.add_document(dict(doc))
        return self

    # ---- 查询 ----
    def query(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """混合查询（图谱 + RAG）。"""
        return hybrid_query(query, graph=self.graph, rag=self.rag, top_k=top_k)

    def suggest(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """alias of query。"""
        return self.query(query, top_k=top_k)

    def agent_suggestion(self, query: str, top_k: int = 5) -> str:
        """返回给 Agent 的纯文本建议。"""
        result = self.query(query, top_k=top_k)
        return str(result.get("agent_output", ""))

    # ---- Decide 对接 ----
    def to_decide_rules(self) -> list[dict[str, Any]]:
        """把全部风格卡片转成 Decide 规则（level=style_card）。"""
        return build_style_card_rules(self.style_cards)

    def to_decide_context(self) -> dict[str, Any]:
        """返回可并入 Decide context 的知识层输入。"""
        return {
            "style_cards": [c.to_dict() for c in self.style_cards],
            "knowledge_rules": self.to_decide_rules(),
        }


def _as_style_card(card: StyleCard | Mapping[str, Any]) -> StyleCard:
    """构造/兼容 StyleCard。"""
    if isinstance(card, StyleCard):
        return card
    from .cards import style_card_from_dict

    return style_card_from_dict(card)


def default_registry() -> KnowledgeRegistry:
    """创建加载全部默认知识的注册表。"""
    return KnowledgeRegistry()


def load_default_registry() -> KnowledgeRegistry:
    """创建默认注册表（别名）。"""
    return default_registry()


def load_registry_from_files(
    *,
    graph_path: str | Path | None = None,
    cards_path: str | Path | None = None,
    documents_path: str | Path | None = None,
) -> KnowledgeRegistry:
    """从外部 JSON 文件加载知识包。"""
    graph = KnowledgeGraph()
    if graph_path is not None:
        graph.load(graph_path)
    else:
        graph = load_default_graph()

    cards = load_style_cards(cards_path) if cards_path else load_style_cards()
    rag = RagIndex()
    if documents_path is not None:
        rag.load_json(documents_path)
    else:
        rag = load_default_rag()

    return KnowledgeRegistry(graph=graph, style_cards=cards, rag=rag)


__all__ = [
    "KnowledgeRegistry",
    "default_registry",
    "load_default_registry",
    "load_registry_from_files",
]
