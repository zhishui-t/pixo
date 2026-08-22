"""pixo.harness.batch_render —— 批量/单张渲染 Harness 兼容入口。

仅 re-export 现有 pixo.pipeline.* 能力，不重复实现。
"""
from __future__ import annotations

from pixo.pipeline.batch import (
    AestheticScore,
    AgentVerdict,
    BatchError,
    BatchGroupResult,
    BatchInput,
    BatchPipeline,
    BatchResult,
    HardFilterConfig,
    HardFilterResult,
    MockAestheticScorer,
    MockAgentSelector,
    PhotoResult,
)
from pixo.pipeline.loop import (
    LoopError,
    LoopResult,
    RawRenderBackend,
    SinglePhotoLoop,
    SyntheticRenderBackend,
    run_single_photo_loop,
)

__all__ = [
    "BatchPipeline",
    "BatchInput",
    "BatchResult",
    "BatchGroupResult",
    "PhotoResult",
    "HardFilterConfig",
    "HardFilterResult",
    "AestheticScore",
    "AgentVerdict",
    "MockAestheticScorer",
    "MockAgentSelector",
    "BatchError",
    "SinglePhotoLoop",
    "SyntheticRenderBackend",
    "RawRenderBackend",
    "LoopResult",
    "LoopError",
    "run_single_photo_loop",
]
