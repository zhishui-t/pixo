"""agent.suggest —— LLM 参数建议编排（P3c）。

职责：组装上下文 → 加载双 prompts → 调 dsh.chat 索取参数补丁 JSON →
经 ``patch_protocol.review_patches`` 校验 → accepted 交调用方注入
``decide_context["llm_suggestions"]``（建议态，绝不直接改终态）、
rejected 连同回复全文交 trace。

安全边界：
- 默认关：由调用方（SinglePhotoLoop(agent_suggest=False)）控制开关。
- 环境未配置（PIXO_DSH_CHAT_URL/KEY/MODEL 任一缺失）且未显式注入
  chat_client 时，整链跳过返回 ``skipped_unconfigured``；
  显式注入 chat_client 视为 DI/测试通道，绕过环境门。
- 校验失败/JSON 解析失败一律降级为 rejected 分组，本模块永不抛错。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from .patch_protocol import review_patches
from .tools import _dsh_chat_config, _dsh_chat_real

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "is_dsh_chat_configured",
    "build_suggest_context",
    "load_system_prompt",
    "run_suggest",
]

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# patch 协议说明（内嵌进系统提示词；与 patch_protocol 校验器同源约束）
PATCH_SCHEMA_DOC = """## 参数补丁输出协议
只输出一个 JSON 数组，每个元素形如：
{"param": "<语义点路径如 tone.brightness>",
 "op": "set" | "delta",
 "value": <数值>,
 "reason": "<一句话依据>"}
约束：
- op=set 为绝对设定，op=delta 为相对步进；
- 用户锁定参数（locked）禁止出现；
- 不确定就不要输出该补丁；宁缺毋滥。
"""

FEW_SHOT_EXAMPLE = """## 示例
输入摘要: {"metrics": {"haze_proxy": 0.24, "mean_luminance": 96}}
正确输出:
```json
[{"param": "dehaze.strength", "op": "delta", "value": 0.06,
  "reason": "haze_proxy 高于浓雾门限"}]
```
"""


def is_dsh_chat_configured() -> bool:
    """DSH Chat 三要素（URL/KEY/MODEL）是否齐备。"""
    return _dsh_chat_config() is not None


# 系统提示词模块级缓存：{"stamp": ((路径, mtime_ns), ...), "value": str}
# 渲染迭代内每张照片都会拼 prompt，避免重复读盘（mtime 变化自动失效）
_SYSTEM_PROMPT_CACHE: dict[str, Any] = {}


def load_system_prompt() -> str:
    """system.md + tools.md + 补丁协议 + few-shot 拼接为系统段。

    结果模块级缓存，仅在 prompts 文件 mtime 变化时重建。
    """
    files = [_PROMPTS_DIR / name for name in ("system.md", "tools.md")]
    stamp = tuple(
        (str(p), p.stat().st_mtime_ns) if p.exists() else (str(p), None)
        for p in files
    )
    cached = _SYSTEM_PROMPT_CACHE.get("value")
    if cached is not None and _SYSTEM_PROMPT_CACHE.get("stamp") == stamp:
        return cached
    parts = [p.read_text(encoding="utf-8") for p in files if p.exists()]
    parts.append(PATCH_SCHEMA_DOC)
    parts.append(FEW_SHOT_EXAMPLE)
    text = chr(10).join(parts) + chr(10)
    _SYSTEM_PROMPT_CACHE["value"] = text
    _SYSTEM_PROMPT_CACHE["stamp"] = stamp
    return text


def _pick_metrics(measurement: Any) -> dict:
    """从 measurement 提取建议上下文关心的关键指标（缺则省）。"""
    if not isinstance(measurement, dict):
        return {}
    keys = (
        "mean_luminance", "face_luminance", "highlight_clip_ratio",
        "shadow_clip_ratio", "preview_highlight_clip_estimate",
        "haze_proxy", "colorfulness_proxy", "tonal_range",
        "contrast",
    )
    out = {}
    for k in keys:
        v = measurement.get(k)
        if isinstance(v, (int, float)):
            out[k] = v
    return out


def _knowledge_top(registry: Any, scene_query: str, top: int = 3):
    """KnowledgeRegistry().query 的防御式取 top-N 条目。"""
    if registry is None or not scene_query:
        return []
    try:
        res = registry.query(scene_query)
    except Exception as exc:            # 图谱查询失败：降级空列表不阻断
        _LOGGER.warning(
            "[pixo.agent.suggest] 知识图谱查询失败，降级空列表: %s", exc)
        return []
    items = res.get("items") if isinstance(res, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for it in items[:top]:
        if isinstance(it, dict):
            meta = it.get("metadata") or {}
            out.append({"id": meta.get("id"), "confidence": it.get("confidence")})
    return out


def build_suggest_context(
    measurement: Any,
    aesthetic_history: Any,
    scene_query: str = "",
    knowledge_registry: Any = None,
) -> dict[str, Any]:
    """①上下文组装：关键指标 + aesthetic 历史 + 知识图谱 top3。"""
    aesthetic = [float(v) for v in (aesthetic_history or [])
                 if isinstance(v, (int, float))]
    return {
        "metrics": _pick_metrics(measurement),
        "aesthetic_history": aesthetic,
        "knowledge_top3": _knowledge_top(knowledge_registry, scene_query),
    }


# 对抗性超长回复上限：超出直接放弃解析（防 O(n) 扫描被滥用为 CPU 消耗）
_EXTRACT_MAX_CHARS = 256 * 1024


def _looks_like_patch(obj: Any) -> bool:
    """元素形如补丁：dict 且带 'param' 键（其余字段交闸门完整校验）。"""
    return isinstance(obj, dict) and "param" in obj


def _extract_json_patches(text: Any, prompt: str | None = None) -> list | None:
    """从回复全文提取补丁 JSON 数组；容忍 ```json 围栏与前后闲话。

    - O(n)：``raw_decode(s, idx)`` 在候选起始位原地解析，无逐位子串复制；
    - 数组优先：扫描全部候选（'[' / '{' 起始位），取第一个「是 list 且
      元素形如补丁」的结果——模型先回显 dict 上下文再给数组时不会误判；
    - ``prompt`` 传入时先剥离回复中回显的提示词前缀：占位/降级路径的
      模型会把整段提示词原样回显，其中内嵌的 few-shot 示例与上下文
      JSON 会被误判为补丁（t107 回归）；剥离后只在回复正文里寻找；
    - 长度上限 256KB，超长回复直接放弃解析；
    - 找不到合格数组返回 None（调用方按全 rejected 处理）。
    """
    if not isinstance(text, str) or not text.strip():
        return None
    if len(text) > _EXTRACT_MAX_CHARS:
        _LOGGER.warning(
            "[pixo.agent.suggest] 回复超长(%d > %d 字符)，放弃补丁提取",
            len(text), _EXTRACT_MAX_CHARS)
        return None
    fence = chr(96) * 3                      # ``` 围栏剥离
    cleaned = text.replace(fence, "")
    if prompt:
        # 提示词回显剥离：占位/降级路径模型会回显整段提示词（常带
        # "已收到 DSH 消息: " 之类前缀）。prompt 与回复同样先剥离围栏
        # （few-shot 内含 ```json 围栏），再定位 prompt 全文出现处并
        # 剥离到其末尾，只在回复正文里寻找补丁；reply_text 保留完整回复。
        probe = prompt.replace(fence, "")
        pos = cleaned.find(probe)
        if pos >= 0:
            cleaned = cleaned[pos + len(probe):].lstrip()
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(cleaned):
        if ch not in "[{":
            continue
        try:
            obj, _end = decoder.raw_decode(cleaned, idx)
        except ValueError:
            continue
        if isinstance(obj, list) and any(_looks_like_patch(o) for o in obj):
            # 保留全部 dict 元素：形如补丁的进 accepted，畸形的交闸门
            # 给出明确 rejected 理由
            return [o for o in obj if isinstance(o, dict)]
        # 非补丁形数组 / dict：继续向后扫描（数组优先，见 docstring）
    return None


# ---- 同上下文指纹缓存（t53）：sha256(system+user) -> 响应，LRU 上限 8 ----
_SUGGEST_CACHE_MAX = 8
_SUGGEST_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
CACHE_STATS = {"hits": 0, "misses": 0}


def _cache_fingerprint(
    prompt: str,
    locked_params: Any = None,
    current_params: Any = None,
) -> str:
    """指纹 = system+user 全文 + locked/current 参数域（排序规范化序列化）。

    prompt 本身不含锁定集与现行参数——若指纹只取 prompt，锁定集不同的
    照片会命中彼此缓存，把按旧锁定集放行的 accepted 直接复用（t94 封堵）。
    """
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8"))
    try:
        locked = sorted(str(k) for k in (locked_params or []))
        extra = json.dumps({"locked": locked, "current": current_params or {}},
                           sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):       # 不可序列化的极端入参：repr 兜底
        extra = repr((locked_params, current_params))
    h.update(extra.encode("utf-8"))
    return h.hexdigest()


def _cache_get(fingerprint: str):
    """命中返回响应副本并置 cache_hit；未命中记 miss 返回 None。"""
    if fingerprint in _SUGGEST_CACHE:
        _SUGGEST_CACHE.move_to_end(fingerprint)
        CACHE_STATS["hits"] += 1
        out = dict(_SUGGEST_CACHE[fingerprint])
        out["cache_hit"] = True
        return out
    CACHE_STATS["misses"] += 1
    return None


def _cache_put(fingerprint: str, result: dict[str, Any]) -> None:
    """仅缓存成功解析的结果；LRU 容量 8，超出淘汰最旧。"""
    _SUGGEST_CACHE[fingerprint] = dict(result)
    _SUGGEST_CACHE.move_to_end(fingerprint)
    while len(_SUGGEST_CACHE) > _SUGGEST_CACHE_MAX:
        _SUGGEST_CACHE.popitem(last=False)


def run_suggest(
    *,
    measurement: Any = None,
    aesthetic_history: Any = None,
    scene_query: str = "",
    chat_client: Callable[[str], Any] | None = None,
    knowledge_registry: Any = None,
    locked_params: Any = None,
    current_params: Any = None,
) -> dict[str, Any]:
    """执行一次建议链，返回::

        {"status": "ok" | "skipped_unconfigured",
         "accepted": [...], "rejected": [...],
         "reply_text": str, "source": str}

    环境未配置且未注入 chat_client → 整链跳过。本函数不抛错。
    """
    if chat_client is None and not is_dsh_chat_configured():
        return {"status": "skipped_unconfigured", "accepted": [],
                "rejected": [], "reply_text": "", "source": "none"}

    context = build_suggest_context(measurement, aesthetic_history,
                                    scene_query, knowledge_registry)
    nl = chr(10)
    prompt = (load_system_prompt() + nl + nl + "## 当前上下文(测量摘要)"
              + nl + json.dumps(context, ensure_ascii=False, default=str))

    fingerprint = _cache_fingerprint(prompt, locked_params, current_params)
    cached = _cache_get(fingerprint)
    if cached is not None:
        # 同上下文指纹命中：跳过 HTTP 直接复用（t53 延迟治理）
        cached["chat_latency_ms"] = 0.0
        return cached

    client: Callable[[str], Any] = chat_client or _dsh_chat_real
    started = time.perf_counter()
    try:
        reply = client(prompt)
    except Exception as exc:                 # 注入客户端自爆也不拖垮闭环
        latency = round((time.perf_counter() - started) * 1000.0, 3)
        _LOGGER.warning(
            "[pixo.agent.suggest] chat 客户端异常，降级 rejected: %s", exc)
        return {"status": "ok", "accepted": [],
                "rejected": [{"item": None, "reason": f"chat 客户端异常 {exc}",
                              "raw_text": ""}],
                "reply_text": "", "source": "client_exception",
                "chat_latency_ms": latency}
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)

    if isinstance(reply, dict):
        text = str(reply.get("text", ""))
        source = str(reply.get("source", "unknown"))
    else:
        text = str(reply)
        source = "injected"

    patches = _extract_json_patches(text, prompt)
    if patches is None:
        # 全文无可解析补丁：整条按 rejected 合成，保证回复全文可进 trace
        _LOGGER.warning(
            "[pixo.agent.suggest] 回复未解析到补丁 JSON (source=%s, "
            "len=%d)，整条降级 rejected", source, len(text))
        return {"status": "ok", "accepted": [],
                "rejected": [{"item": None,
                              "reason": "回复中未解析到补丁 JSON",
                              "raw_text": text}],
                "reply_text": text, "source": source,
                "chat_latency_ms": latency_ms, "cache_hit": False}
    review = review_patches(patches, locked_params=locked_params,
                            current_params=current_params)
    result = {"status": "ok", "accepted": list(review.accepted),
              "rejected": list(review.rejected), "reply_text": text,
              "source": source, "chat_latency_ms": latency_ms,
              "cache_hit": False}
    _cache_put(fingerprint, result)
    return result
