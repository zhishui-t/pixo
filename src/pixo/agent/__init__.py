"""pixo.agent —— Agent 编排 / 工具注册 / 连拍选帧。

Phase C 目录：
  - orchestrator.py: 单张/批量闭环入口与 re-export
  - tools.py: 工具注册与 pixo-service/DSH 调用封装
  - burst_selection.py: 连拍选帧核心
  - prompts/: 系统提示词与工具说明
"""
from __future__ import annotations

from .burst_selection import (
    BurstFrame,
    BurstSelectionConfig,
    BurstSelectionResult,
    select_burst_frames,
)
from .orchestrator import (
    AestheticScore,
    AgentVerdict,
    BatchError,
    BatchGroupResult,
    BatchInput,
    BatchPipeline,
    BatchResult,
    HardFilterConfig,
    HardFilterResult,
    LoopError,
    LoopResult,
    MockAestheticScorer,
    MockAgentSelector,
    PhotoResult,
    PixoOrchestrator,
    PixoServiceRuntime,
    RawRenderBackend,
    SUPPORTED_EXTENSIONS,
    SinglePhotoLoop,
    SyntheticRenderBackend,
    create_app,
    run_batch,
    run_photo,
    run_single_photo_loop,
)
from .prompts import SYSTEM_PROMPT, TOOL_PROMPT
from .tools import (
    DEFAULT_SERVICE_URL,
    ToolRegistry,
    ToolSpec,
    call_tool,
    create_default_registry,
    register_default_tools,
)

__all__ = [
    "PixoOrchestrator",
    "run_photo",
    "run_batch",
    "run_single_photo_loop",
    "SinglePhotoLoop",
    "SyntheticRenderBackend",
    "RawRenderBackend",
    "LoopResult",
    "LoopError",
    "BatchPipeline",
    "BatchInput",
    "BatchResult",
    "BatchGroupResult",
    "PhotoResult",
    "AestheticScore",
    "AgentVerdict",
    "MockAestheticScorer",
    "MockAgentSelector",
    "HardFilterConfig",
    "HardFilterResult",
    "BatchError",
    "BurstFrame",
    "BurstSelectionConfig",
    "BurstSelectionResult",
    "select_burst_frames",
    "ToolRegistry",
    "ToolSpec",
    "create_default_registry",
    "register_default_tools",
    "call_tool",
    "DEFAULT_SERVICE_URL",
    "SYSTEM_PROMPT",
    "TOOL_PROMPT",
    "PixoServiceRuntime",
    "SUPPORTED_EXTENSIONS",
    "create_app",
]
