"""rawlux.core.calibration —— DCP + camera cache 合并入口 (兼容层)。

迁移目标: 原 rawlab/dcp.py (load_dcp / DcpProfile) + engine/calibration.py
(每机标定 camera_look_curves / camera_neutral_trim) + dng_camera_cache 加载。
当前阶段保留旧模块, 本文件仅作兼容回指, 公共符号不变。
"""
from __future__ import annotations

from rawlab.dcp import (  # noqa: F401
    DcpProfile,
    load_dcp,
    write_dcp,
    find_camera_dcp,
)
from rawlab.engine.calibration import (  # noqa: F401
    camera_look_curves,
    camera_neutral_trim,
)

__all__ = [
    "DcpProfile", "load_dcp", "write_dcp", "find_camera_dcp",
    "camera_look_curves", "camera_neutral_trim",
]
