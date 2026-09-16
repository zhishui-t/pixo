"""R22 F04 —— 参数栅栏单测（正/反向 + 派生性证明）。

覆盖 design-r22 §2.3/§4「安全（F04）」判据：
  - 白名单**由各 stage param_schema 派生**（非硬编码；改 schema 即生效）；
  - 敏感面严格：路径类键、路径形态字符串值、LUT 激活 → 拒；
  - 未知 stage / 未知键 / 类型 / 枚举 / 数值域（含 NaN/Inf）→ 拒；
  - **不误拒既有前端调整参数**（正向用例逐个跑真实前端键集）；
  - 25 张胶片卡与 6 个场景预设的 params **全部**通过 strict 校验
    （防 F04 卡注入被自身栅栏拒掉 = design §5 风险行）。
"""
from __future__ import annotations

import math

import pytest

from pixo.know.cards import StyleCard
from pixo.render.params import PARAM_SCHEMAS
from pixo.render.pipeline.scene_apply import (apply_scene_preset,
                                              load_scene_presets)
from pixo.render.web.session import (ParamValidationError, RawPreviewSession,
                                     validate_param_patch)

# 既有前端调整面板实际提交的参数键集合（AdjustmentsPanel / SliderParam /
# DomainToggle / HslBandRow / RegionSection / HueSpectrumBar；见
# frontend/src/components/*.tsx）。这份清单是「不误拒既有参数」的正向面。
FRONTEND_PATCHES = [
    {"exposure": {"mode": 0.35}},                       # 曝光滑杆（数值 EV）
    {"exposure": {"mode": "auto"}},                     # 缺省 as_shot/auto
    {"tone": {"highlights": -0.2, "shadows": 0.1}},     # 高光/阴影 ±1.0
    {"whitebalance": {"temp": 5200.0, "tint": -12.0}},
    {"clarity": {"strength": 0.5, "enabled": True}},
    {"skin": {"strength": 0.4, "enabled": True}},
    {"refine": {"sharpen": 0.2, "chroma_denoise": 0.5}},
    {"dehaze": {"strength": 0.3, "enabled": True}},
    {"calibration": {"red_hue": -180.0, "red_sat": 100.0,
                     "green_hue": 0.0, "blue_hue": 180.0}},
    {"split_tone": {"highlights_hue": 55.0, "highlights_sat": 8.0,
                    "shadows_hue": 264.0, "shadows_sat": 6.0,
                    "balance": 0.55, "strength": 0.5}},
    {"hsl": {"enabled": True, "smooth": 0.8, "color_domain": "oklch"}},
    # hsl.bands 前端提交**结构数组**（HslBandRow.buildBandFieldPatch），
    # 不是补丁通道的 JSON 串 —— 必须放行。
    {"hsl": {"bands": [{"name": "red", "domain": "oklch",
                        "hue_center": 29, "hue_shift": 3.0,
                        "saturation": 12.0, "luminance": 4.0}]}},
    {"region_adjust": {"enabled": True,
                       "regions": {"sky": {"exposure": -0.5,
                                           "saturation": 0.2,
                                           "warmth": 0.4}}}},
    {"compose": {"mode": "ratio", "ratio": "16:9", "center": [0.5, 0.5]}},
    {"stylize": {}},                                    # 卡内 stylize 空对象
    {"exposure": {}},                                   # 空桶 = no-op
    {"tone": {"highlights": None}},                     # None = 取消覆盖
]


@pytest.mark.parametrize("patch", FRONTEND_PATCHES,
                         ids=lambda p: "+".join(p.keys()))
def test_frontend_patch_passes_strict_fence(patch):
    """正向：既有前端调整参数一律通过（设计 §4「不误拒既有参数」）。"""
    validate_param_patch(patch, strict=True)


def test_all_film_cards_pass_strict_fence():
    """正向：25 张胶片卡的 params 全部通过（卡注入不被自身栅栏拒）。"""
    cards = StyleCard.from_films_dir()
    assert len(cards) == 25, f"卡数变化需同步本测试: {len(cards)}"
    for card in cards:
        validate_param_patch(card["params"], strict=True)


def test_all_scene_presets_pass_strict_fence():
    """正向：6 个场景预设的 params 全部通过（F05 纯 params 覆盖）。"""
    presets = load_scene_presets()
    assert sorted(presets) == ["food", "landscape", "mono", "night",
                               "portrait", "street"]
    for scene_id in presets:
        params, lut = apply_scene_preset(scene_id)
        assert lut is None, f"{scene_id} 本轮要求 lut=null（纯 params 覆盖）"
        validate_param_patch(params, strict=True)


def test_fence_derives_from_param_schema_not_hardcoded(monkeypatch):
    """派生性证明：新键进 param_schema 即被放行（无硬编码白名单）。

    R22 若有人把白名单写死成键名常量，本测试翻红：临时给 tone 的
    param_schema 加一个探测键 → 栅栏（每次调用现取 PARAM_SCHEMAS）必须
    立刻认它，并对其套用同一数值域。
    """
    probe = {"type": "float", "min": 0.0, "max": 1.0}
    monkeypatch.setitem(PARAM_SCHEMAS["tone"], "r22_probe_key", probe)

    validate_param_patch({"tone": {"r22_probe_key": 0.5}}, strict=True)
    with pytest.raises(ParamValidationError, match="r22_probe_key"):
        validate_param_patch({"tone": {"r22_probe_key": 5.0}}, strict=True)


NEGATIVE = [
    ({"s1": {"x": 1}}, "未知 stage"),
    ({"unknown_stage": {"a": 1}}, "未知 stage 2"),
    ({"__meta__": {"scene": "x"}}, "服务层控制键不归会话栅栏"),
    ({"tone": {"nope": 1}}, "未知键"),
    ({"tone": {"contrast": 5.0}}, "越上限"),
    ({"tone": {"highlights": -20.0}}, "越下限"),
    ({"whitebalance": {"temp": 10.0}}, "越下限 2"),
    ({"colorcal": {"neutral_mode": "bogus"}}, "枚举越界"),
    ({"tone": {"use_filmic": "yes"}}, "类型不符 bool"),
    ({"tone": {"contrast": "0.5"}}, "类型不符 float"),
    ({"stylize": {"lut_path": "C:/x.cube"}}, "lut_path（本轮一律拒）"),
    ({"stylize": {"lut_path": "/tmp/x.cube"}}, "lut_path 绝对路径"),
    ({"whitebalance": {"warm_cal_file": "/tmp/w.json"}}, "路径类键 _file"),
    ({"huesat": {"oklch_points_file": "..\\x.json"}}, "路径类键 _file 2"),
    ({"compose": {"ratio": "..\\..\\secret"}}, "路径形态字符串值"),
    ({"tone": {"user_curve": "/etc/passwd"}}, "路径形态值 2"),
    ({"stylize": {"lut": "velvia"}}, "LUT 激活（无 .cube 资产）"),
    ({"stylize": {"lut": [1, 2, 3]}}, "LUT 激活 2"),
    ({"compose": {"rotation": float("nan")}}, "NaN"),
    ({"compose": {"rotation": float("inf")}}, "Infinity"),
    ({"compose": {"rotation": -math.inf}}, "-Infinity"),
    ({"tone": 5}, "非 dict 参数桶"),
    ([1, 2], "非 dict patch"),
]


@pytest.mark.parametrize("patch,why", NEGATIVE, ids=[n[1] for n in NEGATIVE])
def test_strict_fence_rejects(patch, why):
    """反向：非法 stage/键/数值域/枚举/路径 → ParamValidationError。"""
    with pytest.raises(ParamValidationError):
        validate_param_patch(patch, strict=True)


def test_non_strict_fence_keeps_synthetic_stages_but_blocks_paths():
    """缺省会话：只查敏感面 —— 合成 stage 放行（既有测试语义不变）、
    路径类恒拒（敏感面默认开）。"""
    for patch in ({"s1": {"x": 1}}, {"s2": {"value": 0.75}},
                  {"wb": {"gain": 0.5}}, {"tone": {"contrast": 5.0, "a": 1}}):
        validate_param_patch(patch, strict=False)      # 不抛

    for patch in ({"stylize": {"lut_path": "/x.cube"}},
                  {"tone": {"user_curve": "../x.json"}}):
        with pytest.raises(ParamValidationError):
            validate_param_patch(patch, strict=False)


def test_session_without_flag_keeps_synthetic_stages():
    """正向：直接构造的会话（validate_params 缺省 False）行为不变。"""
    sess = RawPreviewSession("x.nef", prof=object())
    assert sess.validate_params is False
    assert sess.update_params({"s1": {"x": 1}}) == 1
    assert sess.params == {"s1": {"x": 1}}


def test_session_strict_flag_rejects_before_merge():
    """strict 会话：拒绝且**不落部分合并**（generation 不推进）。"""
    sess = RawPreviewSession("x.nef", prof=object(), validate_params=True)
    sess.update_params({"tone": {"contrast": 0.2}})
    gen = sess.generation

    with pytest.raises(ParamValidationError):
        # 同一 patch 里既有合法键又有非法键 → 整批拒绝
        sess.update_params({"whitebalance": {"temp": 5200.0},
                            "tone": {"contrast": 99.0}})
    assert sess.generation == gen
    assert "whitebalance" not in sess.params
    assert sess.params["tone"]["contrast"] == 0.2


def test_default_session_blocks_lut_path():
    """敏感面默认开：不设 strict 的会话也拒 lut_path。"""
    sess = RawPreviewSession("x.nef", prof=object())
    with pytest.raises(ParamValidationError, match="lut_path"):
        sess.update_params({"stylize": {"lut_path": "/x.cube"}})
