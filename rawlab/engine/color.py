"""rawlab/engine/color.py —— 兼容 shim, 真实实现已迁至 rawlux。保留旧 import 路径。"""
from rawlux.core.color import (  # noqa: F401
    D50_XY,
    D65_XY,
    PROPHOTO_RGB_TO_XYZ_D50,
    ColorMatrixFallbackWarning,
    illuminant_cct,
    xy_to_cct,
    xyz_to_xy,
    xy_to_xyz,
    bradford_adapt,
    interpolate_color_matrices,
    interpolate_forward_matrix,
    temperature_from_xy,
    wb_to_neutral,
    neutral_to_xy,
    cct_from_wb,
    temp_to_xy,
    temp_tint_to_xy,
    temp_tint_to_wb,
    wb_to_temp_tint,
    cam_to_xyz_matrix,
    cam_to_linear_srgb_matrix,
    camera_white,
    cam_to_prophoto_matrix,
    prophoto_to_linear_srgb_matrix,
    linear_prophoto_to_srgb,
    cam_wb_to_prophoto,
    cam_to_xyz,
    xyz_to_linear_srgb,
    linear_srgb_to_linear_prophoto,
    linear_prophoto_to_linear_srgb,
)

dng_temperature_from_xy = temperature_from_xy
dng_camera_white = camera_white
dng_cam_to_prophoto_matrix = cam_to_prophoto_matrix
dng_prophoto_to_linear_srgb_matrix = prophoto_to_linear_srgb_matrix
dng_linear_prophoto_to_srgb = linear_prophoto_to_srgb

__all__ = ["D50_XY", "D65_XY", "PROPHOTO_RGB_TO_XYZ_D50", "ColorMatrixFallbackWarning", "illuminant_cct", "xy_to_cct", "xyz_to_xy", "xy_to_xyz", "bradford_adapt", "interpolate_color_matrices", "interpolate_forward_matrix", "dng_temperature_from_xy", "wb_to_neutral", "neutral_to_xy", "cct_from_wb", "temp_to_xy", "temp_tint_to_xy", "temp_tint_to_wb", "wb_to_temp_tint", "cam_to_xyz_matrix", "cam_to_linear_srgb_matrix", "dng_camera_white", "dng_cam_to_prophoto_matrix", "dng_prophoto_to_linear_srgb_matrix", "dng_linear_prophoto_to_srgb", "cam_wb_to_prophoto", "cam_to_xyz", "xyz_to_linear_srgb", "linear_srgb_to_linear_prophoto", "linear_prophoto_to_linear_srgb", "temperature_from_xy", "camera_white", "cam_to_prophoto_matrix", "prophoto_to_linear_srgb_matrix", "linear_prophoto_to_srgb"]
