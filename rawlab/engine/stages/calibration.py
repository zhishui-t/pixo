"""rawlab.engine.stages.calibration —— 兼容 shim, 实现已迁至 rawlux.modules.calibration。"""
from rawlux.modules.calibration import (  # noqa: F401
    CalibrationStage,
)
__all__ = ["CalibrationStage"]
