"""pixo.state.machine —— 照片状态机与服务端强校验。

状态顺序与补充转移对齐 docs/架构设计文档.md §11.1：
  RAW_PENDING → SCREENED → BASE_RENDERED → EXPOSURE_ALIGNING
  → COLOR_CORRECTING → STYLE_APPLIED → FINAL_QC
  → ACCEPTED / MANUAL_REVIEW / REJECTED

补充约束：
  - 任意迭代状态可经 AGENT_ESCALATED 转 MANUAL_REVIEW，必须带 reason。
  - FINAL_QC 可回退到 EXPOSURE_ALIGNING / COLOR_CORRECTING，限一次。
  - FINAL_QC 二次超标不再自动回退，应转 MANUAL_REVIEW。
  - MANUAL_REVIEW 不是终态（对 §11.1 原图约束的修订）：人工复核后可出边
    ACCEPTED / REJECTED 结案，或回 COLOR_CORRECTING 回锅调色，避免状态机
    在人工复核队列驱动下卡死。终态仅 ACCEPTED / REJECTED。
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .exceptions import (
    IllegalTransitionError,
    InvalidTransitionReasonError,
    RollbackLimitError,
)
from pixo.trace import TraceEvent

_LOGGER = logging.getLogger(__name__)

INITIAL_STATE = "RAW_PENDING"

STATES = (
    "RAW_PENDING",
    "SCREENED",
    "BASE_RENDERED",
    "EXPOSURE_ALIGNING",
    "COLOR_CORRECTING",
    "STYLE_APPLIED",
    "FINAL_QC",
    "ACCEPTED",
    "MANUAL_REVIEW",
    "REJECTED",
)

# MANUAL_REVIEW 已非终态（可经人工复核出边），终态仅剩 ACCEPTED/REJECTED。
TERMINAL_STATES = {"ACCEPTED", "REJECTED"}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "RAW_PENDING": {"SCREENED"},
    "SCREENED": {"BASE_RENDERED", "MANUAL_REVIEW"},
    "BASE_RENDERED": {"EXPOSURE_ALIGNING", "MANUAL_REVIEW"},
    "EXPOSURE_ALIGNING": {"COLOR_CORRECTING", "MANUAL_REVIEW"},
    "COLOR_CORRECTING": {"STYLE_APPLIED", "MANUAL_REVIEW"},
    "STYLE_APPLIED": {"FINAL_QC", "MANUAL_REVIEW"},
    "FINAL_QC": {
        "ACCEPTED",
        "REJECTED",
        "MANUAL_REVIEW",
        "COLOR_CORRECTING",
        "EXPOSURE_ALIGNING",
    },
    "ACCEPTED": set(),
    # 人工复核出边：接受 / 拒绝 / 回锅调色（§11.1 修订，见模块头）。
    "MANUAL_REVIEW": {"ACCEPTED", "REJECTED", "COLOR_CORRECTING"},
    "REJECTED": set(),
}

_MAX_QC_ROLLBACKS = 1
MAX_QC_ROLLBACKS = _MAX_QC_ROLLBACKS
QC_ROLLBACK_TARGETS = {"EXPOSURE_ALIGNING", "COLOR_CORRECTING"}

# transition 会改写的 StateRecord 字段（落盘失败时逐字段回滚）。
_RECORD_MUTABLE_FIELDS = (
    "state",
    "iteration",
    "current_params",
    "last_measurement",
    "rule_hits",
    "next_action",
    "agent_decision",
    "qc_rollback_count",
    "updated_at",
)


def _now_iso() -> str:
    """生成带时区的 ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class StateRecord:
    """单张照片的当前状态记录（对应文档 §11.2 结构）。"""

    photo_id: str
    state: str = INITIAL_STATE
    iteration: int = 0
    current_params: dict[str, Any] = field(default_factory=dict)
    last_measurement: dict[str, Any] = field(default_factory=dict)
    rule_hits: list[dict[str, Any]] = field(default_factory=list)
    next_action: str = ""
    agent_decision: str = ""
    qc_rollback_count: int = 0
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "photo_id": self.photo_id,
            "state": self.state,
            "iteration": self.iteration,
            "current_params": self.current_params,
            "last_measurement": self.last_measurement,
            "rule_hits": self.rule_hits,
            "next_action": self.next_action,
            "agent_decision": self.agent_decision,
            "qc_rollback_count": self.qc_rollback_count,
            "updated_at": self.updated_at,
        }


class PhotoStateMachine:
    """单张照片的状态机。

    支持传入 SQLiteStateTraceStore 做持久化；不传时使用进程内状态和历史，
    便于纯逻辑单测。
    """

    states = STATES
    allowed_transitions = ALLOWED_TRANSITIONS
    max_qc_rollbacks = MAX_QC_ROLLBACKS

    @staticmethod
    def is_transition_allowed(from_state: str, to_state: str) -> bool:
        """判断两个状态之间是否允许直接转移（不含回退次数校验）。"""
        return to_state in ALLOWED_TRANSITIONS.get(from_state, set())

    can_transition = is_transition_allowed

    def __init__(
        self,
        photo_id: str,
        store: Any | None = None,
        state_store: Any | None = None,
        trace_store: Any | None = None,
        initial_state: str = INITIAL_STATE,
    ) -> None:
        self.photo_id = photo_id
        self._state_store = state_store or store
        self._trace_store = trace_store or store or state_store
        self._store = self._state_store  # 兼容旧属性名
        if initial_state not in STATES:
            raise ValueError(f"未知初始状态: {initial_state}")
        self._record = self._load_or_create(initial_state)

    @property
    def state(self) -> str:
        """当前状态。"""
        return self._record.state

    @property
    def current_state(self) -> str:
        """当前状态（兼容命名）。"""
        return self._record.state

    def get_state(self) -> str:
        """返回当前状态（兼容函数式调用）。"""
        return self._record.state

    def get_record(self) -> StateRecord:
        """返回当前状态记录。"""
        return self._record

    @property
    def record(self) -> StateRecord:
        """当前状态记录（可读；修改请通过转移/写入方法）。"""
        return self._record

    def _load_or_create(self, initial_state: str) -> StateRecord:
        """从存储加载；不存在则创建初始记录。"""
        if self._state_store is None:
            return StateRecord(photo_id=self.photo_id, state=initial_state)
        existing = self._state_store.load_state(self.photo_id)
        if existing is not None:
            return existing
        record = StateRecord(photo_id=self.photo_id, state=initial_state)
        self._state_store.save_state(record)
        return record

    @staticmethod
    def _is_rollback(from_state: str, to_state: str) -> bool:
        """是否为 FINAL_QC 回退转移。"""
        return (
            from_state == "FINAL_QC" and to_state in QC_ROLLBACK_TARGETS
        )

    def _validate_transition(
        self,
        from_state: str,
        to_state: str,
        reason: str,
        event_type: str | None,
    ) -> None:
        """校验转移合法性；非法输入直接抛异常。"""
        allowed = ALLOWED_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            raise IllegalTransitionError(from_state, to_state)

        if to_state == "MANUAL_REVIEW":
            if not reason or not reason.strip():
                raise InvalidTransitionReasonError(
                    f"转向 MANUAL_REVIEW 必须提供 reason（event_type="
                    f"{event_type or 'AGENT_ESCALATED'}）"
                )

        if self._is_rollback(from_state, to_state):
            if self._record.qc_rollback_count >= _MAX_QC_ROLLBACKS:
                raise RollbackLimitError(
                    from_state,
                    to_state,
                    f"QC 回退次数已达上限 {_MAX_QC_ROLLBACKS}，"
                    f"请转 MANUAL_REVIEW",
                )

    def _auto_event_type(
        self, from_state: str, to_state: str
    ) -> str:
        """根据转移自动推断事件类型。"""
        if to_state == "MANUAL_REVIEW":
            return "AGENT_ESCALATED"
        if to_state == "ACCEPTED":
            return "FINAL_QC_ACCEPT"
        if to_state == "REJECTED":
            return "FINAL_QC_REJECT"
        if self._is_rollback(from_state, to_state):
            return "QC_ROLLBACK"
        return "STATE_CHANGE"

    def transition(
        self,
        target: str,
        *,
        event_type: str | None = None,
        reason: str = "",
        iteration: int | None = None,
        params: dict[str, Any] | None = None,
        measurement: dict[str, Any] | None = None,
        rule_hits: list[dict[str, Any]] | None = None,
        agent_decision: str = "",
        next_action: str = "",
        source: str = "state_machine",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """执行状态转移；非法转移被拒绝并抛出异常。"""
        from_state = self.state
        if target not in STATES:
            raise IllegalTransitionError(from_state, target, f"未知目标状态: {target}")

        self._validate_transition(from_state, target, reason, event_type)
        actual_event_type = event_type or self._auto_event_type(
            from_state, target
        )

        old_state = from_state
        # 落盘失败回滚快照：save_state 抛异常时恢复转移前内存状态，
        # 避免内存与持久层不一致（浅拷贝足够：以下均为整体字段重赋值）。
        snapshot = copy.copy(self._record)
        self._record.state = target
        if self._is_rollback(old_state, target):
            self._record.qc_rollback_count += 1
        if iteration is not None:
            self._record.iteration = int(iteration)
        if params is not None:
            self._record.current_params = dict(params)
        if measurement is not None:
            self._record.last_measurement = dict(measurement)
        if rule_hits is not None:
            self._record.rule_hits = list(rule_hits)
        if agent_decision:
            self._record.agent_decision = agent_decision
        if next_action:
            self._record.next_action = next_action
        self._record.updated_at = _now_iso()

        if self._state_store is not None:
            try:
                self._state_store.save_state(self._record)
            except Exception:
                # 回滚内存到转移前快照并原地上写，外部持有的 record 引用同步恢复。
                for f in _RECORD_MUTABLE_FIELDS:
                    setattr(self._record, f, getattr(snapshot, f))
                _LOGGER.exception(
                    "save_state 失败，已回滚内存状态 %s -> %s（photo=%s）",
                    old_state,
                    target,
                    self.photo_id,
                )
                # re-raise：让调用方感知转移失败，由其决定重试/降级。
                raise

        event_metadata = dict(metadata or {})
        event_metadata.setdefault("from_state", old_state)
        event_metadata.setdefault("to_state", target)
        self.add_trace(
            event_type=actual_event_type,
            reason=reason,
            source=source,
            old_value=old_state,
            new_value=target,
            iteration=self._record.iteration,
            metadata=event_metadata,
        )
        return target

    def escalate(self, reason: str, **kwargs: Any) -> str:
        """Agent 升级到人工复核，必须带 reason。"""
        return self.transition(
            "MANUAL_REVIEW",
            event_type="AGENT_ESCALATED",
            reason=reason,
            **kwargs,
        )

    def accept(self, reason: str = "FINAL_QC 达标", **kwargs: Any) -> str:
        """FINAL_QC 验收通过。"""
        return self.transition(
            "ACCEPTED",
            event_type="FINAL_QC_ACCEPT",
            reason=reason,
            **kwargs,
        )

    def reject(self, reason: str = "用户拒绝", **kwargs: Any) -> str:
        """FINAL_QC 拒绝。"""
        return self.transition(
            "REJECTED",
            event_type="FINAL_QC_REJECT",
            reason=reason,
            **kwargs,
        )

    def rollback(
        self,
        target: str = "EXPOSURE_ALIGNING",
        reason: str = "FINAL_QC 超标，回退一次",
        **kwargs: Any,
    ) -> str:
        """执行一次 QC 回退；超过上限时拒绝。"""
        if target not in QC_ROLLBACK_TARGETS:
            raise IllegalTransitionError(self.state, target)
        return self.transition(
            target,
            event_type="QC_ROLLBACK",
            reason=reason,
            source="qc_rollback",
            **kwargs,
        )

    def add_trace(self, **kwargs: Any) -> TraceEvent:
        """记录一条溯源事件；自动补 photo_id 与 iteration。"""
        data = dict(kwargs)
        data.setdefault("photo_id", self.photo_id)
        data.setdefault("iteration", self._record.iteration)
        data.setdefault("event_type", "iteration")
        if "before" in data and "old_value" not in data:
            data["old_value"] = data.pop("before")
        if "after" in data and "new_value" not in data:
            data["new_value"] = data.pop("after")
        if data.get("new_value") is None and data.get("value") is not None:
            data["new_value"] = data["value"]
        event = TraceEvent(**data)
        if self._trace_store is not None:
            event.id = self._trace_store.add_trace(event)
        else:
            if not hasattr(self, "_in_memory_history"):
                self._in_memory_history = []
            self._in_memory_history.append(event)
        return event

    # 常用别名
    add_param_trace = add_trace
    trace_param = add_trace
    record_trace = add_trace
    log_trace = add_trace

    def history(
        self,
        param: str | None = None,
        event_type: str | None = None,
        source: str | None = None,
    ) -> list[TraceEvent]:
        """查询该照片的完整溯源历史。"""
        if self._trace_store is not None:
            return self._trace_store.query_traces(
                self.photo_id,
                param=param,
                event_type=event_type,
                source=source,
            )
        events = getattr(self, "_in_memory_history", [])
        if param is not None:
            events = [e for e in events if e.param == param]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if source is not None:
            events = [e for e in events if e.source == source]
        return list(events)

    trace_history = history
    get_history = history


# 兼容命名：状态机也可称为 StateMachine。
StateMachine = PhotoStateMachine


__all__ = [
    "STATES",
    "TERMINAL_STATES",
    "ALLOWED_TRANSITIONS",
    "INITIAL_STATE",
    "MAX_QC_ROLLBACKS",
    "QC_ROLLBACK_TARGETS",
    "StateRecord",
    "PhotoStateMachine",
    "StateMachine",
]
