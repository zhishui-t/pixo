"""P1-4 单元测试：Pixo State + Trace 状态机与参数溯源。

覆盖：
  - 合法状态链
  - 非法转移拒绝
  - AGENT_ESCALATED / MANUAL_REVIEW 必须带 reason
  - FINAL_QC 回退限一次
  - Trace 参数级查询、历史查询、SQLite 持久化
"""
from __future__ import annotations

import pytest

from pixo.state import (
    IllegalTransitionError,
    InvalidTransitionReasonError,
    PhotoStateMachine,
    RollbackLimitError,
    TraceStore,
)


def _full_chain_to_final(sm: PhotoStateMachine) -> None:
    """走到 FINAL_QC。"""
    sm.transition("SCREENED")
    sm.transition("BASE_RENDERED")
    sm.transition("EXPOSURE_ALIGNING")
    sm.transition("COLOR_CORRECTING")
    sm.transition("STYLE_APPLIED")
    sm.transition("FINAL_QC")


def test_legal_state_chain():
    """标准状态链全部合法。"""
    sm = PhotoStateMachine("DSC_0001")
    sm.transition("SCREENED")
    sm.transition("BASE_RENDERED")
    sm.transition("EXPOSURE_ALIGNING")
    sm.transition("COLOR_CORRECTING")
    sm.transition("STYLE_APPLIED")
    sm.transition("FINAL_QC")
    sm.transition("ACCEPTED")
    assert sm.state == "ACCEPTED"


def test_illegal_transition_rejected():
    """服务端强校验：非法跳转必须拒绝。"""
    sm = PhotoStateMachine("DSC_0002")
    with pytest.raises(IllegalTransitionError):
        sm.transition("ACCEPTED")
    with pytest.raises(IllegalTransitionError):
        sm.transition("REJECTED")
    assert sm.state == "RAW_PENDING"


def test_manual_review_requires_reason():
    """AGENT_ESCALATED / MANUAL_REVIEW 必须携带 reason。"""
    sm = PhotoStateMachine("DSC_0003")
    sm.transition("SCREENED")
    with pytest.raises(InvalidTransitionReasonError):
        sm.transition("MANUAL_REVIEW")
    with pytest.raises(InvalidTransitionReasonError):
        sm.transition("MANUAL_REVIEW", reason="   ")

    sm.transition("MANUAL_REVIEW", reason="人脸主体过曝无法自动修复")
    assert sm.state == "MANUAL_REVIEW"
    events = sm.history(event_type="AGENT_ESCALATED")
    assert len(events) == 1
    assert events[0].reason == "人脸主体过曝无法自动修复"


def test_escalate_helper_records_reason_and_event():
    """escalate() 是 AGENT_ESCALATED 的便捷入口。"""
    sm = PhotoStateMachine("DSC_0004")
    sm.transition("SCREENED")
    sm.escalate("天空高光溢出，需人工确认")
    assert sm.state == "MANUAL_REVIEW"
    traces = sm.history(event_type="AGENT_ESCALATED")
    assert len(traces) == 1
    assert traces[0].metadata["from_state"] == "SCREENED"
    assert traces[0].metadata["to_state"] == "MANUAL_REVIEW"


def test_qc_rollback_limit_enforced():
    """FINAL_QC 回退只允许一次，第二次必须拒绝。"""
    sm = PhotoStateMachine("DSC_0005")
    _full_chain_to_final(sm)
    assert sm.state == "FINAL_QC"

    sm.rollback("EXPOSURE_ALIGNING", reason="高光溢出 4.2% > 3%")
    assert sm.state == "EXPOSURE_ALIGNING"
    assert sm.record.qc_rollback_count == 1

    # 重新走到 FINAL_QC，再回退应超限
    sm.transition("COLOR_CORRECTING")
    sm.transition("STYLE_APPLIED")
    sm.transition("FINAL_QC")
    with pytest.raises(RollbackLimitError):
        sm.rollback("COLOR_CORRECTING", reason="再次超标")


def test_trace_param_query_and_history():
    """Trace 可按参数/事件类型查询，前后值完整。"""
    store = TraceStore(":memory:")
    sm = PhotoStateMachine("DSC_0006", store=store)
    sm.transition("SCREENED")
    sm.transition("BASE_RENDERED")

    sm.add_trace(
        event_type="iteration",
        param="Exposure",
        value=0.28,
        old_value=0.0,
        new_value=0.28,
        reason="face_luminance 95 < target 115",
        rule_id="exposure_rule_001",
        formula="2.2 * log2(115/95)",
        source="quantitative_decision",
        meta_ref="capture.iso",
        iteration=1,
    )
    sm.add_trace(
        event_type="user_override",
        param="WhiteBalance",
        value=5200,
        old_value=5000,
        new_value=5200,
        reason="用户手动指定色温",
        source="user",
        iteration=1,
    )

    exposure = sm.history(param="Exposure")
    assert len(exposure) == 1
    assert exposure[0].old_value == 0.0
    assert exposure[0].new_value == 0.28
    assert exposure[0].rule_id == "exposure_rule_001"
    assert exposure[0].meta_ref == "capture.iso"

    user = store.query_traces("DSC_0006", event_type="user_override")
    assert len(user) == 1
    assert user[0].param == "WhiteBalance"

    all_events = store.history("DSC_0006")
    # 2 次状态转移 + 2 条参数溯源
    assert len(all_events) == 4


def test_state_and_trace_persistence():
    """同一 SQLite 存储可恢复照片状态和历史。"""
    store = TraceStore(":memory:")
    sm1 = PhotoStateMachine("DSC_0007", store=store)
    sm1.transition("SCREENED")
    sm1.add_trace(event_type="iteration", param="Contrast", value=0.1,
                  old_value=0.0, new_value=0.1, source="decide")

    sm2 = PhotoStateMachine("DSC_0007", store=store)
    assert sm2.state == "SCREENED"
    traces = sm2.history(param="Contrast")
    assert len(traces) == 1
    assert traces[0].new_value == 0.1


def test_store_clear_and_close():
    """存储可清空并关闭。"""
    store = TraceStore(":memory:")
    sm = PhotoStateMachine("DSC_0008", store=store)
    sm.transition("SCREENED")
    assert len(store.history("DSC_0008")) == 1
    store.clear()
    assert store.history("DSC_0008") == []
    assert store.load_state("DSC_0008") is None
    store.close()
