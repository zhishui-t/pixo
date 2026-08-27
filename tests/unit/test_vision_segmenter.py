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

from pixo.vision import (
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
    """真实模型未加载时 vision_health 应报告未就绪，但仍打通 multi_router
    聚合健康信息（t110 后真实分割栈缺省取 multi_router 聚合）。"""
    health = vision_health()

    assert health["status"] == "not_ready"
    assert health["ready"] is False
    assert health["available"] is False
    assert health["segmenter"]["name"] == "MultiModelSegmenter"
    assert health["segmenter"]["ready"] is False
    assert health["segmenter"]["loaded"] is False
    assert health["models"]["segmenter"]["name"] == "MultiModelSegmenter"
    assert "multi_router" in health["models"]

    # Mock 可用于测试，但不能作为生产模型就绪
    assert health["mock"]["available"] is True
    assert health["mock"]["ready"] is True
    assert health["mock"]["version"] == "0.1.0"


class _FakeRealSegmenter:
    """用于测试的真实分割器健康状态桩。"""

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
        detail = "真实分割器已就绪。" if self._ready else "尚未加载"
        return {
            "name": "FakeSegmenter",
            "type": "real",
            "provider": "fake",
            "available": self._ready,
            "ready": self._ready,
            "loaded": self._ready,
            "version": self._version,
            "model_path": self._model_path,
            "detail": detail,
        }


def test_vision_health_reflects_loaded_real_segmenter():
    """注入已就绪真实分割器时，vision_health 的 segmenter 信息与实例一致。"""
    fake = _FakeRealSegmenter(
        ready=True, version="8.4.99", model_path="/models/fake.pt"
    )
    health = vision_health(segmenter=fake)

    assert health["status"] == "ready"
    assert health["ready"] is True
    assert health["available"] is True
    for key in ("segmenter",):
        assert health[key]["ready"] is True
        assert health[key]["available"] is True
        assert health[key]["loaded"] is True
        assert health[key]["version"] == "8.4.99"
        assert health[key]["model_path"] == "/models/fake.pt"
    for key in ("segmenter", "multi_router"):
        assert key in health["models"]
    assert health["models"]["segmenter"]["status"] == "ready"


def test_vision_health_reflects_unloaded_real_segmenter():
    """注入未加载真实分割器时，实例的 not_ready 状态应原样反映。"""
    fake = _FakeRealSegmenter(
        ready=False, version="0.1.0", model_path="/missing/fake.pt"
    )
    health = vision_health(segmenter=fake)

    assert health["status"] == "not_ready"
    assert health["ready"] is False
    assert health["segmenter"]["ready"] is False
    assert health["segmenter"]["loaded"] is False
    assert health["segmenter"]["model_path"] == "/missing/fake.pt"
    assert health["segmenter"]["detail"] == "尚未加载"


def test_heavy_imports_isolated_in_adapters() -> None:
    """隔离门禁：全 vision 包禁止直接 import ultralytics（t110 AGPL 清偿
    后应零命中）；torch/transformers/rfdetr 仅限 aesthetic.py 与
    segmenters/ 各适配器文件内（t90 多模型扩展隔离岛纪律）。"""
    import ast
    from pathlib import Path

    vision_dir = (Path(__file__).resolve().parents[2] / "src" / "pixo" / "vision")
    segmenters_dir = vision_dir / "segmenters"
    torch_allowed_files = {vision_dir / "aesthetic.py"}
    forbidden_ultralytics = "ultralytics"
    heavy_roots = {"torch", "transformers", "rfdetr"}

    def _assert_allowed(py_file, root):
        in_segmenters = py_file.parent == segmenters_dir
        if root == forbidden_ultralytics:
            raise AssertionError(
                f"{py_file} 不允许直接 import {root}（AGPL 依赖已清零，t110）"
            )
        if root in heavy_roots:
            assert py_file in torch_allowed_files or in_segmenters, (
                f"{py_file} 不允许直接 import {root}（仅 aesthetic 与 "
                f"segmenters/ 各适配器文件内允许）"
            )

    for py_file in vision_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _assert_allowed(py_file, alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    _assert_allowed(py_file, node.module.split(".")[0])
