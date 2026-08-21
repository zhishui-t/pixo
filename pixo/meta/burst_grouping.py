"""兼容入口：``render.meta.burst_grouping`` 与 guanlan burst_grouping.py 对应。"""
from .burst import (
    BurstGroup,
    FrameMeta,
    _parse_exif_params,
    detect_burst_groups,
    group_bursts,
    normalize_image_meta,
)

__all__ = [
    "BurstGroup",
    "FrameMeta",
    "_parse_exif_params",
    "detect_burst_groups",
    "group_bursts",
    "normalize_image_meta",
]
