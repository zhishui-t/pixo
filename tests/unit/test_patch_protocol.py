"""t46 单元测试：LLM 参数补丁校验器（P3b 闸门）。

覆盖：
  - 合法补丁通过且 fully_accepted；
  - decide 层扁平方言（exposure_ev）拒绝；
  - 未注册 stage / 不在 param_schema 的参数拒绝；
  - op 白名单外拒绝；
  - 越界预检拒绝而非截断（含 delta 目标域）；
  - 用户锁定（全键/整段）拒绝；
  - 混合批次分组正确；
  - apply_patches：set/delta 落地、纯函数性、越界兜底截断；
  - oklch 域量纲防御（hsl.bands 结构字符串域感知拒绝 + 协议量纲说明）。
"""
from __future__ import annotations

import json

import pytest

from pixo.agent.patch_protocol import (
    OKLCH_DIMENSION_DOC,
    OKLCH_SAT_HINT_LIMIT,
    PatchReview,
    apply_patches,
    review_patches,
)


def _patch(param, op="set", value=0.35, **kw):
    item = {"param": param, "op": op, "value": value,
            "reason": "测试", "rule_ids": ["r1"]}
    item.update(kw)
    return item


def test_valid_patch_accepted_and_fully_accepted():
    review = review_patches([_patch("tone.brightness", value=0.35)])
    assert review.fully_accepted
    assert review.accepted[0]["param"] == "tone.brightness"
    assert review.rejected == []


def test_decide_dialect_exposure_ev_rejected():
    review = review_patches([_patch("exposure_ev", value=0.2)])
    assert not review.accepted
    assert "方言" in review.rejected[0]["reason"]


def test_unknown_stage_rejected():
    review = review_patches([_patch("nonstage.foo", value=1.0)])
    assert not review.accepted
    assert "未注册" in review.rejected[0]["reason"]


def test_param_not_in_schema_rejected():
    review = review_patches([_patch("tone.no_such_key", value=0.1)])
    assert not review.accepted
    assert "param_schema" in review.rejected[0]["reason"]


def test_op_whitelist_rejects_unknown_op():
    review = review_patches([_patch("tone.brightness", op="mul")])
    assert not review.accepted
    assert "白名单" in review.rejected[0]["reason"]


def test_out_of_range_rejected_not_truncated():
    review = review_patches(
        [_patch("tone.contrast", value=5.0)],
        current_params={"tone": {"contrast": 0.5}},
    )
    assert not review.accepted
    assert "越界" in review.rejected[0]["reason"]


def test_delta_target_range_precheck_with_current_params():
    # delta 目标 0.2+0.05=0.25 在 [0,0.5] 内 -> 通过
    ok = review_patches(
        [_patch("exposure.vignette", op="delta", value=0.05)],
        current_params={"exposure": {"vignette": 0.2}},
    )
    assert ok.fully_accepted
    # delta 目标 0.2+0.9=1.1 越出 [0,0.5] -> 拒绝
    bad = review_patches(
        [_patch("exposure.vignette", op="delta", value=0.9)],
        current_params={"exposure": {"vignette": 0.2}},
    )
    assert not bad.accepted
    assert "越界" in bad.rejected[0]["reason"]


@pytest.mark.parametrize("locked", [["tone.brightness"], ["tone"]])
def test_locked_params_reject(locked):
    review = review_patches(
        [_patch("tone.brightness", value=0.35)], locked_params=locked)
    assert not review.accepted
    assert "锁定" in review.rejected[0]["reason"]


def test_mixed_batch_grouping_correct():
    batch = [
        _patch("tone.brightness", value=0.35),
        _patch("exposure_ev", value=0.2),
        _patch("nonstage.foo", value=1.0),
        _patch("tone.contrast", value=5.0),
        _patch("exposure.vignette", op="delta", value=0.05),
    ]
    review = review_patches(
        batch,
        locked_params=["tone.brightness"],
        current_params={"exposure": {"vignette": 0.2}},
    )
    assert [i["param"] for i in review.accepted] == [
        "exposure.vignette"]
    rejected_params = [r["item"]["param"] for r in review.rejected]
    assert rejected_params == [
        "tone.brightness", "exposure_ev", "nonstage.foo", "tone.contrast"]
    assert not review.fully_accepted


def test_apply_patches_set_delta_and_purity():
    params = {"tone": {"brightness": 0.25},
              "exposure": {"vignette": 0.2}}
    review = PatchReview(
        accepted=[
            _patch("tone.brightness", value=0.35),
            _patch("exposure.vignette", op="delta", value=0.05),
        ]
    )
    merged = apply_patches(params, review)
    assert merged["tone"]["brightness"] == pytest.approx(0.35)
    assert merged["exposure"]["vignette"] == pytest.approx(0.25)
    # 纯函数：入参不被修改
    assert params["tone"]["brightness"] == 0.25
    assert params["exposure"]["vignette"] == 0.2


def test_apply_patches_clamps_fallback_for_unreviewed_use():
    """越界兜底：绕过 review 直接构造时落地值仍被 clamp 截断。"""
    review = PatchReview(accepted=[_patch("tone.contrast", value=5.0)])
    merged = apply_patches({"tone": {}}, review)
    assert merged["tone"]["contrast"] == 1.0


def test_empty_and_none_inputs():
    empty = review_patches([])
    assert empty.fully_accepted is False  # 空批次无可 apply 项
    none_result = review_patches(None)
    assert none_result.accepted == [] and none_result.rejected == []


# ---------------------------------------------------------------------------
# oklch 域量纲防御（hsl.bands 结构字符串域感知拒绝 + 协议量纲说明）
# ---------------------------------------------------------------------------

_OKLCH_BAND = {"name": "red", "domain": "oklch", "hue_center": 29,
               "width": 45, "hue_shift": 0.0, "saturation": 0.0,
               "luminance": 0.0}


def _bands_patch(bands):
    return _patch("hsl.bands", value=json.dumps(bands, ensure_ascii=False))


def test_bands_string_channel_stays_closed_but_clean():
    """合法 oklch bands 字符串仍被拒（通道只收数值），理由无域告警。"""
    review = review_patches([_bands_patch([dict(_OKLCH_BAND)])])
    assert not review.accepted
    reason = review.rejected[0]["reason"]
    assert "只收数值" in reason
    assert "越界" not in reason and "提示" not in reason


def test_bands_string_hue_out_of_range_hard_named():
    """oklch 色相角 ≥360 硬拒并命名（380 虽被内核 %360 求模也不放行语义错误）。"""
    reason = review_patches(
        [_bands_patch([dict(_OKLCH_BAND, hue_center=380)])]
    ).rejected[0]["reason"]
    assert "hue_center" in reason and "[0,360)" in reason
    assert "硬拒" in reason


@pytest.mark.parametrize("hc", [360, -20, "29", None, True, float("inf")])
def test_bands_string_hue_invalid_variants_hard(hc):
    reason = review_patches(
        [_bands_patch([dict(_OKLCH_BAND, hue_center=hc)])]
    ).rejected[0]["reason"]
    assert "hue_center" in reason


def test_bands_string_chroma_hint_not_hard():
    """saturation 超常规幅度：语义提示措辞（无"越界/硬拒"字样），非硬拒。"""
    reason = review_patches(
        [_bands_patch([dict(_OKLCH_BAND, saturation=150)])]
    ).rejected[0]["reason"]
    assert "150" in reason and "提示" in reason
    assert "硬拒" not in reason


def test_bands_no_domain_checked_as_oklch_by_default():
    """无 domain 键 band 按 Stage 缺省归属做量纲检查（F10 后缺省 oklch）。

    F10 前本测试钉「缺省 hsv → 不做 oklch 检查」；F10 缺省翻 oklch 后
    期望翻转：无 domain 键 band 归属 oklch 内核 → hue_center=9999 硬拒
    命名（运行时同按 oklch 内核执行，校验必须同语义）。「缺省=hsv 时不
    检」的旧语义由 F09 parity 测试（两缺省翻转对照）继续覆盖。
    显式 domain 戳不受缺省影响：hsv 戳 band 仍不检（第二组断言）。
    """
    no_domain = {"name": "red", "hue_center": 9999, "saturation": 900}
    reason = review_patches([_bands_patch([no_domain])]).rejected[0]["reason"]
    assert "只收数值" in reason
    assert "hue_center" in reason and "硬拒" in reason
    # 显式 hsv 戳：恒不属 oklch 量纲（与缺省翻转无关）
    stamped_hsv = {"name": "blue", "domain": "hsv",
                   "hue_center": 9999, "saturation": 900}
    reason = review_patches([_bands_patch([stamped_hsv])]).rejected[0]["reason"]
    assert "hue_center" not in reason


def test_bands_string_unparseable_json():
    reason = review_patches(
        [_patch("hsl.bands", value="{not json")]).rejected[0]["reason"]
    assert "解析失败" in reason


def test_generic_string_value_rejection_unchanged():
    """非 bands 参数的字符串值维持原通用拒绝（行为零迁移）。"""
    review = review_patches([_patch("tone.brightness", value="bright")])
    assert not review.accepted
    assert "必须是数值" in review.rejected[0]["reason"]


def test_oklch_dimension_doc_embedded_in_protocol_text():
    """协议文案内嵌 oklch 三轴量纲（单一出处 OKLCH_DIMENSION_DOC）。"""
    for token in ("[0,360)", "0.33", "L∈[0,1]", "hsl.bands", "UI_OKLCH_SPEC"):
        assert token in OKLCH_DIMENSION_DOC, token
    from pixo.agent.suggest import PATCH_SCHEMA_DOC
    assert OKLCH_DIMENSION_DOC in PATCH_SCHEMA_DOC
    assert OKLCH_SAT_HINT_LIMIT == 100.0



# ---------------------------------------------------------------------------
# F09 band 归属同源化（oklch 前置修补 d）：
# patch 校验归属 == 运行时分派归属（hsl.py:_split_bands_by_domain）
# ---------------------------------------------------------------------------

def _flip_hsl_default_domain(monkeypatch, target: str) -> None:
    """进程内把 HslStage 缺省 color_domain 覆盖为 target（零源码改动）。

    真实原始 default_params 挂在函数属性上暂存（只捕获一次, monkeypatch
    撤销后类属性已还原, 多次翻转/多测试复用均安全）。无条件覆盖（不判断
    现值）——F10 后真实缺省已是 oklch, 仍需能翻回 hsv 做双向对照。
    """
    from pixo.render.modules.hsl import HslStage
    real = getattr(_flip_hsl_default_domain, "_real", None)
    if real is None:
        real = HslStage.default_params
        _flip_hsl_default_domain._real = real

    def flipped(self, _real=real):
        d = dict(_real(self))
        d["color_domain"] = target
        return d

    monkeypatch.setattr(HslStage, "default_params", flipped)


def test_stage_default_color_domain_source():
    """归属域单一直接来源 = Stage.default_params()（F09 禁字面量复制的读点）。

    期望值与 default_params 读同源比较（翻转无关）——F10 翻缺省后本测试
    自动成立，无需修订；具体缺省值由 test_stage_default_params_preserved
    （split_tone）等缺省断言钉死。
    """
    from pixo.agent.patch_protocol import _stage_default_color_domain
    from pixo.render.modules.hsl import HslStage
    from pixo.render.modules.split_tone import SplitToneStage
    assert (_stage_default_color_domain("hsl")
            == HslStage().default_params()["color_domain"])
    assert (_stage_default_color_domain("split_tone")
            == SplitToneStage().default_params()["color_domain"])
    assert _stage_default_color_domain("no_such_stage") == ""


def test_no_domain_band_attribution_follows_stage_default(monkeypatch):
    """同源翻转自证：无 domain 键 band 的校验归属随 Stage 缺省自动跟随。

    读当前真实缺省 D（不钉具体值），进程内翻转到另一域 D'：同一
    hue_center=9999 的无 domain 键 band 的量纲检查结论必须随翻转改变
    （D 量纲下的结论 ≠ D' 量纲下的结论）。若 patch_protocol 残留字面量
    归属，翻转后结论不变 → 本测试红 —— t52 §3.3「校验假设与运行时分派
    静默分叉」由此关闭，且形态翻转无关（F10 落地后自动成立）。
    """
    from pixo.agent.patch_protocol import _stage_default_color_domain
    band = {"name": "red", "hue_center": 9999, "saturation": 900}
    current = _stage_default_color_domain("hsl")
    flipped = "oklch" if current != "oklch" else "hsv"

    def checked_as_oklch():
        reason = review_patches(
            [_bands_patch([dict(band)])]).rejected[0]["reason"]
        return "hue_center" in reason

    assert checked_as_oklch() == (current == "oklch")
    _flip_hsl_default_domain(monkeypatch, flipped)
    assert _stage_default_color_domain("hsl") == flipped
    assert checked_as_oklch() == (flipped == "oklch")


def test_patch_attribution_equals_runtime_dispatch(monkeypatch):
    """钉死「patch 校验归属 == 运行时分派归属」（F09 完成标准）。

    三种 band 形态（无 domain 键/显式 hsv/显式 oklch）× 两种 Stage 缺省
    （hsv/翻转 oklch）下, patch 侧被做 oklch 量纲检查的 band 集合必须与
    运行时 _split_bands_by_domain 的 oklch 分组逐 band 一致 —— 期望值读
    同源（default_params）, F10 切换后本测试自动成立, 无需修订。
    """
    from pixo.agent.patch_protocol import (
        _oklch_band_issues,
        _stage_default_color_domain,
    )
    from pixo.render.modules.hsl import _split_bands_by_domain
    bands = [
        {"name": "nodomain", "hue_center": 380},
        {"name": "explicit_hsv", "domain": "hsv", "hue_center": 380},
        {"name": "explicit_oklch", "domain": "oklch", "hue_center": 380},
    ]
    for target in ("hsv", "oklch"):
        _flip_hsl_default_domain(monkeypatch, target)
        default_domain = _stage_default_color_domain("hsl")
        _, oklch_group = _split_bands_by_domain(
            [dict(b) for b in bands], default_domain)
        runtime_oklch = sorted(b["name"] for b in oklch_group)
        hard, _hints = _oklch_band_issues(
            [dict(b) for b in bands], default_domain)
        patch_checked = sorted(
            b["name"] for b in bands
            if any(f"band {b['name']} " in h for h in hard))
        assert patch_checked == runtime_oklch, (
            f"缺省 {target}: patch 校验归属 {patch_checked} != "
            f"运行时分派 {runtime_oklch}")
