"""rawlux.modules.calibration —— 用户 RGB 校准 Stage (兼容层, 回指 rawlab.engine.stages.calibration)。

注: rawlux/modules/color_cal.py 指向 ColorCalStage (场景自适应校准), 两者不同。
"""
from __future__ import annotations

from rawlab.engine.stages.calibration import CalibrationStage  # noqa: F401

__all__ = ["CalibrationStage"]
