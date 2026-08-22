"""pixo.review.models —— 人工复核队列实体。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_REVIEW_STATUSES = ("pending", "accepted", "rejected", "edited")


def _now_iso() -> str:
    """生成带时区的 ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ReviewItem:
    """一条人工复核事项。

    before / after 为图床或文件引用，可由上层填入原图/处理图路径。
    """
    photo_id: str
    state: str = "MANUAL_REVIEW"
    unreliable_regions: list[str] = field(default_factory=list)
    rule_hits: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    before: Any = None
    after: Any = None
    agent_reason: str = ""
    escalation: str = ""
    status: str = "pending"
    edit_params: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.status not in VALID_REVIEW_STATUSES:
            raise ValueError(
                f"非法复核状态: {self.status!r}，允许: {VALID_REVIEW_STATUSES}"
            )

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "photo_id": self.photo_id,
            "state": self.state,
            "status": self.status,
            "unreliable_regions": list(self.unreliable_regions),
            "rule_hits": list(self.rule_hits),
            "trace": list(self.trace),
            "before": self.before,
            "after": self.after,
            "agent_reason": self.agent_reason,
            "escalation": self.escalation,
            "edit_params": self.edit_params,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
