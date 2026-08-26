"""P2-4 单元测试：ReviewQueue / CSV / HTML / Trace 导出。"""
from __future__ import annotations

from pathlib import Path

import pytest

from pixo.review import (
    ReviewError,
    ReviewItem,
    ReviewQueue,
    csv_report,
    csv_summary,
    export_trace_csv,
    export_trace_json,
    html_report,
    summary_stats,
)


def _item(photo_id="P001", **overrides) -> ReviewItem:
    data = {
        "photo_id": photo_id,
        "state": "MANUAL_REVIEW",
        "unreliable_regions": ["face"],
        "rule_hits": [{"rule_id": "R1", "reason": "不可靠"}],
        "trace": [{"event_type": "decide", "param": "exposure", "value": 0.2}],
        "before": "/tmp/before.jpg",
        "after": "/tmp/after.jpg",
        "agent_reason": "需要人工确认",
        "escalation": "AGENT_ESCALATED",
    }
    data.update(overrides)
    return ReviewItem(**data)


class TraceStore:
    """记录 TraceEvent 的测试替身。"""

    def __init__(self) -> None:
        self.events = []

    def add_trace(self, event) -> int:
        self.events.append(event)
        return len(self.events)


def test_enqueue_get_list_and_duplicate():
    """重复 photo_id 入队按 docstring 覆盖旧项而非报错。"""
    q = ReviewQueue()
    item = _item()
    q.enqueue(item)
    assert q.get("P001") is item
    assert len(q.list()) == 1
    assert q.list("pending") == [item]

    replacement = _item()  # 同 photo_id 的新待审项
    returned = q.enqueue(replacement)
    assert returned is replacement
    assert q.get("P001") is replacement
    assert len(q.list()) == 1

    with pytest.raises(ReviewError):
        q.enqueue(_item("P002", status="accepted"))  # 非 pending 仍拒绝


def test_invalid_review_status_raises():
    with pytest.raises(ValueError, match="非法复核状态"):
        ReviewItem(photo_id="BAD", status="unknown")


def test_accept_reject_edit_actions():
    """无状态机（缺省）路径：accept/reject 直接置目标 state；edit 不改 state。"""
    q = ReviewQueue()
    q.enqueue(_item("A"))
    a = q.accept("A", reason="通过")
    assert a.status == "accepted" and a.state == "ACCEPTED"

    q.enqueue(_item("B"))
    b = q.reject("B", reason="废片")
    assert b.status == "rejected" and b.state == "REJECTED"

    q.enqueue(_item("C"))
    c = q.edit("C", edit_params={"exposure": {"mode": 0.3}}, after="/tmp/edited.jpg")
    assert c.status == "edited"
    # 语义变化：不再写不在状态机词表的 "EDITING" 死值，state 保持不变。
    assert c.state == "MANUAL_REVIEW"
    assert c.edit_params == {"exposure": {"mode": 0.3}}
    assert c.after == "/tmp/edited.jpg"


def test_illegal_action_on_non_pending():
    q = ReviewQueue()
    q.enqueue(_item("X"))
    q.accept("X")
    with pytest.raises(ReviewError):
        q.reject("X")
    with pytest.raises(ReviewError):
        q.edit("X")
    with pytest.raises(ReviewError):
        q.accept("X")


def test_queue_writes_trace():
    store = TraceStore()
    q = ReviewQueue(trace_store=store)
    q.enqueue(_item("T"))
    q.accept("T")
    types = [e.event_type for e in store.events]
    assert "review.enqueue" in types
    assert "review.accept" in types


def test_enqueue_duplicate_writes_overwrite_trace():
    """重复入队覆盖旧项时，trace 元数据注明 overwritten。"""
    store = TraceStore()
    q = ReviewQueue(trace_store=store)
    q.enqueue(_item("D1"))
    q.enqueue(_item("D1"))
    enq = [e for e in store.events if e.event_type == "review.enqueue"]
    assert len(enq) == 2
    assert enq[0].metadata.get("overwritten") is False
    assert enq[1].metadata.get("overwritten") is True


def _machine_factory():
    """构造 photo_id → PhotoStateMachine 工厂（新照片停在 MANUAL_REVIEW）。"""
    from pixo.state import PhotoStateMachine

    machines: dict = {}

    def factory(photo_id: str):
        sm = machines.get(photo_id)
        if sm is None:
            sm = PhotoStateMachine(photo_id)
            sm.transition("SCREENED")
            sm.escalate("需要人工复核")
            machines[photo_id] = sm
        return sm

    return factory, machines


def test_queue_with_machines_drives_state_transitions():
    """注入状态机工厂：accept/reject/edit 驱动真实转移并镜像 sm.state。"""
    factory, machines = _machine_factory()
    q = ReviewQueue(machines=factory)

    q.enqueue(_item("M1"))
    a = q.accept("M1", reason="人工验收")
    assert machines["M1"].state == "ACCEPTED"
    assert a.state == "ACCEPTED"
    assert any(e.event_type == "REVIEW_ACCEPTED"
               for e in machines["M1"].history())

    q.enqueue(_item("M2"))
    b = q.reject("M2", reason="废片")
    assert machines["M2"].state == "REJECTED"
    assert b.state == "REJECTED"
    assert any(e.event_type == "REVIEW_REJECTED"
               for e in machines["M2"].history())

    q.enqueue(_item("M3"))
    c = q.edit("M3", edit_params={"exposure": {"mode": 0.3}})
    assert c.status == "edited"
    assert c.state == "COLOR_CORRECTING"  # 回锅调色，不再出现 EDITING
    assert machines["M3"].state == "COLOR_CORRECTING"
    assert any(e.event_type == "REVIEW_EDIT" for e in machines["M3"].history())


def test_queue_without_machines_keeps_default_behavior():
    """缺省（machines=None）保持纯内存行为，不触发任何状态机。"""
    q = ReviewQueue()
    q.enqueue(_item("N1"))
    a = q.accept("N1")
    assert a.state == "ACCEPTED" and a.status == "accepted"


def test_csv_report_and_summary():
    items = [
        _item("A", status="accepted", state="ACCEPTED"),
        _item("B", status="rejected", state="REJECTED"),
        _item("C"),
    ]
    csv_text = csv_report(items)
    assert "photo_id" in csv_text
    assert "A" in csv_text and "B" in csv_text and "C" in csv_text

    summary = summary_stats(items)
    assert summary["total"] == 3
    assert summary["accepted"] == 1
    assert summary["rejected"] == 1
    assert summary["pending"] == 1
    assert summary["manual"] >= 1

    summary_csv = csv_summary(items)
    assert "stat,value" in summary_csv
    assert "accepted,1" in summary_csv


def test_html_report_contains_images_and_details():
    items = [_item("IMG1")]
    text = html_report(items, title="Pixo 复核报告")
    assert "Pixo 复核报告" in text
    assert "IMG1" in text
    assert "/tmp/before.jpg" in text
    assert "<img" in text


def test_trace_export_json_and_csv():
    item = _item("TRACE1", trace=[
        {"event_type": "decide", "param": "exposure", "value": 0.2,
         "reason": "提亮", "source": "decide", "timestamp": "2026-01-01T00:00:00Z"},
        {"event_type": "review.accept", "param": None, "value": "ok",
         "source": "review"},
    ])
    json_text = export_trace_json(item)
    assert "decide" in json_text
    assert "TRACE1" in json_text

    csv_text = export_trace_csv([item])
    assert "event_type" in csv_text
    assert "decide" in csv_text
    assert "review.accept" in csv_text


def test_report_writes_files(tmp_path):
    item = _item("FILE1")
    csv_path = tmp_path / "review.csv"
    html_path = tmp_path / "review.html"
    json_path = tmp_path / "trace.json"
    csv_report([item], path=csv_path)
    html_report([item], path=html_path)
    export_trace_json(item, path=json_path)
    assert csv_path.exists()
    assert html_path.exists()
    assert json_path.exists()
    assert "FILE1" in csv_path.read_text(encoding="utf-8")
    assert "FILE1" in html_path.read_text(encoding="utf-8")
    assert "FILE1" in json_path.read_text(encoding="utf-8")
