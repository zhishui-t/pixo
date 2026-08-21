"""T4 单元测试: 场景→风格预设注册表与应用。

覆盖 (验收 AC-04 / 任务 T4):
  - 6 个场景预设可加载 (portrait/landscape/night/street/food/mono)
  - 每个预设参数能过 engine 参数 schema (param_schema 校验)
  - 同场景两次 apply 输出一致 (确定性)
  - 未知场景 → ({}, None) 并告警
  - load_scene_presets 进程内缓存

运行: python -m pytest render/tests/test_scene_presets.py -q
"""
from __future__ import annotations

import pytest

from render.pipeline.scene_apply import apply_scene_preset, load_scene_presets
import render.modules as stages  # noqa: F401 触发注册
from render.pipeline.graph import STAGE_REGISTRY

SCENE_IDS = ["portrait", "landscape", "night", "street", "food", "mono"]


def test_six_presets_load():
    presets = load_scene_presets()
    for sid in SCENE_IDS:
        assert sid in presets, f"缺失场景预设: {sid}"
        assert isinstance(presets[sid], dict)
        assert isinstance(presets[sid].get("params"), dict)


def test_preset_params_pass_stage_schema():
    """每个预设的 stage 参数必须过对应 Stage 的 param_schema 校验。"""
    presets = load_scene_presets()
    for sid in SCENE_IDS:
        params = presets[sid]["params"]
        for stage_name, kv in params.items():
            cls = STAGE_REGISTRY.get(stage_name)
            assert cls is not None, f"[{sid}] 未知 stage: {stage_name}"
            schema = getattr(cls, "param_schema", {})
            for key, value in kv.items():
                rule = schema.get(key)
                if not rule:
                    continue  # 未声明 schema 的参数不校验
                typ = rule.get("type")
                if typ == "float" or typ == "float_or_str":
                    assert isinstance(value, (int, float)), \
                        f"[{sid}.{stage_name}.{key}] 需数值, 实得 {value!r}"
                    if "min" in rule:
                        assert value >= rule["min"], \
                            f"[{sid}.{stage_name}.{key}] {value} < min {rule['min']}"
                    if "max" in rule:
                        assert value <= rule["max"], \
                            f"[{sid}.{stage_name}.{key}] {value} > max {rule['max']}"
                elif typ == "str":
                    assert isinstance(value, str)
                    if "choices" in rule:
                        assert value in rule["choices"]
                elif typ == "bool":
                    assert isinstance(value, bool)


def test_apply_deterministic():
    for sid in SCENE_IDS:
        p1, l1 = apply_scene_preset(sid)
        p2, l2 = apply_scene_preset(sid)
        assert p1 == p2, f"[{sid}] params 非确定"
        assert l1 == l2, f"[{sid}] lut 非确定"


def test_unknown_scene_fallback():
    with pytest.warns(UserWarning, match="未知场景"):
        params, lut = apply_scene_preset("nonexistent_scene")
    assert params == {}
    assert lut is None


def test_load_cached():
    assert load_scene_presets() is load_scene_presets()


def test_portrait_enables_skin_and_landscape_boosts_contrast():
    pp, _ = apply_scene_preset("portrait")
    assert pp["skin"]["enabled"] is True
    assert pp["tone"]["contrast"] < 0.1
    lp, _ = apply_scene_preset("landscape")
    assert lp["tone"]["contrast"] > 0.15
    assert lp["colorcal"]["saturation"] > 0.1
    mp, _ = apply_scene_preset("mono")
    assert mp["colorcal"]["saturation"] == -1.0
