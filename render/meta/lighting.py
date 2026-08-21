"""Pixo Meta —— 基础光照/场景上下文 (P0-5)。

算法移植自 ``guanlan/src/rules/daylight.py``:
  - NOAA 简化日出日落 (太阳赤纬 + 时角), 误差 <±5 分钟；
  - 太阳高度 > 0° → day；
  - 0° ~ -6° → golden_hour；
  - < -6° → night；
  - 无 GPS 时使用默认北京位置 (116.4E, 39.9N)。

来源注释：
  Ported/adapted from Guanlan (观澜) src/rules/daylight.py.
  原项目许可信息未在本仓库内单独列出；迁移时保留算法与注释归属。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

__all__ = [
    "compute_daylight",
    "classify_daylight",
    "parse_exif_time",
    "infer_lighting_context",
]

# 太阳高度角阈值 (度)
_SUN_DAY = 0.0       # 日出/日落
_SUN_CIVIL = -6.0    # 民用暮光结束

# 默认位置 (无 GPS 时): 中国北京
DEFAULT_LONGITUDE = 116.4
DEFAULT_LATITUDE = 39.9

# 默认时区（无 EXIF OffsetTime 时）：UTC+8
DEFAULT_OFFSET_HOURS = 8.0


@dataclass
class Daylight:
    """一天的昼夜时刻 (UTC naive datetime)。"""

    sunrise: datetime
    sunset: datetime
    civil_dawn: datetime
    civil_dusk: datetime


def _solar_declination(doy: float) -> float:
    """太阳赤纬(度)。doy = 1月1日=1。"""
    return 23.44 * math.sin(math.radians(360.0 / 365.0 * (doy - 81)))


def _hour_angle(lat_deg: float, decl_deg: float, elev_deg: float) -> float:
    """太阳时角(度), 使太阳高度角 = elev_deg。纬度北纬为正。"""
    lat = math.radians(lat_deg)
    decl = math.radians(decl_deg)
    elev = math.radians(elev_deg)
    cos_h = (math.sin(elev) - math.sin(lat) * math.sin(decl)) / \
            (math.cos(lat) * math.cos(decl))
    cos_h = max(-1.0, min(1.0, cos_h))
    return math.degrees(math.acos(cos_h))


def _solar_noon_utc(lon_deg: float, doy: float) -> float:
    """太阳正午 (UTC 小时, 忽略均时差, 误差 ±15 分钟)。"""
    return 12.0 - lon_deg / 15.0


def compute_daylight(
    dt_local: datetime,
    utc_offset_hours: float,
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
) -> Daylight:
    """计算 dt_local 当天的日出日落 (UTC naive datetime)。

    Args:
        dt_local: 拍摄的本地时刻 (naive, 或带 tzinfo 则忽略 offset)。
        utc_offset_hours: 时区偏移小时数 (如 +8.0 表示 UTC+8)。
        latitude: 纬度 (北纬为正)。
        longitude: 经度 (东经为正)。
    """
    if dt_local.tzinfo is not None:
        # 天文算法使用本地 wall-clock；aware datetime 保留墙上时间即可。
        dt_local = dt_local.replace(tzinfo=None)
    dt_utc = dt_local - timedelta(hours=utc_offset_hours)
    doy = dt_local.timetuple().tm_yday

    decl = _solar_declination(doy)
    noon_utc = _solar_noon_utc(longitude, doy)

    def _to_dt(utc_hours: float) -> datetime:
        day = datetime(dt_utc.year, dt_utc.month, dt_utc.day)
        return day + timedelta(hours=utc_hours)

    ha_day = _hour_angle(latitude, decl, _SUN_DAY)
    ha_civil = _hour_angle(latitude, decl, _SUN_CIVIL)

    return Daylight(
        sunrise=_to_dt(noon_utc - ha_day / 15.0),
        sunset=_to_dt(noon_utc + ha_day / 15.0),
        civil_dawn=_to_dt(noon_utc - ha_civil / 15.0),
        civil_dusk=_to_dt(noon_utc + ha_civil / 15.0),
    )


def classify_daylight(
    dt_local: datetime,
    utc_offset_hours: float,
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
) -> str:
    """判断拍摄时刻 day / golden_hour / night。"""
    if dt_local.tzinfo is not None:
        dt_local = dt_local.replace(tzinfo=None)
    dl = compute_daylight(dt_local, utc_offset_hours, latitude, longitude)
    dt_utc = dt_local - timedelta(hours=utc_offset_hours)

    if dt_utc < dl.civil_dawn or dt_utc > dl.civil_dusk:
        return "night"
    if dl.civil_dawn <= dt_utc < dl.sunrise or dl.sunset < dt_utc <= dl.civil_dusk:
        return "golden_hour"
    return "day"


def parse_exif_time(
    datetime_original: str,
    offset_time: Optional[str] = None,
) -> Optional[tuple]:
    """解析 EXIF DateTimeOriginal + OffsetTime → (本地 naive datetime, utc_offset_hours)。

    Args:
        datetime_original: "YYYY:MM:DD HH:MM:SS"
        offset_time: "+08:00" (可 None, 默认 +08:00)

    Returns:
        (datetime, utc_offset_hours) 或 None (解析失败)
    """
    try:
        dt = datetime.strptime(datetime_original, "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None

    off_h = DEFAULT_OFFSET_HOURS
    if offset_time:
        try:
            sign = 1.0 if offset_time[0] != "-" else -1.0
            hh = int(offset_time[1:3])
            mm = int(offset_time[4:6])
            off_h = sign * (hh + mm / 60.0)
        except (ValueError, IndexError):
            pass
    return dt, off_h


# ---------------------------------------------------------------------------
# Pixo Meta 光照上下文
# ---------------------------------------------------------------------------

def _parse_offset(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    text = text.strip()
    if text.endswith("Z"):
        return 0.0
    try:
        sign = 1.0 if text[0] != "-" else -1.0
        hh = int(text[1:3])
        mm = int(text[4:6])
        return sign * (hh + mm / 60.0)
    except Exception:
        return None


def _parse_datetime_iso(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def infer_lighting_context(meta: dict) -> dict:
    """基于时间 + GPS 推断基础光照/场景上下文。

    返回:
        {
          "lighting": "day" | "golden_hour" | "night" | "unknown",
          "scene": "daylight" | "golden_hour" | "night" | "unknown",
          "sunrise": "YYYY-MM-DDTHH:MM:SSZ" | None,
          "sunset": ...,
          "civil_dawn": ...,
          "civil_dusk": ...,
          "gps_used": bool,
          "confidence": "high" | "medium" | "low",
          "source": "time+gps" | "time(default_location)" | "unknown"
        }
    """
    capture = meta.get("capture") if isinstance(meta, dict) else {}
    if not isinstance(capture, dict):
        capture = {}

    dt_value = capture.get("datetime") or (meta.get("datetime") if isinstance(meta, dict) else None)
    offset_text = capture.get("timezone_offset") or (meta.get("timezone_offset") if isinstance(meta, dict) else None)
    gps = capture.get("gps") or (meta.get("gps") if isinstance(meta, dict) else None) or {}

    dt = _parse_datetime_iso(dt_value)
    if dt is None:
        return {
            "lighting": "unknown",
            "scene": "unknown",
            "sunrise": None,
            "sunset": None,
            "civil_dawn": None,
            "civil_dusk": None,
            "gps_used": False,
            "confidence": "low",
            "source": "unknown",
        }
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)

    offset_h = _parse_offset(offset_text) or DEFAULT_OFFSET_HOURS
    lat = gps.get("lat") if isinstance(gps, dict) else None
    lon = gps.get("lon") if isinstance(gps, dict) else None
    gps_used = bool(lat is not None and lon is not None)
    if not gps_used:
        lat = DEFAULT_LATITUDE
        lon = DEFAULT_LONGITUDE

    try:
        lighting = classify_daylight(dt, offset_h, lat, lon)
    except Exception:
        lighting = "unknown"

    scene_map = {
        "day": "daylight",
        "golden_hour": "golden_hour",
        "night": "night",
        "unknown": "unknown",
    }

    result = {
        "lighting": lighting,
        "scene": scene_map.get(lighting, "unknown"),
        "gps_used": gps_used,
        "source": "time+gps" if gps_used else "time(default_location)",
        "confidence": "high" if gps_used else "medium",
    }

    if lighting != "unknown":
        try:
            dl = compute_daylight(dt, offset_h, lat, lon)
            result["sunrise"] = dl.sunrise.isoformat() + "Z"
            result["sunset"] = dl.sunset.isoformat() + "Z"
            result["civil_dawn"] = dl.civil_dawn.isoformat() + "Z"
            result["civil_dusk"] = dl.civil_dusk.isoformat() + "Z"
        except Exception:
            result["sunrise"] = None
            result["sunset"] = None
            result["civil_dawn"] = None
            result["civil_dusk"] = None
    else:
        result["sunrise"] = None
        result["sunset"] = None
        result["civil_dawn"] = None
        result["civil_dusk"] = None

    return result
