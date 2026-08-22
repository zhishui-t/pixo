"""pixo.know.rag —— 轻量混合检索（关键词 + 简单 BM25 风格打分）。

不引入重型向量库；本地文档/案例以 JSON 或 Python dict 形式载入，
按标题/正文/标签关键词做词频与覆盖度打分，返回来源文本与置信度。
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

DEFAULT_RAG_DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "rag_golden_hour_portrait",
        "title": "黄金时刻人像修图经验",
        "content": "黄金时刻人像建议保留暖色高光，肤色可略偏暖粉；"
                   "若高光过亮优先压高光而不是整体降曝光。",
        "tags": ["人像", "黄金时刻", "高光", "肤色", "portrait", "golden"],
        "source": "builtin_cases",
    },
    {
        "id": "rag_iso3200_nikon",
        "title": "Nikon Z 6 ISO 3200 降噪案例",
        "content": "Nikon Z 6 在 ISO 3200 下彩色噪点明显，推荐 DCP 之后使用"
                   "约 35 强度降噪，并保留眼睛/发丝细节。",
        "tags": ["nikon", "z6", "iso", "3200", "降噪", "noise"],
        "source": "builtin_camera_notes",
    },
    {
        "id": "rag_backlight_skin",
        "title": "逆光人像肤色偏黄修正",
        "content": "逆光人像易出现肤色偏黄；可在 HSL 橙色相中略向红偏移，"
                   "同时限制肤色 b 不超过 22，避免塑料感。",
        "tags": ["逆光", "肤色", "偏黄", "hsl", "橙色", "backlight"],
        "source": "builtin_cases",
    },
    {
        "id": "rag_portra_style",
        "title": "Kodak Portra 400 风格模拟要点",
        "content": "Kodak Portra 400 风格：低反差、高光软滚降、肤色暖粉、"
                   "天空偏青蓝；适合婚礼/户外人像。",
        "tags": ["kodak", "portra", "风格", "胶片", "人像"],
        "source": "builtin_style",
    },
    {
        "id": "rag_overcast_flat",
        "title": "阴天画面发灰修正",
        "content": "阴天平光容易发灰，可适当增加对比度与清晰度，"
                   "再轻微提升饱和度，避免天空死白。",
        "tags": ["阴天", "发灰", "对比度", "清晰度", "overcast"],
        "source": "builtin_cases",
    },
]


def _tokenize(text: str) -> list[str]:
    """英文小写词 + 中文连续短语。"""
    text = (text or "").lower()
    ascii_words = re.findall(r"[a-z0-9]+", text)
    chinese_phrases = re.findall(r"[\u4e00-\u9fff]+", text)
    return ascii_words + chinese_phrases


def _field_text(doc: dict[str, Any]) -> str:
    """把文档可检索字段拼接成文本。"""
    return " ".join([
        str(doc.get("title", "")),
        str(doc.get("content", "")),
        " ".join(str(t) for t in doc.get("tags") or []),
    ])


class RagIndex:
    """轻量本地知识文档索引。"""

    def __init__(
        self,
        documents: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        self.documents: list[dict[str, Any]] = []
        for doc in documents or []:
            self.add_document(doc)

    def add_document(self, doc: dict[str, Any]) -> None:
        """添加一篇文档。"""
        record = dict(doc)
        if "id" not in record:
            record["id"] = "rag_doc_%d" % (len(self.documents) + 1)
        self.documents.append(record)

    def load_json(self, path: str | Path) -> "RagIndex":
        """从 JSON 文件加载文档列表。"""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            items = data.get("documents") or data.get("docs")
            if items is None and "id" in data:
                items = [data]
            else:
                items = items or []
        else:
            items = data
        for doc in items:
            self.add_document(doc)
        return self

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """关键词检索，返回 {source_type, confidence, knowledge_ref, content}。"""
        query = (query or "").strip()
        if not query:
            return []
        query_terms = _tokenize(query)
        if not query_terms:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            haystack = _field_text(doc).lower()
            doc_terms = _tokenize(haystack)
            term_freq = {
                term: doc_terms.count(term)
                for term in doc_terms
            }

            score = 0.0
            overlap = 0
            for term in query_terms:
                if term in haystack:
                    overlap += 1
                    tf = term_freq.get(term, 0) or 1
                    score += 1.0 + math.log1p(tf)
            if overlap == 0:
                continue
            # 覆盖率权重：查询词命中比例越高越可信。
            coverage = overlap / len(query_terms)
            score = score * (0.6 + 0.4 * coverage)
            confidence = min(0.95, 0.25 + score * 0.12)

            scored.append((
                score,
                {
                    "source_type": "rag",
                    "confidence": round(confidence, 4),
                    "knowledge_ref": f"rag:{doc.get('id', 'unknown')}",
                    "content": str(doc.get("content", "")),
                    "title": str(doc.get("title", "")),
                    "source": str(doc.get("source", "builtin")),
                    "metadata": dict(doc),
                },
            ))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]


def load_default_rag() -> RagIndex:
    """加载内置知识文档。"""
    return RagIndex(DEFAULT_RAG_DOCUMENTS)


__all__ = [
    "RagIndex",
    "DEFAULT_RAG_DOCUMENTS",
    "load_default_rag",
]
