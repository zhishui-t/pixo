"""Pixo Meta —— 连拍分组 (P0-5)。

算法移植自 ``guanlan/src/rules/burst_grouping.py``，保留原边界处理:
- 单张 → standalone
- 超大组 > 10 → 拆分子组
- 跨日期 → 绝对时间差
- 残缺组 < 3 → 跳过语义优选
- 参数微调 → 严格匹配，不归一组

来源注释：
  Ported/adapted from Guanlan (观澜) src/rules/burst_grouping.py.
  原项目许可信息未在本仓库内单独列出；迁移时保留算法与注释归属。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

__all__ = [
    "detect_burst_groups",
    "group_bursts",
    "normalize_image_meta",
    "_parse_exif_params",
    "BurstGroup",
    "FrameMeta",
]


class BurstGroup(dict):
    """连拍组结果。

    同时支持 dict 访问 (``g["frame_count"]``) 和属性访问 (``g.frame_count``)，
    便于与 guanlan 参考实现及文档 §6.3 的 dict schema 兼容。
    """

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


@dataclass
class FrameMeta:
    """帧元数据（兼容 guanlan FrameMeta 命名）。"""

    file_path: str
    datetime: Optional[datetime] = None
    focal_length: Optional[float] = None
    aperture: Optional[float] = None
    shutter_speed: Optional[float] = None
    iso: Optional[int] = None


# ---------------------------------------------------------------------------
# 图像元数据归一化
# ---------------------------------------------------------------------------

def _parse_datetime(value: Any) -> Optional[datetime]:
    """解析 datetime / ISO 字符串 / EXIF 冒号字符串。

    统一归一为 **UTC naive**：aware 时间按本地时区转 UTC 后剥掉 tzinfo，
    naive 时间视为本地时区。保证混排（EXIF OffsetTime aware + mtime naive
    回退）的输入在排序/差值计算时不因 aware/naive 类型冲突崩溃。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_utc_naive(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            return _to_utc_naive(dt)
        except ValueError:
            pass
        for fmt in (
            "%Y:%m:%d %H:%M:%S",
            "%Y:%m:%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return _to_utc_naive(datetime.strptime(text, fmt))
            except ValueError:
                continue
    return None


def _to_utc_naive(dt: datetime) -> datetime:
    """aware → UTC naive；naive 视为本地时区转 UTC naive。"""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.astimezone().astimezone(timezone.utc).replace(tzinfo=None)


def _as_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        # "f/2.8"
        if text.lower().startswith("f/"):
            text = text[2:]
        if "/" in text:
            try:
                a, b = text.split("/", 1)
                return float(a) / float(b)
            except Exception:
                return None
        try:
            return float(text)
        except Exception:
            return None
    return None


def _get_field(obj: Any, *names: str):
    """从 dict / 带属性对象中取第一个字段。"""
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        else:
            try:
                return getattr(obj, name)
            except AttributeError:
                pass
    return None


def _nested(candidate: Any, section: str, field: str, default=None):
    """从可能嵌套的 dict 中取 ``section.field``。"""
    if isinstance(candidate, dict):
        sec = candidate.get(section)
        if isinstance(sec, dict):
            return sec.get(field, default)
        return default
    return default


def _first_not_none(*values):
    """取第一个非 None 值；0/False/空串等合法值不视为缺失。"""
    for v in values:
        if v is not None:
            return v
    return None


def normalize_image_meta(item: Any) -> dict:
    """把路径或元数据 dict 转成连拍聚类所需的内部字典。"""
    if isinstance(item, (str, os.PathLike)):
        path = os.fspath(item)
        from .exif import extract

        meta = extract(path)
        dt = _parse_datetime(
            _first_not_none(
                _nested(meta, "capture", "datetime"),
                _get_field(meta, "datetime"),
            )
        )
        return {
            "file_path": path,
            "datetime": dt,
            "focal_length": _as_number(
                _first_not_none(
                    _nested(meta, "exposure", "focal_length"),
                    _get_field(meta, "focal_length"),
                )
            ),
            "aperture": _as_number(
                _first_not_none(
                    _nested(meta, "exposure", "aperture_value"),
                    _nested(meta, "exposure", "aperture"),
                    _get_field(meta, "aperture"),
                )
            ),
            "shutter_speed": _as_number(
                _first_not_none(
                    _nested(meta, "exposure", "shutter_seconds"),
                    _nested(meta, "exposure", "shutter_speed"),
                    _get_field(meta, "shutter_speed"),
                )
            ),
            "iso": _as_number(
                _first_not_none(
                    _nested(meta, "exposure", "iso"),
                    _get_field(meta, "iso"),
                )
            ),
        }

    # dict 或对象输入
    file_path = (
        _get_field(item, "file_path")
        or _get_field(item, "path")
        or _get_field(item, "image_id")
    )
    capture = item.get("capture") if isinstance(item, dict) else None
    exposure = item.get("exposure") if isinstance(item, dict) else None

    def pick(field: str):
        if isinstance(exposure, dict) and field in exposure:
            return exposure[field]
        if isinstance(capture, dict) and field in capture:
            return capture[field]
        return _get_field(item, field)

    dt_value = (
        pick("datetime")
        or (capture.get("datetime") if isinstance(capture, dict) else None)
        or _get_field(item, "datetime")
    )
    focal = pick("focal_length")
    aperture = pick("aperture_value")
    if aperture is None:
        aperture = pick("aperture")
    shutter = pick("shutter_seconds")
    if shutter is None:
        shutter = pick("shutter_speed")
    iso = pick("iso")

    return {
        "file_path": str(file_path) if file_path is not None else None,
        "datetime": _parse_datetime(dt_value),
        "focal_length": _as_number(focal),
        "aperture": _as_number(aperture),
        "shutter_speed": _as_number(shutter),
        "iso": _as_number(iso),
    }


def _parse_exif_params(raw_path: str) -> FrameMeta:
    """兼容 guanlan ``_parse_exif_params``：从单张 RAW 路径提取帧元数据。"""
    meta = normalize_image_meta(raw_path)
    iso = meta.get("iso")
    return FrameMeta(
        file_path=meta.get("file_path") or str(raw_path),
        datetime=meta.get("datetime"),
        focal_length=meta.get("focal_length"),
        aperture=meta.get("aperture"),
        shutter_speed=meta.get("shutter_speed"),
        iso=int(iso) if iso is not None else None,
    )


# ---------------------------------------------------------------------------
# 分组主算法
# ---------------------------------------------------------------------------

def _make_group(
    files: list,
    frame_count: int,
    group_id: str,
    *,
    is_standalone: bool = False,
    is_oversized: bool = False,
    parent_group_id: Optional[str] = None,
    skip_vlm: bool = False,
) -> BurstGroup:
    return BurstGroup({
        "group_id": group_id,
        "files": list(files),
        "frame_count": frame_count,
        "is_standalone": is_standalone,
        "is_oversized": is_oversized,
        "parent_group_id": parent_group_id,
        "skip_vlm": skip_vlm,
        "best_frame": None,
        "all_frames": list(files),
        "frame_scores": {},
    })


def _split_oversized(files: list, max_size: int, start_counter: int) -> list:
    groups = []
    # parent_group_id 需全局唯一：start_counter 是跨组累加的全局序号，
    # 直接用作 parent 序号（每块递增），保证不同超大组不碰撞。
    parent_counter = start_counter
    for i in range(0, len(files), max_size):
        chunk = files[i:i + max_size]
        n = len(chunk)
        gid = f"burst_{start_counter:03d}"
        groups.append(_make_group(
            chunk,
            n,
            gid,
            is_oversized=True,
            parent_group_id=f"oversized_{parent_counter:03d}",
            skip_vlm=(n < 3),
        ))
        start_counter += 1
        parent_counter += 1
    return groups


def detect_burst_groups(
    images: Iterable,
    profile: Optional[dict] = None,
    *,
    max_interval_sec: float = 1.0,
    max_interval: Optional[float] = None,
    interval: Optional[float] = None,
    max_group_size: int = 10,
) -> list[dict]:
    """按时间 + 焦距 + 曝光组合三维聚类识别连拍组。

    Args:
        images: 图像路径列表，或已提取的元数据 dict 列表。
        profile: 可选相机配置字典，读取 ``profile["burst_grouping"]``。
        max_interval_sec / max_interval / interval: 同组最大时间间隔（秒）。
        max_group_size: 超大组拆分上限。

    Returns:
        ``BurstGroup`` 对应字段的 dict 列表。
    """
    if max_interval is not None:
        max_interval_sec = max_interval
    if interval is not None:
        max_interval_sec = interval
    if profile is not None and isinstance(profile, dict):
        cfg = profile.get("burst_grouping", {})
        if isinstance(cfg, dict):
            max_interval_sec = cfg.get("max_interval_sec", max_interval_sec)
            max_group_size = cfg.get("max_group_size", max_group_size)

    metas = []
    for item in images:
        try:
            meta = normalize_image_meta(item)
        except Exception:
            continue
        metas.append(meta)

    if not metas:
        return []

    # 无时间戳的照片不进时间聚类，但不得从结果中消失：各自成 standalone
    # 组返回（batch 侧据此保持输入全集可还原）。
    timed = [m for m in metas if m.get("datetime") is not None]
    untimed = [m for m in metas if m.get("datetime") is None]

    result: list[dict] = []
    for meta in untimed:
        result.append(_make_group(
            [meta["file_path"]], 1,
            f"standalone_{len(result):04d}",
            is_standalone=True, skip_vlm=True,
        ))

    if not timed:
        return result

    timed.sort(key=lambda m: m["datetime"])

    raw_groups: list[list[dict]] = []
    current_group = [timed[0]]
    for i in range(1, len(timed)):
        prev = current_group[-1]
        curr = timed[i]
        time_diff = abs((curr["datetime"] - prev["datetime"]).total_seconds())

        focal_match = (
            prev["focal_length"] is None or curr["focal_length"] is None or
            abs(prev["focal_length"] - curr["focal_length"]) < 0.1
        )
        exposure_match = (
            (prev["aperture"] is None or curr["aperture"] is None or
             abs(prev["aperture"] - curr["aperture"]) < 0.01)
            and (prev["shutter_speed"] is None or curr["shutter_speed"] is None or
                 abs(prev["shutter_speed"] - curr["shutter_speed"]) < 1e-6)
            and (prev["iso"] is None or curr["iso"] is None or
                 prev["iso"] == curr["iso"])
        )

        if time_diff <= max_interval_sec and focal_match and exposure_match:
            current_group.append(curr)
        else:
            raw_groups.append(current_group)
            current_group = [curr]
    raw_groups.append(current_group)

    group_counter = 0
    for rg in raw_groups:
        files = [m["file_path"] for m in rg]
        n = len(files)
        if n == 1:
            result.append(_make_group(
                files, n, f"standalone_{len(result):04d}",
                is_standalone=True, skip_vlm=True,
            ))
        elif n > max_group_size:
            subgroups = _split_oversized(files, max_group_size, group_counter)
            result.extend(subgroups)
            group_counter += len(subgroups)
        elif n < 3:
            result.append(_make_group(
                files, n, f"burst_{group_counter:03d}", skip_vlm=True,
            ))
            group_counter += 1
        else:
            result.append(_make_group(
                files, n, f"burst_{group_counter:03d}",
            ))
            group_counter += 1

    return result


# guanlan 兼容别名
group_bursts = detect_burst_groups
