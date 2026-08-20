"""rawlab.engine.skin —— 兼容 shim, 实现已迁至 rawlux.core.skin。"""
from rawlux.core.skin import (  # noqa: F401
    GUIDED_EPS, GUIDED_R, SKIN_ANGLE, SKIN_LAB_A, SKIN_LAB_B, SKIN_MAJOR,
    SKIN_MINOR, guided_filter, skin_mask, skin_smooth,
)

__all__ = ["GUIDED_EPS", "GUIDED_R", "SKIN_ANGLE", "SKIN_LAB_A", "SKIN_LAB_B",
           "SKIN_MAJOR", "SKIN_MINOR", "guided_filter", "skin_mask", "skin_smooth"]
