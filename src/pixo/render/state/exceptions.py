"""pixo.render.state.exceptions —— 状态机与 Trace 异常。"""
from __future__ import annotations


class StateError(ValueError):
    """Pixo State 相关错误基类。"""


class IllegalTransitionError(StateError):
    """非法状态转移。"""

    def __init__(
        self,
        from_state: str,
        to_state: str,
        message: str | None = None,
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        if message is None:
            message = f"非法状态转移: {from_state} -> {to_state}"
        super().__init__(message)


class InvalidTransitionReasonError(StateError):
    """转向 MANUAL_REVIEW / 需要理由的转移缺少理由。"""


class RollbackLimitError(IllegalTransitionError):
    """超过 QC 回退次数上限。"""


__all__ = [
    "StateError",
    "IllegalTransitionError",
    "InvalidTransitionReasonError",
    "RollbackLimitError",
]
