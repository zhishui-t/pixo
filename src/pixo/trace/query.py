"""pixo.trace.query —— Trace 事件查询/过滤。

提供纯函数式过滤与分组，供 DSH/Service/测试直接使用。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .recorder import TraceEvent


def filter_events(
    events: Iterable[TraceEvent],
    *,
    photo_id: str | None = None,
    param: str | None = None,
    event_type: str | None = None,
    source: str | None = None,
) -> list[TraceEvent]:
    """按可选条件过滤 Trace 事件。"""
    result: list[TraceEvent] = []
    for event in events:
        if photo_id is not None and event.photo_id != photo_id:
            continue
        if param is not None and event.param != param:
            continue
        if event_type is not None and event.event_type != event_type:
            continue
        if source is not None and event.source != source:
            continue
        result.append(event)
    return result


def query_events(
    events: Sequence[TraceEvent],
    **kwargs: Any,
) -> list[TraceEvent]:
    """query_events = filter_events，兼容函数命名。"""
    return filter_events(events, **kwargs)


def group_by_param(events: Iterable[TraceEvent]) -> dict[str, list[TraceEvent]]:
    """按参数名分组 Trace 事件。"""
    grouped: dict[str, list[TraceEvent]] = {}
    for event in events:
        if event.param is None:
            continue
        grouped.setdefault(event.param, []).append(event)
    return grouped


__all__ = ["filter_events", "query_events", "group_by_param"]
