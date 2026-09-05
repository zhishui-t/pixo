"""LLM 建议影子验证单测（原型）：拒绝/晋升/关态三路径 + 降级 + 确定性。

覆盖（评审决议：新接入的 LLM 建议先不直接应用，后台低分辨率验证，
得分显著高于当前才纳入；GOVERNANCE §1.4）：
  - 晋升路径：试渲染分显著高于当前（≥ max(min_gain, rel_gain·|当前|)）
    → llm_shadow_promote 留痕（含分数对照），补丁进候选通道
    （decide metrics llm_suggest_count / metrics["llm_shadow"]="promote"）；
  - 拒绝路径：分数不达标 → llm_shadow_reject 留痕（含分数对照），
    候选通道不进入（llm_suggest_count 缺席）；
  - 阈值可配：rel_gain 调高后同一分数信号由晋升翻转为拒绝；
  - 开关关态（DI llm_shadow=False 与 env PIXO_LLM_SHADOW=0 两形态）：
    行为与影子引入前一致——无任何 llm_shadow_* 事件，accepted 直进候选；
  - 降级路径：未配置美学评分器 → llm_shadow_skipped，按现行行为放行；
  - 确定性纪律：同输入（同图/同建议/同评分器）两次独立闭环，
    影子分数对照逐位一致；LLM 生成侧伪件注入不影响该确定性；
  - 开关解析：PIXO_LLM_SHADOW 关态值集与 DI 优先级。

建议链经 monkeypatch run_suggest 伪件注入（对齐 test_agent_suggest 约定），
LLM 生成侧不确定性不在本文件覆盖范围。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend, \
    llm_shadow_enabled
from pixo.vision import MockSegmenter

import pixo.agent.suggest as suggest_mod

_ENV = ("PIXO_DSH_CHAT_URL", "PIXO_DSH_CHAT_KEY", "PIXO_DSH_CHAT_MODEL")


def _img():
    """均匀暗图（tone.brightness 补丁会确定性地提亮试渲染图）。"""
    return np.full((64, 64, 3), 0.08, dtype=np.float32)


def _make_loop(scorer=None, **kw):
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_img()),
        segmenter=MockSegmenter(),
        max_iterations=1,
        preview_long_edge=64,
        aesthetic_scorer=scorer,
        **kw)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔离 DSH 三要素与影子开关（不依赖外部 env）。"""
    for k in _ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("PIXO_LLM_SHADOW", raising=False)


def _inject_suggestion(monkeypatch, value=0.6, param="tone.brightness",
                       op="set"):
    """DSH 环境齐备 + run_suggest 伪件：accepted 单补丁（无 rejected）。"""
    for k, v in zip(_ENV, ("http://fake", "key", "m")):
        monkeypatch.setenv(k, v)

    def fake_run_suggest(**kw):
        return {"status": "ok",
                "accepted": [{"param": param, "op": op, "value": value,
                              "reason": "测试建议"}],
                "rejected": [], "reply_text": "", "source": "test",
                "chat_latency_ms": 1.0, "cache_hit": False}

    monkeypatch.setattr(suggest_mod, "run_suggest", fake_run_suggest)


def _bright_pref_scorer(image_rgb, masks=None):
    """越亮分越高（确定性内容评分）：tone.brightness 补丁必然加分。"""
    return float(np.asarray(image_rgb).mean()) / 255.0


def _dark_pref_scorer(image_rgb, masks=None):
    """越暗分越高（确定性内容评分）：提亮补丁必然减分。"""
    return -float(np.asarray(image_rgb).mean()) / 255.0


def _shadow_events(result, *types):
    want = set(types)
    return [e for e in result.trace_events
            if (e.get("event_type") if isinstance(e, dict)
                else getattr(e, "event_type", "")) in want]


def _decide_metrics(result):
    dec = [e for e in result.trace_events
           if (e.get("event_type") if isinstance(e, dict)
               else getattr(e, "event_type", "")) == "decide"]
    assert dec
    return dec[-1]["value"]["metrics"]


# --- 晋升路径 ------------------------------------------------------------------

def test_shadow_promote_enters_candidate_channel(monkeypatch):
    _inject_suggestion(monkeypatch, value=0.6)   # 提亮幅度 ≫ 相对 5% 阈值
    loop = _make_loop(_bright_pref_scorer, agent_suggest=True,
                      llm_shadow=True)
    result = loop.run("shadow_promote", image_rgb=_img())

    prom = _shadow_events(result, "llm_shadow_promote")
    assert prom, "应产生影子晋升事件"
    meta = prom[0]["metadata"]
    assert meta["scores"]["trial"] > meta["scores"]["current"]
    assert meta["scores"]["gain"] >= meta["scores"]["threshold"]
    assert meta["patches"] == ["tone.brightness"]

    metrics = _decide_metrics(result)
    assert metrics["llm_suggest_count"] == 1     # 补丁进候选通道
    assert metrics["llm_shadow"] == "promote"
    assert not _shadow_events(result, "llm_shadow_reject",
                              "llm_shadow_skipped")


def test_shadow_reject_drops_candidate_and_traces_scores(monkeypatch):
    _inject_suggestion(monkeypatch, value=0.6)   # 提亮补丁
    loop = _make_loop(_dark_pref_scorer, agent_suggest=True,
                      llm_shadow=True)
    result = loop.run("shadow_reject", image_rgb=_img())

    rej = _shadow_events(result, "llm_shadow_reject")
    assert rej, "应产生影子拒绝事件"
    meta = rej[0]["metadata"]
    # 分数对照齐全：current/trial/gain/threshold
    assert set(meta["scores"]) == {"current", "trial", "gain", "threshold"}
    assert meta["scores"]["gain"] < meta["scores"]["threshold"]

    metrics = _decide_metrics(result)
    assert metrics["llm_shadow"] == "reject"
    # 候选通道未进入：观测指标不暴露（accepted 直进路径才会写）
    assert "llm_suggest_count" not in metrics
    assert "llm_suggest_params" not in metrics
    assert all("llm_suggest_count" not in m for m in result.measurements)


def test_shadow_threshold_configurable_flips_verdict(monkeypatch):
    """同一分数信号：rel_gain 缺省 5% 晋升，调到 50% 后翻转为拒绝。"""
    _inject_suggestion(monkeypatch, value=0.6)   # 相对增益 ~25%

    promote_loop = _make_loop(_bright_pref_scorer, agent_suggest=True,
                              llm_shadow=True)
    r1 = promote_loop.run("thr_default", image_rgb=_img())
    assert _shadow_events(r1, "llm_shadow_promote")

    reject_loop = _make_loop(_bright_pref_scorer, agent_suggest=True,
                             llm_shadow=True, llm_shadow_rel_gain=0.5)
    r2 = reject_loop.run("thr_high", image_rgb=_img())
    rej = _shadow_events(r2, "llm_shadow_reject")
    assert rej, "rel_gain=0.5 应翻转为拒绝"
    assert rej[0]["metadata"]["scores"]["threshold"] == pytest.approx(
        0.5 * abs(rej[0]["metadata"]["scores"]["current"]))

    # 绝对下限形态（+0.05σ 类）：min_gain 拉高同样翻转
    abs_loop = _make_loop(_bright_pref_scorer, agent_suggest=True,
                          llm_shadow=True, llm_shadow_min_gain=10.0)
    r3 = abs_loop.run("thr_abs", image_rgb=_img())
    rej3 = _shadow_events(r3, "llm_shadow_reject")
    assert rej3 and rej3[0]["metadata"]["scores"]["threshold"] == 10.0


# --- 开关关态：行为与影子引入前一致 ---------------------------------------------

def test_shadow_off_via_di_keeps_legacy_behavior(monkeypatch):
    _inject_suggestion(monkeypatch, value=0.6)
    loop = _make_loop(_dark_pref_scorer, agent_suggest=True,
                      llm_shadow=False)          # DI 显式关
    result = loop.run("off_di", image_rgb=_img())

    assert not _shadow_events(result, "llm_shadow_promote",
                              "llm_shadow_reject", "llm_shadow_skipped")
    metrics = _decide_metrics(result)
    assert metrics["llm_suggest_count"] == 1     # accepted 直进候选通道
    assert "llm_shadow" not in metrics


def test_shadow_off_via_env_keeps_legacy_behavior(monkeypatch):
    _inject_suggestion(monkeypatch, value=0.6)
    monkeypatch.setenv("PIXO_LLM_SHADOW", "0")   # env 关（llm_shadow=None 走 env）
    loop = _make_loop(_dark_pref_scorer, agent_suggest=True)
    result = loop.run("off_env", image_rgb=_img())

    assert not _shadow_events(result, "llm_shadow_promote",
                              "llm_shadow_reject", "llm_shadow_skipped")
    assert _decide_metrics(result)["llm_suggest_count"] == 1


def test_env_unset_defaults_on_within_optin_parent():
    """缺省开（双层门）：env 未设即开；关态值集按 GOVERNANCE §1.4。"""
    assert llm_shadow_enabled() is True
    for v in ("0", "false", "off", "no", " OFF "):
        assert llm_shadow_enabled({"PIXO_LLM_SHADOW": v}) is False, v
    for v in ("", "1", "true", "yes", "on", "whatever"):
        assert llm_shadow_enabled({"PIXO_LLM_SHADOW": v}) is True, v
    # DI 优先于 env：env=0 但显式 llm_shadow=True 仍开
    loop = SinglePhotoLoop(llm_shadow=True)
    assert loop.llm_shadow is True


# --- 降级路径：影子基础设施不可用不改变既有行为 ----------------------------------

def test_shadow_without_scorer_skips_and_promotes(monkeypatch):
    """未配置评分器：llm_shadow_skipped 留痕，按现行行为放行候选。"""
    _inject_suggestion(monkeypatch, value=0.6)
    loop = _make_loop(None, agent_suggest=True, llm_shadow=True)
    result = loop.run("shadow_skip", image_rgb=_img())

    skip = _shadow_events(result, "llm_shadow_skipped")
    assert skip and "评分器" in skip[0]["reason"]
    metrics = _decide_metrics(result)
    assert metrics["llm_shadow"] == "skipped"
    assert metrics["llm_suggest_count"] == 1     # 降级 = 现行行为（直进候选）


def test_shadow_off_env_missing_suggestion_chain_untouched(monkeypatch):
    """父开关关（agent_suggest 缺省）：影子代码零触达，无任何影子事件。"""
    loop = _make_loop(_bright_pref_scorer)       # agent_suggest 默认关
    result = loop.run("parent_off", image_rgb=_img())
    assert not _shadow_events(result, "llm_shadow_promote",
                              "llm_shadow_reject", "llm_shadow_skipped")
    assert not _shadow_events(result, "agent_suggest_accepted")


# --- 确定性纪律：同输入同分 ------------------------------------------------------

def test_shadow_verification_deterministic(monkeypatch):
    """同图/同建议/同确定性评分器：两次独立闭环影子分数对照逐位一致。"""
    _inject_suggestion(monkeypatch, value=0.6)
    runs = []
    for i in range(2):
        loop = _make_loop(_bright_pref_scorer, agent_suggest=True,
                          llm_shadow=True)
        r = loop.run(f"det_{i}", image_rgb=_img())
        evs = _shadow_events(r, "llm_shadow_promote", "llm_shadow_reject")
        assert len(evs) == 1
        runs.append((evs[0]["event_type"], evs[0]["metadata"]["scores"]))
    assert runs[0] == runs[1], "同输入必须同分（影子验证确定性）"
