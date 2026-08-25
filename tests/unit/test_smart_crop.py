"""smart_crop 单测: 归一化坐标约定 + 硬约束分级 + 三分法/scorer 注入 (t29)。"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.geometry.smart_crop import (
    _passes_hard,
    SUBJECT_KEEP_MASK,
    SUBJECT_KEEP_NATIVE,
    suggest_crop,
)


def _img(h=100, w=200, value=40):
    return np.full((h, w, 3), value, dtype=np.uint8)


def _contains(rect, box):
    return (rect[0] <= box[0] + 1e-9 and box[2] <= rect[2] + 1e-9
            and rect[1] <= box[1] + 1e-9 and box[3] <= rect[3] + 1e-9)


def test_output_is_normalized():
    """输出 rect 一律归一化 [0,1] 相对全幅 (接口约定)。"""
    img = _img()
    best, cands = suggest_crop(img, {}, ratios=("1:1",))
    for c in cands:
        r = c["rect"]
        assert len(r) == 4 and all(0.0 <= v <= 1.0 for v in r)
    orig_best, orig_cands = suggest_crop(img, {}, ratios=(None,))
    assert tuple(orig_cands[0]["rect"]) == (0.0, 0.0, 1.0, 1.0)
    assert orig_cands[0]["parts"]["coverage"] == pytest.approx(1.0)


def test_subject_and_face_never_cut():
    """主体框完整包含; 人脸另加头顶留白 >= 脸高 10%。"""
    img = _img()
    subj = [0.30, 0.30, 0.55, 0.70]
    best, cands = suggest_crop(img, {"subjects": [subj]}, ratios=("1:1",))
    assert cands and not cands[0].get("fallback")
    assert _contains(best, subj)

    face = [0.40, 0.20, 0.60, 0.45]
    best_f, cands_f = suggest_crop(img, {"faces": [face]}, ratios=("1:1",))
    assert _contains(best_f, face)
    fh = face[3] - face[1]
    assert best_f[1] <= face[1] - 0.10 * fh + 1e-9


def test_thirds_alignment_wins():
    """焦点恰在画面三分交点 → 规则分选中三分贴合度高的窗口。"""
    img = _img()
    subj = [0.28, 0.26, 0.38, 0.40]     # 中心 ≈ (1/3, 1/3)
    best, cands = suggest_crop(img, {"subjects": [subj]}, ratios=("1:1",))
    assert cands[0]["parts"]["thirds"] >= 0.7
    assert best == cands[0]["rect"]


def test_scorer_injection_path():
    """注入 scorer 生效: 调用计数/parts.scorer/选择随分数走; None 不致命。"""
    img = _img()
    img[:, :100] = 220                  # 左半亮
    calls = {"n": 0}

    def fake_scorer(crop):
        calls["n"] += 1
        return float(crop.mean()) / 255.0

    best, cands = suggest_crop(img, {}, ratios=("1:1",), scorer=fake_scorer)
    assert calls["n"] > 0
    assert cands[0]["parts"].get("scorer") is not None
    assert best[2] <= 0.65              # 均值分驱动选择亮侧

    best2, cands2 = suggest_crop(img, {}, ratios=("1:1",),
                                 scorer=lambda c: None)
    assert cands2 and best2             # 退化规则分仍有结果


def test_all_filtered_falls_back_full_frame():
    """脸贴上缘使头顶留白不可能满足 → 全过滤 → 回退全幅归一化窗。"""
    img = _img()
    impossible = [0.05, 0.0, 0.50, 0.50]
    best, cands = suggest_crop(img, {"faces": [impossible]},
                               ratios=("1:1", "16:9"))
    assert len(cands) == 1 and cands[0]["fallback"] is True
    assert tuple(best) == (0.0, 0.0, 1.0, 1.0)


def test_mask_bbox_tolerates_looser_cut():
    """来源分级: 同一 ~6% 出画窗口, native_box 拒绝 / mask_bbox 容忍。

    窗口右界 0.788 切掉主体 [0.60,0.80] 的左段 → 保留 (0.788-0.60)/0.20
    = 94%: native 需 >=95% 拒绝, mask_bbox 需 >=92% 通过。
    """
    win = (0.0, 0.0, 0.788, 1.0)
    subj = ([0.60, 0.30, 0.80, 0.70], SUBJECT_KEEP_NATIVE)
    assert not _passes_hard(win, [], [subj])
    win2 = (0.0, 0.0, 0.788, 1.0)
    subj_m = ([0.60, 0.30, 0.80, 0.70], SUBJECT_KEEP_MASK)
    assert _passes_hard(win2, [], [subj_m])


def test_mask_source_end_to_end():
    """带 source 标注的 dict 框走通端到端且结果非空。"""
    img = _img()
    boxes = {"subjects": [{"box": [0.30, 0.30, 0.55, 0.70],
                           "source": "mask_bbox"}]}
    best, cands = suggest_crop(img, boxes, ratios=("1:1",))
    assert cands and not cands[0].get("fallback")
    assert _contains(best, [0.30, 0.30, 0.55, 0.70])
