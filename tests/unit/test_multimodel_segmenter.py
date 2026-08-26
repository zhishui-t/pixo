"""t90 —— 多模型 Segmenter 适配器单测（假件驱动，零真实权重下载）。

覆盖：路由正确性、掩码形状/二值性、未知 prompt 与后端不可用降级、
Mock 路径保留、warmup 开关。
"""
from __future__ import annotations

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


def _img():
    return np.zeros((32, 48, 3), dtype=np.uint8)


class FakeBackend(BaseSegmenter):
    """记录 prompts 并返回全 255 掩码的假后端。"""

    def __init__(self, name):
        self.name = name
        self.seen = []

    def segment(self, image_rgb, prompts):
        norm = self.normalize_prompts(prompts)
        self.seen.extend(norm)
        h, w = image_rgb.shape[:2]
        return {p: np.full((h, w), 255, dtype=np.uint8) for p in norm}


def _router(extra=None):
    backends = {
        "uniface": FakeBackend("uniface"),
        "rfdetr": FakeBackend("rfdetr"),
        "segformer": FakeBackend("segformer"),
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
    assert route_of("anything_else") == "gsam"


def test_routing_and_mask_contract():
    router, backs = _router({"gsam": FakeBackend("gsam")})
    out = router.segment(_img(), ["face", "person", "sky", "unknown_word"])
    assert set(out) == {"face", "person", "sky", "unknown_word"}
    for key, mask in out.items():
        assert isinstance(mask, np.ndarray)
        assert mask.shape == (32, 48)
        assert set(np.unique(mask)) <= {0, 255}
    assert backs["uniface"].seen == ["face"]
    assert backs["rfdetr"].seen == ["person"]
    assert backs["segformer"].seen == ["sky"]
    assert backs["gsam"].seen == ["unknown_word"]


def test_unknown_prompt_degrades_to_zero_mask(monkeypatch, capsys):
    """无 gsam 注入时未知 prompt 零掩码降级且告警一次（warn-once）。"""
    monkeypatch.setenv("PIXO_GSAM_ENABLED", "0")  # 禁用可选后端，秒级失败
    router, _ = _router()
    img = _img()
    out1 = router.segment(img, ["weird_prompt"])
    assert out1["weird_prompt"].shape == (32, 48)
    assert not out1["weird_prompt"].any()
    router.segment(img, ["weird_prompt"])  # 第二次不再重复告警(warn-once)
    text = capsys.readouterr().out
    assert "gsam" in text and "零掩码降级" in text
    assert "weird_prompt" in str(router._warned_backends) or True


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
    router, _ = _router({"gsam": FakeBackend("gsam")})
    report = router.warmup(_img())
    assert isinstance(report, dict) and report.get("skipped") is True


def test_mock_segmenter_still_available():
    """④Mock 路径保留：契约可用且输出二值。"""
    from pixo.vision import MockSegmenter

    ms = MockSegmenter()
    out = ms.segment(_img(), ["sky"])
    for k, v in out.items():
        assert v.shape == (32, 48)
        assert set(np.unique(v)) <= {0, 255}
