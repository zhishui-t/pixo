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

import json
from pathlib import Path
from typing import Any, Callable

from .patch_protocol import review_patches
from .tools import _dsh_chat_config, _dsh_chat_real

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


def load_system_prompt() -> str:
    """system.md + tools.md + 补丁协议 + few-shot 拼接为系统段。"""
    parts = []
    for name in ("system.md", "tools.md"):
        p = _PROMPTS_DIR / name
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    parts.append(PATCH_SCHEMA_DOC)
    parts.append(FEW_SHOT_EXAMPLE)
    return chr(10).join(parts) + chr(10)


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
    except Exception:
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


def _extract_json_patches(text: Any) -> list | None:
    """从回复全文提取补丁 JSON 数组；容忍 ```json 围栏与前后闲话。

    返回 list[dict]；解析失败/无数组 → None（调用方按全 rejected 处理）。
    """
    if not isinstance(text, str) or not text.strip():
        return None
    fence = chr(96) * 3                      # ``` 围栏剥离
    cleaned = text.replace(fence, "")
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(cleaned):
        if ch not in "[{":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned[idx:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, list):
            return [o for o in obj if isinstance(o, dict)]
        return None
    return None


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

    client: Callable[[str], Any] = chat_client or _dsh_chat_real
    try:
        reply = client(prompt)
    except Exception as exc:                 # 注入客户端自爆也不拖垮闭环
        return {"status": "ok", "accepted": [],
                "rejected": [{"item": None, "reason": f"chat 客户端异常 {exc}",
                              "raw_text": ""}],
                "reply_text": "", "source": "client_exception"}

    if isinstance(reply, dict):
        text = str(reply.get("text", ""))
        source = str(reply.get("source", "unknown"))
    else:
        text = str(reply)
        source = "injected"

    patches = _extract_json_patches(text)
    if patches is None:
        # 全文无可解析补丁：整条按 rejected 合成，保证回复全文可进 trace
        return {"status": "ok", "accepted": [],
                "rejected": [{"item": None,
                              "reason": "回复中未解析到补丁 JSON",
                              "raw_text": text}],
                "reply_text": text, "source": source}
    review = review_patches(patches, locked_params=locked_params,
                            current_params=current_params)
    return {"status": "ok", "accepted": list(review.accepted),
            "rejected": list(review.rejected), "reply_text": text,
            "source": source}
