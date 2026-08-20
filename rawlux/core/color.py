"""rawlux.core.color —— 色度学 / 矩阵 (兼容层, 回指 rawlab.engine.color)。

迁移目标: 原 engine/color.py 的 DCP 色彩链路纯函数。
当前阶段保留旧模块, 本文件仅作兼容回指, 公共符号不变 (rawlab.engine 旧名继续可用)。
公开面已剔除全部 dng_ 符号: dng 名以私有导入绑定, 对外只暴露 clean 名。
"""
from __future__ import annotations

# dng 底层以私有名导入, 不进入模块公开命名空间
from rawlab.engine.color import (  # noqa: F401
    dng_temperature_from_xy as _dng_temperature_from_xy,
    dng_camera_white as _dng_camera_white,
    dng_cam_to_prophoto_matrix as _dng_cam_to_prophoto_matrix,
    dng_prophoto_to_linear_srgb_matrix as _dng_prophoto_to_linear_srgb_matrix,
    dng_linear_prophoto_to_srgb as _dng_linear_prophoto_to_srgb,
)
from rawlab.engine.color import (  # noqa: F401
    BRADFORD_D50_TO_D65,
    D50_XY,
    D65_XY,
    PROPHOTO_RGB_TO_XYZ_D50,
    SRGB_TO_XYZ_D65,
    XYZ_D65_TO_SRGB,
    ColorMatrixFallbackWarning,
    bradford_adapt,
    cam_to_linear_srgb_matrix,
    cam_to_xyz,
    cam_to_xyz_matrix,
    cam_wb_to_prophoto,
    cct_from_wb,
    illuminant_cct,
    interpolate_color_matrices,
    interpolate_forward_matrix,
    linear_prophoto_to_linear_srgb,
    linear_srgb_to_linear_prophoto,
    neutral_to_xy,
    temp_tint_to_wb,
    temp_tint_to_xy,
    temp_to_xy,
    wb_to_neutral,
    wb_to_temp_tint,
    xy_to_cct,
    xy_to_xyz,
    xyz_to_linear_srgb,
    xyz_to_xy,
)

# 去 dng_ 前缀别名 (迁移规范: 禁止 dng_ 公开符号)
temperature_from_xy = _dng_temperature_from_xy
camera_white = _dng_camera_white
cam_to_prophoto_matrix = _dng_cam_to_prophoto_matrix
prophoto_to_linear_srgb_matrix = _dng_prophoto_to_linear_srgb_matrix
linear_prophoto_to_srgb = _dng_linear_prophoto_to_srgb

__all__ = [
    "BRADFORD_D50_TO_D65", "D50_XY", "D65_XY",
    "PROPHOTO_RGB_TO_XYZ_D50", "SRGB_TO_XYZ_D65", "XYZ_D65_TO_SRGB",
    "ColorMatrixFallbackWarning",
    "bradford_adapt", "cam_to_linear_srgb_matrix", "cam_to_xyz",
    "cam_to_xyz_matrix", "cam_wb_to_prophoto", "cct_from_wb",
    "illuminant_cct", "interpolate_color_matrices",
    "interpolate_forward_matrix", "linear_prophoto_to_linear_srgb",
    "linear_srgb_to_linear_prophoto", "neutral_to_xy", "temp_tint_to_wb",
    "temp_tint_to_xy", "temp_to_xy", "wb_to_neutral", "wb_to_temp_tint",
    "xy_to_cct", "xy_to_xyz", "xyz_to_linear_srgb", "xyz_to_xy",
    # 去 dng 前缀的 clean 别名
    "temperature_from_xy", "camera_white", "cam_to_prophoto_matrix",
    "prophoto_to_linear_srgb_matrix", "linear_prophoto_to_srgb",
]
