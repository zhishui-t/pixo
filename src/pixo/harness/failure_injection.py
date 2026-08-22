"""pixo.harness.failure_injection —— 故障注入兼容工具。

提供轻量上下文管理器，用于测试分割/审核失败路径；不重复实现引擎。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable

from pixo.review import ReviewError
from pixo.vision import SegmenterUnavailable

__all__ = [
    "SegmenterUnavailable",
    "ReviewError",
    "inject_segmenter_failure",
]


@contextmanager
def inject_segmenter_failure(
    segmenter: Any,
    exc: Exception | None = None,
):
    """临时把 segmenter.segment 替换为抛异常，用于测试降级路径。"""
    original: Callable = getattr(segmenter, "segment")
    error = exc or SegmenterUnavailable("注入分割故障")

    def _fail(*args, **kwargs):
        raise error

    segmenter.segment = _fail
    try:
        yield
    finally:
        segmenter.segment = original
