"""rawlab.engine.stages.colorcal —— 兼容 shim, 实现已迁至 rawlux.modules.color_cal。"""
from rawlux.modules.color_cal import (  # noqa: F401
    ColorCalStage,
)
__all__ = ["ColorCalStage"]
