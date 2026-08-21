"""pixo.review.trace_export —— 单张 Trace JSON / 多张 CSV 导出。"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable

from .models import ReviewItem


def _as_trace_events(trace_source: Any) -> list[dict[str, Any]]:
    """把 ReviewItem / 事件列表 / TraceEvent 对象统一转为 dict 列表。"""
    item: ReviewItem | None = None
    if isinstance(trace_source, ReviewItem):
        item = trace_source
        raw = trace_source.trace
    elif isinstance(trace_source, dict):
        raw = trace_source.get("trace", [])
    else:
        raw = trace_source
    events: list[dict[str, Any]] = []
    for event in list(raw or []):
        if hasattr(event, "to_dict"):
            converted = event.to_dict()
        elif isinstance(event, dict):
            converted = dict(event)
        else:
            converted = {"value": str(event)}
        if item is not None and "photo_id" not in converted:
            converted["photo_id"] = item.photo_id
        events.append(converted)
    return events


def export_trace_json(
    trace_source: Any,
    path: str | Path | None = None,
    *,
    indent: int = 2,
) -> str:
    """导出单张 Trace 为 JSON 字符串，可选写入 path。"""
    events = _as_trace_events(trace_source)
    text = json.dumps(events, ensure_ascii=False, indent=indent, default=str)
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text


def export_trace_csv(
    items: Iterable[Any],
    path: str | Path | None = None,
) -> str:
    """导出多张 Trace 为 CSV（每个事件一行）。"""
    fieldnames = [
        "photo_id", "event_type", "param", "value", "reason", "rule_id",
        "source", "iteration", "old_value", "new_value", "before", "after",
        "timestamp", "metadata",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        photo_id = item.photo_id if isinstance(item, ReviewItem) else ""
        for event in _as_trace_events(item):
            row = {
                "photo_id": event.get("photo_id", photo_id),
                "event_type": event.get("event_type", ""),
                "param": event.get("param", "") or "",
                "value": json.dumps(event.get("value"), ensure_ascii=False, default=str)
                         if event.get("value") is not None else "",
                "reason": event.get("reason", "") or "",
                "rule_id": event.get("rule_id", "") or "",
                "source": event.get("source", "") or "",
                "iteration": event.get("iteration", "") or "",
                "old_value": json.dumps(event.get("old_value"), ensure_ascii=False, default=str)
                               if event.get("old_value") is not None else "",
                "new_value": json.dumps(event.get("new_value"), ensure_ascii=False, default=str)
                               if event.get("new_value") is not None else "",
                "before": json.dumps(event.get("before", event.get("old_value")), ensure_ascii=False, default=str)
                           if event.get("before", event.get("old_value")) is not None else "",
                "after": json.dumps(event.get("after", event.get("new_value")), ensure_ascii=False, default=str)
                          if event.get("after", event.get("new_value")) is not None else "",
                "timestamp": event.get("timestamp", "") or "",
                "metadata": json.dumps(event.get("metadata"), ensure_ascii=False, default=str)
                             if event.get("metadata") is not None else "",
            }
            writer.writerow(row)
    text = buf.getvalue()
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text


__all__ = ["export_trace_json", "export_trace_csv"]
