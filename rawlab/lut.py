"""rawlab.lut —— 兼容 shim, 实现已迁至 rawlux.core.lut。"""
from rawlux.core.lut import (  # noqa: F401
    LUT3D, hald_to_lut, parse_cube, load_lut,
)

__all__ = ["LUT3D", "hald_to_lut", "parse_cube", "load_lut"]
