"""rawlux.modules.denoise —— 降噪 Stage (兼容层, 回指 rawlab.engine.stages.reshape)。"""
from __future__ import annotations

from rawlab.engine.stages.reshape import DenoiseStage  # noqa: F401

__all__ = ["DenoiseStage"]
