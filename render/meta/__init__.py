"""Pixo Meta —— 元数据提取/标准化、连拍分组、基础光照推断。

P0-5 先在 ``render.meta`` 落地；后续 P1 迁移到 ``pixo.meta``。

公共 API:
  - extract(raw_path, *, strip_gps=False, include_gps=True) -> dict
  - detect_burst_groups(images, profile=None, ...) -> list[dict]
  - infer_lighting_context(meta) -> dict
  - normalize_exif(tags, image_id=None, ...) -> dict
  - strip_gps(meta) -> dict
"""
from __future__ import annotations

from .exif import PixoMeta, extract, normalize_exif, strip_gps
from .burst import (
    BurstGroup,
    FrameMeta,
    _parse_exif_params,
    detect_burst_groups,
    group_bursts,
    normalize_image_meta,
)
from .lighting import (
    Daylight,
    classify_daylight,
    compute_daylight,
    infer_lighting_context,
    parse_exif_time,
)

__all__ = [
    "PixoMeta",
    "extract",
    "normalize_exif",
    "strip_gps",
    "detect_burst_groups",
    "group_bursts",
    "normalize_image_meta",
    "_parse_exif_params",
    "BurstGroup",
    "FrameMeta",
    "infer_lighting_context",
    "classify_daylight",
    "compute_daylight",
    "parse_exif_time",
    "Daylight",
]
