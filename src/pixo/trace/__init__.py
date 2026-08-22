"""pixo.trace —— 参数级溯源事件模型与查询。

包含:
  - TraceEvent: 溯源事件记录。
  - recorder: 事件模型与后续记录器入口。
  - query: 事件过滤/分组查询工具。
"""
from __future__ import annotations

from .query import filter_events, group_by_param, query_events
from .recorder import TraceEvent, TraceRecorder

__all__ = [
    "TraceEvent",
    "TraceRecorder",
    "filter_events",
    "query_events",
    "group_by_param",
]
