"""t90 —— 多模型 Segmenter 适配器单测（假件驱动，零真实权重下载）。

覆盖：路由正确性、掩码形状/二值性、未知 prompt 与后端不可用降级、
Mock 路径保留、warmup 开关。

注：uniface/sapiens 在 model_licenses.json 中为 internal_development_only，
multi_router 默认门控（PIXO_ALLOW_RESTRICTED=1 放行）；本文件测 canonical
路由表，故 autouse 放行。门控行为另见 test_vision_router_semantics.py。
"""
from __future__ import annotations

import logging

import numpy as np
import pytest

from pixo.vision.base import BaseSegmenter
from pixo.vision.exceptions import SegmenterUnavailable
from pixo.vision.segmenters.common import to_binary_mask, zeros_mask
from pixo.vision.segmenters.multi_router import (
    MultiModelSegmenter,
    route_of,
)
from pixo.vision.segmenters.uniface_face import UniFaceSegmenter


@pytest.fixture(autouse=True)
def _allow_restricted(monkeypatch):
    """放行 internal_development_only 后端以测完整路由表。"""
    monkeypatch.setenv("PIXO_ALLOW_RESTRICTED", "1")


def _img():
    return np.zeros((32, 48, 3), dtype=np.uint8)


class FakeBackend(BaseSegmenter):
    """记录 prompts 并返回全 255 掩码的假后端。"""

    def __init__(self, name):
        self.name = name
        self.seen = []
        self.warmup_calls = 0

    def segment(self, image_rgb, prompts):
        norm = self.normalize_prompts(prompts)
        self.seen.extend(norm)
        h, w = image_rgb.shape[:2]
        return {p: np.full((h, w), 255, dtype=np.uint8) for p in norm}

    def warmup(self, image=None):
        self.warmup_calls += 1
        return {"warmed": True}


def _router(extra=None):
    backends = {
        "uniface": FakeBackend("uniface"),
        "rfdetr": FakeBackend("rfdetr"),
        "segformer": FakeBackend("segformer"),
        "sapiens": FakeBackend("sapiens"),
    }
    if extra:
        backends.update(extra)
    return MultiModelSegmenter(backends=backends), backends


def test_route_table():
    assert route_of("face") == "uniface"
    assert route_of("person") == "rfdetr"
    assert route_of("subject") == "rfdetr"
    for p in ("sky", "plant", "mountain", "tree", "grass"):
        assert route_of(p) == "segformer", p
    assert route_of("anything_else") is None  # 未知 prompt 无路由后端


def test_routing_and_mask_contract():
    router, backs = _router()
    out = router.segment(_img(), ["face", "person", "sky", "unknown_word"])
    assert set(out) == {"face", "person", "sky", "unknown_word"}
    for key, mask in out.items():
        assert isinstance(mask, np.ndarray)
        assert mask.shape == (32, 48)
        assert set(np.unique(mask)) <= {0, 255}
    assert backs["uniface"].seen == ["face"]
    assert backs["rfdetr"].seen == ["person"]
    assert backs["segformer"].seen == ["sky"]
    # 未知 prompt 不投递到任何后端（零掩码兜底见下一用例）
    assert all("unknown_word" not in b.seen for b in backs.values())
    assert not out["unknown_word"].any()


def test_unknown_prompt_degrades_to_zero_mask(caplog):
    """未知 prompt（无路由后端）零掩码降级，告警一次（warn-once）。"""
    router, _ = _router()
    img = _img()
    with caplog.at_level(logging.WARNING):
        out1 = router.segment(img, ["sky", "weird_prompt"])
    # 已知组正常；未知 prompt 零掩码，契约形状保持
    assert out1["sky"].all()
    assert out1["weird_prompt"].shape == (32, 48)
    assert not out1["weird_prompt"].any()
    assert "weird_prompt" in caplog.text and "零掩码降级" in caplog.text
    # 路由未命中≠模型错误：不记 last_degraded、不上抛
    assert router.last_degraded == []
    with caplog.at_level(logging.WARNING):
        router.segment(img, ["sky", "weird_prompt"])  # 第二次不再重复告警
    assert caplog.text.count("零掩码降级") == 1
    assert "missing:weird_prompt" in router._warned_backends


def test_all_groups_unavailable_raises():
    """请求的全部 prompt 组后端均不可用 → 抛 SegmenterUnavailable（契约）。"""

    class _Down(FakeBackend):
        def segment(self, image_rgb, prompts):
            raise SegmenterUnavailable("simulated-down")

    router = MultiModelSegmenter(backends={
        "uniface": _Down("uniface"), "rfdetr": _Down("rfdetr")})
    with pytest.raises(SegmenterUnavailable, match="uniface.*rfdetr|rfdetr.*uniface"):
        router.segment(_img(), ["face", "person"])
    assert sorted(router.last_degraded) == ["rfdetr", "uniface"]


def test_single_group_unavailable_raises():
    """仅一个 prompt 组且其后端不可用 → 同样上抛（契约）。"""

    class _Down(FakeBackend):
        def segment(self, image_rgb, prompts):
            raise SegmenterUnavailable("simulated-down")

    router = MultiModelSegmenter(backends={"uniface": _Down("uniface")})
    with pytest.raises(SegmenterUnavailable):
        router.segment(_img(), ["face"])
    assert router.last_degraded == ["uniface"]


def test_all_unknown_prompts_zero_mask_no_raise():
    """纯未知 prompt 请求：路由未命中≠模型错误 → 全零掩码，不上抛。"""
    router, _ = _router()
    out = router.segment(_img(), ["weird_prompt", "another_unknown"])
    assert not out["weird_prompt"].any()
    assert not out["another_unknown"].any()
    assert router.last_degraded == []


def test_backend_unavailable_degrades_others_untouched():
    class _Down(FakeBackend):
        def segment(self, image_rgb, prompts):
            raise SegmenterUnavailable("simulated-down")

    router, _ = _router({"face_backend_unused": None})
    router.backends["uniface"] = _Down("uniface")
    out = router.segment(_img(), ["face", "sky"])
    assert not out["face"].any()
    assert out["sky"].all()


def test_adapter_unavailable_raises_for_direct_use(monkeypatch):
    """直连适配器在加载失败时抛 SegmenterUnavailable（隔离验证）。"""
    ad = UniFaceSegmenter()

    def _boom():
        raise SegmenterUnavailable("simulated-missing-deps")

    monkeypatch.setattr(ad, "_load", _boom)
    with pytest.raises(SegmenterUnavailable):
        ad.segment(_img(), ["face"])


def test_binary_helper():
    raw = np.array([[0.0, 0.7], [0.2, 3.0]], dtype=np.float32)
    m = to_binary_mask(raw, 2, 2)
    assert set(np.unique(m)) <= {0, 255}
    assert (m[[0, 1], [1, 1]] == 255).all()
    z = zeros_mask(4, 6)
    assert z.shape == (4, 6) and not z.any()


def test_warmup_gate(monkeypatch):
    monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", "0")
    router, _ = _router()
    report = router.warmup(_img())
    assert isinstance(report, dict) and report.get("skipped") is True


def test_warmup_iterates_all_routed_backends():
    """warmup 遍历路由表全量后端并逐个实例化（假件断言被调）。"""
    router, backs = _router()
    router.warmup(_img())
    assert set(router.backends) >= {
        "uniface", "rfdetr", "segformer", "sapiens"}
    for name, fake in backs.items():
        assert fake.warmup_calls == 1, name


def test_mock_segmenter_still_available():
    """④Mock 路径保留：契约可用且输出二值。"""
    from pixo.vision import MockSegmenter

    ms = MockSegmenter()
    out = ms.segment(_img(), ["sky"])
    for k, v in out.items():
        assert v.shape == (32, 48)
        assert set(np.unique(v)) <= {0, 255}
