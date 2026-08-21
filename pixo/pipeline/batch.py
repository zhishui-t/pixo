"""pixo.pipeline.batch —— 批量流程 + 连拍选帧三层过滤（P2-2）。

流程：
  照片列表 → Pixo Meta 分组（连拍组）
  → 硬过滤（运动模糊/锐度/曝光裁切/人脸可用性）
  → 美学预筛（Mock/占位 Scorer）
  → Agent 语义优选 Top N（可注入 mock/规则）
  → 输出推荐/废片/转人工，并写入 State/Trace。

设计约束：
  - 不引入重型依赖；真实模型未接入时使用 MockSegmenter/MockAestheticScorer。
  - 可注入单张闭环 runner，批量只负责调度，不重复实现修图逻辑。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from pixo.meta import detect_burst_groups, extract
from pixo.render.state import PhotoStateMachine
from pixo.vision import (
    MockSegmenter,
    VisionMeasure,
    measure_global,
    measure_motion_blur,
    measure_sharpness,
)


class BatchError(RuntimeError):
    """批量编排错误基类。"""


@dataclass
class BatchInput:
    """批量输入的一张照片。"""

    photo_id: str
    image_rgb: np.ndarray | None = None
    raw_path: str | Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class HardFilterConfig:
    """硬过滤阈值配置。"""

    motion_strength_max: float = 0.35
    sharpness_min: float = 3.0
    highlight_clip_max: float = 0.03
    shadow_clip_max: float = 0.20
    face_required: bool = False


@dataclass
class HardFilterResult:
    """单张硬过滤结果。"""

    passed: bool
    reasons: list[str]
    scores: dict[str, float]
    measurement: dict[str, Any] | None = None


@dataclass
class AestheticScore:
    """美学预筛结果（0-5 分）。"""

    overall: float
    dimensions: dict[str, float] = field(default_factory=dict)


@dataclass
class AgentVerdict:
    """Agent 语义优选结果。"""

    recommended: bool
    confidence: float
    reason: str
    manual_review: bool = False


@dataclass
class PhotoResult:
    """批量单张结果。"""

    photo_id: str
    group_id: str
    status: str
    hard_filter: HardFilterResult
    aesthetic: AestheticScore | None
    agent: AgentVerdict | None
    state: str
    next_action: str = ""
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    single_loop_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "photo_id": self.photo_id,
            "group_id": self.group_id,
            "status": self.status,
            "hard_filter": {
                "passed": self.hard_filter.passed,
                "reasons": list(self.hard_filter.reasons),
                "scores": dict(self.hard_filter.scores),
            },
            "aesthetic": (
                {
                    "overall": self.aesthetic.overall,
                    "dimensions": dict(self.aesthetic.dimensions),
                }
                if self.aesthetic is not None else None
            ),
            "agent": (
                {
                    "recommended": self.agent.recommended,
                    "confidence": self.agent.confidence,
                    "reason": self.agent.reason,
                    "manual_review": self.agent.manual_review,
                }
                if self.agent is not None else None
            ),
            "state": self.state,
            "next_action": self.next_action,
            "trace_events": self.trace_events,
            "single_loop_result": self.single_loop_result,
        }


@dataclass
class BatchGroupResult:
    """单个连拍组结果。"""

    group_id: str
    photos: list[PhotoResult]

    @property
    def recommended(self) -> list[str]:
        """推荐 photo_id 列表。"""
        return [p.photo_id for p in self.photos if p.status == "recommended"]

    @property
    def rejected(self) -> list[str]:
        """硬过滤淘汰 photo_id 列表。"""
        return [p.photo_id for p in self.photos if p.status == "hard_rejected"]

    @property
    def manual_review(self) -> list[str]:
        """转人工 photo_id 列表。"""
        return [p.photo_id for p in self.photos if p.status == "manual_review"]

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "group_id": self.group_id,
            "photos": [p.to_dict() for p in self.photos],
            "recommended": self.recommended,
            "rejected": self.rejected,
            "manual_review": self.manual_review,
        }


@dataclass
class BatchResult:
    """批量流程整体结果。"""

    groups: list[BatchGroupResult]

    @property
    def all_recommended(self) -> list[str]:
        """全部组推荐 photo_id。"""
        out: list[str] = []
        for group in self.groups:
            out.extend(group.recommended)
        return out

    @property
    def all_rejected(self) -> list[str]:
        """全部组硬过滤淘汰 photo_id。"""
        out: list[str] = []
        for group in self.groups:
            out.extend(group.rejected)
        return out

    @property
    def all_manual_review(self) -> list[str]:
        """全部组转人工 photo_id。"""
        out: list[str] = []
        for group in self.groups:
            out.extend(group.manual_review)
        return out

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "groups": [g.to_dict() for g in self.groups],
            "recommended": self.all_recommended,
            "rejected": self.all_rejected,
            "manual_review": self.all_manual_review,
        }


class MockAestheticScorer:
    """确定性美学评分占位实现。

    当前根据全局亮度、对比度、锐度做简单打分，保证批量选帧可测可复现。
    """

    def score(
        self,
        image_rgb: np.ndarray,
        meta: dict[str, Any] | None = None,
    ) -> AestheticScore:
        """计算 0-5 美学分。"""
        del meta
        global_metrics = measure_global(image_rgb)
        sharpness = measure_sharpness(image_rgb)

        mean_lum = float(global_metrics["mean_luminance"]) / 255.0
        contrast = float(global_metrics["contrast"])
        detail = float(sharpness["detail_score"])

        # 亮度适中、对比度适中、细节分越高越好。
        lighting = 5.0 - 4.0 * abs(mean_lum - 0.5)
        quality = float(np.clip(detail / 15.0, 0.0, 1.0)) * 3.0 + 1.5
        composition = float(np.clip(contrast / 0.8, 0.0, 1.0)) * 2.0 + 1.8
        color = 3.2
        overall = float(np.clip(
            (lighting * 0.35 + quality * 0.30 + composition * 0.20 + color * 0.15),
            0.0, 5.0,
        ))
        return AestheticScore(
            overall=round(overall, 3),
            dimensions={
                "lighting": round(lighting, 3),
                "quality": round(quality, 3),
                "composition": round(composition, 3),
                "color": round(color, 3),
            },
        )


class MockAgentSelector:
    """Agent 语义优选占位实现。

    按美学排序取 Top N；confidence 由美学分推导，低于阈值时转人工。
    """

    def __init__(
        self,
        top_n: int = 3,
        confidence_threshold: float = 0.6,
        manual_threshold: float = 0.5,
    ) -> None:
        self.top_n = int(top_n)
        self.confidence_threshold = float(confidence_threshold)
        self.manual_threshold = float(manual_threshold)

    def select(
        self,
        candidates: Sequence[tuple[BatchInput, AestheticScore]],
    ) -> dict[str, AgentVerdict]:
        """返回 photo_id -> AgentVerdict（只处理 Top N）。"""
        ranked = sorted(candidates, key=lambda x: x[1].overall, reverse=True)[
            : self.top_n
        ]
        verdicts: dict[str, AgentVerdict] = {}
        for index, (item, score) in enumerate(ranked):
            # 分数 5.0 时 confidence 约 0.98；越靠前额外加少量权重。
            confidence = float(np.clip(
                0.50 + score.overall / 10.0 + (self.top_n - index) * 0.02,
                0.0, 0.98,
            ))
            confidence = round(confidence, 3)
            manual = confidence < self.manual_threshold
            recommended = confidence >= self.confidence_threshold and not manual
            verdicts[item.photo_id] = AgentVerdict(
                recommended=recommended,
                confidence=confidence,
                reason=(
                    f"美学评分 {score.overall:.2f}/5，"
                    f"候选第 {index + 1} 位"
                ),
                manual_review=manual,
            )
        return verdicts


class BatchPipeline:
    """批量流程编排器。

    参数均可注入，便于用合成图与 Mock 组件做单测。
    """

    def __init__(
        self,
        *,
        hard_filter_config: HardFilterConfig | None = None,
        aesthetic_scorer: Any | None = None,
        agent_selector: Any | None = None,
        segmenter: Any | None = None,
        single_photo_runner: Callable[..., Any] | None = None,
        top_n: int = 3,
    ) -> None:
        self.hard_filter_config = hard_filter_config or HardFilterConfig()
        self.aesthetic_scorer = aesthetic_scorer or MockAestheticScorer()
        self.agent_selector = agent_selector or MockAgentSelector(top_n=top_n)
        self.segmenter = segmenter or MockSegmenter()
        self.single_photo_runner = single_photo_runner
        self.top_n = int(top_n)

    # ---- 分组 ----

    def _meta_dict(self, item: BatchInput) -> dict[str, Any]:
        """构造供连拍分组使用的元数据字典。"""
        if item.meta:
            meta = dict(item.meta)
        elif item.raw_path is not None:
            try:
                meta = extract(str(item.raw_path))
            except Exception:  # noqa: BLE001 - Meta 缺失不阻断批量
                meta = {}
        else:
            meta = {}
        meta.setdefault("file_path", str(item.raw_path or item.photo_id))
        return meta

    def _group_inputs(
        self,
        photos: Sequence[BatchInput],
    ) -> list[tuple[str, list[BatchInput]]]:
        """按 Meta 连拍分组；无时间信息时每组一张。"""
        metas = [self._meta_dict(item) for item in photos]
        by_key = {
            str(meta.get("file_path") or item.photo_id): item
            for item, meta in zip(photos, metas)
        }
        groups_meta = detect_burst_groups(metas) if any(
            (m.get("datetime") or m.get("capture", {}).get("datetime"))
            for m in metas
        ) else []

        if not groups_meta:
            return [
                (f"standalone_{idx:04d}", [item])
                for idx, item in enumerate(photos)
            ]

        result: list[tuple[str, list[BatchInput]]] = []
        for group in groups_meta:
            group_id = str(group.get("group_id", f"burst_{len(result):03d}"))
            files = list(group.get("files") or [])
            items = [by_key[str(f)] for f in files if str(f) in by_key]
            if not items:
                continue
            result.append((group_id, items))
        return result

    # ---- 单张筛选 ----

    def _image_for(self, item: BatchInput) -> np.ndarray | None:
        """取批量输入图像；无图返回 None。"""
        if item.image_rgb is not None:
            return np.asarray(item.image_rgb)
        return None

    def hard_filter(
        self,
        item: BatchInput,
        image: np.ndarray | None,
    ) -> HardFilterResult:
        """硬过滤：运动模糊、锐度、曝光裁切、可选人脸可用性。"""
        if image is None:
            return HardFilterResult(
                passed=False,
                reasons=["no_image"],
                scores={},
            )
        cfg = self.hard_filter_config
        reasons: list[str] = []
        scores: dict[str, float] = {}

        motion = measure_motion_blur(image)
        scores["motion_blur_strength"] = motion["strength"]
        if motion["strength"] > cfg.motion_strength_max:
            reasons.append("motion_blur")

        sharp = measure_sharpness(image)
        scores["detail_score"] = sharp["detail_score"]
        if sharp["detail_score"] < cfg.sharpness_min:
            reasons.append("sharpness")

        global_metrics = measure_global(image)
        scores["highlight_clip_ratio"] = global_metrics["highlight_clip_ratio"]
        scores["shadow_clip_ratio"] = global_metrics["shadow_clip_ratio"]
        if global_metrics["highlight_clip_ratio"] > cfg.highlight_clip_max:
            reasons.append("highlight_clip")
        if global_metrics["shadow_clip_ratio"] > cfg.shadow_clip_max:
            reasons.append("shadow_clip")

        measurement: dict[str, Any] | None = None
        if cfg.face_required:
            try:
                masks = self.segmenter.segment(image, ["face"])
                measurement = VisionMeasure().measure(
                    image, {"face": masks.get("face", np.zeros_like(image[..., 0]))}
                )
                face = measurement.get("regions", {}).get("face", {})
                if not face.get("reliable", False):
                    reasons.append("face_unreliable")
            except Exception:  # noqa: BLE001 - 分割不可用按人脸不可靠处理
                reasons.append("face_unreliable")

        return HardFilterResult(
            passed=not reasons,
            reasons=reasons,
            scores=scores,
            measurement=measurement,
        )

    # ---- 主流程 ----

    def process(
        self,
        photos: Sequence[BatchInput],
    ) -> BatchResult:
        """执行批量流程，返回分组结果。"""
        groups = self._group_inputs(photos)
        group_results: list[BatchGroupResult] = []

        for group_id, group_items in groups:
            photo_results: list[PhotoResult] = []
            candidates: list[tuple[BatchInput, AestheticScore]] = []

            for item in group_items:
                image = self._image_for(item)
                hard = self.hard_filter(item, image)
                aesthetic: AestheticScore | None = None
                if hard.passed and image is not None:
                    aesthetic = self.aesthetic_scorer.score(image, item.meta)
                    candidates.append((item, aesthetic))
                photo_results.append(
                    self._make_photo_result(item, group_id, hard, aesthetic, None)
                )

            agent_verdicts = self.agent_selector.select(candidates)
            for result in photo_results:
                verdict = agent_verdicts.get(result.photo_id)
                if result.status == "hard_rejected":
                    continue
                if verdict is None:
                    result.status = "not_selected"
                elif verdict.manual_review:
                    result.status = "manual_review"
                elif verdict.recommended:
                    result.status = "recommended"
                else:
                    result.status = "not_selected"
                result.agent = verdict
                result.next_action = (
                    "single_photo_loop"
                    if result.status == "recommended"
                    else "manual_review"
                    if result.status == "manual_review"
                    else ""
                )

                if (
                    result.status == "recommended"
                    and self.single_photo_runner is not None
                ):
                    result.single_loop_result = self._run_single(
                        item, result
                    )

            self._write_state_and_trace(group_id, photo_results)
            group_results.append(BatchGroupResult(
                group_id=group_id, photos=photo_results
            ))

        return BatchResult(groups=group_results)

    def _make_photo_result(
        self,
        item: BatchInput,
        group_id: str,
        hard: HardFilterResult,
        aesthetic: AestheticScore | None,
        agent: AgentVerdict | None,
    ) -> PhotoResult:
        """构造单张结果初值。"""
        status = "hard_rejected" if not hard.passed else "pending"
        return PhotoResult(
            photo_id=item.photo_id,
            group_id=group_id,
            status=status,
            hard_filter=hard,
            aesthetic=aesthetic,
            agent=agent,
            state="RAW_PENDING",
        )

    def _run_single(
        self,
        item: BatchInput,
        result: PhotoResult,
    ) -> dict[str, Any]:
        """调用注入的单张闭环 runner。"""
        assert self.single_photo_runner is not None
        loop_result = self.single_photo_runner(
            item.photo_id,
            image_rgb=item.image_rgb,
            raw_path=item.raw_path,
            meta=item.meta,
        )
        if hasattr(loop_result, "to_dict"):
            return loop_result.to_dict()
        if isinstance(loop_result, dict):
            return loop_result
        return {"raw": str(loop_result)}

    def _write_state_and_trace(
        self,
        group_id: str,
        photo_results: Sequence[PhotoResult],
    ) -> None:
        """为批量结果写入 in-memory State/Trace。"""
        for result in photo_results:
            sm = PhotoStateMachine(result.photo_id)
            sm.transition("SCREENED", reason="进入批量筛选")
            events: list[dict[str, Any]] = []
            events.append(sm.add_trace(
                event_type="batch_hard_filter",
                param="status",
                value=result.hard_filter.reasons or ["passed"],
                reason=(
                    "硬过滤淘汰"
                    if result.status == "hard_rejected"
                    else "硬过滤通过"
                ),
                source="batch_pipeline",
            ).to_dict())
            if result.aesthetic is not None:
                events.append(sm.add_trace(
                    event_type="aesthetic_score",
                    param="overall",
                    value=result.aesthetic.overall,
                    reason=f"美学评分 {result.aesthetic.overall:.2f}/5",
                    source="batch_pipeline",
                ).to_dict())
            if result.agent is not None:
                event_type = "agent_manual" if result.agent.manual_review else "agent_recommend"
                events.append(sm.add_trace(
                    event_type=event_type,
                    param="confidence",
                    value=result.agent.confidence,
                    reason=result.agent.reason,
                    source="agent_mock",
                ).to_dict())
                if result.agent.manual_review and sm.state not in ("MANUAL_REVIEW", "ACCEPTED", "REJECTED"):
                    sm.escalate(result.agent.reason)
            result.state = sm.state
            result.next_action = result.next_action or sm.record.next_action
            result.trace_events = [e.to_dict() for e in sm.history()]


__all__ = [
    "BatchError",
    "BatchInput",
    "BatchResult",
    "BatchGroupResult",
    "PhotoResult",
    "HardFilterConfig",
    "HardFilterResult",
    "AestheticScore",
    "AgentVerdict",
    "MockAestheticScorer",
    "MockAgentSelector",
    "BatchPipeline",
]
