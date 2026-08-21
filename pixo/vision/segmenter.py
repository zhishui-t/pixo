"""pixo.vision.segmenter —— Segmenter 接口便捷入口。

保留独立 segmenter 模块名，方便 P0-3 真实适配器按统一目录组织。
"""
from __future__ import annotations

from .base import BaseSegmenter, Segmenter
from .exceptions import (
    EmptyImageError,
    InvalidPromptsError,
    PromptNotSupportedError,
    SegmenterError,
    SegmenterUnavailable,
)
from .mock import MockSegmenter

__all__ = [
    "Segmenter",
    "BaseSegmenter",
    "MockSegmenter",
    "SegmenterError",
    "SegmenterUnavailable",
    "InvalidPromptsError",
    "PromptNotSupportedError",
    "EmptyImageError",
]
