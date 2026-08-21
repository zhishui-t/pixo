"""Pixo Meta —— EXIF 提取与标准化 (P0-5 基础)。

当前位于 ``render.meta``, 后续 P1 迁移到 ``pixo.meta``。
输出结构对齐 ``doc/架构设计文档.md`` §6.3。

实现要点:
  - 统一从 exifread 标签字典读取并归一化字段；
  - 所有缺失字段优雅降级为 None, 不抛异常；
  - 支持 GPS 隐私剥离 (``strip_gps=True`` / ``include_gps=False``)。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

__all__ = [
    "extract",
    "normalize_exif",
    "strip_gps",
    "PixoMeta",
]


# ---------------------------------------------------------------------------
# 低层 EXIF 标签读取辅助
# ---------------------------------------------------------------------------

def _first(tags: dict, *keys: str):
    """按优先级从 exifread 标签字典取第一个存在的标签。"""
    for key in keys:
        if key in tags:
            return tags[key]
    return None


def _tag_text(tag: Any) -> Optional[str]:
    """把 exifread IfdTag / 字符串 / 数字转换为干净字符串。"""
    if tag is None:
        return None
    try:
        if hasattr(tag, "printable"):
            text = str(tag.printable)
        else:
            text = str(tag)
    except Exception:
        return None
    text = text.strip()
    return text or None


def _tag_values(tag: Any) -> list:
    """返回标签的原始数值列表；普通值包装成单元素列表。"""
    if tag is None:
        return []
    values = getattr(tag, "values", None)
    if values is None:
        values = tag
    if isinstance(values, (list, tuple)):
        return list(values)
    return [values]


def _coerce_float(value: Any) -> Optional[float]:
    """尽力把 EXIF 值转换为 float (支持 Ratio / tuple / 字符串比值)。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    # exifread IfdTag: 直接取 values 首项
    if hasattr(value, "values") and not hasattr(value, "numerator"):
        vals = _tag_values(value)
        if vals:
            return _coerce_float(vals[0])
    # exifread Ratio (Fraction子类) / 有 numerator+denominator
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            den = float(value.denominator)
            if den == 0:
                return float(value.numerator)
            return float(value.numerator) / den
        except Exception:
            return None
    if hasattr(value, "decimal") and callable(value.decimal):
        try:
            return float(value.decimal())
        except Exception:
            pass
    if isinstance(value, tuple):
        # PIL 写入的 float 字段可能是 (2.8,) 这种单元素 tuple
        if len(value) == 1:
            return _coerce_float(value[0])
        if len(value) >= 2:
            try:
                return float(value[0]) / float(value[1])
            except Exception:
                return None
    if isinstance(value, (list,)):
        if not value:
            return None
        return _coerce_float(value[0])
    text = str(value).strip().strip("()")
    if not text:
        return None
    # 形如 "1/500" 或 "50/1"
    if "/" in text and not text.lower().startswith("0x"):
        try:
            a, b = text.split("/", 1)
            return float(a) / float(b)
        except Exception:
            pass
    try:
        return float(text)
    except Exception:
        return None


def _float_value(tags: dict, *keys: str) -> Optional[float]:
    return _coerce_float(_first(tags, *keys))


def _int_value(tags: dict, *keys: str) -> Optional[int]:
    value = _float_value(tags, *keys)
    if value is None:
        return None
    try:
        return int(round(value))
    except Exception:
        return None


def _text_value(tags: dict, *keys: str) -> Optional[str]:
    return _tag_text(_first(tags, *keys))


# ---------------------------------------------------------------------------
# 时间 / GPS / 曝光格式化
# ---------------------------------------------------------------------------

def _parse_exif_datetime(tags: dict) -> Optional[datetime]:
    """解析 DateTimeOriginal / Image DateTime（含亚秒）。"""
    text = _text_value(
        tags,
        "EXIF DateTimeOriginal",
        "EXIF DateTime",
        "Image DateTimeOriginal",
        "Image DateTime",
    )
    if not text:
        return None
    text = text.strip()
    dt = None
    for fmt in (
        "%Y:%m:%d %H:%M:%S",
        "%Y:%m:%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            break
        except (ValueError, TypeError):
            continue
    if dt is None:
        return None
    sub = _text_value(
        tags,
        "EXIF SubSecTimeOriginal",
        "EXIF SubSecTime",
        "Image SubSecTimeOriginal",
        "Image SubSecTime",
    )
    if sub:
        try:
            digits = re.sub(r"\D", "", sub)[:3]
            if digits:
                dt = dt.replace(microsecond=int(digits.ljust(3, "0")) * 1000)
        except Exception:
            pass
    return dt


def _parse_offset_hours(tags: dict) -> Optional[float]:
    """从 EXIF OffsetTime* 解析时区偏移小时数，例如 +08:00 -> 8.0。"""
    text = _text_value(
        tags,
        "EXIF OffsetTimeOriginal",
        "EXIF OffsetTime",
        "Image OffsetTimeOriginal",
        "Image OffsetTime",
        "Image TimeZoneOffset",
    )
    if not text:
        return None
    m = re.match(r"([+-])(\d{1,2}):(\d{2})", text.strip())
    if not m:
        return None
    sign = 1.0 if m.group(1) == "+" else -1.0
    try:
        return sign * (int(m.group(2)) + int(m.group(3)) / 60.0)
    except ValueError:
        return None


def _format_offset(offset_hours: Optional[float]) -> Optional[str]:
    if offset_hours is None:
        return None
    sign = "+" if offset_hours >= 0 else "-"
    total_min = int(round(abs(offset_hours) * 60))
    hh, mm = divmod(total_min, 60)
    return f"{sign}{hh:02d}:{mm:02d}"


def _format_datetime(dt: Optional[datetime],
                     offset_hours: Optional[float]) -> Optional[str]:
    """输出 ISO 8601 字符串；有 EXIF 时区时保留本地偏移。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.isoformat()
    offset = _format_offset(offset_hours)
    if offset:
        return f"{dt.isoformat()}{offset}"
    return dt.isoformat()


def _gps_decimal(coords: list) -> Optional[float]:
    """把 [度, 分, 秒] 或单个十进制值转成十进制度。"""
    nums = [_coerce_float(v) for v in coords]
    nums = [n for n in nums if n is not None]
    if not nums:
        return None
    if len(nums) >= 3:
        return nums[0] + nums[1] / 60.0 + nums[2] / 3600.0
    return nums[0]


def _gps_coord(tag: Any, ref_tag: Any) -> Optional[float]:
    vals = _tag_values(tag)
    coord = _gps_decimal(vals)
    if coord is None:
        return None
    ref = _tag_text(ref_tag)
    if ref and ref.strip().upper() in ("S", "W"):
        coord = -coord
    return coord


def _parse_gps(tags: dict) -> Optional[dict]:
    lat_tag = _first(
        tags, "GPS GPSLatitude", "GPS Latitude", "GPS GPSLatitude", "GPSLatitude"
    )
    lon_tag = _first(
        tags, "GPS GPSLongitude", "GPS Longitude", "GPS GPSLongitude", "GPSLongitude"
    )
    if lat_tag is None or lon_tag is None:
        return None
    lat = _gps_coord(lat_tag, _first(tags, "GPS GPSLatitudeRef", "GPSLatitudeRef"))
    lon = _gps_coord(lon_tag, _first(tags, "GPS GPSLongitudeRef", "GPSLongitudeRef"))
    if lat is None or lon is None:
        return None
    altitude = None
    alt_tag = _first(tags, "GPS GPSAltitude", "GPSAltitude")
    if alt_tag is not None:
        altitude = _coerce_float(alt_tag)
        alt_ref = _tag_text(_first(tags, "GPS GPSAltitudeRef", "GPSAltitudeRef"))
        if altitude is not None and alt_ref and alt_ref.strip() in ("1", "B", "b"):
            altitude = -abs(altitude)
    return {
        "lat": round(float(lat), 6),
        "lon": round(float(lon), 6),
        "altitude": round(float(altitude), 6) if altitude is not None else None,
    }


def _format_aperture(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"f/{value:g}"


def _format_shutter(seconds: Optional[float]) -> Optional[str]:
    """把快门秒数格式化为 EXIF 风格字符串，如 1/500、1、2。"""
    if seconds is None or seconds == 0:
        return None if seconds is None else "0"
    if seconds >= 1:
        return f"{seconds:g}"
    inv = int(round(1.0 / seconds))
    if inv > 0 and abs(1.0 / inv - seconds) <= max(0.02 * seconds, 1e-6):
        return f"1/{inv}"
    return f"{seconds:g}"


def _normalize_flash(tag: Any) -> Optional[str]:
    text = _tag_text(tag)
    if text is None:
        return None
    low = text.lower()
    if "did not fire" in low or low in ("off", "0", "none", "no"):
        return "off"
    if "fired" in low or "on" in low or low in ("1", "yes"):
        return "on"
    value = _coerce_float(tag)
    if value is not None:
        return "on" if value > 0 else "off"
    return text


def _normalize_metering_mode(tag: Any) -> Optional[str]:
    text = _tag_text(tag)
    if text is None:
        return None
    low = text.lower()
    value = _coerce_float(tag)
    mapping = {
        0: "unknown",
        1: "average",
        2: "center-weighted",
        3: "spot",
        4: "multi-spot",
        5: "matrix",
        6: "partial",
        255: "other",
    }
    if value is not None:
        int_val = int(round(value))
        if int_val in mapping:
            return mapping[int_val]
    if any(k in low for k in ("matrix", "multi", "center", "spot", "average", "partial")):
        return low
    return text


def _normalize_white_balance(tag: Any) -> Optional[str]:
    text = _tag_text(tag)
    if text is None:
        return None
    low = text.lower()
    if "auto" in low or low in ("0",):
        return "auto"
    if "manual" in low or "custom" in low or low in ("1",):
        return "manual"
    return text


# ---------------------------------------------------------------------------
# 标准化
# ---------------------------------------------------------------------------

# EXIF 常见字段别名（优先顺序）
_MAKE_KEYS = ("Image Make", "EXIF Make", "Make")
_MODEL_KEYS = ("Image Model", "EXIF Model", "Model")
_LENS_KEYS = (
    "EXIF LensModel",
    "Image LensModel",
    "EXIF Lens",
    "Image Lens",
    "LensModel",
)
_SERIAL_KEYS = (
    "EXIF BodySerialNumber",
    "EXIF SerialNumber",
    "EXIF CameraSerialNumber",
    "Image SerialNumber",
    "Image CameraSerialNumber",
    "BodySerialNumber",
)
_FOCAL_KEYS = ("EXIF FocalLength", "Image FocalLength", "FocalLength")
_APERTURE_KEYS = ("EXIF FNumber", "Image FNumber", "FNumber", "EXIF ApertureValue")
_SHUTTER_KEYS = ("EXIF ExposureTime", "Image ExposureTime", "ExposureTime")
_ISO_KEYS = (
    "EXIF ISOSpeedRatings",
    "Image ISOSpeedRatings",
    "EXIF PhotographicSensitivity",
    "Image PhotographicSensitivity",
    "ISOSpeedRatings",
)
_EXP_COMP_KEYS = (
    "EXIF ExposureBiasValue",
    "Image ExposureBiasValue",
    "ExposureBiasValue",
)
_METERING_KEYS = ("EXIF MeteringMode", "Image MeteringMode", "MeteringMode")
_FLASH_KEYS = ("EXIF Flash", "Image Flash", "Flash")
_WB_KEYS = ("EXIF WhiteBalance", "Image WhiteBalance", "WhiteBalance")
_ORIENT_KEYS = ("Image Orientation", "EXIF Orientation", "Orientation")
_TEMPERATURE_KEYS = (
    "EXIF Temperature",
    "Image Temperature",
    "EXIF ColorTemperature",
    "ColorTemperature",
)
_TINT_KEYS = ("EXIF Tint", "Image Tint", "Tint")


def normalize_exif(
    tags: dict,
    image_id: Optional[str] = None,
    *,
    strip_gps: bool = False,
    include_gps: bool = True,
    remove_gps: bool = False,
    privacy: bool = False,
    no_gps: bool = False,
) -> dict:
    """把 exifread 标签字典转换为文档 §6.3 的标准化元数据。

    缺失字段一律为 None，调用方无需担心 KeyError。
    """
    strip_gps = strip_gps or remove_gps or privacy or no_gps or not include_gps
    gps = None
    if not strip_gps:
        gps = _parse_gps(tags)

    dt = _parse_exif_datetime(tags)
    offset_h = _parse_offset_hours(tags)

    aperture_value = _float_value(tags, *_APERTURE_KEYS)
    shutter_seconds = _float_value(tags, *_SHUTTER_KEYS)
    focal_length = _float_value(tags, *_FOCAL_KEYS)

    return {
        "image_id": image_id,
        "camera": {
            "make": _text_value(tags, *_MAKE_KEYS),
            "model": _text_value(tags, *_MODEL_KEYS),
            "lens": _text_value(tags, *_LENS_KEYS),
            "serial_number": _text_value(tags, *_SERIAL_KEYS),
        },
        "capture": {
            "datetime": _format_datetime(dt, offset_h),
            "timezone_offset": _format_offset(offset_h),
            "gps": gps,
            "orientation": _int_value(tags, *_ORIENT_KEYS),
        },
        "exposure": {
            "aperture": _format_aperture(aperture_value),
            "aperture_value": aperture_value,
            "shutter_speed": _format_shutter(shutter_seconds),
            "shutter_seconds": shutter_seconds,
            "iso": _int_value(tags, *_ISO_KEYS),
            "exposure_compensation": _float_value(tags, *_EXP_COMP_KEYS),
            "metering_mode": _normalize_metering_mode(_first(tags, *_METERING_KEYS)),
            "flash": _normalize_flash(_first(tags, *_FLASH_KEYS)),
            "focal_length": focal_length,
        },
        "white_balance": {
            "as_shot": _normalize_white_balance(_first(tags, *_WB_KEYS)),
            "temperature": _int_value(tags, *_TEMPERATURE_KEYS),
            "tint": _float_value(tags, *_TINT_KEYS),
        },
        "shot_context": {
            "burst_group": None,
            "shot_index": None,
            "total_shots_in_group": None,
        },
    }


def extract(
    raw_path: str | Path,
    *,
    strip_gps: bool = False,
    include_gps: bool = True,
    remove_gps: bool = False,
    privacy: bool = False,
    no_gps: bool = False,
    fallback_to_file_mtime: bool = True,
) -> dict:
    """从 RAW/JPEG 路径提取并标准化元数据。

    Args:
        raw_path: 图片文件路径。
        strip_gps: 为 True 时剥离 GPS（隐私选项）。
        remove_gps / privacy / no_gps: 与 strip_gps 等价的可读别名。
        include_gps: 为 False 时同样剥离 GPS。
        fallback_to_file_mtime: 无 EXIF 时间时回退到文件修改时间。
    """
    path = Path(raw_path)
    tags: dict = {}
    try:
        import exifread
        with open(str(path), "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception:
        tags = {}

    meta = normalize_exif(
        tags,
        image_id=path.stem,
        strip_gps=strip_gps or remove_gps or privacy or no_gps or not include_gps,
        include_gps=include_gps,
    )

    if meta["capture"]["datetime"] is None and fallback_to_file_mtime:
        try:
            from datetime import datetime as _dt
            ts = path.stat().st_mtime
            local = _dt.fromtimestamp(ts)
            meta["capture"]["datetime"] = local.isoformat()
        except Exception:
            pass
    return meta


def strip_gps(meta: dict) -> dict:
    """返回剥离 GPS 后的元数据副本，不修改原字典。"""
    import copy
    out = copy.deepcopy(meta)
    capture = out.setdefault("capture", {})
    if isinstance(capture, dict):
        capture["gps"] = None
    return out


class PixoMeta:
    """文档 §6.5 的面向对象门面；与模块级函数等价。"""

    def extract(self, raw_path, **kwargs) -> dict:
        return extract(raw_path, **kwargs)

    def infer_lighting_context(self, meta: dict) -> dict:
        from .lighting import infer_lighting_context
        return infer_lighting_context(meta)

    def detect_burst_groups(self, images: Iterable, **kwargs) -> list:
        from .burst import detect_burst_groups
        return detect_burst_groups(images, **kwargs)
