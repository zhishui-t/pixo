"""rawlab/dcp.py —— 兼容 shim, 真实实现已迁至 rawlux。保留旧 import 路径。"""
from rawlux.core.calibration import (  # noqa: F401
    XYZ_D65_TO_SRGB,
    SRGB_TO_XYZ_D65,
    BRADFORD_D50_TO_D65,
    DcpProfile,
    load_dcp,
    write_dcp,
    find_camera_dcp,
)

__all__ = ["XYZ_D65_TO_SRGB", "SRGB_TO_XYZ_D65", "BRADFORD_D50_TO_D65", "DcpProfile", "load_dcp", "write_dcp", "find_camera_dcp"]
