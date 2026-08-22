"""P0-4 单元测试：Pixo Vision 区域/全局测量。

覆盖:
  - 全局测量：纯色/灰度图、高光/阴影裁切、preview 估计。
  - 区域测量：合成区域数值、mean_lab/亮度/裁切、面积占比。
  - 可靠性：低置信度、低面积占比。
  - 失败注入：空 mask、NaN mask、全零 mask 不抛异常。
  - VisionMeasure 整图组装输出符合 §5.4 结构。
"""
from __future__ import annotations

import numpy as np
import pytest

from render.vision import (
    MockSegmenter,
    VisionMeasure,
    measure_global,
    measure_haze,
    measure_motion_blur,
    measure_region,
    measure_sharpness,
    measure_zone_exposure,
)


def _image(height: int = 100, width: int = 100) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_measure_global_solid_gray():
    """纯灰图的全局均值/裁切/对比度应为稳定值。"""
    result = measure_global(np.full((32, 48, 3), 128, dtype=np.uint8))

    assert result["mean_luminance"] == pytest.approx(128.0, abs=0.5)
    assert result["highlight_clip_ratio"] == 0.0
    assert result["shadow_clip_ratio"] == 0.0
    assert result["contrast"] == pytest.approx(0.0, abs=1e-6)
    assert 0.0 <= result["preview_highlight_clip_estimate"] <= 1.0


def test_measure_global_white_and_black():
    """纯白/纯黑图的高光与阴影裁切占比应正确。"""
    white = measure_global(np.full((16, 16, 3), 255, dtype=np.uint8))
    black = measure_global(np.full((16, 16, 3), 0, dtype=np.uint8))

    assert white["mean_luminance"] == pytest.approx(255.0, abs=0.5)
    assert white["highlight_clip_ratio"] == pytest.approx(1.0)
    assert white["shadow_clip_ratio"] == 0.0
    assert white["preview_highlight_clip_estimate"] == pytest.approx(1.0)

    assert black["mean_luminance"] == pytest.approx(0.0, abs=0.5)
    assert black["highlight_clip_ratio"] == 0.0
    assert black["shadow_clip_ratio"] == pytest.approx(1.0)


def test_measure_region_valid_half_white():
    """有效 mask 区域应返回正确面积、亮度和 Lab 字段。"""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:50, :] = (255, 255, 255)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[:50, :] = 255

    result = measure_region(img, mask, confidence=0.9, mask_id="sky_0")

    assert result["mask_id"] == "sky_0"
    assert result["area_ratio"] == pytest.approx(0.5)
    assert result["mean_luminance"] == pytest.approx(255.0, abs=0.5)
    assert result["highlight_clip_ratio"] == pytest.approx(1.0)
    assert result["reliable"] is True
    assert result["mean_lab"] is not None
    assert set(result["mean_lab"]) == {"L", "a", "b"}
    # 纯白区域 Lab 的 L 应接近 100，a/b 接近 0。
    assert result["mean_lab"]["L"] == pytest.approx(100.0, abs=1.0)
    assert result["mean_lab"]["a"] == pytest.approx(0.0, abs=1.0)
    assert result["mean_lab"]["b"] == pytest.approx(0.0, abs=1.0)


def test_measure_region_empty_mask():
    """空 mask 不抛异常，返回不可靠结果。"""
    img = _image()
    mask = np.zeros((100, 100), dtype=np.uint8)

    result = measure_region(img, mask, confidence=0.9)

    assert result["area_ratio"] == 0.0
    assert result["reliable"] is False
    assert result["mean_lab"] is None
    assert result["mean_luminance"] is None
    assert result["highlight_clip_ratio"] == 0.0


def test_measure_region_all_zero_mask():
    """全零 mask 与空 mask 行为一致。"""
    img = _image()
    mask = np.zeros((100, 100), dtype=np.uint8)

    result = measure_region(img, mask)

    assert result["reliable"] is False
    assert result["mean_lab"] is None


def test_measure_region_nan_mask_no_crash():
    """NaN mask 不抛异常并视为空/剔除。"""
    img = _image()
    nan_mask = np.full((100, 100), np.nan)

    result = measure_region(img, nan_mask)

    assert result["reliable"] is False
    assert result["area_ratio"] == 0.0
    assert result["mean_lab"] is None


def test_measure_region_nan_mask_mixed_only_valid_counts():
    """NaN 像素不计入区域，但有效像素仍可测量。"""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:10, :10] = (255, 255, 255)
    mask = np.zeros((100, 100), dtype=np.float32)
    mask[:10, :10] = 255.0
    mask[10, 10] = np.nan

    result = measure_region(img, mask, confidence=0.9)

    assert result["area_ratio"] == pytest.approx(0.01)
    assert result["mean_luminance"] == pytest.approx(255.0, abs=0.5)
    assert result["reliable"] is True


def test_measure_region_low_confidence_unreliable():
    """置信度低于 0.6 时即使区域有效也应标记不可靠。"""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:50, :] = (200, 200, 200)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[:50, :] = 255

    result = measure_region(img, mask, confidence=0.5)

    assert result["area_ratio"] == pytest.approx(0.5)
    assert result["reliable"] is False


def test_measure_region_tiny_area_unreliable():
    """面积占比低于 0.5% 时标记不可靠。"""
    img = _image()
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[0, 0] = 255

    result = measure_region(img, mask, confidence=1.0)

    assert result["area_ratio"] == pytest.approx(0.0001)
    assert result["reliable"] is False


def test_measure_region_grayscale_color_no_crash():
    """灰度/纯色图像上的区域测量不应崩溃。"""
    img = np.full((32, 32, 3), (120, 80, 40), dtype=np.uint8)
    mask = np.ones((32, 32), dtype=np.uint8)

    global_result = measure_global(img)
    region_result = measure_region(img, mask, confidence=0.8)

    assert global_result["mean_luminance"] > 0
    assert region_result["mean_lab"] is not None
    assert region_result["reliable"] is True


def test_vision_measure_assemble_schema():
    """VisionMeasure.measure 应组装包含 global/regions 的完整报告。"""
    seg = MockSegmenter()
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    img[:80, :] = (220, 220, 220)
    img[120:, :] = (40, 80, 30)
    masks = seg.segment(img, ["face", "sky", "plant"])

    reporter = VisionMeasure()
    report = reporter.measure(
        img,
        masks,
        confidences={"face": 0.8, "sky": 0.9, "plant": 0.7},
        image_id="DSC_0001",
        render_version="v0.1.0",
        detection_version="mock_v1",
    )



    for region in report["regions"].values():
        # MockSegmenter 在 200x200 上面积足够大，置信度默认足够高，应全部可靠。
        assert region["reliable"] is True
        assert region["mean_lab"] is not None
        assert region["mean_luminance"] > 0
        assert region["area_ratio"] > 0.005


def test_measure_zone_exposure_synthetic():
    """分区曝光应返回完整九宫格/中央区域结构。"""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:50, :] = (255, 255, 255)

    result = measure_zone_exposure(img)

    assert set(result) == {
        "full", "center", "grid_center", "grid", "top_mid_bottom"
    }
    assert result["full"] == pytest.approx(127.5, abs=1.0)
    assert result["center"] == pytest.approx(127.5, abs=1.0)
    assert len(result["grid"]) == 9
    assert len(result["top_mid_bottom"]) == 3
    assert result["grid_center"] >= 0


def test_measure_sharpness_synthetic():
    """锐度测量在纯色图上应稳定且返回完整字段。"""
    img = np.full((64, 64, 3), 128, dtype=np.uint8)

    result = measure_sharpness(img)

    assert set(result) == {
        "laplacian_raw",
        "laplacian_denoised",
        "noise_ratio",
        "fft_high_ratio",
        "detail_score",
    }
    assert result["laplacian_raw"] == pytest.approx(0.0, abs=1e-3)
    assert result["noise_ratio"] == pytest.approx(0.0, abs=1e-3)
    assert 0.0 <= result["fft_high_ratio"] <= 1.0


def test_measure_motion_blur_synthetic():
    """运动模糊检测在纯色图上返回无模糊且不抛异常。"""
    img = np.full((64, 64, 3), 128, dtype=np.uint8)

    result = measure_motion_blur(img)

    assert set(result) == {"has_motion_blur", "angle", "strength", "error"}
    assert result["has_motion_blur"] is False
    assert result["strength"] == pytest.approx(0.0, abs=0.1)
    assert result["error"] is None


def test_measure_haze_synthetic():
    """雾密度测量在黑白图上应返回合法范围且不抛异常。"""
    black = measure_haze(np.zeros((32, 32, 3), dtype=np.uint8))
    white = measure_haze(np.full((32, 32, 3), 255, dtype=np.uint8))

    assert set(black) == {"haze_density", "dark_channel_mean", "sky_ratio"}
    assert 0.0 <= black["haze_density"] <= 1.0
    assert 0.0 <= white["haze_density"] <= 1.0
    assert black["sky_ratio"] == pytest.approx(0.0, abs=1e-6)


def test_vision_measure_custom_mask_version():
    """VisionMeasure.measure 应支持自定义 mask_version。"""
    seg = MockSegmenter()
    img = np.zeros((128, 128, 3), dtype=np.uint8)
    img[:40, :] = (200, 200, 200)
    masks = seg.segment(img, ["face", "sky"])

    report = VisionMeasure().measure(
        img,
        masks,
        mask_version="mask_custom_2",
    )

    assert report["mask_version"] == "mask_custom_2"


def test_render_vision_measure_module_importable():
    """模块路径 render.vision.measure 可作为独立模块导入。"""
    import render.vision.measure as measure_module

    assert hasattr(measure_module, "measure_global")
    assert hasattr(measure_module, "measure_region")
    assert hasattr(measure_module, "VisionMeasure")
    assert hasattr(measure_module, "measure_zone_exposure")
    assert hasattr(measure_module, "measure_sharpness")
    assert hasattr(measure_module, "measure_motion_blur")
    assert hasattr(measure_module, "measure_haze")
    assert hasattr(measure_module, "DEFAULT_MASK_VERSION")
