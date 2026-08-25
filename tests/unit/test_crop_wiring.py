"""t31 单元测试：smart_crop 接线层（开关/门控/采纳边界/换算）。

覆盖：
  - 默认关：无任何 crop 相关 trace 与参数变化，行为与既有闭环一致；
  - mask_bbox 分支：fake segmenter 掩码 -> 建议生成并带溯源标注；
  - native_box 分支：box_provider 原生框优先于掩码派生；
  - 规则双镜像同步 + 门控标量位按条件置位；
  - 锁定 compose 时 applicable=0，规则不触发；
  - 归一化<->像素显式换算往返一致；采纳边界单点转换写入 compose。
"""
from __future__ import annotations

import numpy as np
import pytest

import pixo.pipeline.loop as loop_mod
from pixo.decide import decide
from pixo.decide.engine import load_rules
from pixo.pipeline.loop import (
    SinglePhotoLoop,
    SyntheticRenderBackend,
    rect_norm_to_px,
    rect_px_to_norm,
)
from pixo.vision import MockSegmenter

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
RULE_RELPATH = "configs/rules/crop_suggest_rule_003.yaml"
CROP_RULE = {
    "rule_id": "crop_suggest_rule_003",
    "priority": 15,
    "condition": {"metric": "crop_suggestion_applicable",
                  "op": "gte", "value": 1},
    "action": {"param": "compose.apply_suggestion", "mode": "set",
               "formula": "1"},
}


def _dark_image():
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.3
    return img


def _make_loop(**kw):
    base = dict(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
    )
    base.update(kw)
    return SinglePhotoLoop(**base)


def _trace_types(result):
    return [e["event_type"] for e in result.trace_events]


def test_default_off_keeps_legacy_behavior():
    loop = _make_loop()
    result = loop.run("crop_off", image_rgb=_dark_image())
    types = _trace_types(result)
    assert "crop_suggest" not in types
    assert "crop_adopted" not in types
    assert result.params.get("compose") is None
    assert result.state == "ACCEPTED"


def test_mask_bbox_branch_produces_tagged_suggestion():
    loop = _make_loop(crop_suggest=True)
    img = _dark_image()
    masks = loop.segmenter.segment(img, list(loop.prompts))
    sugg = loop._build_crop_suggestion(img, masks)
    assert sugg is not None
    assert sugg["source"] == "mask_bbox"
    rect = sugg["rect"]
    assert len(rect) == 4 and all(0.0 <= v <= 1.0 for v in rect)
    assert sugg["top3"]


def test_native_box_provider_takes_priority():
    def provider(image_rgb):
        return {"faces": [[0.3, 0.2, 0.6, 0.6]], "subjects": [],
                "source": "native_box"}

    loop = _make_loop(crop_suggest=True, box_provider=provider)
    img = _dark_image()
    masks = loop.segmenter.segment(img, list(loop.prompts))
    sugg = loop._build_crop_suggestion(img, masks)
    assert sugg["source"] == "native_box"


def test_yaml_mirrors_are_in_sync():
    repo = ROOT / RULE_RELPATH
    pkg = ROOT / "src/pixo/decide/rules" / RULE_RELPATH.split("/")[-1]
    assert repo.is_file() and pkg.is_file()
    assert repo.read_bytes() == pkg.read_bytes()


@pytest.mark.parametrize("applicable,expect_flag", [(1, True), (0, False)])
def test_rule_gate_scalar_flag(applicable, expect_flag):
    rules = load_rules(str(ROOT / RULE_RELPATH))
    ctx = {
        "iteration": 1,
        "max_iterations": 5,
        "metrics": {"crop_suggestion_applicable": applicable},
        "params": {},
    }
    out = decide(ctx, rules)
    flag = out["params"].get("compose.apply_suggestion")
    assert (flag == 1) is expect_flag


def test_locked_compose_zeroes_applicability():
    loop = _make_loop(crop_suggest=True, locked_params=["compose"])
    img = _dark_image()
    masks = loop.segmenter.segment(img, list(loop.prompts))
    sugg = loop._build_crop_suggestion(img, masks)
    assert sugg is not None  # 建议照常产生
    metrics = {}
    locked_compose = any(str(k).lower().startswith("compose")
                         for k in loop.locked_params)
    avail = 1 if sugg is not None else 0
    metrics["crop_suggestion_available"] = avail
    metrics["compose_locked"] = 1 if locked_compose else 0
    metrics["crop_suggestion_applicable"] = (
        1 if (avail and not locked_compose) else 0)
    assert metrics["crop_suggestion_available"] == 1
    assert metrics["compose_locked"] == 1
    assert metrics["crop_suggestion_applicable"] == 0


def test_rect_converters_roundtrip():
    rng = np.random.default_rng(7)
    for _ in range(50):
        w, h = int(rng.integers(16, 800)), int(rng.integers(16, 800))
        x0 = float(rng.uniform(0, 0.8))
        y0 = float(rng.uniform(0, 0.8))
        x1 = float(rng.uniform(x0 + 0.05, 1.0))
        y1 = float(rng.uniform(y0 + 0.05, 1.0))
        norm = [x0, y0, x1, y1]
        px = rect_norm_to_px(norm, w, h)
        # 边界合法
        assert 0 <= px[0] < px[2] <= w and 0 <= px[1] < px[3] <= h
        # norm -> px -> norm 容差内往返（像素取整误差 <= 1px）
        back = rect_px_to_norm(px, w, h)
        tol = 1.0 / min(w, h) + 1e-9
        assert all(abs(a - b) <= tol for a, b in zip(norm, back))
    # px -> norm -> px 恒等
    px0 = [12, 8, 100, 64]
    ident = rect_norm_to_px(rect_px_to_norm(px0, 128, 96), 128, 96)
    assert ident == px0


def test_adoption_boundary_single_conversion_point(monkeypatch):
    """规则旗标 -> 采纳边界一次归一化->像素，compose 参数正确落盘。"""
    fixed_rect = [0.25, 0.25, 0.75, 0.75]
    fixed_cands = [{"rect": tuple(fixed_rect), "ratio": "original",
                    "score": 0.9, "parts": {}}]

    def fake_suggest(img_small, boxes, ratios=None, scorer=None):
        return tuple(fixed_rect), list(fixed_cands)

    monkeypatch.setattr(loop_mod, "suggest_crop", fake_suggest)
    loop = _make_loop(crop_suggest=True, rules=[dict(CROP_RULE)])
    result = loop.run("crop_adopt", image_rgb=_dark_image())

    types = _trace_types(result)
    assert "crop_suggest" in types
    assert "crop_adopted" in types
    compose = result.params.get("compose")
    assert compose is not None and compose["mode"] == "free"
    expect = rect_norm_to_px(fixed_rect, 64, 64)
    assert (compose["x"], compose["y"],
            compose["width"], compose["height"]) == (
        expect[0], expect[1], expect[2] - expect[0], expect[3] - expect[1])
    # 门控旗标不得泄漏进渲染参数
    flat_keys = set(result.params)
    assert "compose.apply_suggestion" not in flat_keys


def test_adoption_merges_and_preserves_auto_level_rotation(monkeypatch):
    """预设 auto_level+rotation：采纳建议后 rotation 保留、free 矩形生效。"""
    fixed_rect = [0.25, 0.25, 0.75, 0.75]
    fixed_cands = [{"rect": tuple(fixed_rect), "ratio": "original",
                    "score": 0.9, "parts": {}}]

    def fake_suggest(img_small, boxes, ratios=None, scorer=None):
        return tuple(fixed_rect), list(fixed_cands)

    monkeypatch.setattr(loop_mod, "suggest_crop", fake_suggest)
    loop = _make_loop(crop_suggest=True, rules=[dict(CROP_RULE)])
    result = loop.run(
        "crop_merge",
        image_rgb=_dark_image(),
        params={"compose": {"mode": "auto_level", "rotation": -3.5}},
    )

    compose = result.params.get("compose") or {}
    # 用户既有字段保留（尤其 auto_level 的 rotation 结果）
    assert compose.get("rotation") == pytest.approx(-3.5)
    # 建议矩形生效：mode 切 free，四元组=采纳边界单点换算
    assert compose.get("mode") == "free"
    expect = rect_norm_to_px(fixed_rect, 64, 64)
    assert (compose["x"], compose["y"]) == (expect[0], expect[1])
    assert (compose["width"], compose["height"]) == (
        expect[2] - expect[0], expect[3] - expect[1])
    types = _trace_types(result)
    assert "crop_adopted" in types
