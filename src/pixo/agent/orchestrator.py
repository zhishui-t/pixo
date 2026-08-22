"""pixo.agent.orchestrator —— 任务编排入口。

收编/包装现有能力：
  - ``pixo.pipeline.loop`` -> 单张闭环
  - ``pixo.pipeline.batch`` -> 批量/连拍选帧调度
  - ``pixo.agent.burst_selection`` -> 可分复用选帧核心
  - ``pixo.service`` 兼容层由 tools / service 模块提供
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from pixo.service import PixoServiceRuntime, SUPPORTED_EXTENSIONS, create_app
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
    "PixoOrchestrator",
    "run_batch",
    "run_photo",
    "SinglePhotoLoop",
    "run_single_photo_loop",
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
    "PixoServiceRuntime",
    "SUPPORTED_EXTENSIONS",
    "create_app",
]


def run_photo(
    photo_id: str,
    *,
    raw_path: str | None = None,
    image_rgb: Any = None,
    **kwargs: Any,
) -> LoopResult:
    """单张闭环快捷入口。"""
    return run_single_photo_loop(
        photo_id,
        raw_path=raw_path,
        image_rgb=image_rgb,
        **kwargs,
    )


def run_batch(
    photos: Sequence[BatchInput],
    *,
    top_n: int = 3,
    single_photo_runner: Any | None = None,
    **kwargs: Any,
) -> BatchResult:
    """批量流程快捷入口。"""
    pipeline = BatchPipeline(
        top_n=top_n,
        single_photo_runner=single_photo_runner,
        **kwargs,
    )
    return pipeline.process(photos)


class PixoOrchestrator:
    """面向 Agent 的统一编排门面。"""

    def __init__(self, **kwargs: Any) -> None:
        self.single_loop = SinglePhotoLoop(**kwargs)

    def run_photo(
        self,
        photo_id: str,
        **kwargs: Any,
    ) -> LoopResult:
        """单张闭环。"""
        return self.single_loop.run(photo_id, **kwargs)

    def run_batch(
        self,
        photos: Sequence[BatchInput],
        *,
        top_n: int = 3,
        single_photo_runner: Any | None = None,
        **kwargs: Any,
    ) -> BatchResult:
        """批量/连拍流程。"""
        return run_batch(
            photos,
            top_n=top_n,
            single_photo_runner=single_photo_runner,
            **kwargs,
        )
