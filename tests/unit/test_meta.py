"""P0-5 单元测试：Pixo Meta 基础（EXIF/连拍/光照）。

覆盖：
  - 标准 EXIF 字段提取/标准化
  - 缺字段不抛异常
  - GPS 解析与剥离隐私选项
  - 连拍分组（与 guanlan 参考实现一致）
  - 基础光照/场景推断
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from render.meta import (
    detect_burst_groups,
    extract,
    infer_lighting_context,
    normalize_exif,
    parse_exif_time,
    strip_gps,
)
from render.meta.lighting import classify_daylight


# ---------------------------------------------------------------------------
# 工具/固定数据
# ---------------------------------------------------------------------------

_STANDARD_TAGS = {
    "Image Make": "NIKON",
    "Image Model": "Z 6",
    "EXIF LensModel": "NIKKOR Z 50mm f/1.8 S",
    "EXIF DateTimeOriginal": "2026:08:18 17:32:45",
    "EXIF SubSecTimeOriginal": "123",
    "EXIF OffsetTimeOriginal": "+08:00",
    "EXIF FNumber": 1.8,
    "EXIF ExposureTime": 0.002,
    "EXIF ISOSpeedRatings": 100,
    "EXIF FocalLength": 50.0,
    "EXIF ExposureBiasValue": 0.0,
    "EXIF MeteringMode": 5,
    "EXIF Flash": 0,
    "EXIF WhiteBalance": 0,
    "Image Orientation": 1,
}


class _FakeTag:
    """模拟 exifread IfdTag 的极简替身。"""

    def __init__(self, values, printable=None):
        self.values = values
        self.printable = printable if printable is not None else str(values)

    def __str__(self):
        return self.printable


_GPS_TAGS = {
    "GPS GPSLatitude": _FakeTag([31, 13, 49.44]),
    "GPS GPSLatitudeRef": "N",
    "GPS GPSLongitude": _FakeTag([121, 28, 25.2]),
    "GPS GPSLongitudeRef": "E",
    "GPS GPSAltitude": _FakeTag([4.5]),
    "GPS GPSAltitudeRef": "0",
}


def _img(i, base=None, interval=0.5, aperture=2.8, shutter=1 / 500, iso=100, focal=50.0):
    if base is None:
        base = datetime(2026, 7, 29, 15, 30, 0)
    return {
        "path": f"/test/DSC_{1000 + i:04d}.NEF",
        "datetime": base + timedelta(seconds=i * interval),
        "focal_length": focal,
        "aperture": aperture,
        "shutter_speed": shutter,
        "iso": iso,
    }


# ---------------------------------------------------------------------------
# EXIF 提取/标准化
# ---------------------------------------------------------------------------

def test_standard_exif_fields():
    meta = normalize_exif(_STANDARD_TAGS, image_id="DSC_5722")

    assert meta["image_id"] == "DSC_5722"
    assert meta["camera"]["make"] == "NIKON"
    assert meta["camera"]["model"] == "Z 6"
    assert meta["camera"]["lens"] == "NIKKOR Z 50mm f/1.8 S"
    assert meta["capture"]["datetime"].startswith("2026-08-18T17:32:45")
    assert meta["capture"]["timezone_offset"] == "+08:00"
    assert meta["capture"]["orientation"] == 1
    assert meta["capture"]["gps"] is None
    assert meta["exposure"]["aperture"] == "f/1.8"
    assert meta["exposure"]["aperture_value"] == pytest.approx(1.8)
    assert meta["exposure"]["shutter_speed"] == "1/500"
    assert meta["exposure"]["shutter_seconds"] == pytest.approx(0.002)
    assert meta["exposure"]["iso"] == 100
    assert meta["exposure"]["exposure_compensation"] == pytest.approx(0.0)
    assert meta["exposure"]["metering_mode"] == "matrix"
    assert meta["exposure"]["flash"] == "off"
    assert meta["exposure"]["focal_length"] == pytest.approx(50.0)
    assert meta["white_balance"]["as_shot"] == "auto"
    assert meta["shot_context"]["burst_group"] is None


def test_missing_exif_graceful():
    meta = normalize_exif({}, image_id="empty")

    for section in ("camera", "capture", "exposure", "white_balance", "shot_context"):
        assert isinstance(meta[section], dict)
    assert meta["camera"]["make"] is None
    assert meta["camera"]["lens"] is None
    assert meta["capture"]["datetime"] is None
    assert meta["capture"]["gps"] is None
    assert meta["exposure"]["iso"] is None
    assert meta["white_balance"]["as_shot"] is None


def test_gps_parsing():
    meta = normalize_exif(_GPS_TAGS, image_id="gps")
    gps = meta["capture"]["gps"]
    assert gps is not None
    assert gps["lat"] == pytest.approx(31.2304, abs=1e-4)
    assert gps["lon"] == pytest.approx(121.4737, abs=1e-4)
    assert gps["altitude"] == pytest.approx(4.5)


def test_privacy_strips_gps():
    meta = normalize_exif(_GPS_TAGS, image_id="gps")
    stripped = strip_gps(meta)
    assert stripped["capture"]["gps"] is None
    # 原字典不受影响
    assert meta["capture"]["gps"] is not None

    meta2 = normalize_exif(_GPS_TAGS, image_id="gps", strip_gps=True)
    assert meta2["capture"]["gps"] is None

    meta3 = normalize_exif(_GPS_TAGS, image_id="gps", include_gps=False)
    assert meta3["capture"]["gps"] is None


def test_extract_integration(monkeypatch, tmp_path):
    import exifread

    def fake_process(f, details=False):
        return dict(_STANDARD_TAGS)

    monkeypatch.setattr(exifread, "process_file", fake_process)
    path = tmp_path / "DSC_5722.NEF"
    path.write_bytes(b"not-a-real-raw")
    meta = extract(path)
    assert meta["image_id"] == "DSC_5722"
    assert meta["camera"]["make"] == "NIKON"
    assert meta["exposure"]["iso"] == 100


# ---------------------------------------------------------------------------
# 连拍分组
# ---------------------------------------------------------------------------

def test_burst_5_frames_grouped():
    images = [_img(i) for i in range(5)]
    groups = detect_burst_groups(images)
    assert len(groups) == 1
    assert groups[0]["frame_count"] == 5
    assert groups[0]["is_standalone"] is False
    assert groups[0]["skip_vlm"] is False
    assert groups[0]["group_id"] == "burst_000"


def test_two_isolated_frames_standalone():
    images = [_img(0, interval=0.0), _img(1, interval=3.0)]
    groups = detect_burst_groups(images)
    assert len(groups) == 2
    assert all(g["is_standalone"] for g in groups)


def test_cross_midnight_absolute_time():
    images = [
        {"path": "a.NEF", "datetime": datetime(2026, 7, 29, 23, 59, 59),
         "focal_length": 50.0, "aperture": 2.8, "shutter_speed": 1 / 500, "iso": 100},
        {"path": "b.NEF", "datetime": datetime(2026, 7, 30, 0, 0, 0),
         "focal_length": 50.0, "aperture": 2.8, "shutter_speed": 1 / 500, "iso": 100},
    ]
    groups = detect_burst_groups(images)
    assert len(groups) == 1
    assert groups[0]["frame_count"] == 2


def test_aperture_change_splits_group():
    images = [_img(i, interval=0.5) for i in range(4)]
    images[2] = dict(images[2], aperture=4.0)
    images[3] = dict(images[3], aperture=4.0)
    groups = detect_burst_groups(images)
    assert len(groups) == 2
    assert groups[0]["frame_count"] == 2
    assert groups[1]["frame_count"] == 2


def test_oversized_group_split():
    images = [_img(i, interval=0.3) for i in range(15)]
    groups = detect_burst_groups(images)
    assert len(groups) == 2
    assert groups[0]["frame_count"] == 10
    assert groups[1]["frame_count"] == 5
    assert groups[0]["is_oversized"] is True
    assert groups[1]["is_oversized"] is True


def test_profile_controls_max_interval():
    images = [_img(0), _img(1, interval=2.0)]
    groups = detect_burst_groups(images, {"burst_grouping": {"max_interval_sec": 2.0}})
    assert len(groups) == 1
    assert groups[0]["frame_count"] == 2


# ---------------------------------------------------------------------------
# 光照推断
# ---------------------------------------------------------------------------

def test_infer_lighting_day_with_gps():
    meta = {
        "capture": {
            "datetime": "2026-08-18T12:00:00+08:00",
            "timezone_offset": "+08:00",
            "gps": {"lat": 39.9, "lon": 116.4},
        }
    }
    ctx = infer_lighting_context(meta)
    assert ctx["lighting"] == "day"
    assert ctx["scene"] == "daylight"
    assert ctx["gps_used"] is True
    assert ctx["source"] == "time+gps"
    assert ctx["confidence"] == "high"


def test_infer_lighting_missing_datetime_unknown():
    ctx = infer_lighting_context({})
    assert ctx["lighting"] == "unknown"
    assert ctx["scene"] == "unknown"


def test_classify_night():
    assert classify_daylight(datetime(2026, 8, 18, 23, 0, 0), 8.0) == "night"


def test_parse_exif_time_default_offset():
    dt, off = parse_exif_time("2026:08:18 17:32:45")
    assert dt == datetime(2026, 8, 18, 17, 32, 45)
    assert off == pytest.approx(8.0)
    dt2, off2 = parse_exif_time("2026:08:18 17:32:45", "-05:00")
    assert off2 == pytest.approx(-5.0)
