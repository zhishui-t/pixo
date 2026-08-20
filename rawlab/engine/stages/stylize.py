"""rawlab.engine.stages.stylize —— 兼容 shim, 实现已迁至 rawlux.modules.style。"""
from rawlux.modules.style import (  # noqa: F401
    StylizeStage,
)
__all__ = ["StylizeStage"]
