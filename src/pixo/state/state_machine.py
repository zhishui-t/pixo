"""pixo.state.state_machine —— 状态机兼容入口。"""
from __future__ import annotations

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

__all__ = [
    "PhotoStateMachine",
    "StateMachine",
    "StateRecord",
    "STATES",
    "TERMINAL_STATES",
    "ALLOWED_TRANSITIONS",
    "INITIAL_STATE",
    "MAX_QC_ROLLBACKS",
    "QC_ROLLBACK_TARGETS",
]
