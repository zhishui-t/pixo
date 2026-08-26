"""pixo.vision.segmenters —— 真实分割模型适配器。

当前仅包含 YOLOE-26L-seg 适配器（P0-3）：
  - yoloe.py：唯一允许直接 import torch / ultralytics 的文件（AGPL 隔离）。

本包不主动导入 yoloe，避免在未使用真实模型时加载 torch/ultralytics。
需要真实分割能力时显式导入：
    from pixo.vision.segmenters.yoloe import YoloeSegmenter
也支持按需属性访问：from pixo.vision.segmenters import YoloeSegmenter
"""
from __future__ import annotations

from typing import Any

__all__ = ["YoloeSegmenter", "MultiModelSegmenter", "UniFaceSegmenter", "RFDetrPersonSegmenter", "SegFormerSceneSegmenter", "GroundedSAMSegmenter"]


def __getattr__(name: str) -> Any:
    """按需导入 YoloeSegmenter，避免包导入时触发 torch/ultralytics。"""
    mapping = {
        "YoloeSegmenter": ("yoloe", "YoloeSegmenter"),
        "MultiModelSegmenter": ("multi_router", "MultiModelSegmenter"),
        "UniFaceSegmenter": ("uniface_face", "UniFaceSegmenter"),
        "RFDetrPersonSegmenter": ("rfdetr_person", "RFDetrPersonSegmenter"),
        "SegFormerSceneSegmenter": ("segformer_scenes",
                                    "SegFormerSceneSegmenter"),
        "GroundedSAMSegmenter": ("grounded_sam", "GroundedSAMSegmenter"),
    }
    if name in mapping:
        from importlib import import_module
        mod, cls = mapping[name]
        return getattr(import_module("." + mod, __name__), cls)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
