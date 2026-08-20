"""rawlux —— RawLux 渲染引擎独立包 (从 rawlab.engine 迁移)。

包内按 core / modules / pipeline 组织。当前处于迁移过渡期:
各子模块仍是 rawlab.engine 的兼容层回指针, 公共 API 统一从
rawlux.api 导出。rawlab/engine 尚未删除, 旧 import 继续可用。
"""
from . import api
from .api import (
    Renderer,
    RenderIntent,
    RawInput,
    RawMetadata,
    CameraCalibration,
)

__version__ = "0.1.0"

__all__ = [
    "api",
    "Renderer", "RenderIntent", "RawInput", "RawMetadata", "CameraCalibration",
]
