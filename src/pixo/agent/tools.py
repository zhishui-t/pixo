"""pixo.agent.tools —— Agent 工具注册与调用封装。

提供：
  - 轻量 ToolRegistry：注册/列出/调用工具。
  - 默认工具集：单张/批量编排、Meta 提取、pixo-service HTTP 调用、
    DSH 占位聊天。
  - HTTP 调用使用标准库 urllib，不引入新依赖。
"""
from __future__ import annotations

import logging
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .burst_selection import select_burst_frames
from .orchestrator import run_batch, run_photo
_LOGGER = logging.getLogger(__name__)

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

# ---- LLM 调用熔断（t94）：连续失败 N 次进入冷却期，冷却内零请求直降级 ----
# 10s 超时 × 2 次重试的同步调用发生在渲染迭代内，最坏 ~20s/张；服务持续
# 不可用时按连续失败计数熔断，冷却期内直接返回降级结果不再发请求。
_LLM_BREAKER_THRESHOLD = 3          # 连续失败阈值（按请求次计，成功清零）
_LLM_COOLDOWN_ENV = "PIXO_LLM_COOLDOWN"
_LLM_COOLDOWN_DEFAULT_S = 60.0
_LLM_BREAKER = {"failures": 0, "cool_until": 0.0}


def _now() -> float:
    """单调时钟（测试经 monkeypatch 注入假时钟）。"""
    return time.monotonic()


def _llm_cooldown_s() -> float:
    """冷却秒数：env PIXO_LLM_COOLDOWN 可调，缺失/非法回退默认 60s。"""
    raw = os.environ.get(_LLM_COOLDOWN_ENV)
    if raw is None:
        return _LLM_COOLDOWN_DEFAULT_S
    try:
        value = float(raw)
    except ValueError:
        return _LLM_COOLDOWN_DEFAULT_S
    return value if value >= 0.0 else _LLM_COOLDOWN_DEFAULT_S


def _llm_breaker_remaining_s() -> float:
    """熔断冷却剩余秒数；未达阈值或已过期返回 0.0。"""
    if _LLM_BREAKER["failures"] < _LLM_BREAKER_THRESHOLD:
        return 0.0
    return max(0.0, _LLM_BREAKER["cool_until"] - _now())


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
    - 熔断（t94）：连续 3 次请求失败进入冷却期（默认 60s，env
      PIXO_LLM_COOLDOWN 可调），冷却期内零请求直接降级；任一次成功
      即清零失败计数；
    - 二次失败 → 本地占位并附 error 字段，不向调用方抛错。
    """
    cfg = _dsh_chat_config()
    if cfg is None:
        _LOGGER.warning(
            "[pixo.agent.tools] dsh.chat 未配置"
            "(PIXO_DSH_CHAT_URL/KEY/MODEL)，降级本地占位")
        return _dsh_chat_placeholder(text)

    remaining = _llm_breaker_remaining_s()
    if remaining > 0.0:
        _LOGGER.warning(
            "[pixo.agent.tools] dsh.chat 熔断冷却中，跳过请求"
            f"(连续失败 {_LLM_BREAKER['failures']} 次，剩余 {remaining:.1f}s)")
        fallback = _dsh_chat_placeholder(text)
        fallback["error"] = (
            f"circuit_breaker_cooldown: 剩余 {remaining:.1f}s")
        return fallback

    last_error: Exception | None = None
    for attempt in range(1, _DSH_CHAT_MAX_ATTEMPTS + 1):
        try:
            reply = _dsh_chat_post(cfg, text)
            _LLM_BREAKER["failures"] = 0      # 成功即清零失败计数
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
            _LLM_BREAKER["failures"] += 1
            if _LLM_BREAKER["failures"] >= _LLM_BREAKER_THRESHOLD:
                _LLM_BREAKER["cool_until"] = _now() + _llm_cooldown_s()
                _LOGGER.warning(
                    "[pixo.agent.tools] dsh.chat 连续失败达 "
                    f"{_LLM_BREAKER['failures']} 次，熔断冷却 "
                    f"{_llm_cooldown_s():.0f}s")
            _LOGGER.warning(
                "[pixo.agent.tools] dsh.chat 请求失败"
                f"(第{attempt}/{_DSH_CHAT_MAX_ATTEMPTS}次): {exc}")
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
