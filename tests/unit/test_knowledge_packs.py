"""知识库内容包单元测试：configs/knowledge/*.json。

覆盖：
  - 内容包可加载，节点含 id/type/label/keywords/content 五字段且 keywords>=3；
  - 节点 id 前缀与文件域一致（tone_/hue_/post2_/cap_|act_）；
  - KnowledgeRegistry 合并后图谱节点总数超过基线（默认图 ~13 + 内容包 ~50）；
  - 查询冒烟：中文关键词命中对应知识域节点。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixo.know import KnowledgeRegistry

ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "configs" / "knowledge"

# 文件 -> 该文件允许的节点 id 前缀域。
# hue 包除 hue_ 主域外还含动作(act_)/边界(bnd_)/策略(strat_)型节点；
# capture_post 基础包使用场景前缀 cap_ 与动作前缀 act_。
PACK_DOMAINS: dict[str, tuple[str, ...]] = {
    "photography_tone.json": ("tone_",),
    "photography_hue.json": ("hue_", "act_", "bnd_", "strat_"),
    "photography_post2.json": ("post2_",),
    "photography_capture_post.json": ("cap_", "act_"),
}

REQUIRED_NODE_FIELDS = ("id", "type", "label", "keywords", "content")


def _load_pack(filename: str) -> dict:
    path = PACK_DIR / filename
    assert path.is_file(), f"知识包缺失: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{filename} 顶层必须是对象"
    return data


@pytest.mark.parametrize("filename", sorted(PACK_DOMAINS))
def test_pack_nodes_schema(filename: str) -> None:
    """内容包可加载，每节点含五字段且 keywords>=3。"""
    data = _load_pack(filename)
    nodes = data.get("nodes")
    assert isinstance(nodes, list) and nodes, f"{filename} 缺少非空 nodes"
    for node in nodes:
        nid = node.get("id")
        assert isinstance(nid, str) and nid, f"{filename} 存在缺 id 的节点: {node}"
        for field in REQUIRED_NODE_FIELDS:
            assert field in node, f"{filename} 节点 {nid} 缺字段 {field}"
        keywords = node["keywords"]
        assert isinstance(keywords, list) and len(keywords) >= 3, (
            f"{filename} 节点 {nid} keywords 数量 < 3: {keywords}"
        )


@pytest.mark.parametrize("filename, prefixes", sorted(PACK_DOMAINS.items()))
def test_pack_id_prefix_matches_domain(filename: str, prefixes: tuple[str, ...]) -> None:
    """节点 id 前缀必须落在文件对应的知识域内。"""
    data = _load_pack(filename)
    for node in data["nodes"]:
        nid = str(node.get("id") or "")
        assert nid.startswith(prefixes), (
            f"{filename} 节点 id '{nid}' 不属于该文件域 {prefixes}"
        )


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch) -> KnowledgeRegistry:
    """默认注册表；cwd 不在仓库根时切回（configs/knowledge 相对 cwd 加载）。"""
    if not (Path.cwd() / "configs" / "knowledge").is_dir():
        monkeypatch.chdir(ROOT)
    return KnowledgeRegistry()


def test_registry_merges_packs_above_baseline(registry: KnowledgeRegistry) -> None:
    """合并默认图与全部内容包后，图谱节点总数应明显超过默认基线。"""
    total = len(registry.graph.nodes)
    assert total > 45, f"图谱节点总数 {total} 未超过基线 45（默认~13 + 三包~30+）"


def _hit_node_ids(registry: KnowledgeRegistry, query: str, top_k: int = 8) -> list[str]:
    """执行混合查询，返回命中条目里的图谱节点 id 列表。"""
    result = registry.query(query, top_k=top_k)
    ids: list[str] = []
    for item in result.get("items", []):
        ref = str(item.get("knowledge_ref") or "")
        if ref.startswith("graph:node:"):
            ids.append(ref.rsplit(":", 1)[-1])
    return ids


def test_query_night_brighten_hits_tone_domain(registry: KnowledgeRegistry) -> None:
    """「夜景 提亮」应命中影调(tone_)域节点。"""
    ids = _hit_node_ids(registry, "夜景 提亮")
    assert any(nid.startswith("tone_") for nid in ids), f"未命中 tone 域节点: {ids}"


def test_query_skin_green_hits_hue_or_action(registry: KnowledgeRegistry) -> None:
    """「肤色 偏绿」应命中色偏(hue_)或动作(action)类节点。"""
    result = registry.query("肤色 偏绿", top_k=8)
    hits: list[tuple[str, str]] = []
    for item in result.get("items", []):
        ref = str(item.get("knowledge_ref") or "")
        if ref.startswith("graph:node:"):
            meta = item.get("metadata") or {}
            hits.append((ref.rsplit(":", 1)[-1], str(meta.get("type") or "")))
    assert any(
        nid.startswith("hue_") or ntype == "action" for nid, ntype in hits
    ), f"未命中 hue/action 节点: {hits}"


def test_query_dehaze_hits_post2_or_capture_post(registry: KnowledgeRegistry) -> None:
    """「去雾」应命中后期二(post2_)或拍摄-后处理(cap_/act_)域节点。"""
    ids = _hit_node_ids(registry, "去雾")
    assert any(
        nid.startswith(("post2_", "cap_", "act_")) for nid in ids
    ), f"未命中 post2/capture_post 域节点: {ids}"
