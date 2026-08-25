"""pixo.know.graph —— 简单知识图谱（结构化硬知识）。

节点/边均为 JSON 友好 dict；支持从 JSON/YAML 文件加载。
默认内置四类知识链：
  - 场景 → 光场 → 策略
  - 风格 → 影调指纹 → 副作用
  - 色彩问题 → 修正动作 → 边界
  - 相机 → 噪点特性 → DCP/降噪
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

DEFAULT_GRAPH: dict[str, Any] = {
    "nodes": [
        {
            "id": "scene_portrait",
            "type": "scene",
            "label": "人像",
            "keywords": ["人像", "portrait", "person", "face"],
            "content": "人像场景优先关注肤色、眼神光、肤质与背景分离。",
        },
        {
            "id": "light_golden_hour",
            "type": "light",
            "label": "黄金时刻",
            "keywords": ["黄金时刻", "golden", "hour", "暖光", "黄昏"],
            "content": "黄金时刻色温偏暖、反差柔和，适合保留暖调高光与肤色光泽。",
        },
        {
            "id": "strategy_warm_skin",
            "type": "strategy",
            "label": "暖肤色策略",
            "keywords": ["肤色", "暖调", "skin", "warm"],
            "content": "人像+黄金时刻：可倾向暖白平衡，适当提升肤色饱和度并压低过亮高光。",
        },
        {
            "id": "style_kodak_portra",
            "type": "style",
            "label": "Kodak Portra 400",
            "keywords": ["kodak", "portra", "胶片", "柯达"],
            "content": "Kodak Portra 400 风格：肤色偏暖粉、天空偏青蓝、影调柔和、高光滚降。",
        },
        {
            "id": "tone_soft_low_contrast",
            "type": "tone",
            "label": "柔和低反差影调",
            "keywords": ["低反差", "柔和", "soft", "low", "contrast"],
            "content": "低反差影调通常伴随高光滚降更早、暗部更开放，需避免整体发灰。",
        },
        {
            "id": "side_effect_warm_highlights",
            "type": "side_effect",
            "label": "暖调高光副作用",
            "keywords": ["高光", "偏黄", "暖", "副作用"],
            "content": "强行拉暖肤色可能让高光/天空偏黄，需要分离色调或 HSL 修正。",
        },
        {
            "id": "issue_skin_green",
            "type": "color_issue",
            "label": "肤色偏绿",
            "keywords": ["肤色偏绿", "green", "皮肤"],
            "content": "肤色偏绿时通常在 HSL 橙色相或分离色调中向品红/红方向补偿。",
        },
        {
            "id": "action_orange_shift",
            "type": "action",
            "label": "橙色相偏移",
            "keywords": ["橙色", "hue", "skin", "修正"],
            "content": "HS L 橙色相左移可将肤色从偏绿拉回暖粉，幅度需限制避免塑料感。",
        },
        {
            "id": "boundary_skin_b",
            "type": "boundary",
            "label": "肤色 b 边界",
            "keywords": ["肤色", "b", "边界", "limit"],
            "content": "肤色 b 建议控制在 16–22；超出时优先收敛而不是继续加暖。",
        },
        {
            "id": "camera_nikon_z6",
            "type": "camera",
            "label": "Nikon Z 6",
            "keywords": ["nikon", "z6", "尼康", "z 6"],
            "content": "Nikon Z 6 高 ISO 噪点偏彩色，建议 DCP 后适度降噪并保留纹理。",
        },
        {
            "id": "noise_iso3200",
            "type": "noise",
            "label": "ISO 3200 噪点",
            "keywords": ["iso", "3200", "噪点", "noise"],
            "content": "ISO 3200 噪声等级 medium，建议降噪强度约 35，避免过度涂抹。",
        },
        {
            "id": "dcp_nikon_z6",
            "type": "dcp",
            "label": "Nikon Z 6 DCP",
            "keywords": ["dcp", "z6", "profile", "相机配置"],
            "content": "Nikon Z 6 推荐相机标准 DCP，并在高 ISO 时配合 35 级降噪。",
        },
    ],
    "edges": [
        {
            "id": "e_dg_portrait_golden",
            "from": "scene_portrait",
            "to": "light_golden_hour",
            "relation": "常见搭配",
            "weight": 0.8,
            "content": "人像常与黄金时刻组合，形成暖调低反差画面。",
        },
        {
            "id": "e_dg_golden_strategy",
            "from": "light_golden_hour",
            "to": "strategy_warm_skin",
            "relation": "策略",
            "weight": 0.9,
            "content": "黄金时刻人像可采用暖肤色策略。",
        },
        {
            "id": "e_dg_portra_tone",
            "from": "style_kodak_portra",
            "to": "tone_soft_low_contrast",
            "relation": "影调指纹",
            "weight": 0.85,
            "content": "Kodak Portra 400 的影调指纹为柔和低反差。",
        },
        {
            "id": "e_dg_tone_side",
            "from": "tone_soft_low_contrast",
            "to": "side_effect_warm_highlights",
            "relation": "副作用",
            "weight": 0.6,
            "content": "柔和低反差可能伴随高光偏黄，需注意平衡。",
        },
        {
            "id": "e_dg_issue_action",
            "from": "issue_skin_green",
            "to": "action_orange_shift",
            "relation": "修正动作",
            "weight": 0.9,
            "content": "肤色偏绿 → 橙色相偏移修正。",
        },
        {
            "id": "e_dg_action_boundary",
            "from": "action_orange_shift",
            "to": "boundary_skin_b",
            "relation": "边界",
            "weight": 0.7,
            "content": "橙色相偏移需限制肤色 b 不超过 22。",
        },
        {
            "id": "e_dg_camera_noise",
            "from": "camera_nikon_z6",
            "to": "noise_iso3200",
            "relation": "噪点特性",
            "weight": 0.8,
            "content": "Nikon Z 6 高 ISO 噪点特性 medium。",
        },
        {
            "id": "e_dg_noise_dcp",
            "from": "noise_iso3200",
            "to": "dcp_nikon_z6",
            "relation": "降噪/DCP",
            "weight": 0.75,
            "content": "ISO 3200 时配合相机标准 DCP 与 35 级降噪。",
        },
    ],
}


def _tokenize(text: str) -> list[str]:
    """简单分词：英文单词 + 中文连续短语，用于图谱关键词匹配。"""
    text = (text or "").lower()
    ascii_words = re.findall(r"[a-z0-9]+", text)
    chinese_phrases = re.findall(r"[\u4e00-\u9fff]+", text)
    return ascii_words + chinese_phrases


def _hit_score(text: str, query_tokens: list[str]) -> float:
    """基于 token 子串命中计算简单分数。"""
    haystack = (text or "").lower()
    score = 0.0
    for token in query_tokens:
        if len(token) == 1 and "\u4e00" <= token <= "\u9fff":
            if token in haystack:
                score += 0.2
        elif token and token in haystack:
            score += 1.0
    return score


class KnowledgeGraph:
    """进程内知识图谱。

    支持添加节点/边、JSON/YAML 导入，以及按关键词查询。
    """

    def __init__(
        self,
        nodes: Iterable[dict[str, Any]] | None = None,
        edges: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        for node in nodes or []:
            self.add_node(node)
        for edge in edges or []:
            self.add_edge(edge)

    def add_node(self, node: dict[str, Any] | str) -> dict[str, Any]:
        """添加节点；传入 str 时按 id 创建轻量节点。"""
        if isinstance(node, str):
            node = {"id": node, "type": "node", "label": node}
        node_id = str(node.get("id") or node.get("label") or "")
        if not node_id:
            raise ValueError("graph node 缺少 id/label")
        record = dict(node)
        record["id"] = node_id
        self.nodes[node_id] = record
        return record

    def add_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        """添加边。"""
        record = dict(edge)
        if "id" not in record:
            record["id"] = "e%d" % (len(self.edges) + 1)
        self.edges.append(record)
        return record

    def load(self, path: str | Path) -> "KnowledgeGraph":
        """从 JSON 或 YAML 文件加载。"""
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError("加载 YAML 图谱需要 PyYAML") from exc
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("图谱文件格式必须为 {nodes, edges}")
        self.nodes = {}
        self.edges = []
        for node in data.get("nodes") or []:
            self.add_node(node)
        for edge in data.get("edges") or []:
            self.add_edge(edge)
        return self

    def to_dict(self) -> dict[str, Any]:
        """导出节点/边为 JSON 友好 dict。"""
        return {
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges),
        }

    def query(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """按关键词查询节点与边，返回带置信度的知识条目。

        Returns:
            list[dict]: 每项含 source_type / confidence / knowledge_ref /
            content / title / metadata。
        """
        tokens = _tokenize(query)
        if not tokens:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []

        for node in self.nodes.values():
            text = " ".join([
                str(node.get("label", "")),
                str(node.get("content", "")),
                " ".join(str(k) for k in node.get("keywords") or []),
                str(node.get("type", "")),
            ])
            score = _hit_score(text, tokens)
            if score <= 0:
                continue
            scored.append((
                score,
                {
                    "source_type": "graph",
                    "source": "graph",
                    "confidence": round(min(0.95, 0.35 + score * 0.12), 4),
                    "knowledge_ref": self._node_ref(node["id"]),
                    "content": str(node.get("content") or node.get("label") or ""),
                    "title": str(node.get("label") or node["id"]),
                    "metadata": dict(node),
                },
            ))

        for edge in self.edges:
            source = self.nodes.get(str(edge.get("from")))
            target = self.nodes.get(str(edge.get("to")))
            text = " ".join([
                str(edge.get("relation", "")),
                str(edge.get("content", "")),
                str(source.get("label", "") if source else edge.get("from", "")),
                str(target.get("label", "") if target else edge.get("to", "")),
            ])
            score = _hit_score(text, tokens)
            if score <= 0:
                continue
            scored.append((
                score,
                {
                    "source_type": "graph",
                    "source": "graph",
                    "confidence": round(min(0.95, 0.30 + score * 0.10), 4),
                    "knowledge_ref": self._edge_ref(edge),
                    "content": str(edge.get("content") or edge.get("relation") or ""),
                    "title": f"{edge.get('from')} → {edge.get('to')}",
                    "metadata": dict(edge),
                },
            ))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:max_results]]

    @staticmethod
    def _node_ref(node_id: str) -> str:
        return f"graph:node:{node_id}"

    @staticmethod
    def _edge_ref(edge: dict[str, Any]) -> str:
        return f"graph:edge:{edge.get('id', 'unknown')}"


def load_default_graph() -> KnowledgeGraph:
    """加载内置默认图谱。"""
    return KnowledgeGraph(
        nodes=DEFAULT_GRAPH["nodes"],
        edges=DEFAULT_GRAPH["edges"],
    )


__all__ = [
    "KnowledgeGraph",
    "DEFAULT_GRAPH",
    "load_default_graph",
]
