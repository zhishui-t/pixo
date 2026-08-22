"""pixo.review.report —— 复核 CSV / HTML 报告生成。"""
from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path
from typing import Any, Iterable

from .models import ReviewItem

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")


def _stringify(value: Any) -> str:
    """把任意值转为可读字符串。"""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _item_dict(item: ReviewItem) -> dict[str, str]:
    """展开 ReviewItem 为 CSV 行。"""
    return {
        "photo_id": item.photo_id,
        "state": item.state,
        "status": item.status,
        "unreliable_regions": _stringify(item.unreliable_regions),
        "rule_hits": _stringify(item.rule_hits),
        "agent_reason": item.agent_reason,
        "escalation": item.escalation,
        "before": _stringify(item.before),
        "after": _stringify(item.after),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "edit_params": _stringify(item.edit_params),
    }


def csv_report(items: Iterable[ReviewItem], path: str | Path | None = None) -> str:
    """生成逐条复核 CSV（含列头），可选写入 path。"""
    fieldnames = [
        "photo_id", "state", "status", "unreliable_regions", "rule_hits",
        "agent_reason", "escalation", "before", "after", "created_at",
        "updated_at", "edit_params",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        writer.writerow(_item_dict(item))
    text = buf.getvalue()
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text


def summary_stats(items: Iterable[ReviewItem]) -> dict[str, Any]:
    """计算批量统计：达标、转人工、失败、吞吐等。"""
    rows = list(items)
    total = len(rows)
    accepted = sum(1 for it in rows if it.status == "accepted")
    rejected = sum(1 for it in rows if it.status == "rejected")
    edited = sum(1 for it in rows if it.status == "edited")
    pending = sum(1 for it in rows if it.status == "pending")
    manual = sum(
        1 for it in rows
        if it.status in ("pending", "edited")
        or it.state == "MANUAL_REVIEW"
        or bool(it.escalation)
    )
    processed = accepted + rejected + edited
    non_auto_fixable_rate = (manual / total) if total else 0.0

    # 吞吐：用首条与末条时间差估算每分钟可处理数；缺少时间时置 None。
    timestamps = [it.created_at for it in rows if it.created_at]
    throughput_per_minute = None
    if len(timestamps) >= 2 and timestamps[0] and timestamps[-1]:
        try:
            from datetime import datetime
            start = datetime.fromisoformat(timestamps[0])
            end = datetime.fromisoformat(timestamps[-1])
            minutes = max((end - start).total_seconds() / 60.0, 1e-9)
            throughput_per_minute = processed / minutes
        except Exception:
            throughput_per_minute = None

    return {
        "total": total,
        "accepted": accepted,
        "rejected": rejected,
        "edited": edited,
        "pending": pending,
        "manual": manual,
        "non_auto_fixable_rate": non_auto_fixable_rate,
        "processed": processed,
        "throughput_per_minute": throughput_per_minute,
    }


def csv_summary(items: Iterable[ReviewItem], path: str | Path | None = None) -> str:
    """生成批量统计 CSV（stat,value 两列）。"""
    stats = summary_stats(items)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["stat", "value"])
    for key, value in stats.items():
        writer.writerow([key, _stringify(value)])
    text = buf.getvalue()
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text


def _render_ref(value: Any) -> str:
    """把 before/after 引用渲染为 HTML；图片路径显示 img 标签。"""
    if value is None:
        return ""
    if isinstance(value, Path):
        value = str(value)
    text = html.escape(str(value))
    if isinstance(value, str) and value.lower().endswith(_IMAGE_SUFFIXES):
        return f'<img src="{text}" alt="ref" style="max-width:160px;">'
    return text


def html_report(
    items: Iterable[ReviewItem],
    path: str | Path | None = None,
    title: str = "Pixo Review Report",
) -> str:
    """生成 HTML 复核报告：概览统计 + 明细（含 before/after 图片引用）。"""
    rows = list(items)
    stats = summary_stats(rows)

    rows_html = []
    for item in rows:
        rows_html.append(
            f"<tr>"
            f"<td>{html.escape(item.photo_id)}</td>"
            f"<td>{html.escape(item.state)}</td>"
            f"<td>{html.escape(item.status)}</td>"
            f"<td>{_render_ref(item.before)}</td>"
            f"<td>{_render_ref(item.after)}</td>"
            f"<td>{html.escape(item.agent_reason)}</td>"
            f"<td>{html.escape(item.escalation)}</td>"
            f"<td>{html.escape(_stringify(item.unreliable_regions))}</td>"
            f"</tr>"
        )

    stat_items = "".join(
        f"<li><b>{html.escape(str(k))}</b>: {html.escape(_stringify(v))}</li>"
        for k, v in stats.items()
    )
    details = "\n".join(rows_html) if rows_html else "<tr><td colspan='8'>无审核项</td></tr>"

    document = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px; text-align: left; }}
th {{ background: #f0f0f0; }}
img {{ vertical-align: middle; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<h2>概览</h2>
<ul>{stat_items}</ul>
<h2>明细</h2>
<table>
<thead><tr><th>photo_id</th><th>state</th><th>status</th>
<th>before</th><th>after</th><th>agent_reason</th>
<th>escalation</th><th>unreliable_regions</th></tr></thead>
<tbody>{details}</tbody>
</table>
</body>
</html>
"""
    if path is not None:
        Path(path).write_text(document, encoding="utf-8")
    return document


__all__ = [
    "csv_report",
    "csv_summary",
    "summary_stats",
    "html_report",
    "_item_dict",
]
