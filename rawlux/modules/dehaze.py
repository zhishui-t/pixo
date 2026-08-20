"""rawlux.modules.dehaze —— 去雾 Stage (兼容层, 回指 rawlab.engine.stages.reshape)。"""
from __future__ import annotations

from rawlab.engine.stages.reshape import DehazeStage  # noqa: F401

__all__ = ["DehazeStage"]
