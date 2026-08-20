"""rawlab.dcp —— 兼容 shim, 实现已迁至 rawlux.core.calibration。"""
from rawlux.core.calibration import (  # noqa: F401
    XYZ_D65_TO_SRGB,
    SRGB_TO_XYZ_D65,
    BRADFORD_D50_TO_D65,
    DcpProfile,
    load_dcp,
    write_dcp,
    find_camera_dcp,
    _TIFF_SIZES,
    _TAG_NAMES,
    _parse_ifd,
    _read_values,
    _RATIONAL_DEN,
    _to_srationals,
    _tiff_entry,
    _validate_tone_curve_endpoint,
)

__all__ = ["XYZ_D65_TO_SRGB", "SRGB_TO_XYZ_D65", "BRADFORD_D50_TO_D65",
           "DcpProfile", "load_dcp", "write_dcp", "find_camera_dcp",
           "_TIFF_SIZES", "_TAG_NAMES", "_parse_ifd", "_read_values",
           "_RATIONAL_DEN", "_to_srationals", "_tiff_entry",
           "_validate_tone_curve_endpoint"]
