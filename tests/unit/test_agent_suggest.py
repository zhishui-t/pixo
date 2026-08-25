"""agent_suggest 编排单测 (t47)：两分支 + 默认关零行为 + 环境门。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from pixo.agent.suggest import (
    build_suggest_context,
    is_dsh_chat_configured,
    run_suggest,
)
from pixo.know.registry import KnowledgeRegistry
from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.vision import MockSegmenter

import pixo.agent.suggest as suggest_mod

_ENV = ("PIXO_DSH_CHAT_URL", "PIXO_DSH_CHAT_KEY", "PIXO_DSH_CHAT_MODEL")


def _img():
    return np.full((64, 64, 3), 0.08, dtype=np.float32)


def _make_loop(**kw):
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_img()),
        segmenter=MockSegmenter(),
        max_iterations=1,
        preview_long_edge=64,
        **kw)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ENV:
        monkeypatch.delenv(k, raising=False)


# --- 纯编排层 ----------------------------------------------------------------

def test_valid_patch_accepted():
    fence = chr(96) * 3
    payload = json.dumps([{"param": "tone.brightness", "op": "set",
                           "value": 0.3, "reason": "偏暗"}])

    def client(_prompt):
        return fence + "json" + chr(10) + payload

    out = run_suggest(chat_client=client,
                      measurement={"mean_luminance": 96},
                      scene_query="portrait")
    assert out["status"] == "ok"
    assert out["accepted"][0]["param"] == "tone.brightness"
    assert out["rejected"] == []


def test_garbage_reply_becomes_rejected_with_full_text():
    out = run_suggest(chat_client=lambda p: "抱歉，我无法生成补丁")
    assert out["status"] == "ok" and len(out["rejected"]) == 1
    assert out["rejected"][0]["raw_text"] == "抱歉，我无法生成补丁"
    assert out["accepted"] == []


def test_locked_param_rejected_by_reviewer():
    text = json.dumps([{"param": "tone.brightness", "op": "set", "value": 0.5}])
    out = run_suggest(chat_client=lambda p: text, locked_params=["tone"])
    assert out["accepted"] == []
    assert "锁" in out["rejected"][0]["reason"] or "locked" in         str(out["rejected"][0]).lower()


def test_env_missing_default_path_skips_whole_chain():
    assert not is_dsh_chat_configured()
    out = run_suggest()          # 默认路径: 无注入客户端 + 环境缺失
    assert out["status"] == "skipped_unconfigured"


def test_context_assembly_uses_real_registry():
    ctx = build_suggest_context(
        {"mean_luminance": 90, "haze_proxy": 0.2}, [0.5, 0.6],
        "portrait sky", KnowledgeRegistry())
    assert set(ctx) == {"metrics", "aesthetic_history", "knowledge_top3"}
    assert ctx["metrics"]["mean_luminance"] == 90
    assert ctx["aesthetic_history"] == [0.5, 0.6]
    assert isinstance(ctx["knowledge_top3"], list)


# --- loop 接线层 --------------------------------------------------------------

def _trace_types(result):
    types = set()
    for e in result.trace_events:
        et = e.get("event_type") if isinstance(e, dict) else getattr(
            e, "event_type", None)
        types.add(et)
    return types


def test_loop_default_off_zero_behavior():
    result = _make_loop().run("off", image_rgb=_img())
    assert not any(t and str(t).startswith("agent_suggest")
                   for t in _trace_types(result))


def test_loop_on_env_missing_traces_skip(monkeypatch):
    loop = _make_loop(agent_suggest=True)
    result = loop.run("skip", image_rgb=_img())
    ts = _trace_types(result)
    assert "agent_suggest_skipped" in ts


def test_loop_on_placeholder_degrade_rejected_full_text_in_trace(monkeypatch):
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)
    loop = _make_loop(agent_suggest=True)
    result = loop.run("degrade", image_rgb=_img())
    evs = [e for e in result.trace_events
           if (e.get("event_type") if isinstance(e, dict)
               else getattr(e, "event_type", "")) == "agent_suggest_rejected"]
    assert evs, "占位降级应产生 rejected 留痕"
    meta = evs[0].get("metadata") if isinstance(evs[0], dict)         else getattr(evs[0], "metadata", {})
    assert "已收到 DSH 消息" in (meta.get("reply_text") or "")


def test_loop_accepted_enters_decide_context(monkeypatch):
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)

    def fake_run_suggest(**kw):
        return {"status": "ok",
                "accepted": [{"param": "tone.brightness", "op": "set",
                              "value": 0.3}],
                "rejected": [{"item": None, "reason": "r",
                              "raw_text": "RAW全文"}],
                "reply_text": "RAW全文", "source": "test"}

    monkeypatch.setattr(suggest_mod, "run_suggest", fake_run_suggest)
    loop = _make_loop(agent_suggest=True)
    result = loop.run("accept", image_rgb=_img())
    evs = [(e.get("event_type") if isinstance(e, dict)
            else getattr(e, "event_type", ""), e) for e in result.trace_events]
    acc = [e for t, e in evs if t == "agent_suggest_accepted"]
    rej = [e for t, e in evs if t == "agent_suggest_rejected"]
    assert acc and acc[0]["metadata"]["params"] == ["tone.brightness"]
    assert rej and "RAW全文" in rej[0]["metadata"]["reply_text"]
