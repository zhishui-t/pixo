"""pixo.agent.tools —— Agent 工具注册与调用封装。

提供：
  - 轻量 ToolRegistry：注册/列出/调用工具。
  - 默认工具集：单张/批量编排、Meta 提取、pixo-service HTTP 调用、
    DSH 占位聊天。
  - HTTP 调用使用标准库 urllib，不引入新依赖。
"""
from __future__ import annotations

import json
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

    def _dsh_chat(text: str) -> dict[str, Any]:
        # DSH 真实嵌入在 P2 接入；当前为占位，返回可追溯消息。
        return {
            "ok": True,
            "role": "agent_placeholder",
            "text": f"已收到 DSH 消息: {text}",
            "source": "pixo.agent.tools.mock",
        }

    registry.register(
        "dsh.chat",
        _dsh_chat,
        description="DSH Agent 聊天占位工具",
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
