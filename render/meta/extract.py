"""兼容入口：``render.meta.extract`` 与 ``render.meta.exif`` 等价。"""
from .exif import PixoMeta, extract, normalize_exif, strip_gps

__all__ = ["PixoMeta", "extract", "normalize_exif", "strip_gps"]
