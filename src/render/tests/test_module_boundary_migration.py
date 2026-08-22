"""Phase B 模块边界迁移测试：decide/state/trace 顶层化与 shim 兼容。

验证:
  - import pixo.decide / pixo.state / pixo.trace 可用；
  - 旧 pixo.render.decide / pixo.render.state / render.decide / render.state
    仍兼容；
  - trace 顶层 recorder/query 可用。
"""
from __future__ import annotations


def test_top_level_decide_state_trace_importable():
    """三个顶层包可直接导入。"""
    import pixo.decide  # noqa: F401
    import pixo.state  # noqa: F401
    import pixo.trace  # noqa: F401

    from pixo.decide import decide
    from pixo.state import PhotoStateMachine
    from pixo.trace import TraceEvent, TraceRecorder

    assert callable(decide)
    assert PhotoStateMachine.__name__ == "PhotoStateMachine"
    assert TraceEvent.__name__ == "TraceEvent"
    assert TraceRecorder.__name__ == "TraceRecorder"


def test_old_render_shims_still_work():
    """pixo.render.* 与 render.* shim 保持兼容。"""
    from pixo.decide import decide as top_decide
    from pixo.render.decide import decide as render_decide
    from pixo.state import PhotoStateMachine as top_state
    from pixo.render.state import PhotoStateMachine as render_state
    from pixo.trace import TraceEvent as top_trace
    from pixo.render.state.trace import TraceEvent as render_trace
    from render.decide import decide as shim_decide
    from render.state import PhotoStateMachine as shim_state
    from render.state.trace import TraceEvent as shim_trace

    assert top_decide is render_decide is shim_decide
    assert top_state is render_state is shim_state
    assert top_trace is render_trace is shim_trace


def test_trace_query_helpers():
    """pixo.trace.query 过滤/分组可用。"""
    from pixo.trace import TraceEvent, filter_events, group_by_param

    events = [
        TraceEvent(photo_id="p1", param="Exposure", value=0.3, event_type="iteration"),
        TraceEvent(photo_id="p1", param="WhiteBalance", value=5000, event_type="user"),
        TraceEvent(photo_id="p2", param="Exposure", value=0.5, event_type="iteration"),
    ]
    assert len(filter_events(events, photo_id="p1")) == 2
    assert len(filter_events(events, param="Exposure")) == 2
    grouped = group_by_param(events)
    assert set(grouped) == {"Exposure", "WhiteBalance"}
    assert len(grouped["Exposure"]) == 2
