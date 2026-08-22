"""T1/T2 单元测试: EditIntent 模型 + 参数映射 + 中文意见解析。

覆盖 (验收 AC-01~AC-04 / 任务 T1+T2):
  - 白名单外 op 报 UnknownOp; 值越界/类型错误报错
  - apply_intents: abs 直接设值、rel 步长×阻尼、钳位、scene/style/wb_temp/tint 映射
  - parse_feedback: 测试表驱动 (方向/程度词/多意见同句)
  - 未识别片段报 UnknownFragment

运行: python -m pytest tests/test_intents.py tests/test_feedback.py -q
"""
from __future__ import annotations

import pytest

from pixo.render.pipeline.intents import (
    DAMPING,
    EditIntent,
    UnknownFragment,
    UnknownOp,
    ValueOutOfRange,
    apply_intents,
    parse_feedback,
)


# ---------------------------------------------------------------------------
# T1: EditIntent 模型
# ---------------------------------------------------------------------------

def test_unknown_op_rejected():
    with pytest.raises(UnknownOp):
        EditIntent(op="nonexistent", value=1.0)


def test_style_requires_str_value():
    with pytest.raises(ValueOutOfRange):
        EditIntent(op="style", value=1.0)


def test_scope_and_semantic_validated():
    with pytest.raises(ValueOutOfRange):
        EditIntent(op="ev", value=1.0, scope="bogus")
    with pytest.raises(ValueOutOfRange):
        EditIntent(op="ev", value=1.0, semantic="bogus")


# ---------------------------------------------------------------------------
# T1: apply_intents
# ---------------------------------------------------------------------------

def test_abs_sets_value_directly():
    out = apply_intents({}, [EditIntent(op="contrast", value=0.3, semantic="abs")])
    assert out["tone"]["contrast"] == 0.3


def test_rel_applies_step_and_damping():
    out = apply_intents({"tone": {"contrast": 0.1}},
                        [EditIntent(op="contrast", value=2.0, semantic="rel")])
    expected = 0.1 + 2.0 * 0.05 * DAMPING
    assert abs(out["tone"]["contrast"] - expected) < 1e-9


def test_rel_clamps_to_range():
    out = apply_intents({"tone": {"contrast": 0.99}},
                        [EditIntent(op="contrast", value=5.0, semantic="rel")])
    assert out["tone"]["contrast"] == 1.0
    out2 = apply_intents({}, [EditIntent(op="contrast", value=-100.0, semantic="rel")])
    assert out2["tone"]["contrast"] == 0.0


def test_ev_maps_to_exposure_mode():
    out = apply_intents({}, [EditIntent(op="ev", value=1.0, semantic="rel")])
    assert "exposure" in out and "mode" in out["exposure"]
    assert abs(out["exposure"]["mode"] - 0.3 * DAMPING) < 1e-9


def test_scene_intent_merges_preset():
    out = apply_intents({}, [EditIntent(op="scene", value="landscape", semantic="abs")])
    assert out["tone"]["contrast"] > 0.15
    assert out["colorcal"]["saturation"] > 0.1
    assert out["__meta__"]["scene"] == "landscape"


def test_style_intent_sets_lut():
    out = apply_intents({}, [EditIntent(op="style", value="velvia", semantic="abs")])
    assert out["stylize"]["lut_path"] == "velvia"


def test_wb_temp_rel_and_abs():
    out = apply_intents({}, [EditIntent(op="wb_temp", value=1.0, semantic="rel")])
    assert out["whitebalance"]["_temp"] == 7000.0  # 默认 6500 + 500
    assert out["whitebalance"]["mode"] == "manual"
    assert out["whitebalance"]["temp"] == 7000.0
    out2 = apply_intents({}, [EditIntent(op="wb_temp", value=5500.0, semantic="abs")])
    assert out2["whitebalance"]["_temp"] == 5500.0
    assert out2["whitebalance"]["temp"] == 5500.0
    assert out2["whitebalance"]["mode"] == "manual"


def test_tint_rel_offsets_b():
    out = apply_intents({}, [EditIntent(op="tint", value=1.0, semantic="rel")])
    assert out["whitebalance"]["_tint"] == pytest.approx(5.0)
    assert out["whitebalance"]["mode"] == "manual"
    assert out["whitebalance"]["tint"] == pytest.approx(5.0)
    out2 = apply_intents({}, [EditIntent(op="tint", value=15.0, semantic="abs")])
    assert out2["whitebalance"]["tint"] == 15.0
    assert out2["whitebalance"]["mode"] == "manual"


def test_apply_does_not_mutate_input():
    params = {"tone": {"contrast": 0.5}}
    apply_intents(params, [EditIntent(op="contrast", value=1.0)])
    assert params["tone"]["contrast"] == 0.5


# ---------------------------------------------------------------------------
# T2: parse_feedback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,op,value_abs,dir_sign", [
    ("更亮一点", "ev", None, +1),
    ("暗一点", "ev", None, -1),
    ("暖一点", "wb_temp", None, -1),
    ("冷一点", "wb_temp", None, +1),
    ("饱和一点", "saturation", None, +1),
    ("清淡一点", "saturation", None, -1),
    ("锐一点", "sharpen", None, +1),
    ("磨皮一点", "skin_strength", None, +1),
    ("降噪", "denoise", None, +1),
    ("对比高一点", "contrast", None, +1),
    ("人像", "scene", "portrait", 0),
    ("风光", "scene", "landscape", 0),
    ("黑白", "scene", "mono", 0),
    ("velvia", "style", "velvia", 0),
])
def test_parse_single_feedback(text, op, value_abs, dir_sign):
    intents = parse_feedback(text)
    assert len(intents) == 1
    it = intents[0]
    assert it.op == op
    if value_abs is not None:
        assert it.value == value_abs
        assert it.semantic == "abs"
    else:
        assert it.semantic == "rel"
        assert float(it.value) * dir_sign > 0


def test_parse_degree_words():
    i1 = parse_feedback("很亮")
    i2 = parse_feedback("亮一点")
    assert float(i1[0].value) == 2.0
    assert float(i2[0].value) == 1.0
    i3 = parse_feedback("再亮一点")
    assert float(i3[0].value) == 1.5


def test_parse_multiple_in_one_sentence():
    intents = parse_feedback("亮一点, 饱和一点, 锐一点")
    assert [i.op for i in intents] == ["ev", "saturation", "sharpen"]


def test_parse_unknown_fragment_raises():
    with pytest.raises(UnknownFragment):
        parse_feedback("亮一点, 量子态渲染")


def test_parse_english_fallback():
    intents = parse_feedback("classic_neg")
    assert intents[0].op == "style" and intents[0].value == "classic_neg"


def test_parse_empty_text():
    assert parse_feedback("") == []


# ---------------------------------------------------------------------------
# Phase 1: 新增 op (tone 四键 / clarity / dehaze / hsl / split_tone / calibration / user_curve)
# ---------------------------------------------------------------------------

def test_tone_four_keys_phase1():
    for op, param in [("shadows", "shadows"), ("highlights", "highlights"),
                      ("whites", "whites"), ("blacks", "blacks")]:
        out = apply_intents({}, [EditIntent(op=op, value=0.5, semantic="abs")])
        assert out["tone"][param] == pytest.approx(0.5)
        # 越界钳位
        out2 = apply_intents({}, [EditIntent(op=op, value=10.0, semantic="abs")])
        assert out2["tone"][param] == 1.0


def test_clarity_dehaze_phase1():
    oc = apply_intents({}, [EditIntent(op="clarity", value=0.6, semantic="abs")])
    assert oc["clarity"]["enabled"] is True
    assert oc["clarity"]["strength"] == pytest.approx(0.6)
    od = apply_intents({}, [EditIntent(op="dehaze", value=0.4, semantic="abs")])
    assert od["dehaze"]["enabled"] is True
    assert od["dehaze"]["strength"] == pytest.approx(0.4)


def test_calibration_enabled_and_params_phase1():
    out = apply_intents({}, [EditIntent(op="calibration",
                                        value={"shadow_tint": 0.3, "red_hue": 20},
                                        semantic="abs")])
    assert out["calibration"]["enabled"] is True
    assert out["calibration"]["shadow_tint"] == pytest.approx(0.3)
    assert out["calibration"]["red_hue"] == pytest.approx(20)


def test_hsl_enabled_bands_phase1():
    bands = [{"hue": 0, "sat": 30}]
    out = apply_intents({}, [EditIntent(op="hsl", value={"bands": bands}, semantic="abs")])
    assert out["hsl"]["enabled"] is True
    assert out["hsl"]["bands"] == {"bands": bands}


def test_split_tone_enabled_phase1():
    out = apply_intents({}, [EditIntent(op="split_tone",
                                        value={"shadows_hue": 45, "shadows_sat": 50,
                                               "highlights_hue": 210, "highlights_sat": 30,
                                               "balance": 0.4, "strength": 0.8},
                                        semantic="abs")])
    assert out["split_tone"]["enabled"] is True
    assert out["split_tone"]["shadows_hue"] == pytest.approx(45)
    assert out["split_tone"]["shadows_sat"] == pytest.approx(50)
    assert out["split_tone"]["balance"] == pytest.approx(0.4)
    assert out["split_tone"]["strength"] == pytest.approx(0.8)


def test_user_curve_phase1():
    curve = [[0, 0], [1, 1.1]]
    out = apply_intents({}, [EditIntent(op="user_curve", value=curve, semantic="abs")])
    assert out["tone"]["user_curve"] == curve


def test_parser_emits_new_ops():
    # 清晰度/去雾等新 op 可从中文解析到 (确定性片段); 多词模糊匹配由通用规则承担
    from pixo.render.pipeline.intents import parse_feedback
    its = parse_feedback("更清晰")
    ops = [i.op for i in its]
    assert "clarity" in ops
    its2 = parse_feedback("去雾")
    assert "dehaze" in [i.op for i in its2] or "clarity" in [i.op for i in its2]
