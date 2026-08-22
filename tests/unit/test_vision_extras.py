"""P2-8 视觉关键算法补充单测（不含 CLIP）。

覆盖：
  - pixo.vision 新算法 API 可导入；
  - 水平线检测纯算法；
  - Aesthetic/FairFace 无模型时的懒加载与降级；
  - vision_health 包含新增模型健康信息；
  - Aesthetic 七维评分（mock 推理）维度映射。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.vision import (
    FairFaceAge,
    HorizonDetector,
    PixoAestheticScorer,
    detect_horizon_angle,
    vision_health,
)
from pixo.vision.aesthetic import PIXO_DIMENSIONS


def test_new_vision_apis_importable():
    """新增算法类与函数均从 pixo.vision 导入。"""
    assert PixoAestheticScorer is not None
    assert HorizonDetector is not None
    assert FairFaceAge is not None
    assert callable(detect_horizon_angle)
    assert set(PIXO_DIMENSIONS) == {
        "overall", "quality", "composition", "lighting", "color",
        "depth_of_field", "content",
    }


def test_horizon_detector_finds_synthetic_horizontal_line():
    """合成水平线可被 Hough 检测出 has_horizon。"""
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    img[50, :, :] = 255
    img[52, :, :] = 255
    result = detect_horizon_angle(img, min_votes=2)
    assert result["has_horizon"] is True
    assert "angle" in result
    assert 0.0 <= result["confidence"] <= 1.0


def test_aesthetic_missing_model_degrades():
    """美学模型缺失时 score 返回 None，health 未就绪。"""
    scorer = PixoAestheticScorer(model_path="missing_aesthetic.pt")
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    assert scorer.score(img) is None
    info = scorer.health_info()
    assert info["ready"] is False
    assert info["loaded"] is False


def test_fairface_missing_model_degrades():
    """FairFace 模型缺失时 predict 返回 None，对象为 falsy。"""
    age = FairFaceAge(model_path="missing_fairface.onnx")
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    assert bool(age) is False
    assert age.predict_face(img) is None
    assert age.health_info()["ready"] is False


def test_vision_health_includes_new_models():
    """vision_health 包含 aesthetic/horizon/fairface 信息。"""
    health = vision_health()
    models = health["models"]
    for key in ("aesthetic", "horizon", "fairface"):
        assert key in models
        assert "ready" in models[key]
    assert models["horizon"]["ready"] is True
    assert models["aesthetic"]["ready"] is False
    assert health["aesthetic"]["ready"] is False


def test_aesthetic_mock_scorer_maps_7_dimensions():
    """注入 mock scorer/processor 验证 7 维评分映射。"""

    class _FakeProcessor:
        def __call__(self, **kwargs):
            class Inputs(dict):
                def to(self, device):
                    return self

            return Inputs(pixel_values=np.zeros((1, 3, 224, 224),
                                                dtype=np.float32))

    class _FakeScorer:
        def __call__(self, **kwargs):
            return tuple([[[float(i)]] for i in range(1, 8)])

    scorer = PixoAestheticScorer(model_path="missing.pt")
    scorer._ready = True
    scorer._scorer = _FakeScorer()
    scorer._processor = _FakeProcessor()
    scorer.device = "cpu"

    img = np.zeros((32, 32, 3), dtype=np.uint8)
    result = scorer.score(img)
    assert result is not None
    assert set(result) == set(PIXO_DIMENSIONS)
    assert result["overall"] == pytest.approx(1.0)
    assert result["quality"] == pytest.approx(2.0)
    assert result["composition"] == pytest.approx(3.0)
    assert result["lighting"] == pytest.approx(4.0)
    assert result["color"] == pytest.approx(5.0)
    assert result["depth_of_field"] == pytest.approx(6.0)
    assert result["content"] == pytest.approx(7.0)
