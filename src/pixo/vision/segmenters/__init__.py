"""pixo.vision.segmenters —— 真实分割模型适配器。

隔离纪律（与 model_licenses.json / docs/tech_debt.md 口径一致）：
  - ultralytics 依赖已随 YOLOE 移除清零（t110 AGPL 清偿）；
  - torch/transformers/rfdetr 等重依赖限各适配器文件内懒 import
    （uniface_face / rfdetr_person / segformer_scenes / grounded_sam /
    sapiens_body），本包顶层不引入。

本包不主动导入任何适配器，避免未使用真实模型时加载重依赖。
需要时显式导入：
    from pixo.vision.segmenters.multi_router import MultiModelSegmenter
也支持按需属性访问：from pixo.vision.segmenters import MultiModelSegmenter
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "MultiModelSegmenter",
    "UniFaceSegmenter",
    "RFDetrPersonSegmenter",
    "SegFormerSceneSegmenter",
    "GroundedSAMSegmenter",
    "SapiensBodySegmenter",
]


def __getattr__(name: str) -> Any:
    """按需导入适配器，避免包导入时触发 torch 等重依赖。"""
    mapping = {
        "MultiModelSegmenter": ("multi_router", "MultiModelSegmenter"),
        "UniFaceSegmenter": ("uniface_face", "UniFaceSegmenter"),
        "RFDetrPersonSegmenter": ("rfdetr_person", "RFDetrPersonSegmenter"),
        "SegFormerSceneSegmenter": ("segformer_scenes",
                                    "SegFormerSceneSegmenter"),
        "GroundedSAMSegmenter": ("grounded_sam", "GroundedSAMSegmenter"),
        "SapiensBodySegmenter": ("sapiens_body", "SapiensBodySegmenter"),
    }
    if name in mapping:
        from importlib import import_module
        mod, cls = mapping[name]
        return getattr(import_module("." + mod, __name__), cls)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
