"""pixo.state.photo_state —— 照片状态模型兼容入口。"""
from __future__ import annotations

from .machine import PhotoStateMachine, StateMachine, StateRecord

__all__ = ["PhotoStateMachine", "StateMachine", "StateRecord"]
