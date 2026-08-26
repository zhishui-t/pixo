"""t91：Sapiens 部位解析适配器与路由接线单测。

不触网：组掩码逻辑测纯函数 _part_masks；路由/降级经 backends= 注入假件；
永久降级语义 monkeypatch _load。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.vision.exceptions import (PromptNotSupportedError,
                                    SegmenterUnavailable)
from pixo.vision.segmenters.multi_router import MultiModelSegmenter
from pixo.vision.segmenters.sapiens_body import (_part_masks,
                                                 SapiensBodySegmenter)

IMG = np.zeros((8, 12, 3), dtype=np.uint8)


def _fake_backend(prompts_ok):
    class _Fake:
        def segment(self, image_rgb, prompts):
            return {p: np.full((8, 12), 255, dtype=np.uint8) for p in prompts}
    return _Fake()


def test_part_masks_groups():
    """28 类 argmap：hair/skin/clothes 各按类索引，body=非零并集。"""
    seg = np.array([[0, 3, 1], [2, 12, 22], [99, 0, 8]], dtype=np.int64)
    masks = _part_masks(seg, ("hair", "skin", "clothes", "body"))
    assert masks["hair"][0, 1] == 255 and masks["hair"].sum() == 255
    assert masks["skin"][1, 0] == 255 and masks["skin"][2, 0] == 0      # 99 不在任何组
    assert masks["clothes"][0, 2] == 255 and masks["clothes"][1, 1] == 255
    assert (masks["body"] == 255).sum() == 7                            # 非零并集=7，含负控
    assert masks["body"][0, 0] == 0 and masks["body"][2, 1] == 0        # 0 类不属 body
    for m in masks.values():
        assert set(np.unique(m)) <= {0, 255}


def test_router_routes_part_prompts_to_sapiens():
    """四个部位 prompt 全部路由 sapiens 假件且掩码契约成立。"""
    calls = {}

    class _FakeSapiens:
        def segment(self, image_rgb, prompts):
            calls["prompts"] = list(prompts)
            return {p: np.zeros((8, 12), dtype=np.uint8) for p in prompts}

    seg = MultiModelSegmenter(backends={"sapiens": _FakeSapiens()})
    out = seg.segment(IMG, ["HAIR", "Skin", "clothes", "body"])
    assert sorted(calls["prompts"]) == ["body", "clothes", "hair", "skin"]
    assert set(out) == {"hair", "skin", "clothes", "body"}
    for m in out.values():
        assert m.shape == (8, 12) and m.dtype == np.uint8


def test_skin_and_face_keys_no_conflict():
    """face(uniface 假件) 与 skin(sapiens 假件) 同请求互不覆盖。"""
    class _U:
        def segment(self, image_rgb, prompts):
            return {p: np.full((8, 12), 128, dtype=np.uint8) for p in prompts}

    class _S:
        def segment(self, image_rgb, prompts):
            return {p: np.ones((8, 12), dtype=np.uint8) for p in prompts}

    seg = MultiModelSegmenter(backends={"uniface": _U(), "sapiens": _S()})
    out = seg.segment(IMG, ["face", "skin"])
    assert set(out) == {"face", "skin"}
    assert np.unique(out["face"]) == [128] and np.unique(out["skin"]) == [1]


def test_unknown_prompt_zero_mask_degrade(monkeypatch):
    """未知 prompt 落 gsam；禁用 gsam 后零掩码降级不崩。"""
    monkeypatch.setenv("PIXO_GSAM_ENABLED", "0")

    class _FakeSapiens:
        def segment(self, image_rgb, prompts):
            return {p: np.zeros((8, 12), dtype=np.uint8) for p in prompts}

    seg = MultiModelSegmenter(backends={"sapiens": _FakeSapiens()})
    out = seg.segment(IMG, ["skin", "car"])
    assert out["skin"].max() == 0 and out["car"].max() == 0


def test_adapter_permanent_degrade(monkeypatch):
    """_load 失败→SegmenterUnavailable 且永久降级不再重试。"""
    adapter = SapiensBodySegmenter()

    def boom():
        raise RuntimeError("权重不可达")

    monkeypatch.setattr(adapter, "_load", boom)
    with pytest.raises(SegmenterUnavailable):
        adapter.segment(IMG, ["skin"])
    assert adapter._degraded is True
    with pytest.raises(SegmenterUnavailable):
        adapter.segment(IMG, ["skin"])


def test_adapter_rejects_unsupported_only():
    adapter = SapiensBodySegmenter()
    with pytest.raises(PromptNotSupportedError):
        adapter.segment(IMG, ["sky"])


# ---------- t99：id2label 核验守卫 ----------

import os

from pixo.vision.segmenters.sapiens_body import (
    _CANON_LABELS, _PART_CLASS_GROUPS, _groups_from_labels,
    _part_group_of, _extract_id2label,
)


def test_canonical_labels_classifier_and_constants_self_consistent():
    """权威 28 类表 → 分类器派生的组 == 常量（守卫'一致'的基准线）。"""
    ref = dict(enumerate(_CANON_LABELS))
    derived = _groups_from_labels(ref)
    for g in ("hair", "skin", "clothes"):
        assert derived[g] == _PART_CLASS_GROUPS[g], g
    assert _part_group_of("Background") is None
    assert _part_group_of("Upper Teeth") is None
    assert _part_group_of("Left Lower Arm") == "skin"
    assert _part_group_of("Hair") == "hair"
    assert _part_group_of("Lower Clothing") == "clothes"


def test_extract_id2label_sources():
    """config.id2label / label2id / meta 三来源都能解析。"""
    ref = {str(i): l for i, l in enumerate(_CANON_LABELS)}
    class _A: id2label = ref
    assert len(_extract_id2label(_A())) == 28
    class _B: label2id = {l: i for i, l in enumerate(_CANON_LABELS)}
    assert len(_extract_id2label(_B())) == 28
    class _C: meta = {"labels": ref}
    assert len(_extract_id2label(_C())) == 28
    class _D: pass
    assert _extract_id2label(_D()) is None
    assert _extract_id2label(None) is None


def test_guard_consistent_branch(monkeypatch, caplog):
    """fake id2label 与常量一致 → 全部组通过核验，无告警无禁用。"""
    ad = SapiensBodySegmenter()
    class _Cfg: id2label = {str(i): l for i, l in enumerate(_CANON_LABELS)}
    class _M: config = _Cfg()
    monkeypatch.setattr(ad, "_load",
                        lambda: (setattr(ad, "_model", _M()),
                                 setattr(ad, "_proc", None)))
    with caplog.at_level("WARNING"):
        ad._ensure_loaded()
    assert ad._disabled == set()
    assert ad._verify_report == {
        "hair": True, "skin": True, "clothes": True, "body": True}
    assert not [r for r in caplog.records
                if r.name.startswith("pixo.vision.segmenters")]


def test_guard_inconsistent_branch(monkeypatch, caplog):
    """fake id2label 与常量不一致（旧错误表）→ 三组全部拒用 + 告警。"""
    wrong = {str(i): list(_CANON_LABELS)[i] for i in range(28)}
    wrong["3"] = "Apparel"           # 3 不再是 Hair
    wrong["12"] = "Hair"             # Hair 跑到 12（旧 bug 位置）
    wrong["15"] = "Upper Clothing"   # 15 不再是裸肤
    ad = SapiensBodySegmenter()
    class _Cfg: id2label = wrong
    class _M: config = _Cfg()
    monkeypatch.setattr(ad, "_load",
                        lambda: (setattr(ad, "_model", _M()),
                                 setattr(ad, "_proc", None)))
    with caplog.at_level("WARNING"):
        ad._ensure_loaded()
    assert ad._disabled == {"hair", "skin", "clothes"}
    assert "body" not in ad._disabled
    assert ad._verify_report["hair"] is False
    assert any("拒用" in r for r in caplog.messages)



def test_guard_unverifiable_warns_and_refuses(monkeypatch, caplog):
    """③ 无权重/无 id2label（未核验）→ 告警 + hair/skin/clothes 拒用，body 保留。"""
    ad = SapiensBodySegmenter()
    class _C: pass
    class _M: config = _C()
    monkeypatch.setattr(ad, "_load",
                        lambda: (setattr(ad, "_model", _M()),
                                 setattr(ad, "_proc", None)))
    with caplog.at_level("WARNING"):
        ad._ensure_loaded()
    assert "未核验" in " ".join(caplog.messages)
    assert ad._disabled == {"hair", "skin", "clothes"}
    assert "body" not in ad._disabled


def test_segment_returns_empty_when_parts_disabled(monkeypatch):
    """拒用的组不出掩码（kept 空 → 返回 {}）。"""
    ad = SapiensBodySegmenter()
    ad._disabled = {"hair", "skin", "clothes"}
    monkeypatch.setattr(ad, "_ensure_loaded", lambda: True)
    out = ad.segment(IMG, ["hair", "skin", "clothes"])
    assert out == {}


def test_segment_keeps_body_when_parts_disabled(monkeypatch):
    """body 组不受核验禁用影响（非零并集，鲁棒）。"""
    import torch
    ad = SapiensBodySegmenter()
    ad._disabled = {"hair", "skin", "clothes"}
    seg = np.zeros((8, 12), dtype=np.int64)
    seg[2:6, 3:9] = 3  # 非零=人体像素
    conf = (seg != 0).astype(np.float32)
    class _R:
        # (N=1,C=2) logits：人物区 argmax→类1(非背景)，背景→类0
        logits = torch.stack(
            [torch.from_numpy(1.0 - conf), torch.from_numpy(conf)])[None]
    class _M:
        def __call__(self, **kw):
            return _R()
    ad._model = _M()
    ad._proc = lambda images, return_tensors="pt": {}
    monkeypatch.setattr(ad, "_ensure_loaded", lambda: True)
    out = ad.segment(IMG, ["hair", "body"])
    assert set(out) == {"body"}
    assert out["body"].dtype == np.uint8
    assert (out["body"] > 0).sum() >= 1


def _real_ckpt_dir() -> str | None:
    """真实 sapiens checkpoint 探测：PIXO_SAPIENS_MODEL 指向含 config.json 的目录。"""
    ck = os.environ.get("PIXO_SAPIENS_MODEL", "facebook/sapiens-seg-0.3b")
    if "/" in ck and os.path.isdir(ck) and os.path.isfile(os.path.join(ck, "config.json")):
        return ck
    return None


def _smoke_portrait() -> np.ndarray:
    """确定性合成上半身人像（头发/肤色/上衣清晰分区）；
    可用 PIXO_SAPIENS_SMOKE_IMG 指向真实名人/人像照片覆盖。"""
    env_img = os.environ.get("PIXO_SAPIENS_SMOKE_IMG")
    if env_img and os.path.isfile(env_img):
        import cv2
        img = cv2.imread(env_img)
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    import cv2
    h, w = 256, 192
    img = np.full((h, w, 3), 205, dtype=np.uint8)
    skin = (216, 178, 156)
    hair = (78, 52, 34)
    cloth = (92, 112, 182)
    cv2.ellipse(img, (96, 64), (34, 44), 0, 0, 360, skin, -1)     # 头
    cv2.ellipse(img, (96, 42), (38, 26), 0, 0, 360, hair, -1)     # 发
    cv2.rectangle(img, (50, 110), (142, 232), cloth, -1)          # 上衣
    for cx in (50, 142):
        cv2.ellipse(img, (cx, 156), (18, 62), 12, 0, 360, skin, -1)  # 双臂
    return img


@pytest.mark.skipif(
    _real_ckpt_dir() is None,
    reason="无 sapiens 权重：设 PIXO_SAPIENS_MODEL 指向含 config.json 的本地 checkpoint 目录")
def test_real_weights_smoke_part_masks(caplog):
    """② 真实权重冒烟：人像图上 hair/skin/clothes 掩码非空且有意义（body 子集）。"""
    img = _smoke_portrait()
    ad = SapiensBodySegmenter(ckpt=_real_ckpt_dir())
    out = ad.segment(img, ["hair", "skin", "clothes", "body"])
    assert set(out) == {"hair", "skin", "clothes", "body"}
    area = img.shape[0] * img.shape[1]
    body = out["body"] > 0
    for k in ("hair", "skin", "clothes", "body"):
        m = out[k]
        assert m.shape[:2] == img.shape[:2]
        assert set(np.unique(m)) <= {0, 255}
        frac = float((m > 0).sum()) / area
        assert 0.001 < frac < 0.9, (k, frac)
    for k in ("hair", "skin", "clothes"):
        assert not ((out[k] > 0) & ~body).any(), k  # 部位是 body 子集
