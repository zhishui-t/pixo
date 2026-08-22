"""pixo.review.queue —— 人工复核队列与审核动作。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .models import ReviewItem

TraceWriter = Callable[..., Any]


def _now_iso() -> str:
    """生成带时区的 ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewError(ValueError):
    """复核队列非法操作错误。"""


class ReviewQueue:
    """内存复核队列，支持入队/查询/接受/拒绝/编辑，并写 Trace。

    trace_store 可以是一个带 ``add_trace`` 方法的对象，也可以是一个
    可调用对象；本期不绑定具体持久化实现。
    """

    def __init__(self, trace_store: Any | None = None) -> None:
        self._items: dict[str, ReviewItem] = {}
        self.trace_store = trace_store

    def _write_trace(self, event_type: str, item: ReviewItem, **extra: Any) -> None:
        metadata = {
            "review_status": item.status,
            "agent_reason": item.agent_reason,
            "escalation": item.escalation,
            **extra,
        }
        if self.trace_store is None:
            return
        if hasattr(self.trace_store, "add_trace"):
            try:
                from pixo.trace import TraceEvent

                self.trace_store.add_trace(TraceEvent(
                    photo_id=item.photo_id,
                    event_type=event_type,
                    value=item.to_dict(),
                    reason=item.agent_reason or "复核队列动作",
                    metadata=metadata,
                ))
            except Exception:
                # 复核不因 Trace 写入失败而阻断。
                pass
        elif callable(self.trace_store):
            try:
                self.trace_store(event_type, item, metadata)
            except Exception:
                pass

    def enqueue(self, item: ReviewItem) -> ReviewItem:
        """入队；同一 photo_id 重复入队时覆盖旧项。"""
        if item.status != "pending":
            raise ReviewError(f"入队项状态必须是 pending，实际: {item.status!r}")
        if item.photo_id in self._items:
            raise ReviewError(f"photo_id 已在队列中: {item.photo_id}")
        self._items[item.photo_id] = item
        self._write_trace("review.enqueue", item)
        return item

    def get(self, photo_id: str) -> ReviewItem:
        """按 photo_id 取审核项；不存在抛 ReviewError。"""
        item = self._items.get(photo_id)
        if item is None:
            raise ReviewError(f"复核队列不存在 photo_id: {photo_id}")
        return item

    def list(self, status: str | None = None) -> list[ReviewItem]:
        """按状态过滤队列；status=None 返回全部（按入队顺序）。"""
        items = list(self._items.values())
        if status is None:
            return items
        return [item for item in items if item.status == status]

    def _require_pending(self, photo_id: str) -> ReviewItem:
        item = self.get(photo_id)
        if item.status != "pending":
            raise ReviewError(
                f"photo_id={photo_id} 状态为 {item.status!r}，只有 pending 可审核"
            )
        return item

    def accept(self, photo_id: str, reason: str = "人工接受") -> ReviewItem:
        """接受结果：状态 accepted，state 置 ACCEPTED。"""
        item = self._require_pending(photo_id)
        item.state = "ACCEPTED"
        item.status = "accepted"
        item.updated_at = _now_iso()
        item.agent_reason = reason or item.agent_reason
        self._write_trace("review.accept", item)
        return item

    def reject(self, photo_id: str, reason: str = "人工拒绝") -> ReviewItem:
        """拒绝/废片：状态 rejected，state 置 REJECTED。"""
        item = self._require_pending(photo_id)
        item.state = "REJECTED"
        item.status = "rejected"
        item.updated_at = _now_iso()
        item.agent_reason = reason or item.agent_reason
        self._write_trace("review.reject", item)
        return item

    def edit(
        self,
        photo_id: str,
        *,
        reason: str = "人工编辑",
        edit_params: dict[str, Any] | None = None,
        after: Any = None,
    ) -> ReviewItem:
        """进入编辑：状态 edited；可携带用户锁定参数与新的 after 引用。"""
        item = self._require_pending(photo_id)
        if edit_params is not None:
            item.edit_params = dict(edit_params)
        if after is not None:
            item.after = after
        item.state = "EDITING"
        item.status = "edited"
        item.updated_at = _now_iso()
        item.agent_reason = reason or item.agent_reason
        self._write_trace("review.edit", item, edit_params=item.edit_params)
        return item
