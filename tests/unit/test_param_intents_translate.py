"""调用方边界意图翻译 —— `session.translate_param_intents` 契约测试。

背景（2026-09-21）：R23 把 clarity/skin/refine/dehaze/hsl/calibration/split_tone
等 Stage 的 `enabled` 归到 False（引擎只提供能力、不猜意图）；但前端
`AdjustmentsPanel.patch()` 只发 `{stage: {param: 值}}`、**不带 `enabled: true`**
⇒ `wants()` 恒 False ⇒ **这些滑杆「调了没效果」**（实测 V1 与基线逐位相同）。

修法不是让引擎自动开启（那会退回 R23 之前的越权），而是在**调用方边界**
（服务层）把「我提交了参数」这一显式意图翻译成「请执行该 Stage」。本文件锁定
该翻译器的全部契约，防止后续改动把它悄悄放宽或收紧。
"""
from __future__ import annotations

import copy

import pytest

from pixo.render.web.session import _param_schemas, translate_param_intents


SCHEMAS = _param_schemas()

# (stage, 代表参数键, 代表值) —— 均为「门控」Stage（param_schema 声明 enabled）
GATED_CASES = [
    ("clarity", "strength", 0.5),
    ("dehaze", "strength", 0.4),
    ("calibration", "red_sat", 20.0),
    ("split_tone", "highlights_sat", 15.0),
    ("skin", "strength", 0.5),
    ("hsl", "bands", [{"name": "red", "hue_center": 0.0, "width": 0.1,
                       "hue_shift": 5.0, "sat_scale": 1.1, "lum_scale": 1.0}]),
    ("refine", "sharpen", 30.0),
    ("huesat", "strength", 0.3),
    ("region_adjust", "regions", {"sky": {"exposure": 0.2}}),
]

# 「无门」Stage（param_schema 无 enabled 键）—— 注入 enabled 会被 F04 栅栏 400
UNGATED_CASES = [
    ("exposure", "vignette", 0.2),
    ("tone", "contrast", 0.1),
    ("whitebalance", "warmth", 0.5),
]


def test_gated_cases_actually_gated():
    """前置守卫：GATED_CASES 里的 stage 确实声明了 enabled 键（防名单漂移）。"""
    for stage, key, _ in GATED_CASES:
        assert "enabled" in SCHEMAS[stage], f"{stage} 不再是门控 Stage"
        assert key in SCHEMAS[stage], f"{stage}.{key} 不是合法参数键"


@pytest.mark.parametrize("stage,key,value", GATED_CASES)
def test_gated_stage_gets_enabled_true(stage, key, value):
    """规则一：门控 Stage 收到非 enabled 参数 ⇒ 自动补 enabled=True。"""
    out = translate_param_intents({stage: {key: value}})
    assert out[stage]["enabled"] is True
    assert out[stage][key] == value


@pytest.mark.parametrize("stage,key,value", UNGATED_CASES)
def test_ungated_stage_not_injected(stage, key, value):
    """无门 Stage 不注入 enabled（否则栅栏按未知键 400）。"""
    out = translate_param_intents({stage: {key: value}})
    assert "enabled" not in out[stage]
    assert out[stage] == {key: value}


def test_explicit_enabled_false_not_overridden():
    """显式 enabled=False 是有效意图（保留参数但关掉），不得被翻转成 True。"""
    out = translate_param_intents({"clarity": {"strength": 0.8, "enabled": False}})
    assert out["clarity"]["enabled"] is False


def test_explicit_enabled_true_kept():
    out = translate_param_intents({"clarity": {"strength": 0.8, "enabled": True}})
    assert out["clarity"]["enabled"] is True


def test_enabled_only_bucket_untouched():
    """桶内只有 enabled（无其它参数）⇒ 不注入、不改动。

    「只发 enabled」= 单纯开/关某个 Stage，不是「我提交了参数」的意图，
    因此不应被当作参数提交而反向补 True。
    """
    assert translate_param_intents({"clarity": {"enabled": False}}) == {
        "clarity": {"enabled": False}}
    assert translate_param_intents({"clarity": {"enabled": True}}) == {
        "clarity": {"enabled": True}}


def test_empty_bucket_untouched():
    assert translate_param_intents({"clarity": {}}) == {"clarity": {}}


def test_empty_patch():
    assert translate_param_intents({}) == {}
    assert translate_param_intents(None) == {}


# ---------------------------------------------------------------------------
# 规则二 · 白平衡滑杆（temp/tint 在 mode="as_shot" 下是死参数）
# ---------------------------------------------------------------------------

def test_wb_temp_switches_to_manual():
    out = translate_param_intents({"whitebalance": {"temp": 5200.0}})
    assert out["whitebalance"]["mode"] == "manual"
    assert out["whitebalance"]["temp"] == 5200.0


def test_wb_tint_only_switches_to_manual():
    """只拖色调也成立：缺的 temp 由 Stage 以相机 as-shot CCT 兜底。"""
    out = translate_param_intents({"whitebalance": {"tint": -12.0}})
    assert out["whitebalance"]["mode"] == "manual"
    assert out["whitebalance"]["tint"] == -12.0


def test_wb_both_temp_and_tint():
    out = translate_param_intents(
        {"whitebalance": {"temp": 5200.0, "tint": -12.0}})
    assert out["whitebalance"]["mode"] == "manual"


def test_wb_explicit_mode_not_overridden():
    """显式 mode 优先：as_shot / off / auto / 数值向量 都不被改写。"""
    for mode in ("as_shot", "off", "auto", [2.0, 1.0, 1.5]):
        out = translate_param_intents(
            {"whitebalance": {"mode": mode, "temp": 5200.0, "tint": -12.0}})
        assert out["whitebalance"]["mode"] == mode, mode


def test_wb_no_temp_tint_no_mode_injection():
    """只调 warmth 不应触发 manual（warmth 与温度滑杆是两回事）。"""
    out = translate_param_intents({"whitebalance": {"warmth": 0.6}})
    assert "mode" not in out["whitebalance"]


def test_wb_none_temp_does_not_trigger_manual():
    """temp=None 语义是「取消该键覆盖」，不是「我要手动色温」。"""
    out = translate_param_intents({"whitebalance": {"temp": None}})
    assert "mode" not in out["whitebalance"]


# ---------------------------------------------------------------------------
# 边界 · 不越权、不污染入参
# ---------------------------------------------------------------------------

def test_values_never_modified():
    """不改任何数值（不靠「把参数改成正数」伪造意图）。"""
    patch = {"clarity": {"strength": -0.7}, "whitebalance": {"tint": -30.0},
             "hsl": {"bands": [], "smooth": 0.25}}
    out = translate_param_intents(patch)
    assert out["clarity"]["strength"] == -0.7
    assert out["whitebalance"]["tint"] == -30.0
    assert out["hsl"]["bands"] == []
    assert out["hsl"]["smooth"] == 0.25


def test_input_dict_not_mutated():
    """返回新 dict：注入的键不写回调用方入参（调用方可能复用同一 dict）。"""
    patch = {"clarity": {"strength": 0.5},
             "whitebalance": {"temp": 5200.0}}
    before = copy.deepcopy(patch)
    out = translate_param_intents(patch)
    assert patch == before, "入参被就地改写"
    assert "enabled" not in patch["clarity"]
    assert "mode" not in patch["whitebalance"]
    assert out is not patch
    assert out["clarity"] is not patch["clarity"]


def test_unknown_stage_passthrough():
    """未知 stage 原样透传（严格栅栏会在后续自行 400，翻译器不加戏）。"""
    out = translate_param_intents({"s1": {"foo": 1}})
    assert out == {"s1": {"foo": 1}}


def test_non_dict_bucket_passthrough():
    out = translate_param_intents({"clarity": None, "tone": 3})
    assert out == {"clarity": None, "tone": 3}


def test_multiple_stages_translated_independently():
    out = translate_param_intents({
        "clarity": {"strength": 0.5},
        "exposure": {"vignette": 0.2},
        "whitebalance": {"temp": 6000.0},
        "tone": {"contrast": 0.1},
    })
    assert out["clarity"]["enabled"] is True
    assert "enabled" not in out["exposure"]
    assert "enabled" not in out["tone"]
    assert out["whitebalance"]["mode"] == "manual"
