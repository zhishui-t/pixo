"""pixo.state —— Pixo State（照片状态机）。

公共 API:
  - PhotoStateMachine: 照片状态机，服务端强校验非法转移。
  - StateRecord: 当前状态记录。
  - TraceEvent: 参数级溯源事件（自 pixo.trace 再导出）。
  - SQLiteStateTraceStore / TraceStore / StateStore: SQLite 持久化。
  - IllegalTransitionError / StateError 等异常。
"""
from __future__ import annotations

from pixo.trace import TraceEvent

from .exceptions import (
    IllegalTransitionError,
    InvalidTransitionReasonError,
    RollbackLimitError,
    StateError,
)
from .machine import (
    ALLOWED_TRANSITIONS,
    INITIAL_STATE,
    MAX_QC_ROLLBACKS,
    QC_ROLLBACK_TARGETS,
    STATES,
    TERMINAL_STATES,
    PhotoStateMachine,
    StateMachine,
    StateRecord,
)
from .store import (
    SQLiteStateStore,
    SQLiteStateTraceStore,
    SQLiteStore,
    StateStore,
    StateTraceStore,
    TraceStore,
)

__all__ = [
    "PhotoStateMachine",
    "StateMachine",
    "StateRecord",
    "TraceEvent",
    "SQLiteStateTraceStore",
    "SQLiteStore",
    "SQLiteStateStore",
    "StateStore",
    "StateTraceStore",
    "TraceStore",
    "StateError",
    "IllegalTransitionError",
    "InvalidTransitionReasonError",
    "RollbackLimitError",
    "STATES",
    "TERMINAL_STATES",
    "ALLOWED_TRANSITIONS",
    "INITIAL_STATE",
    "MAX_QC_ROLLBACKS",
    "QC_ROLLBACK_TARGETS",
]
