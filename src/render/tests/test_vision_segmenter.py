"""P0-2 单元测试：Segmenter 接口、MockSegmenter、vision_health。

覆盖:
  - MockSegmenter 输出 mask 形状/dtype/0-255 值域
  - face/sky/plant 基础合成
  - prompt 缺失（空列表/None）、空图、不可用降级
  - vision_health 未就绪状态
"""
from __future__ import annotations

import numpy as np
import pytest

from render.vision import health as health_module
from render.vision import (
    BaseSegmenter,
    EmptyImageError,
    InvalidPromptsError,
    MockSegmenter,
    Segmenter,
    SegmenterUnavailable,
    vision_health,
)


def _sample_image(height: int = 64, width: int = 96) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_mock_segmenter_face_sky_plant_output_contract():
    """MockSegmenter 能按 prompts 返回符合契约的 face/sky/plant mask。"""
    seg = MockSegmenter()
    image = _sample_image()
    masks = seg.segment(image, ["face", "sky", "plant"])

    assert set(masks) == {"face", "sky", "plant"}
    for name, mask in masks.items():
        assert isinstance(mask, np.ndarray)
        assert mask.shape == image.shape[:2]
        assert mask.dtype == np.uint8
        assert set(np.unique(mask)).issubset({0, 255})
        assert int(mask.max()) == 255
        assert int(mask.min()) == 0


def test_mock_segmenter_sky_and_plant_regions():
    """sky 位于上半部，plant 位于下半部，便于后续测量测试。"""
    seg = MockSegmenter()
    image = _sample_image()
    masks = seg.segment(image, ["sky", "plant"])

    sky = masks["sky"]
    plant = masks["plant"]
    # 天空：顶部存在像素，底部应为空
    assert bool(sky[: image.shape[0] // 2, :].any())
    assert not bool(sky[image.shape[0] // 2 :, :].any())
    # 植物：底部存在像素，顶部应为空
    assert bool(plant[image.shape[0] // 2 :, :].any())
    assert not bool(plant[: image.shape[0] // 3, :].any())


def test_empty_prompts_returns_empty_dict():
    """空 prompt 列表是合法无操作，返回空 dict。"""
    seg = MockSegmenter()
    assert seg.segment(_sample_image(), []) == {}


def test_none_prompts_returns_empty_dict_by_default():
    """prompts 缺失（None）默认优雅降级为空结果。"""
    seg = MockSegmenter()
    assert seg.segment(_sample_image(), None) == {}  # type: ignore[arg-type]


def test_none_prompts_strict_raises_invalid_prompts_error():
    """strict=True 时 prompts 缺失按输入非法处理。"""
    seg = MockSegmenter(strict=True)
    with pytest.raises(InvalidPromptsError):
        seg.segment(_sample_image(), None)  # type: ignore[arg-type]


def test_empty_image_returns_empty_dict_by_default():
    """空图（宽或高为 0）默认返回空结果，不进入 mask 合成。"""
    seg = MockSegmenter()
    assert seg.segment(np.zeros((0, 8, 3), dtype=np.uint8), ["face"]) == {}
    assert seg.segment(np.zeros((8, 0, 3), dtype=np.uint8), ["face"]) == {}


def test_empty_image_strict_raises_empty_image_error():
    """strict=True 时空图按输入非法处理。"""
    seg = MockSegmenter(strict=True)
    with pytest.raises(EmptyImageError):
        seg.segment(np.zeros((0, 8, 3), dtype=np.uint8), ["face"])
    with pytest.raises(EmptyImageError):
        seg.segment(np.zeros((8, 0, 3), dtype=np.uint8), ["face"])


def test_unavailable_mock_raises_segmenter_unavailable():
    """模型未就绪时抛 SegmenterUnavailable，上层应降级。"""
    seg = MockSegmenter(available=False)
    with pytest.raises(SegmenterUnavailable):
        seg.segment(_sample_image(), ["face"])


def test_unknown_prompt_still_returns_a_mask():
    """Mock 对未知类别回退到中央椭圆，调用方始终能拿到对应 key。"""
    seg = MockSegmenter()
    masks = seg.segment(_sample_image(), ["unknown_object"])
    assert "unknown_object" in masks
    assert masks["unknown_object"].shape == (64, 96)
    assert masks["unknown_object"].dtype == np.uint8


def test_segmenter_protocol_runtime_check():
    """MockSegmenter 符合 Segmenter 协议与 BaseSegmenter 基类契约。"""
    seg = MockSegmenter()
    assert isinstance(seg, Segmenter)
    assert isinstance(seg, BaseSegmenter)


def test_vision_health_reports_not_ready_with_mock_only():
    """真实模型未加载时 vision_health 应报告未就绪，但仍打通 YOLOE 健康信息。"""
    health = vision_health()

    assert health["status"] == "not_ready"
    assert health["ready"] is False
    assert health["available"] is False
    assert health["segmenter"]["available"] is False
    assert health["segmenter"]["ready"] is False
    assert health["segmenter"]["loaded"] is False
    assert health["segmenter"]["model_path"]
    assert health["models"]["yoloe_seg"]["loaded"] is False
    assert health["models"]["yoloe_seg"]["version"] == "0.1.0"
    assert "未就绪" in health["segmenter"]["detail"]

    # Mock 可用于测试，但不能作为生产模型就绪
    assert health["mock"]["available"] is True
    assert health["mock"]["ready"] is True
    assert health["mock"]["version"] == "0.1.0"


class _FakeYoloeSegmenter:
    """用于测试的 YoloeSegmenter 健康状态桩。"""

    def __init__(
        self,
        ready: bool = False,
        version: str = "0.1.0",
        model_path: str = "fake.pt",
    ) -> None:
        self._ready = ready
        self._version = version
        self._model_path = model_path

    def health_info(self) -> dict:
        detail = "YOLOE-26L-seg 已就绪。" if self._ready else "尚未加载"
        return {
            "name": "YOLOE-26L-seg",
            "type": "real",
            "provider": "ultralytics",
            "available": self._ready,
            "ready": self._ready,
            "loaded": self._ready,
            "version": self._version,
            "model_path": self._model_path,
            "detail": detail,
        }


def test_vision_health_reflects_loaded_yoloe_segmenter():
    """已加载 YOLOE 时，vision_health 的 real/yoloe 信息与实例一致。"""
    fake = _FakeYoloeSegmenter(
        ready=True, version="8.4.99", model_path="/models/yoloe.pt"
    )
    health = vision_health(yoloe_segmenter=fake)

    assert health["status"] == "ready"
    assert health["ready"] is True
    assert health["available"] is True
    for key in ("segmenter", "yoloe_segmenter", "yoloe"):
        assert health[key]["ready"] is True
        assert health[key]["available"] is True
        assert health[key]["loaded"] is True
        assert health[key]["version"] == "8.4.99"
        assert health[key]["model_path"] == "/models/yoloe.pt"
    for key in ("yoloe_seg", "yoloe_segmenter", "yoloe", "segmenter"):
        assert health["models"][key]["ready"] is True
    assert health["models"]["segmenter"]["status"] == "ready"


def test_vision_health_reflects_unloaded_yoloe_segmenter():
    """未加载 YOLOE 时，注入实例的 not_ready 状态应原样反映。"""
    fake = _FakeYoloeSegmenter(
        ready=False, version="0.1.0", model_path="/missing/yoloe.pt"
    )
    health = vision_health(yoloe_segmenter=fake)

    assert health["status"] == "not_ready"
    assert health["ready"] is False
    assert health["segmenter"]["ready"] is False
    assert health["segmenter"]["loaded"] is False
    assert health["segmenter"]["model_path"] == "/missing/yoloe.pt"
    assert health["segmenter"]["detail"] == "尚未加载"


def test_vision_health_uses_monkeypatched_yoloe_segmenter(monkeypatch):
    """vision_health 通过 YoloeSegmenter 类获取健康信息，便于注入测试。"""
    fake = _FakeYoloeSegmenter(ready=True, version="test-ver", model_path="mock.pt")
    monkeypatch.setattr(health_module, "YoloeSegmenter", lambda: fake)
    health = vision_health()

    assert health["segmenter"]["ready"] is True
    assert health["segmenter"]["version"] == "test-ver"
    assert health["segmenter"]["model_path"] == "mock.pt"
