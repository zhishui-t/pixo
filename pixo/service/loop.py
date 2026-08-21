"""pixo.service.loop —— 单张闭环兼容入口。

实际实现位于 ``pixo.pipeline.loop``，本模块仅做转发，避免调用方在
pipeline 与 service 两个命名空间之间纠结。
"""
from __future__ import annotations

from pixo.pipeline.loop import (
    LoopError,
    LoopResult,
    RawRenderBackend,
    SinglePhotoLoop,
    SyntheticRenderBackend,
    run_single_photo_loop,
)

__all__ = [
    "SinglePhotoLoop",
    "run_single_photo_loop",
    "SyntheticRenderBackend",
    "RawRenderBackend",
    "LoopResult",
    "LoopError",
]
