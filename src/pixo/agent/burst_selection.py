"""pixo.agent.burst_selection —— 连拍选帧 / 批内优选逻辑。

从 ``pixo.pipeline.batch`` 的三层过滤中拆出可复用的硬过滤 + 美学 TopN
选帧核心，供 Agent / 批量流程共同调用。

设计:
  - 纯 Python + NumPy，不引入新依赖。
  - 输入支持 dict 或轻量 dataclass，便于上层注入 mock 美学分。
  - 硬过滤与 TopN 逻辑与 batch 参考实现保持一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from pixo.vision import measure_global, measure_motion_blur, measure_sharpness

__all__ = [
    "BurstFrame",
    "BurstSelectionConfig",
    "BurstSelectionResult",
    "hard_filter_frame",
    "select_burst_frames",
]


@dataclass
class BurstFrame:
    """参与连拍选帧的一张照片。"""

    photo_id: str
    image_rgb: np.ndarray | None = None
    aesthetic: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)
    hard_filter_passed: bool | None = None


@dataclass
class BurstSelectionConfig:
    """连拍选帧配置。"""

    top_n: int = 3
    confidence_threshold: float = 0.6
    manual_threshold: float = 0.5
    motion_strength_max: float = 0.35
    sharpness_min: float = 3.0
    highlight_clip_max: float = 0.03
    shadow_clip_max: float = 0.20


@dataclass
class BurstSelectionResult:
    """单帧选帧结果。"""

    photo_id: str
    status: str
    confidence: float = 0.0
    reason: str = ""
    hard_filter_reasons: list[str] = field(default_factory=list)
    aesthetic: float = 0.0


def _get(frame: Any, name: str, default: Any = None) -> Any:
    """兼容 dict / 对象输入。"""
    if isinstance(frame, dict):
        return frame.get(name, default)
    return getattr(frame, name, default)


def hard_filter_frame(
    image_rgb: np.ndarray,
    config: BurstSelectionConfig | None = None,
) -> tuple[bool, list[str], dict[str, float]]:
    """对单帧执行硬过滤（运动模糊/锐度/曝光裁切）。"""
    cfg = config or BurstSelectionConfig()
    reasons: list[str] = []
    scores: dict[str, float] = {}

    motion = measure_motion_blur(image_rgb)
    scores["motion_blur_strength"] = float(motion["strength"])
    if motion["strength"] > cfg.motion_strength_max:
        reasons.append("motion_blur")

    sharp = measure_sharpness(image_rgb)
    scores["detail_score"] = float(sharp["detail_score"])
    if sharp["detail_score"] < cfg.sharpness_min:
        reasons.append("sharpness")

    global_metrics = measure_global(image_rgb)
    scores["highlight_clip_ratio"] = float(global_metrics["highlight_clip_ratio"])
    scores["shadow_clip_ratio"] = float(global_metrics["shadow_clip_ratio"])
    if float(global_metrics["highlight_clip_ratio"]) > cfg.highlight_clip_max:
        reasons.append("highlight_clip")
    if float(global_metrics["shadow_clip_ratio"]) > cfg.shadow_clip_max:
        reasons.append("shadow_clip")

    return not reasons, reasons, scores


def select_burst_frames(
    frames: Sequence[Any],
    config: BurstSelectionConfig | None = None,
    top_n: int | None = None,
    confidence_threshold: float | None = None,
    manual_threshold: float | None = None,
) -> list[BurstSelectionResult]:
    """执行连拍选帧：硬过滤 → 美学排序 → TopN/转人工。

    输入可传 ``BurstFrame`` 或含 ``photo_id`` / ``aesthetic`` /
    ``image_rgb`` / ``hard_filter_passed`` 的 dict。
    """
    cfg = config or BurstSelectionConfig()
    if top_n is not None:
        cfg.top_n = int(top_n)
    if confidence_threshold is not None:
        cfg.confidence_threshold = float(confidence_threshold)
    if manual_threshold is not None:
        cfg.manual_threshold = float(manual_threshold)
    results: list[BurstSelectionResult] = []
    candidates: list[tuple[Any, float]] = []

    for frame in frames:
        photo_id = str(_get(frame, "photo_id", "unknown"))
        aesthetic = float(_get(frame, "aesthetic", 0.0) or 0.0)
        image = _get(frame, "image_rgb")
        hard_passed = _get(frame, "hard_filter_passed")
        reasons: list[str] = []

        if image is not None:
            passed, reasons, _ = hard_filter_frame(np.asarray(image), cfg)
        else:
            passed = True if hard_passed is None else bool(hard_passed)

        if not passed:
            results.append(BurstSelectionResult(
                photo_id=photo_id,
                status="hard_rejected",
                reason="硬过滤淘汰",
                hard_filter_reasons=reasons,
                aesthetic=aesthetic,
            ))
            continue

        results.append(BurstSelectionResult(
            photo_id=photo_id,
            status="pending",
            aesthetic=aesthetic,
        ))
        candidates.append((frame, aesthetic))

    ranked = sorted(candidates, key=lambda item: item[1], reverse=True)[: cfg.top_n]
    selected_ids = {str(_get(f, "photo_id", "")) for f, _ in ranked}

    for result in results:
        if result.status != "pending":
            continue
        if result.photo_id not in selected_ids:
            result.status = "not_selected"
            result.reason = "未进入 TopN"
            continue
        rank = [r[1] for r in ranked]
        conf = float(np.clip(
            0.50 + result.aesthetic / 10.0
            + (cfg.top_n - rank.index(result.aesthetic)) * 0.02,
            0.0,
            0.98,
        ))
        result.confidence = round(conf, 3)
        if result.confidence < cfg.manual_threshold:
            result.status = "manual_review"
            result.reason = "置信度过低，建议人工复核"
        elif result.confidence >= cfg.confidence_threshold:
            result.status = "recommended"
            result.reason = "通过硬过滤并进入推荐"
        else:
            result.status = "not_selected"
            result.reason = "置信度未达推荐阈值"

    return results
