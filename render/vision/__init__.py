"""pixo.render.vision —— Pixo Vision 视觉感知基础包（P0-2）。

当前包含:
  - Segmenter / BaseSegmenter: 分割器对外契约与基类。
  - MockSegmenter: 合成 face/sky/plant 等 mask，用于测量/闭环测试。
  - VisionMeasure / measure_global / measure_region / 测量扩展:
    区域/全局测量，输出对齐架构文档 §5.4，并含分区曝光/锐度/运动模糊/雾密度。
  - vision_health(): 模型可用性/版本/加载状态，真实模型未接入时返回未就绪。
  - SegmenterUnavailable 等异常与降级约定。

设计约束:
  - 本包不引入 torch/ultralytics，真实 YOLOE 适配留待 P0-3 独立文件。
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
from .health import VISION_PACKAGE_VERSION, get_yoloe_segmenter, vision_health
from .measure import (
    VisionMeasure,
    measure_global,
    measure_haze,
    measure_motion_blur,
    measure_region,
    measure_sharpness,
    measure_zone_exposure,
)
from .mock import MockSegmenter

__all__ = [
    "Segmenter",
    "BaseSegmenter",
    "MockSegmenter",
    "VisionMeasure",
    "measure_global",
    "measure_region",
    "measure_zone_exposure",
    "measure_sharpness",
    "measure_motion_blur",
    "measure_haze",
    "vision_health",
    "get_yoloe_segmenter",
    "VISION_PACKAGE_VERSION",
    "SegmenterError",
    "SegmenterUnavailable",
    "InvalidPromptsError",
    "PromptNotSupportedError",
    "EmptyImageError",
]
