"""pixo.agent.tools —— Agent 工具注册与调用封装。

提供：
  - 轻量 ToolRegistry：注册/列出/调用工具。
  - 默认工具集：单张/批量编排、Meta 提取、pixo-service HTTP 调用、
    DSH 占位聊天。
  - HTTP 调用使用标准库 urllib，不引入新依赖。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .burst_selection import select_burst_frames
from .orchestrator import run_batch, run_photo

__all__ = [
    "ToolRegistry",
    "ToolSpec",
    "create_default_registry",
    "register_default_tools",
    "call_tool",
    "DEFAULT_SERVICE_URL",
]

DEFAULT_SERVICE_URL = "http://127.0.0.1:8000"


@dataclass
class ToolSpec:
    """一个可调用工具的描述。"""

    name: str
    description: str
    func: Callable[..., Any]
    category: str = "generic"


class ToolRegistry:
    """进程内工具注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        description: str = "",
        category: str = "generic",
    ) -> None:
        """注册工具；同名覆盖。"""
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            func=func,
            category=category,
        )

    def unregister(self, name: str) -> None:
        """注销工具。"""
        self._tools.pop(name, None)

    def list(self) -> list[ToolSpec]:
        """列出全部工具。"""
        return list(self._tools.values())

    def call(self, name: str, **kwargs: Any) -> Any:
        """调用指定工具，未注册抛 KeyError。"""
        if name not in self._tools:
            raise KeyError(f"未注册工具: {name}")
        return self._tools[name].func(**kwargs)


def _service_get(path: str) -> dict[str, Any]:
    """HTTP GET pixo-service，失败时抛 RuntimeError。"""
    url = f"{DEFAULT_SERVICE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"pixo-service 不可用: {exc}") from exc


_DSH_CHAT_ENV_URL = "PIXO_DSH_CHAT_URL"
_DSH_CHAT_ENV_KEY = "PIXO_DSH_CHAT_KEY"
_DSH_CHAT_ENV_MODEL = "PIXO_DSH_CHAT_MODEL"
_DSH_CHAT_TIMEOUT_S = 10.0
_DSH_CHAT_MAX_ATTEMPTS = 2  # 首次 + 重试 1 次


def _dsh_chat_config() -> dict[str, str] | None:
    """读取 DSH Chat 三要素配置；任一缺失返回 None。"""
    url = os.environ.get(_DSH_CHAT_ENV_URL)
    key = os.environ.get(_DSH_CHAT_ENV_KEY)
    model = os.environ.get(_DSH_CHAT_ENV_MODEL)
    if not (url and key and model):
        return None
    return {"url": url.rstrip("/"), "key": key, "model": model}


def _dsh_chat_placeholder(text: str) -> dict[str, Any]:
    """本地占位应答（带 source 标记，便于调用方可观测降级）。"""
    return {
        "ok": True,
        "role": "agent_placeholder",
        "text": f"已收到 DSH 消息: {text}",
        "source": "placeholder",
    }


def _dsh_chat_post(cfg: dict[str, str], text: str) -> str:
    """OpenAI 兼容 POST {endpoint}/chat/completions；失败抛异常。"""
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "user", "content": text}],
    }).encode("utf-8")
    request = urllib.request.Request(
        cfg["url"] + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_DSH_CHAT_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("dsh.chat 响应缺少 choices")
    content = (choices[0].get("message") or {}).get("content")
    if content is None:
        raise ValueError("dsh.chat 响应缺少 message.content")
    return str(content)


def _dsh_chat_real(text: str) -> dict[str, Any]:
    """DSH Agent 聊天真实客户端（可降级）。

    - PIXO_DSH_CHAT_URL/KEY/MODEL 任一缺失 → 本地占位(source=placeholder)；
    - 超时 10s、失败重试 1 次；
    - 二次失败 → 本地占位并附 error 字段，不向调用方抛错。
    """
    cfg = _dsh_chat_config()
    if cfg is None:
        print(
            "[pixo.agent.tools] dsh.chat 未配置"
            "(PIXO_DSH_CHAT_URL/KEY/MODEL)，降级本地占位"
        )
        return _dsh_chat_placeholder(text)

    last_error: Exception | None = None
    for attempt in range(1, _DSH_CHAT_MAX_ATTEMPTS + 1):
        try:
            reply = _dsh_chat_post(cfg, text)
            return {
                "ok": True,
                "role": "agent",
                "text": reply,
                "source": "pixo.agent.tools.dsh_chat_real",
                "model": cfg["model"],
                "retries_used": attempt - 1,
            }
        except Exception as exc:  # noqa: BLE001 - 网络异常一律走重试/降级
            last_error = exc
            print(
                "[pixo.agent.tools] dsh.chat 请求失败"
                f"(第{attempt}/{_DSH_CHAT_MAX_ATTEMPTS}次): {exc}"
            )
    fallback = _dsh_chat_placeholder(text)
    fallback["error"] = f"{type(last_error).__name__}: {last_error}"
    return fallback


def create_default_registry() -> ToolRegistry:
    """创建并填充分默认工具集。"""
    registry = ToolRegistry()

    registry.register(
        "orchestrator.run_photo",
        lambda **kw: run_photo(**kw),
        description="运行单张修图闭环",
        category="orchestrator",
    )
    registry.register(
        "orchestrator.run_batch",
        lambda **kw: run_batch(**kw),
        description="运行批量/连拍流程",
        category="orchestrator",
    )
    registry.register(
        "burst.select_frames",
        lambda frames, **kw: select_burst_frames(frames, **kw),
        description="连拍选帧：硬过滤 + 美学 TopN",
        category="burst",
    )

    def _meta_extract(raw_path: str) -> dict[str, Any]:
        from pixo.meta import extract
        return extract(raw_path)

    registry.register(
        "meta.extract",
        _meta_extract,
        description="提取 RAW/JPEG 标准化元数据",
        category="meta",
    )

    def _service_health() -> dict[str, Any]:
        try:
            return _service_get("/api/health")
        except RuntimeError:
            return {"status": "mock", "service": "pixo-service", "reachable": False}

    registry.register(
        "service.health",
        _service_health,
        description="查询 pixo-service 健康状态",
        category="service",
    )

    def _service_photos() -> dict[str, Any]:
        return _service_get("/api/photos")

    registry.register(
        "service.photos",
        _service_photos,
        description="获取 photo 列表",
        category="service",
    )

    registry.register(
        "dsh.chat",
        _dsh_chat_real,
        description="DSH Agent 聊天（未配置时降级本地占位）",
        category="dsh",
    )

    return registry


def register_default_tools(registry: ToolRegistry | None = None) -> ToolRegistry:
    """把默认工具注册到指定 registry（或新建）。"""
    registry = registry or ToolRegistry()
    default = create_default_registry()
    for spec in default.list():
        registry.register(
            spec.name,
            spec.func,
            description=spec.description,
            category=spec.category,
        )
    return registry


_default_registry: ToolRegistry | None = None


def call_tool(name: str, **kwargs: Any) -> Any:
    """使用默认 registry 调用工具。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = create_default_registry()
    return _default_registry.call(name, **kwargs)
