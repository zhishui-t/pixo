"""P0-3 单元测试：YoloeSegmenter mask 提取、合并与降级。

使用假模型验证：
  - 遵守 Segmenter 协议与 BaseSegmenter 契约；
  - 读取 results[0].masks 并把多实例按 label 合并为 0/255 mask；
  - prompt-free 未命中时走文本模型兜底；
  - 无检测时返回全零 mask；
  - 模型文件缺失时抛 SegmenterUnavailable；
  - 输入 RGB 正确转换为 BGR uint8；
  - AGPL 隔离：render/vision 内只有 yoloe.py 直接 import ultralytics/torch。
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from render.vision import BaseSegmenter, Segmenter, SegmenterUnavailable
from render.vision.segmenters.yoloe import YoloeSegmenter


class _FakeBoxes:
    """最小 boxes 桩，只提供 cls。"""

    def __init__(self, cls: list[int]) -> None:
        self.cls = np.asarray(cls, dtype=np.int64)


class _FakeMasks:
    """最小 masks 桩，提供 ndarray data。"""

    def __init__(self, data: np.ndarray) -> None:
        self.data = np.asarray(data, dtype=np.uint8)

    def numpy(self) -> "_FakeMasks":
        return self


class _FakeResult:
    """最小 ultralytics Results 桩。"""

    def __init__(
        self,
        names: dict[int, str],
        cls: list[int],
        masks: np.ndarray,
    ) -> None:
        self.names = names
        self.boxes = _FakeBoxes(cls)
        self.masks = _FakeMasks(masks)


class _FakeModel:
    """最小 YOLOE 模型桩：predict 返回固定结果。"""

    def __init__(self, names: dict[int, str]) -> None:
        self.names = names
        self.predict_calls: list[np.ndarray] = []

    def predict(
        self,
        image: np.ndarray,
        conf: float | None = None,
        verbose: bool = False,
    ) -> list[_FakeResult]:
        self.predict_calls.append(image)
        return []


class _FakeTextModel(_FakeModel):
    """文本模式桩：记录 set_classes，并返回固定 masks。"""

    def __init__(
        self,
        names: dict[int, str],
        masks: np.ndarray,
        cls: list[int],
    ) -> None:
        super().__init__(names)
        self._masks = masks
        self._cls = cls
        self.last_classes: list[str] | None = None

    def set_classes(self, classes: list[str]) -> None:
        self.last_classes = list(classes)

    def predict(
        self,
        image: np.ndarray,
        conf: float | None = None,
        verbose: bool = False,
    ) -> list[_FakeResult]:
        self.predict_calls.append(image)
        return [_FakeResult(self.names, self._cls, self._masks)]


def _make_segmenter(
    model: _FakeModel | None = None,
    text_model: _FakeTextModel | None = None,
) -> YoloeSegmenter:
    """构造不触发真实模型加载的 YoloeSegmenter 测试实例。"""
    seg = YoloeSegmenter(model_path="fake.pt", conf_threshold=0.25)
    if model is not None:
        seg.model = model
        seg.names = model.names
        seg._ready = True
    if text_model is not None:
        seg._text_model = text_model
    return seg


def _sample_image() -> np.ndarray:
    """8x8 RGB 图，各通道用不同值便于验证 BGR 转换。"""
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    img[..., 0] = 10
    img[..., 1] = 20
    img[..., 2] = 30
    return img


def test_yoloe_segmenter_conforms_to_segmenter_protocol() -> None:
    """YoloeSegmenter 实现 Segmenter 协议与 BaseSegmenter 基类。"""
    seg = YoloeSegmenter(model_path="fake.pt")
    assert isinstance(seg, Segmenter)
    assert isinstance(seg, BaseSegmenter)
    assert seg.ready is False
    health = seg.health_info()
    assert health["ready"] is False
    assert health["name"] == "YOLOE-26L-seg"


def test_yoloe_segmenter_merges_multiple_instances_by_prompt() -> None:
    """同 label 多实例 OR 合并，返回 0/255 uint8 mask。"""
    names = {0: "face", 1: "face", 2: "sky"}
    masks = np.zeros((3, 8, 8), dtype=np.uint8)
    masks[0, 0:4, 0:4] = 1
    masks[1, 4:8, 4:8] = 1
    masks[2, 0:2, :] = 1
    cls = [0, 1, 2]
    model = _FakeModel(names)
    model.predict = lambda image, conf=None, verbose=False: [
        _FakeResult(names, cls, masks)
    ]  # type: ignore[method-assign]

    seg = _make_segmenter(model=model)
    result = seg.segment(_sample_image(), ["face", "sky"])

    assert set(result) == {"face", "sky"}
    for mask in result.values():
        assert mask.shape == (8, 8)
        assert mask.dtype == np.uint8
        assert set(np.unique(mask)).issubset({0, 255})

    # face 的两块实例被 OR 合并，且覆盖两个区域
    face = result["face"]
    assert bool(face[0:4, 0:4].any())
    assert bool(face[4:8, 4:8].any())
    assert int(np.count_nonzero(face)) == int(
        np.count_nonzero(masks[0]) + np.count_nonzero(masks[1])
    )
    # sky 只保留顶部条带
    assert not bool(result["sky"][4:, :].any())


def test_yoloe_segmenter_falls_back_to_text_model() -> None:
    """prompt-free 未命中时用文本模式实例补充。"""
    main_names = {0: "face"}
    main_masks = np.zeros((1, 8, 8), dtype=np.uint8)
    main_masks[0, 2:6, 2:6] = 1
    main_model = _FakeModel(main_names)
    main_model.predict = lambda image, conf=None, verbose=False: [
        _FakeResult(main_names, [0], main_masks)
    ]  # type: ignore[method-assign]

    plant_names = {0: "plant"}
    plant_masks = np.zeros((1, 8, 8), dtype=np.uint8)
    plant_masks[0, 0:5, 0:8] = 1
    text_model = _FakeTextModel(plant_names, plant_masks, [0])

    seg = _make_segmenter(model=main_model, text_model=text_model)
    result = seg.segment(_sample_image(), ["face", "plant"])

    assert text_model.last_classes == ["plant"]
    assert bool(result["face"].any())
    assert bool(result["plant"].any())
    assert result["plant"].shape == (8, 8)


def test_yoloe_segmenter_returns_zero_mask_when_no_detection() -> None:
    """无检测时每个请求 prompt 返回全零 mask，不抛异常。"""
    names = {0: "face"}
    model = _FakeModel(names)
    model.predict = lambda image, conf=None, verbose=False: [
        _FakeResult(names, [], np.zeros((0, 8, 8), dtype=np.uint8))
    ]  # type: ignore[method-assign]
    seg = _make_segmenter(model=model)
    result = seg.segment(_sample_image(), ["face", "sky"])
    assert result["face"].shape == (8, 8)
    assert not bool(result["face"].any())
    assert not bool(result["sky"].any())


def test_yoloe_segmenter_unavailable_when_model_missing() -> None:
    """模型文件不存在时抛 SegmenterUnavailable。"""
    seg = YoloeSegmenter(
        model_path="definitely-not-exist-yoloe.pt",
        conf_threshold=0.25,
    )
    with pytest.raises(SegmenterUnavailable):
        seg.segment(_sample_image(), ["face"])


def test_yoloe_segmenter_converts_rgb_float_to_bgr_uint8() -> None:
    """RGB float32 [0,1] 转 BGR uint8 且通道顺序正确。"""
    seg = _make_segmenter()
    rgb = np.zeros((4, 4, 3), dtype=np.float32)
    rgb[..., 0] = 0.1
    rgb[..., 1] = 0.2
    rgb[..., 2] = 0.3
    bgr = seg._to_bgr_uint8(rgb)
    assert bgr.dtype == np.uint8
    assert bgr.shape == (4, 4, 3)
    # R=25.5→26, G=51, B=76.5→76（四舍五入）
    assert bgr[0, 0, 0] == 76
    assert bgr[0, 0, 1] == 51
    assert bgr[0, 0, 2] == 26


def test_agpl_imports_isolated_in_yoloe_only() -> None:
    """AGPL 隔离：render/vision 内只有 yoloe.py 直接 import torch/ultralytics。"""
    vision_dir = Path(__file__).resolve().parents[2] / "vision"
    allowed = vision_dir / "segmenters" / "yoloe.py"
    forbidden_imports = {
        "ultralytics",
        "torch",
    }
    for py_file in vision_dir.rglob("*.py"):
        if py_file == allowed:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in forbidden_imports, (
                        f"{py_file} 不允许直接 import {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    assert root not in forbidden_imports, (
                        f"{py_file} 不允许从 {node.module} import"
                    )
