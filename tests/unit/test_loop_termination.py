"""闭环终止链路单测：last_iteration 透传 / stop_reason 进最终 reason /
目标距 improvement 度量 / agent_suggest 回复截断。

对应缺陷修复：
  - decide() 不透传 last_iteration 导致 loop.py 的 break 分支死代码；
  - run() 丢弃 _run_preview_iterations 的 stop_reason；
  - improvement 用 |Δ观测值| 度量，绕目标振荡被误判为大改善；
  - agent_suggest_rejected 事件 reply_text/raw_text 双份全文无截断。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.pipeline.loop import (
    SinglePhotoLoop,
    SyntheticRenderBackend,
    _TRACE_RAW_TEXT_MAX,
    _TRACE_REPLY_TEXT_MAX,
    _target_value,
    _truncate_text,
)
from pixo.vision import MockSegmenter

import pixo.agent.suggest as suggest_mod

_ENV = ("PIXO_DSH_CHAT_URL", "PIXO_DSH_CHAT_KEY", "PIXO_DSH_CHAT_MODEL")


def _dark_image() -> np.ndarray:
    """低亮度合成图，FINAL_QC 不会高光溢出。"""
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.3
    return img


def _make_loop(**kw):
    kw.setdefault("max_iterations", 3)
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        preview_long_edge=64,
        **kw,
    )


def _decide_events(result):
    return [e for e in result.trace_events if e["event_type"] == "decide"]


# ---------------------------------------------------------------------------
# last_iteration 透传 + stop_reason 进最终 reason
# ---------------------------------------------------------------------------

def test_max_iterations_one_decide_event_marks_last_iteration():
    """max_iterations=1：decide 事件输出含 last_iteration=True，stop_reason
    （term 的 reason）不再被 run() 丢弃。"""
    result = _make_loop(max_iterations=1).run("last_it", image_rgb=_dark_image())

    assert result.state == "ACCEPTED"
    events = _decide_events(result)
    assert len(events) == 1
    assert events[0]["value"]["decision"] == "adjust_and_continue"
    assert events[0]["value"].get("last_iteration") is True
    assert events[0]["reason"] == "达到最大迭代轮数 (1)"
    # stop_reason 进最终 trace 的 reason 字段
    assert "preview 终止" in result.reason
    assert "达到最大迭代轮数 (1)" in result.reason


def test_max_iterations_one_rule_params_still_applied():
    """末轮参数必须落地：规则给出的曝光修正写进 exposure.target_offset。"""
    rule = {
        "rule_id": "brighten",
        "condition": {"metric": "mean_luminance", "op": "lt", "value": 120},
        "action": {"param": "exposure_ev", "mode": "delta", "value": 0.3},
    }
    result = _make_loop(rules=[rule], max_iterations=1).run(
        "last_param", image_rgb=_dark_image())

    assert result.params["exposure"]["target_offset"] == pytest.approx(0.3)
    # 有参数更新 trace（Decide 参数更新 → exposure_ev 0.0 -> 0.3）
    updates = [e for e in result.trace_events
               if e["event_type"] == "param_update"]
    assert any(e["param"] == "exposure_ev" for e in updates)


# ---------------------------------------------------------------------------
# improvement 度量：有显式目标按目标距，绕目标振荡不再误判大改善
# ---------------------------------------------------------------------------

class _SequenceMeasurer:
    """按预设序列返回全局亮度的假测量器（绕目标 110 振荡 90/130）。"""

    def __init__(self, seq: list[float]) -> None:
        self.seq = seq
        self.i = 0

    def measure(self, image, masks, **kw):
        value = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return {
            "global": {
                "mean_luminance": value,
                "highlight_clip_ratio": 0.0,
                "shadow_clip_ratio": 0.0,
                "contrast": 0.5,
            },
            "regions": {},
        }


def test_oscillation_with_target_yields_zero_improvement_and_stops():
    """有 target 时振荡（两侧等距）improvement=0 → 第 3 轮 low_improvement
    stopped（停滞优先于轮数上限）。"""
    measurer = _SequenceMeasurer([90.0, 130.0, 90.0])
    result = _make_loop(
        measurer=measurer, targets={"mean_luminance": 110.0},
    ).run("osc_target", image_rgb=_dark_image())

    assert len(result.measurements) == 3
    last = _decide_events(result)[-1]
    assert last["value"]["decision"] == "stopped"
    assert "连续两轮改善低于阈值" in result.reason


def test_oscillation_without_target_counts_as_big_improvement():
    """无 target 时保持旧差分行为：|Δ|=40 视为大改善，末轮走
    last_iteration（对照，证明度量差异来自目标距）。"""
    measurer = _SequenceMeasurer([90.0, 130.0, 90.0])
    result = _make_loop(measurer=measurer).run(
        "osc_notarget", image_rgb=_dark_image())

    last = _decide_events(result)[-1]
    assert last["value"]["decision"] == "adjust_and_continue"
    assert last["value"].get("last_iteration") is True
    assert "达到最大迭代轮数" in result.reason


def test_target_value_resolution_forms():
    """_target_value 兼容纯数值 / {value,target} 字典 / 缺失与非法形态。"""
    assert _target_value({"mean_luminance": 110}, "mean_luminance") == 110.0
    assert _target_value(
        {"face_luminance": {"value": 0.5}}, "face_luminance") == 0.5
    assert _target_value(
        {"face_luminance": {"target": 0.6}}, "face_luminance") == 0.6
    assert _target_value({"mean_luminance": 110}, "face_luminance") is None
    assert _target_value({"m": "bad"}, "m") is None
    assert _target_value(None, "m") is None


# ---------------------------------------------------------------------------
# agent_suggest_rejected 回复截断（reply_text 4KB / raw_text 2KB）
# ---------------------------------------------------------------------------

def test_truncate_text_helper():
    short, truncated = _truncate_text("abc", 10)
    assert (short, truncated) == ("abc", False)
    long_text = "x" * 20
    cut, truncated = _truncate_text(long_text, 10)
    assert len(cut) == 10 and truncated is True
    assert _truncate_text(None, 10) == (None, False)


def test_rejected_reply_and_raw_text_truncated_in_trace(monkeypatch):
    """同一事件双份超长全文：reply_text 截 4KB 并记 reply_truncated，
    项内 raw_text 截 2KB 并记 raw_truncated。"""
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)

    def fake_run_suggest(**kw):
        return {
            "status": "ok",
            "accepted": [],
            "rejected": [{"item": None, "reason": "未解析到补丁 JSON",
                          "raw_text": "X" * (_TRACE_RAW_TEXT_MAX + 3000)}],
            "reply_text": "R" * (_TRACE_REPLY_TEXT_MAX + 6000),
            "source": "test",
        }

    monkeypatch.setattr(suggest_mod, "run_suggest", fake_run_suggest)
    result = _make_loop(agent_suggest=True, max_iterations=1).run(
        "trunc", image_rgb=_dark_image())

    evs = [e for e in result.trace_events
           if e["event_type"] == "agent_suggest_rejected"]
    assert evs
    meta = evs[0]["metadata"]
    assert meta["reply_truncated"] is True
    assert len(meta["reply_text"]) == _TRACE_REPLY_TEXT_MAX
    raw_items = [r for r in meta["rejected"]
                 if isinstance(r, dict) and r.get("raw_text") is not None]
    assert raw_items
    assert all(len(r["raw_text"]) <= _TRACE_RAW_TEXT_MAX for r in raw_items)
    assert raw_items[0].get("raw_truncated") is True
    # 截断后 llm_review 注明非全文
    assert result.llm_review is not None
    assert any("已截断" in n for n in result.llm_review["notes"])


def test_rejected_short_reply_not_truncated(monkeypatch):
    """短回复原样保留且不带截断标记。"""
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)

    def fake_run_suggest(**kw):
        return {
            "status": "ok",
            "accepted": [],
            "rejected": [{"item": None, "reason": "r", "raw_text": "RAW全文"}],
            "reply_text": "RAW全文", "source": "test",
        }

    monkeypatch.setattr(suggest_mod, "run_suggest", fake_run_suggest)
    result = _make_loop(agent_suggest=True, max_iterations=1).run(
        "short", image_rgb=_dark_image())

    evs = [e for e in result.trace_events
           if e["event_type"] == "agent_suggest_rejected"]
    meta = evs[0]["metadata"]
    assert meta["reply_text"] == "RAW全文"
    assert "reply_truncated" not in meta
    assert meta["rejected"][0]["raw_text"] == "RAW全文"
    assert "raw_truncated" not in meta["rejected"][0]
