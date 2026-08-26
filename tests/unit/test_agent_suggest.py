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


# --- t53：指纹缓存与延迟观测 ---------------------------------------------------

def _valid_payload_client(counter):
    fence = chr(96) * 3

    def client(_prompt):
        counter["n"] += 1
        return (fence + "json" + chr(10)
                + json.dumps([{"param": "tone.brightness", "op": "set",
                               "value": 0.3, "reason": "偏暗"}]))

    return client


def test_same_fingerprint_second_call_skips_http(monkeypatch):
    suggest_mod._SUGGEST_CACHE.clear()
    counter = {"n": 0}
    client = _valid_payload_client(counter)

    first = suggest_mod.run_suggest(measurement={"mean_luminance": 96},
                                    chat_client=client)
    second = suggest_mod.run_suggest(measurement={"mean_luminance": 96},
                                     chat_client=client)
    assert counter["n"] == 1                      # 二次命中零 HTTP
    assert first.get("cache_hit") is False
    assert second.get("cache_hit") is True
    assert second["accepted"] == first["accepted"]


def test_lru_eviction_at_max_8(monkeypatch):
    suggest_mod._SUGGEST_CACHE.clear()
    counter = {"n": 0}
    client = _valid_payload_client(counter)
    for i in range(9):                            # 9 个不同上下文 -> 淘汰最旧
        suggest_mod.run_suggest(
            measurement={"mean_luminance": 100 + i}, chat_client=client)
    assert len(suggest_mod._SUGGEST_CACHE) == 8
    before = counter["n"]
    suggest_mod.run_suggest(measurement={"mean_luminance": 100},
                            chat_client=client)   # 最旧已被淘汰 -> 重新 HTTP
    assert counter["n"] == before + 1


def test_chat_latency_ms_present_on_result():
    suggest_mod._SUGGEST_CACHE.clear()

    def slow_client(_prompt):
        import time as _t
        _t.sleep(0.005)
        return json.dumps([{"param": "tone.brightness", "op": "delta",
                            "value": 0.05, "reason": "r"}])

    out = suggest_mod.run_suggest(measurement={"mean_luminance": 90},
                                  chat_client=slow_client)
    assert isinstance(out.get("chat_latency_ms"), (int, float))
    assert out["chat_latency_ms"] > 0.0


def test_loop_accepted_trace_carries_chat_latency(monkeypatch):
    suggest_mod._SUGGEST_CACHE.clear()
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)
    counter = {"n": 0}

    def fake_real(prompt):
        counter["n"] += 1
        return json.dumps([{"param": "tone.brightness", "op": "set",
                            "value": 0.3, "reason": "r"}])

    monkeypatch.setattr(suggest_mod, "_dsh_chat_real", fake_real)
    loop = _make_loop(agent_suggest=True)
    result = loop.run("latency", image_rgb=_img())
    evs = [e for e in result.trace_events
           if (e.get("event_type") if isinstance(e, dict)
               else getattr(e, "event_type", "")) == "agent_suggest_accepted"]
    assert evs, "应有 accepted 留痕"
    meta = evs[0].get("metadata") if isinstance(evs[0], dict)         else getattr(evs[0], "metadata", {})
    assert isinstance(meta.get("chat_latency_ms"), (int, float))


# --- t65：llm_suggestions 观测指标暴露 ---------------------------------------

def _decide_metrics(result):
    dec = [e for e in result.trace_events
           if (e.get("event_type") if isinstance(e, dict)
               else getattr(e, "event_type", "")) == "decide"]
    assert dec
    return dec[-1]["value"]["metrics"]


def test_accepted_suggestions_expose_observability_metrics(monkeypatch):
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)

    def fake_run_suggest(**kw):
        return {"status": "ok",
                "accepted": [
                    {"param": "tone.brightness", "op": "set", "value": 0.3},
                    {"param": "exposure.vignette", "op": "delta",
                     "value": 0.05},
                ],
                "rejected": [], "reply_text": "", "source": "test",
                "chat_latency_ms": 1.0, "cache_hit": False}

    monkeypatch.setattr(suggest_mod, "run_suggest", fake_run_suggest)
    loop = _make_loop(agent_suggest=True)
    result = loop.run("obs_on", image_rgb=_img())

    metrics = _decide_metrics(result)
    assert metrics["llm_suggest_count"] == 2
    assert metrics["llm_suggest_params"] == [
        "tone.brightness", "exposure.vignette"]
    # measurement 同步暴露（键名不含数值）
    assert result.measurements[0]["llm_suggest_count"] == 2
    assert result.measurements[0]["llm_suggest_params"] == [
        "tone.brightness", "exposure.vignette"]


def test_agent_off_leaves_metrics_absent():
    loop = _make_loop()                       # agent_suggest 默认关
    result = loop.run("obs_off", image_rgb=_img())
    metrics = _decide_metrics(result)
    assert "llm_suggest_count" not in metrics
    assert "llm_suggest_params" not in metrics
    assert all("llm_suggest_count" not in m for m in result.measurements)



# --- t65：llm_suggestions 观测指标暴露 ---------------------------------------

def _decide_metrics(result):
    dec = [e for e in result.trace_events
           if (e.get("event_type") if isinstance(e, dict)
               else getattr(e, "event_type", "")) == "decide"]
    assert dec
    return dec[-1]["value"]["metrics"]


def test_accepted_suggestions_expose_observability_metrics(monkeypatch):
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)

    def fake_run_suggest(**kw):
        return {"status": "ok",
                "accepted": [
                    {"param": "tone.brightness", "op": "set", "value": 0.3},
                    {"param": "exposure.vignette", "op": "delta",
                     "value": 0.05},
                ],
                "rejected": [], "reply_text": "", "source": "test",
                "chat_latency_ms": 1.0, "cache_hit": False}

    monkeypatch.setattr(suggest_mod, "run_suggest", fake_run_suggest)
    loop = _make_loop(agent_suggest=True)
    result = loop.run("obs_on", image_rgb=_img())

    metrics = _decide_metrics(result)
    assert metrics["llm_suggest_count"] == 2
    assert metrics["llm_suggest_params"] == [
        "tone.brightness", "exposure.vignette"]
    assert result.measurements[0]["llm_suggest_count"] == 2
    assert result.measurements[0]["llm_suggest_params"] == [
        "tone.brightness", "exposure.vignette"]


def test_agent_off_leaves_metrics_absent():
    loop = _make_loop()                       # agent_suggest 默认关
    result = loop.run("obs_off", image_rgb=_img())
    metrics = _decide_metrics(result)
    assert "llm_suggest_count" not in metrics
    assert "llm_suggest_params" not in metrics
    assert all("llm_suggest_count" not in m for m in result.measurements)


# --- t69: llm_review 人工审核报表块 -------------------------------------------

def test_loop_review_block_complete_when_suggestions_exist(monkeypatch):
    """有建议时块完整：accepted 逐条明细 + rejected 计数与原因分布。"""
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)

    def fake_run_suggest(**kw):
        return {"status": "ok",
                "accepted": [{"param": "tone.brightness", "op": "set",
                              "value": 0.3, "reason": "偏暗"}],
                "rejected": [{"item": None, "reason": "未解析到补丁 JSON",
                              "raw_text": "全文"},
                             {"param": "exposure_ev", "op": "delta",
                              "value": 9.9, "reason": "锁定参数"}],
                "reply_text": "RAW", "source": "test"}

    monkeypatch.setattr(suggest_mod, "run_suggest", fake_run_suggest)
    result = _make_loop(agent_suggest=True).run("review", image_rgb=_img())
    blk = result.llm_review
    assert blk is not None
    assert blk["accepted"] == [{"param": "tone.brightness", "op": "set",
                                "value": 0.3, "reason": "偏暗"}]
    assert blk["rejected"]["count"] == 2
    assert blk["rejected"]["reasons"] == {"未解析到补丁 JSON": 1,
                                          "锁定参数": 1}
    assert result.to_dict()["llm_review"] == blk      # to_dict 可导出


def test_loop_review_block_absent_by_default():
    """默认关/无建议时块缺席（to_dict 不含该键，而非 null）。"""
    result = _make_loop().run("absent", image_rgb=_img())
    assert result.llm_review is None
    assert "llm_review" not in result.to_dict()


# --- t92：RF-DETR 原生框直供 box_provider -------------------------------------

class _DetectingSegmenter(MockSegmenter):
    """带 detect_boxes 的假件：模拟 MultiModelSegmenter→RF-DETR 直供。"""

    def detect_boxes(self, image_rgb, prompts):
        return {"person": [[0.3, 0.2, 0.6, 0.7]]}


def test_native_detector_boxes_feed_suggest_and_exposure():
    suggest_mod._SUGGEST_CACHE.clear()
    loop = _make_loop(crop_suggest=True)
    loop.segmenter = _DetectingSegmenter()
    result = loop.run("native_box", image_rgb=_img())

    crop_evs = [e for e in result.trace_events
                if (e.get("event_type") if isinstance(e, dict)
                    else getattr(e, "event_type", "")) == "crop_suggest"]
    assert crop_evs, "应产生构图建议"
    val = crop_evs[-1]["value"]
    assert val["source"] == "native_box"
    # 原生框归一化透传进建议
    assert val["rect"] and all(0.0 <= v <= 1.0 for v in val["rect"])

    # 粘性框注入后端：exposure 测光可消费（person→face 分组惯例）
    backend = loop.render_backend
    extras = getattr(backend, "state_extras", None)
    assert isinstance(extras, dict)
    assert extras.get("face_boxes"), "原生框应按 person→faces 映射进 face_boxes"


def test_mask_bbox_fallback_still_works_without_detect_boxes():
    suggest_mod._SUGGEST_CACHE.clear()
    loop = _make_loop(crop_suggest=True)          # MockSegmenter 无 detect_boxes
    result = loop.run("mask_fallback", image_rgb=_img())
    crop_evs = [e for e in result.trace_events
                if (e.get("event_type") if isinstance(e, dict)
                    else getattr(e, "event_type", "")) == "crop_suggest"]
    assert crop_evs
    assert crop_evs[-1]["value"]["source"] == "mask_bbox"
