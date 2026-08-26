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

import logging
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from pixo.meta import detect_burst_groups, extract
from pixo.state import PhotoStateMachine
from pixo.vision import (
    MockSegmenter,
    VisionMeasure,
    measure_global,
    measure_motion_blur,
    measure_sharpness,
)
_LOGGER = logging.getLogger(__name__)


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
    """美学预筛结果（契约域 0-5 分）。

    source 标记分数出处："mock"（占位评分器）/"pixo"（真模型，经仿射标定）。
    raw_overall/domain_hint 仅 source="pixo" 时由适配器填充：
      - raw_overall：标定前模型原始分（带符号），供追溯与再标定；
      - domain_hint="synthetic_like"：原始分超实拍域上尾(p75_raw)，
        疑似合成/低纹理域，绝对分不可与实拍跨域比较(t58)。
    """

    overall: float
    dimensions: dict[str, float] = field(default_factory=dict)
    source: str = "mock"
    raw_overall: float | None = None
    domain_hint: str | None = None


@dataclass
class AgentVerdict:
    """Agent 语义优选结果。"""

    recommended: bool
    confidence: float
    reason: str
    manual_review: bool = False
    synthetic_rank: int | None = None
    synthetic_pool_size: int | None = None


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
            source="mock",
        )



# ---- 真评分器仿射标定（t63；锚点=docs/metrics/scorer_distribution.md t58 表）----
_PIXO_CAL_TARGET_LO = 2.0
_PIXO_CAL_TARGET_HI = 4.0
_PIXO_CAL_ANCHORS_RAW = {
    # 维度: (p25_raw, p75_raw)，overall 行为主锚点
    "overall": (-0.637, -0.272),
    "quality": (-0.790, 0.058),
    "composition": (-0.886, -0.411),
    "lighting": (0.146, 0.811),
    "color": (0.541, 0.693),
    "depth_of_field": (-0.452, 0.609),
    "content": (-0.790, -0.271),
}
_DOMAIN_HINT_HIGH = "synthetic_like"


def _pixo_calibrate(raw: float, dim: str = "overall") -> float:
    """t58 分布锚点的保序仿射映射 raw -> [0,5]。

    两锚点 (p25,p75)->(2,4) 定直线，外延线性延伸后 np.clip 兜底；
    锚点来自实拍分布——合成/低纹理输入绝对分不可跨域比较。
    """
    lo_raw, hi_raw = _PIXO_CAL_ANCHORS_RAW.get(dim, _PIXO_CAL_ANCHORS_RAW["overall"])
    if hi_raw <= lo_raw:
        return _PIXO_CAL_TARGET_LO
    slope = (_PIXO_CAL_TARGET_HI - _PIXO_CAL_TARGET_LO) / (hi_raw - lo_raw)
    mapped = _PIXO_CAL_TARGET_LO + slope * (float(raw) - lo_raw)
    return round(float(np.clip(mapped, 0.0, 5.0)), 3)


def make_default_scorer() -> Any:
    """构造批量流程默认美学评分器。

    优先尝试真评分器（pixo.vision.aesthetic.PixoAestheticScorer，懒加载）：
    torch/transformers 缺失、模型权重不存在或初始化异常时回退
    MockAestheticScorer，保证坏环境不致命、批量流程永远可用。
    """
    try:
        from pixo.vision.aesthetic import PixoAestheticScorer

        candidate = PixoAestheticScorer()
        if not candidate.health_info().get("available"):
            _LOGGER.warning(
                "[pixo.pipeline.batch] 真美学评分器不可用"
                "(torch/transformers 缺失或权重缺失/损坏)，回退 Mock")
            return MockAestheticScorer()
        _LOGGER.info("[pixo.pipeline.batch] 使用真美学评分器(PixoAestheticScorer)")
        return _PixoScorerAdapter(candidate)
    except Exception as exc:  # noqa: BLE001 - 真评分器不可用一律降级 Mock
        _LOGGER.warning("[pixo.pipeline.batch] 真评分器构造异常，回退 Mock: %s", exc)
        return MockAestheticScorer()


class _PixoScorerAdapter:
    """把 PixoAestheticScorer 适配为批量流程的评分契约。

    批量侧约定 score(image_rgb, meta) -> AestheticScore | None；
    真评分器为 score(image_rgb) -> dict[dimension, float] | None，
    本适配器负责签名与返回类型转换（overall 缺失时取维度均值）。

    量纲说明（t63）：真模型输出带符号原始分（实拍 overall 全负，粗钳制会
    削平信号）；此处按 t58 分布表逐维 p25/p75 双锚点保序仿射到契约域 [0,5]，
    外延延伸+硬界兜底。合成/低纹理输入在域外，绝对分不可跨域比较——
    raw 超实拍 p75 时 domain_hint="synthetic_like"。
    健壮性：真评分器抛异常或返回空结果即永久降级为内置 Mock，
    不再重试（_degraded），保证暗路径不崩批。
    """

    def __init__(self, scorer: Any) -> None:
        self._scorer = scorer
        self._mock = MockAestheticScorer()
        self._degraded = False

    @property
    def inner(self) -> Any:
        """底层真评分器实例。"""
        return self._scorer

    @property
    def degraded(self) -> bool:
        """是否已永久降级为 Mock。"""
        return self._degraded

    def _mock_score(self, image_rgb: np.ndarray) -> AestheticScore:
        result = self._mock.score(image_rgb)
        result.source = "mock"
        return result

    def score(
        self,
        image_rgb: np.ndarray,
        meta: dict[str, Any] | None = None,
    ) -> AestheticScore | None:
        del meta  # 真评分器不消费 meta
        if self._degraded:
            return self._mock_score(image_rgb)
        try:
            result = self._scorer.score(image_rgb)
        except Exception as exc:  # noqa: BLE001 - 单张失败不崩批
            _LOGGER.warning("[pixo.pipeline.batch] 真评分器异常，永久降级为Mock: %s", exc)
            self._degraded = True
            return self._mock_score(image_rgb)
        if not isinstance(result, dict) or not result:
            _LOGGER.warning(
                "[pixo.pipeline.batch] 真评分器返回空结果(None/空dict)，"
                "永久降级为Mock")
            self._degraded = True
            return self._mock_score(image_rgb)

        dims: dict[str, float] = {}
        for name, value in result.items():
            if name == "overall":
                continue
            try:
                dims[str(name)] = _pixo_calibrate(value, str(name))
            except (TypeError, ValueError):
                continue

        overall_raw = result.get("overall")
        if overall_raw is None:
            if not dims:
                self._degraded = True
                _LOGGER.warning(
                    "[pixo.pipeline.batch] 真评分器输出无可信分数，"
                    "永久降级为Mock")
                return self._mock_score(image_rgb)
            overall = sum(dims.values()) / len(dims)
            raw_overall = None
            domain_hint = None
        else:
            raw_val = float(overall_raw)
            overall = _pixo_calibrate(raw_val, "overall")
            raw_overall = round(raw_val, 6)
            domain_hint = (
                _DOMAIN_HINT_HIGH
                if raw_val > _PIXO_CAL_ANCHORS_RAW["overall"][1]
                else None
            )

        return AestheticScore(
            overall=round(float(overall), 3),
            dimensions=dims,
            source="pixo",
            raw_overall=raw_overall,
            domain_hint=domain_hint,
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
        include_synthetic: bool = False,
    ) -> None:
        self.top_n = int(top_n)
        self.confidence_threshold = float(confidence_threshold)
        self.manual_threshold = float(manual_threshold)
        # t68 域外隔离：synthetic_like 候选默认不与实拍域混排。
        self.include_synthetic = bool(include_synthetic)

    def select(
        self,
        candidates: Sequence[tuple[BatchInput, AestheticScore]],
    ) -> dict[str, AgentVerdict]:
        """评分 → 选片；合成域候选隔离 + 池内相对排序（t68 → t98 语义扩展）。

        结构（无论 include_synthetic 取值）：
          - 实拍域（domain_hint != synthetic_like）：按标定分取 Top N 推荐。
          - 合成域（domain_hint == synthetic_like）：从不与实拍绝对分混排
            （t58 禁跨域比）；include_synthetic=True 时以「隔离合成池」可见
            形式输出——仅在池内按标定分相对排序（synthetic_rank），供人审
            参考。t98 实测同场景退化阶梯 Spearman ρ≈0.03 非单调，域内相对
            排名自洽性不足，**不得据此作质检硬结论**：recommended 恒 False
            （即使 include_synthetic=True 也不推荐）。
        """
        usable = [
            (item, score)
            for item, score in candidates
            if score is not None
            and isinstance(getattr(score, "overall", None), (int, float))
        ]
        skipped = len(candidates) - len(usable)
        if skipped:
            _LOGGER.warning(
                "[pixo.pipeline.batch] AgentSelector 有 %d 个无有效美学得分"
                "的候选被跳过",
                skipped)
        real_pool = [
            pair for pair in usable
            if getattr(pair[1], "domain_hint", None) != _DOMAIN_HINT_HIGH
        ]
        synth_pool = [
            pair for pair in usable
            if getattr(pair[1], "domain_hint", None) == _DOMAIN_HINT_HIGH
        ]
        ranked = sorted(real_pool, key=lambda x: x[1].overall, reverse=True)[
            : self.top_n
        ]
        verdicts: dict[str, AgentVerdict] = {}
        for index, (item, score) in enumerate(ranked):
            # 当 score=5.0 时 confidence 约 0.98；越靠前排名加权越高。
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
                    f"美学得分 {score.overall:.2f}/5，"
                    f"选片第 {index + 1} 位"
                ),
                manual_review=manual,
            )
        # 合成域：隔离池。池内排序仅作参考（t98 ρ≈0.03 自洽性不足），
        # 不参与实拍 TopN，也不产出任何推荐/人工评审。
        ordered_synth = sorted(
            synth_pool, key=lambda x: x[1].overall, reverse=True)
        pool_size = len(ordered_synth)
        for rank, (item, _score) in enumerate(ordered_synth, start=1):
            pid = item.photo_id
            if not self.include_synthetic:
                verdicts[pid] = AgentVerdict(
                    recommended=False,
                    confidence=0.0,
                    reason="合成域候选隔离：不与实拍域绝对分混排(t68)",
                    manual_review=False,
                    synthetic_rank=None,
                    synthetic_pool_size=pool_size if pool_size else None,
                )
                continue
            verdicts[pid] = AgentVerdict(
                recommended=False,
                confidence=0.0,
                reason=(
                    f"合成域池内第 {rank}/{pool_size}：相对排名自洽性不足"
                    "(ρ≈0.03 非单调)仅供人审参考，不作质检硬结论；"
                    "未与实拍混排(t98)"
                ),
                manual_review=False,
                synthetic_rank=rank,
                synthetic_pool_size=pool_size,
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
        include_synthetic: bool = False,
    ) -> None:
        self.hard_filter_config = hard_filter_config or HardFilterConfig()
        self.aesthetic_scorer = (
            aesthetic_scorer
            if aesthetic_scorer is not None
            else make_default_scorer()
        )
        self.agent_selector = agent_selector or MockAgentSelector(
            top_n=top_n, include_synthetic=include_synthetic)
        self.segmenter = segmenter or MockSegmenter()
        self.single_photo_runner = single_photo_runner
        self.top_n = int(top_n)
        self._none_score_count = 0  # 无分候选累计（可观测）

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
                from pixo.vision.measure import compute_proxy_metrics
                proxies = compute_proxy_metrics(image)
                if proxies:
                    measurement.update(proxies)
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
                    if aesthetic is None:
                        # 暗路径防御：无分候选绝不入排序池
                        self._none_score_count += 1
                        _LOGGER.warning(
                            "[pixo.pipeline.batch] 候选 %s 美学分缺失(None)，"
                            "跳出排序池(累计%d)",
                            item.photo_id, self._none_score_count)
                    else:
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
    "make_default_scorer",
    "MockAgentSelector",
    "BatchPipeline",
]
