"""t46 单元测试：LLM 参数补丁校验器（P3b 闸门）。

覆盖：
  - 合法补丁通过且 fully_accepted；
  - decide 层扁平方言（exposure_ev）拒绝；
  - 未注册 stage / 不在 param_schema 的参数拒绝；
  - op 白名单外拒绝；
  - 越界预检拒绝而非截断（含 delta 目标域）；
  - 用户锁定（全键/整段）拒绝；
  - 混合批次分组正确；
  - apply_patches：set/delta 落地、纯函数性、越界兜底截断。
"""
from __future__ import annotations

import pytest

from pixo.agent.patch_protocol import (
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
