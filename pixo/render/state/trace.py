"""pixo.render.state.trace —— 参数级溯源事件模型。

TraceEvent 对应架构文档 §13 的参数溯源条目，并额外记录事件类型、
迭代轮次、前后值和时间，用于完整回放参数修改链。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    """生成带时区的 ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TraceEvent:
    """一条参数/状态溯源事件。"""

    photo_id: str
    param: str | None = None
    value: Any = None
    event_type: str = "iteration"
    reason: str = ""
    rule_id: str = ""
    formula: str = ""
    source: str = ""
    knowledge_ref: str | None = None
    meta_ref: str | None = None
    old_value: Any = None
    new_value: Any = None
    iteration: int = 0
    timestamp: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "id": self.id,
            "photo_id": self.photo_id,
            "event_type": self.event_type,
            "param": self.param,
            "value": self.value,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "formula": self.formula,
            "source": self.source,
            "knowledge_ref": self.knowledge_ref,
            "meta_ref": self.meta_ref,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "before": self.old_value,
            "after": self.new_value,
            "iteration": self.iteration,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @property
    def before(self) -> Any:
        """兼容前值字段命名。"""
        return self.old_value

    @property
    def after(self) -> Any:
        """兼容后值字段命名。"""
        return self.new_value

    @property
    def time(self) -> str:
        """兼容时间字段命名。"""
        return self.timestamp

    @property
    def created_at(self) -> str:
        """兼容创建时间字段命名。"""
        return self.timestamp


__all__ = ["TraceEvent"]
