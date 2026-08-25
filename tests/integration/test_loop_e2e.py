"""P1-5 端到端单测：单张闭环（MockSegmenter + 合成图）。

覆盖：
  - 完整闭环 ACCEPTED：Meta/compose/preview×3/FINAL_QC/Trace 齐备；
  - mask 只在第一次 preview 计算并复用（后续 preview 与全分辨率只缩放）；
  - FINAL_QC 超标回退一次，二次超标转 MANUAL_REVIEW；
  - Agent 只允许 agree/escalate；
  - 分割模型不可用时降级 MANUAL_REVIEW。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.pipeline.loop import (
    SinglePhotoLoop,
    SyntheticRenderBackend,
    run_single_photo_loop,
)
from pixo.vision import MockSegmenter, SegmenterUnavailable


class CountingSegmenter(MockSegmenter):
    """统计 segment 调用次数的 MockSegmenter。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def segment(self, image_rgb, prompts):
        self.calls += 1
        return super().segment(image_rgb, prompts)


def _dark_image() -> np.ndarray:
    """低亮度合成图，FINAL_QC 不会高光溢出。"""
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.3
    return img


def _bright_image() -> np.ndarray:
    """高亮度合成图，用于触发 FINAL_QC 回退/人工。

    2026-08: 取值 0.8 依赖 tone 默认 brightness=0.5 才溢出; 该默认已按
    标定回归为 0.25 (0.8×2^0.25≈0.95 不裁切)。改用 0.92 —— 无论该默认
    在合理标定范围内如何变化都必然溢出, 测试意图不再绑定引擎默认值。
    """
    return np.full((64, 64, 3), 0.92, dtype=np.float32)


def _black_image() -> np.ndarray:
    """全黑图像，可用于快速无溢出验证。"""
    return np.zeros((64, 64, 3), dtype=np.float32)


def test_single_photo_loop_accepted_with_three_preview_iterations():
    """合成图走完整闭环，3 轮 preview 后 FINAL_QC 达标 ACCEPTED。"""
    loop = SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
    )
    result = loop.run(
        "pic_accept",
        image_rgb=_dark_image(),
        compose_params={"mode": "free", "x": 8, "y": 8, "width": 32, "height": 32},
    )

    assert result.state == "ACCEPTED"
    assert result.decision == "ACCEPTED"
    assert result.iteration == 3
    assert len(result.measurements) == 3
    assert result.final_measurement is not None
    assert result.final_image is not None
    assert result.final_image.shape == (32, 32, 3)
    assert result.qc_rollback_count == 0

    event_types = [e["event_type"] for e in result.trace_events]
    assert "meta_extracted" in event_types
    assert "compose_params" in event_types
    assert event_types.count("decide") == 3
    assert "FINAL_QC_ACCEPT" in event_types


def test_mask_computed_once_and_reused_for_later_previews_and_full():
    """segment 只调用 1 次，后续 preview 与全分辨率 QC 复用缓存 mask。"""
    segmenter = CountingSegmenter()
    loop = SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=segmenter,
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
    )
    result = loop.run("pic_mask", image_rgb=_dark_image())

    assert segmenter.calls == 1
    assert len(result.measurements) == 3
    assert result.state == "ACCEPTED"
    # 全分辨率测量确实执行
    assert result.final_measurement is not None
    assert result.final_measurement["regions"]["face"]["area_ratio"] > 0


def test_qc_overflow_rolls_back_once_then_manual_review():
    """高光溢出先回退一次 Exposure -0.15EV，二次超标转 MANUAL_REVIEW。"""
    loop = SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_bright_image()),
        segmenter=MockSegmenter(),
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
    )
    result = loop.run("pic_qc", image_rgb=_bright_image())

    assert result.state == "MANUAL_REVIEW"
    assert result.qc_rollback_count == 1
    assert result.final_measurement is not None
    # Trace 中应看到 QC_ROLLBACK 与最终 AGENT_ESCALATED
    event_types = [e["event_type"] for e in result.trace_events]
    assert "QC_ROLLBACK" in event_types
    assert "AGENT_ESCALATED" in event_types
    assert "FINAL_QC_ACCEPT" not in event_types


def test_agent_escalate_stops_before_preview_loop():
    """Agent 选择 escalate 时立即转 MANUAL_REVIEW，不进入 preview 迭代。"""
    loop = SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
    )
    result = loop.run(
        "pic_agent",
        image_rgb=_dark_image(),
        agent_decision="escalate",
    )

    assert result.state == "MANUAL_REVIEW"
    assert len(result.measurements) == 0
    event_types = [e["event_type"] for e in result.trace_events]
    assert "AGENT_ESCALATED" in event_types


def test_segmenter_unavailable_maps_to_manual_review():
    """SegmenterUnavailable 必须被上层捕获并降级 MANUAL_REVIEW。"""

    class BrokenSegmenter(MockSegmenter):
        def segment(self, image_rgb, prompts):
            raise SegmenterUnavailable("模拟模型未就绪")

    loop = SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=BrokenSegmenter(),
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
    )
    result = loop.run("pic_broken", image_rgb=_dark_image())

    assert result.state == "MANUAL_REVIEW"
    assert len(result.measurements) == 0
    event_types = [e["event_type"] for e in result.trace_events]
    assert "AGENT_ESCALATED" in event_types


def test_functional_entry_and_render_shim():
    """函数式入口可用，且 pixo.pipeline.loop shim 能导入同一实现。"""
    from pixo.pipeline.loop import SinglePhotoLoop as ShimLoop

    assert ShimLoop is SinglePhotoLoop

    result = run_single_photo_loop(
        "pic_func",
        image_rgb=_black_image(),
        segmenter=MockSegmenter(),
        max_iterations=1,
        prompts=["face"],
    )
    assert result.state == "ACCEPTED"
    assert len(result.measurements) == 1
