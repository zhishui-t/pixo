"""pixo.state.store —— SQLite 状态与 Trace 持久化。

使用标准库 sqlite3，不引入新依赖。存储两张表：
  - photo_states: 当前状态记录。
  - trace_events: 参数/状态溯源事件流。
默认 `:memory:` 便于单测；也可传入文件路径持久化。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .machine import StateRecord
from pixo.trace import TraceEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_states (
    photo_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    iteration INTEGER NOT NULL DEFAULT 0,
    current_params TEXT NOT NULL DEFAULT '{}',
    last_measurement TEXT NOT NULL DEFAULT '{}',
    rule_hits TEXT NOT NULL DEFAULT '[]',
    next_action TEXT NOT NULL DEFAULT '',
    agent_decision TEXT NOT NULL DEFAULT '',
    qc_rollback_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    param TEXT,
    value TEXT,
    reason TEXT NOT NULL DEFAULT '',
    rule_id TEXT NOT NULL DEFAULT '',
    formula TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    knowledge_ref TEXT,
    meta_ref TEXT,
    old_value TEXT,
    new_value TEXT,
    iteration INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_trace_photo ON trace_events(photo_id);
CREATE INDEX IF NOT EXISTS idx_trace_photo_type ON trace_events(photo_id, event_type);
"""


def _json_dumps(value: Any) -> str:
    """JSON 序列化，支持简单对象；失败时退化为字符串。"""
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def _json_loads(value: str | None, default: Any = None) -> Any:
    """JSON 反序列化；空/非法时返回默认值。"""
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


class SQLiteStateTraceStore:
    """SQLite 状态与 Trace 存储。"""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── 状态记录 ──────────────────────────────────────────────
    def save_state(self, record: StateRecord) -> None:
        """写入/更新一张照片的状态记录。"""
        self._conn.execute(
            """
            INSERT INTO photo_states (
                photo_id, state, iteration, current_params, last_measurement,
                rule_hits, next_action, agent_decision, qc_rollback_count,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(photo_id) DO UPDATE SET
                state = excluded.state,
                iteration = excluded.iteration,
                current_params = excluded.current_params,
                last_measurement = excluded.last_measurement,
                rule_hits = excluded.rule_hits,
                next_action = excluded.next_action,
                agent_decision = excluded.agent_decision,
                qc_rollback_count = excluded.qc_rollback_count,
                updated_at = excluded.updated_at
            """,
            (
                record.photo_id,
                record.state,
                int(record.iteration),
                _json_dumps(record.current_params),
                _json_dumps(record.last_measurement),
                _json_dumps(record.rule_hits),
                record.next_action,
                record.agent_decision,
                int(record.qc_rollback_count),
                record.updated_at,
            ),
        )
        self._conn.commit()

    def load_state(self, photo_id: str) -> StateRecord | None:
        """按 photo_id 加载状态记录；不存在返回 None。"""
        row = self._conn.execute(
            "SELECT * FROM photo_states WHERE photo_id = ?", (photo_id,)
        ).fetchone()
        if row is None:
            return None
        return StateRecord(
            photo_id=row["photo_id"],
            state=row["state"],
            iteration=int(row["iteration"]),
            current_params=_json_loads(row["current_params"], default={}),
            last_measurement=_json_loads(row["last_measurement"], default={}),
            rule_hits=_json_loads(row["rule_hits"], default=[]),
            next_action=row["next_action"] or "",
            agent_decision=row["agent_decision"] or "",
            qc_rollback_count=int(row["qc_rollback_count"]),
            updated_at=row["updated_at"] or "",
        )

    def list_states(self) -> list[StateRecord]:
        """返回所有照片状态记录。"""
        rows = self._conn.execute(
            "SELECT * FROM photo_states ORDER BY photo_id"
        ).fetchall()
        return [self._state_from_row(row) for row in rows]

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> StateRecord:
        return StateRecord(
            photo_id=row["photo_id"],
            state=row["state"],
            iteration=int(row["iteration"]),
            current_params=_json_loads(row["current_params"], default={}),
            last_measurement=_json_loads(row["last_measurement"], default={}),
            rule_hits=_json_loads(row["rule_hits"], default=[]),
            next_action=row["next_action"] or "",
            agent_decision=row["agent_decision"] or "",
            qc_rollback_count=int(row["qc_rollback_count"]),
            updated_at=row["updated_at"] or "",
        )

    # ── Trace 事件 ────────────────────────────────────────────
    def add_trace(
        self,
        event: TraceEvent | None = None,
        **kwargs: Any,
    ) -> int:
        """写入一条 Trace 事件，返回自增 id。

        支持直接传 TraceEvent，也支持按字段关键字创建。
        """
        if event is None:
            event = TraceEvent(**kwargs)
        cursor = self._conn.execute(
            """
            INSERT INTO trace_events (
                photo_id, event_type, param, value, reason, rule_id,
                formula, source, knowledge_ref, meta_ref, old_value,
                new_value, iteration, timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.photo_id,
                event.event_type,
                event.param,
                _json_dumps(event.value),
                event.reason or "",
                event.rule_id or "",
                event.formula or "",
                event.source or "",
                event.knowledge_ref,
                event.meta_ref,
                _json_dumps(event.old_value),
                _json_dumps(event.new_value),
                int(event.iteration),
                event.timestamp,
                _json_dumps(event.metadata),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    add_event = add_trace
    add = add_trace
    record_trace = add_trace
    append = add_trace

    def query_traces(
        self,
        photo_id: str,
        param: str | None = None,
        event_type: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[TraceEvent]:
        """按 photo_id 查询溯源事件，可按 param/event_type/source 过滤。"""
        sql = "SELECT * FROM trace_events WHERE photo_id = ?"
        args: list[Any] = [photo_id]
        if param is not None:
            sql += " AND param = ?"
            args.append(param)
        if event_type is not None:
            sql += " AND event_type = ?"
            args.append(event_type)
        if source is not None:
            sql += " AND source = ?"
            args.append(source)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        rows = self._conn.execute(sql, args).fetchall()
        return [self._event_from_row(row) for row in rows]

    history = query_traces
    query = query_traces
    events = query_traces
    list_traces = query_traces
    get_history = query_traces

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> TraceEvent:
        return TraceEvent(
            id=int(row["id"]),
            photo_id=row["photo_id"],
            event_type=row["event_type"],
            param=row["param"],
            value=_json_loads(row["value"]),
            reason=row["reason"] or "",
            rule_id=row["rule_id"] or "",
            formula=row["formula"] or "",
            source=row["source"] or "",
            knowledge_ref=row["knowledge_ref"],
            meta_ref=row["meta_ref"],
            old_value=_json_loads(row["old_value"]),
            new_value=_json_loads(row["new_value"]),
            iteration=int(row["iteration"]),
            timestamp=row["timestamp"],
            metadata=_json_loads(row["metadata"], default={}),
        )

    # ── 工具方法 ──────────────────────────────────────────────
    def clear(self) -> None:
        """清空所有状态与 Trace 数据。"""
        self._conn.execute("DELETE FROM photo_states")
        self._conn.execute("DELETE FROM trace_events")
        self._conn.commit()

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()


# 快捷别名
SQLiteStore = SQLiteStateTraceStore
SQLiteStateStore = SQLiteStateTraceStore
StateStore = SQLiteStateTraceStore
StateTraceStore = SQLiteStateTraceStore
TraceStore = SQLiteStateTraceStore


__all__ = [
    "SQLiteStateTraceStore",
    "SQLiteStore",
    "SQLiteStateStore",
    "StateStore",
    "StateTraceStore",
    "TraceStore",
]
