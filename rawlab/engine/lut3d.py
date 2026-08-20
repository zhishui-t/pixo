"""rawlab/engine/lut3d.py —— 兼容 shim, 真实实现已迁至 rawlux。保留旧 import 路径。"""
from rawlux.core.lut3d import (  # noqa: F401
    tetrahedral_interp,
    LUT3D,
    parse_cube,
    hald_to_lut,
)

__all__ = ["tetrahedral_interp", "LUT3D", "parse_cube", "hald_to_lut"]
