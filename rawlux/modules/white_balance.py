"""rawlux.modules.white_balance —— 白平衡/色彩矫正 Stage (兼容层, 回指 rawlab.engine.stages.whitebalance)。"""
from __future__ import annotations

from rawlab.engine.stages.whitebalance import (  # noqa: F401
    WhiteBalanceStage,
    apply_warmth,
    cct_kelvin_from_wb,
    auto_wb_linear,
)

__all__ = ["WhiteBalanceStage", "apply_warmth", "cct_kelvin_from_wb",
           "auto_wb_linear"]
