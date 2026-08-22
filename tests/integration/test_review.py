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
    q = ReviewQueue()
    item = _item()
    q.enqueue(item)
    assert q.get("P001") is item
    assert len(q.list()) == 1
    assert q.list("pending") == [item]
    with pytest.raises(ReviewError):
        q.enqueue(item)


def test_invalid_review_status_raises():
    with pytest.raises(ValueError, match="非法复核状态"):
        ReviewItem(photo_id="BAD", status="unknown")


def test_accept_reject_edit_actions():
    q = ReviewQueue()
    q.enqueue(_item("A"))
    a = q.accept("A", reason="通过")
    assert a.status == "accepted" and a.state == "ACCEPTED"

    q.enqueue(_item("B"))
    b = q.reject("B", reason="废片")
    assert b.status == "rejected" and b.state == "REJECTED"

    q.enqueue(_item("C"))
    c = q.edit("C", edit_params={"exposure": {"mode": 0.3}}, after="/tmp/edited.jpg")
    assert c.status == "edited" and c.state == "EDITING"
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
