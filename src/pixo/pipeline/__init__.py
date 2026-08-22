"""pixo.pipeline —— Pixo 单张/批量闭环编排层。

包含:
  - loop.SinglePhotoLoop: 单张修图闭环编排（P1-5）。
  - loop.run_single_photo_loop: 常用函数式入口。
  - loop.SyntheticRenderBackend / RawRenderBackend: 渲染后端适配。
"""
from __future__ import annotations

from .batch import (
    BatchError,
    BatchInput,
    BatchResult,
    BatchGroupResult,
    PhotoResult,
    HardFilterConfig,
    HardFilterResult,
    AestheticScore,
    AgentVerdict,
    MockAestheticScorer,
    MockAgentSelector,
    BatchPipeline,
)
from .loop import (
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
    "run_single_photo_loop",
    "SyntheticRenderBackend",
    "RawRenderBackend",
    "LoopResult",
    "LoopError",
]
