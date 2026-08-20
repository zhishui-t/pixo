"""rawlab.engine.stages.whitebalance —— 兼容 shim, 实现已迁至 rawlux.modules.white_balance。"""
from rawlux.modules.white_balance import (  # noqa: F401
    WARMTH_B0_FROZEN,
    WARMTH_B1_FROZEN,
    WARMTH_DAY_BAND,
    WARMTH_SLOPE_BOUNDS,
    apply_warmth,
    cct_kelvin_from_wb,
    auto_wb_linear,
    WhiteBalanceStage,
)
__all__ = ["WARMTH_B0_FROZEN", "WARMTH_B1_FROZEN", "WARMTH_DAY_BAND", "WARMTH_SLOPE_BOUNDS", "apply_warmth", "cct_kelvin_from_wb", "auto_wb_linear", "WhiteBalanceStage"]
