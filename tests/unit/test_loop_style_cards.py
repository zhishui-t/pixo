"""R13 单元测试: 风格卡片接入 loop decide_context（知识层→决策链最后公里）。

覆盖:
  - 接线: decide_context 携带 style_cards（builtin 卡, card.to_dict() schema,
    test_know 权威用法）; 开关关闭时键整体缺席（decide 零感知, 行为回退）
  - 开关: PIXO_STYLE_CARDS **缺省关**（R13 裁决）; "1/true/on" 开;
    "0/false/off/no" 显式关; 构造入参 DI 优先; 默认关态零影响
    （decide_context 无键 + know 层零触达, 与接线前逐位一致）
  - e2e 闭环: 卡条件命中（highlight_clip_ratio > 0.03 → portra 卡
    exposure_-0.15）→ decide rule_ids 含 style_card 级 → exposure 桶落位
    （auto target_offset）→ 渲染变暗（测量回读）; 关闭对照不变
  - 优先级语义: 卡(6000) 压系统默认规则(3000)、被用户软偏好(9000)压、
    用户锁定参数硬保护
  - 降级: know 层加载失败 → 空卡表, 闭环不阻断

运行: python -m pytest tests/unit/test_loop_style_cards.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

import pixo.pipeline.loop as loop_mod
from pixo.decide import decide
from pixo.pipeline.loop import (
    SinglePhotoLoop,
    SyntheticRenderBackend,
    style_cards_enabled,
)
from pixo.vision import MockSegmenter


def _image(h=64, w=64):
    img = np.full((h, w, 3), 0.25, dtype=np.float32)
    img[h // 4: h // 2, w // 4: w // 2] = 0.45
    return img


class _LumMeasurer:
    """真实读图全局亮度（渲染变化可回读）；高光裁剪恒 0（避免喂进
    FINAL_QC 触发 qc_rollback 干扰卡建议断言——QC 链路有独立测试）。"""

    def __init__(self):
        self.seen: list[float] = []

    def measure(self, image, masks, **kw):
        arr = np.asarray(image, dtype=np.float32)
        lum = float((0.299 * arr[..., 0] + 0.587 * arr[..., 1]
                     + 0.114 * arr[..., 2]).mean())
        self.seen.append(lum)
        return {
            "global": {
                "mean_luminance": lum,
                "highlight_clip_ratio": 0.0,
                "shadow_clip_ratio": 0.0,
                "contrast": 0.5,
            },
            "regions": {},
        }


_TEST_CARD = {
    "style_id": "r13_test_card",
    "name": "R13 测试卡",
    "recommended_adjustments": {
        # 合成图经 tone gamma 编码后均值 ~151 (u8) → 条件命中;
        # dict 形态动作 = param/value 直落
        "if_mean_luminance_lt_200": {"param": "exposure", "value": -0.15},
    },
    "source": "builtin",
}


def _make_loop(**kw):
    kw.setdefault("max_iterations", 2)
    kw.setdefault("jnd_threshold", None)
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_image()),
        segmenter=MockSegmenter(),
        measurer=_LumMeasurer(),
        preview_long_edge=64,
        **kw,
    )


def _decide_events(result):
    return [e for e in result.trace_events if e["event_type"] == "decide"]


# ---------------------------------------------------------------------------
# 接线: decide_context 携带 / 开关关闭键缺席
# ---------------------------------------------------------------------------

def test_decide_context_carries_style_cards(monkeypatch):
    captured: dict = {}
    real_decide = loop_mod.decide

    def spy(ctx, rules=None):
        captured.setdefault("style_cards", ctx.get("style_cards"))
        return real_decide(ctx, rules)

    monkeypatch.setattr(loop_mod, "decide", spy)
    _make_loop(enable_style_cards=True, max_iterations=1).run(
        "sc_on", image_rgb=_image())
    cards = captured.get("style_cards")
    assert cards, "decide_context 未携带 style_cards"
    assert any(c["style_id"] == "kodak_portra_400" for c in cards)
    assert all(isinstance(c, dict) and "recommended_adjustments" in c
               for c in cards)


def test_style_cards_disabled_key_absent(monkeypatch):
    """缺省关（R13 裁决）: 默认构造不带 style_cards 键 = 与接线前逐位一致。"""
    captured: dict = {}
    real_decide = loop_mod.decide

    def spy(ctx, rules=None):
        captured["has_key"] = "style_cards" in ctx
        return real_decide(ctx, rules)

    monkeypatch.setattr(loop_mod, "decide", spy)
    _make_loop(max_iterations=1).run("sc_off", image_rgb=_image())
    assert captured["has_key"] is False
    # DI 显式关同样缺席
    captured.clear()
    _make_loop(enable_style_cards=False, max_iterations=1).run(
        "sc_off_di", image_rgb=_image())
    assert captured["has_key"] is False


# ---------------------------------------------------------------------------
# 开关: 缺省开 / 关态值 / DI 优先
# ---------------------------------------------------------------------------

def test_style_cards_env_default_off():
    """缺省关（R13 裁决）: 未设置/空 = False; 关态值 = False; 开态值 = True。"""
    assert style_cards_enabled({}) is False                      # 缺省关
    assert style_cards_enabled({"PIXO_STYLE_CARDS": ""}) is False
    for off in ("0", "false", "off", "no", "OFF"):
        assert style_cards_enabled({"PIXO_STYLE_CARDS": off}) is False
    for on in ("1", "true", "on", "yes"):
        assert style_cards_enabled({"PIXO_STYLE_CARDS": on}) is True


def test_env_and_di_precedence(monkeypatch):
    monkeypatch.setenv("PIXO_STYLE_CARDS", "1")
    loop = _make_loop(max_iterations=1)
    assert loop.enable_style_cards is True                       # env 开
    loop2 = _make_loop(enable_style_cards=False, max_iterations=1)
    assert loop2.enable_style_cards is False                     # DI 优先
    monkeypatch.delenv("PIXO_STYLE_CARDS")
    loop3 = _make_loop(max_iterations=1)
    assert loop3.enable_style_cards is False                     # 缺省关


def test_disabled_loop_must_not_fire_card_rules():
    result = _make_loop().run("sc_off_e2e", image_rgb=_image())   # 默认关
    for e in _decide_events(result):
        assert all("portra" not in rid
                   for rid in (e["value"].get("rule_ids") or []))
    assert "exposure" not in result.params


# ---------------------------------------------------------------------------
# e2e 闭环: 卡 → 决策（rule_ids 含 style_card 级）→ 参数落位 → 渲染变化
# ---------------------------------------------------------------------------

def test_style_card_rule_fires_and_render_darkens(monkeypatch):
    """e2e 闭环: 卡条件（mean_luminance<100）命中 → decide rule_ids 含
    style_card 级 → exposure 桶落位（auto target_offset -0.15）→ 渲染变暗
    （测量回读, 2^-0.15 ≈ 0.901）。"""
    import pixo.know as know_mod
    from pixo.know.cards import style_card_from_dict

    # loop 消费侧约定: load_style_cards 返回 StyleCard 对象 (构造期 .to_dict());
    # 激活走 env 路径 (PIXO_STYLE_CARDS=1), 覆盖开关->加载->接线全链
    monkeypatch.setenv("PIXO_STYLE_CARDS", "1")
    monkeypatch.setattr(know_mod, "load_style_cards",
                        lambda source=None: [style_card_from_dict(_TEST_CARD)])
    result = _make_loop().run("sc_e2e", image_rgb=_image())

    # 1) 决策: style_card 级规则真实触发（rule_ids 含卡前缀）
    fired = [rid for e in _decide_events(result)
             for rid in (e["value"].get("rule_ids") or [])]
    assert any(rid.startswith("r13_test_card_") for rid in fired), fired

    # 2) 参数落位: exposure -0.15 → auto 桶 target_offset（loop 别名映射）
    exposure = result.params["exposure"]
    assert exposure["mode"] == "auto"
    assert exposure["target_offset"] == pytest.approx(-0.15)

    # 3) 渲染变化: 施加卡建议后的测量亮度显著低于首轮
    assert len(result.measurements) == 2
    lum1 = result.measurements[0]["global"]["mean_luminance"]
    lum2 = result.measurements[-1]["global"]["mean_luminance"]
    assert lum2 < lum1 - 1.0, f"卡建议未落渲染: {lum1} -> {lum2}"


def test_disabled_control_group_render_unchanged():
    """对照: 关闭风格卡片, 同输入两轮渲染逐位一致（排除其他改动源）。"""
    result = _make_loop().run("sc_ctrl", image_rgb=_image())   # 默认关
    assert len(result.measurements) == 2
    assert result.measurements[0]["global"]["mean_luminance"] == \
        result.measurements[-1]["global"]["mean_luminance"]
    assert "exposure" not in result.params


# ---------------------------------------------------------------------------
# 优先级语义: 卡(6000) vs 规则级 / 用户锁定
# ---------------------------------------------------------------------------

def _card_rules():
    from pixo.know import load_style_cards
    return [load_style_cards()[0].to_dict()]


def test_style_card_priority_beats_default_rule():
    """卡(6000) vs 系统默认规则(3000) 同参数冲突 → 卡意图主导。"""
    result = decide({
        "style_cards": _card_rules(),
        "rules": [{"rule_id": "user_default",
                   "condition": {"metric": "highlight_clip_ratio",
                                 "op": "gt", "value": 0.01},
                   "action": {"param": "exposure", "mode": "set",
                              "value": 0.3}}],
        "params": {},
        "metrics": {"highlight_clip_ratio": 0.05},
    })
    assert result["params"]["exposure"] == pytest.approx(-0.15)
    assert any("kodak_portra_400" in rid for rid in result["rule_ids"])


def test_user_preference_rule_beats_style_card():
    """用户软偏好(9000) > 卡(6000): 用户意图恒高于卡意图。"""
    result = decide({
        "style_cards": _card_rules(),
        "rules": [{"rule_id": "user_pref",
                   "priority": 9000,
                   "condition": {"metric": "highlight_clip_ratio",
                                 "op": "gt", "value": 0.01},
                   "action": {"param": "exposure", "mode": "set",
                              "value": 0.3}}],
        "params": {},
        "metrics": {"highlight_clip_ratio": 0.05},
    })
    assert result["params"]["exposure"] == pytest.approx(0.3)
    assert "user_pref" in result["rule_ids"]


def test_locked_param_protected_against_style_card():
    """用户锁定参数: 卡规则被引擎硬保护（权威用例复述, 经 context 路径）。"""
    result = decide({
        "style_cards": _card_rules(),
        "params": {"exposure": 0.2},
        "metrics": {"highlight_clip_ratio": 0.05},
        "locked_params": ["exposure"],
    })
    assert result["params"]["exposure"] == pytest.approx(0.2)
    assert result["rule_ids"] == []


# ---------------------------------------------------------------------------
# 降级: know 层故障不阻断闭环
# ---------------------------------------------------------------------------

def test_know_layer_failure_degrades_gracefully(monkeypatch):
    import pixo.know as know_mod

    def boom(source=None):
        raise RuntimeError("know down")

    monkeypatch.setattr(know_mod, "load_style_cards", boom)
    loop = SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_image()),
        segmenter=MockSegmenter(),
        measurer=_LumMeasurer(),
        preview_long_edge=64,
        max_iterations=1,
        jnd_threshold=None,
        enable_style_cards=True,                  # 显式开 (默认关不触达 know)
    )
    assert loop.enable_style_cards is True
    assert loop._style_cards == []                # 降级为空卡表
    result = loop.run("sc_degrade", image_rgb=_image())
    assert result.state == "ACCEPTED"             # 闭环照常完成


def test_disabled_default_never_touches_know_layer(monkeypatch):
    """缺省关 = know 层**零触达** (R13 裁决承诺的 never-touches 断言,
    r13 门禁补齐): 默认关不得产生任何知识层加载/IO —— load_style_cards
    以哨兵替换, 构造期与迭代全程调用即翻红 (防未来重构把加载提到
    开关判断之前的静默回归)。"""
    import pixo.know as know_mod

    def sentinel(source=None):
        raise AssertionError(
            "默认关态触达 know.load_style_cards —— 裁决承诺 (默认关零知识层 "
            "加载/IO) 被破坏")

    monkeypatch.setattr(know_mod, "load_style_cards", sentinel)
    loop = _make_loop(max_iterations=1)           # 默认构造 (缺省关)
    assert loop.enable_style_cards is False
    assert loop._style_cards == []
    loop.run("sc_never", image_rgb=_image())      # 全流程零触达即通过
