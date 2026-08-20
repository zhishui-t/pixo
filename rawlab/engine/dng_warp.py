"""rawlab/engine/dng_warp.py —— 兼容 shim, 真实实现已迁至 rawlux。保留旧 import 路径。"""
from rawlux.core.warp import (  # noqa: F401
    warp_rectilinear,
)

dng_warp_rectilinear = warp_rectilinear

__all__ = ["dng_warp_rectilinear"]
