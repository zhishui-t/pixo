"""pixo.pipeline.loop —— 单张修图闭环编排（P1-5）。

流程：
  Meta 提取 → 构图参数确定 → preview 渲染 + Vision 分割/测量（mask 只算一次）
  → Decide 计算参数/终止判断（最多 3 轮 preview 迭代）
  → FINAL_QC 全分辨率渲染 + 全分辨率测量
  → 达标 ACCEPTED / 超标回退一次 / 不可修复转 MANUAL_REVIEW
  → 输出结果 + State/Trace。

设计要点：
  - 渲染、分割、测量、Decide、State/Trace 全部通过依赖注入组合，
    方便用 MockSegmenter + 合成图做端到端单测。
  - mask 在第一次 preview 上计算后复用；后续 preview 与全分辨率 QC
    仅按尺寸调整，不再调分割模型。
  - 状态转移全部走 PhotoStateMachine 强校验。
  - Agent 边界：本层只接受 agree/escalate，接口留桩，不绕过 Decide。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import cv2
import numpy as np

from pixo.decide import decide, qc_rollback
from pixo.state import PhotoStateMachine, TraceEvent
from pixo.vision import MockSegmenter, Segmenter, SegmenterUnavailable, VisionMeasure

# 曝光参数别名与 Stage 参数映射（统一小写比较）。
_EXPOSURE_PARAM_ALIASES = (
    "exposure",
    "exposure_ev",
    "exposureev",
    "ev",
)


class LoopError(RuntimeError):
    """闭环编排错误基类。"""


@dataclass
class LoopResult:
    """单张闭环的最终结果。"""

    photo_id: str
    state: str
    iteration: int
    params: dict[str, Any]
    measurements: list[dict[str, Any]]
    final_measurement: dict[str, Any] | None
    final_image: np.ndarray | None
    trace_events: list[dict[str, Any]]
    decision: str
    reason: str
    qc_rollback_count: int
    metadata: dict[str, Any]
    compose_geometry: dict[str, Any] | None = None
    agent_decision: str = "agree"

    def __getitem__(self, key: str) -> Any:
        """支持 result["state"] 式访问，兼容 dict 风格调用。"""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """dict 风格 get。"""
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典（最终图像仅保留 shape/dtype 摘要）。"""
        image_info = None
        if self.final_image is not None:
            image_info = {
                "shape": list(self.final_image.shape),
                "dtype": str(self.final_image.dtype),
            }
        return {
            "photo_id": self.photo_id,
            "state": self.state,
            "iteration": self.iteration,
            "params": self.params,
            "measurements": self.measurements,
            "final_measurement": self.final_measurement,
            "final_image": image_info,
            "trace_events": self.trace_events,
            "decision": self.decision,
            "reason": self.reason,
            "qc_rollback_count": self.qc_rollback_count,
            "metadata": self.metadata,
            "compose_geometry": self.compose_geometry,
            "agent_decision": self.agent_decision,
        }


# ---------------------------------------------------------------------------
# 渲染后端
# ---------------------------------------------------------------------------

class SyntheticRenderBackend:
    """合成图渲染后端：用真实 compose/tone Stage 处理内存 RGB 图。

    主要用于不依赖真实 RAW 的端到端测试。输入当作 linear_rgb 交给管线；
    若需要模拟 Decide 给出的曝光参数，会在进入管线前按 EV 乘线性增益。
    """

    def __init__(
        self,
        image_rgb: np.ndarray,
        stages: Sequence[str] = ("compose", "tone"),
    ) -> None:
        arr = np.asarray(image_rgb)
        if arr.dtype == np.uint8:
            arr = arr.astype(np.float32) / 255.0
        elif np.issubdtype(arr.dtype, np.floating) and float(arr.max()) > 1.0:
            arr = arr.astype(np.float32) / 255.0
        else:
            arr = arr.astype(np.float32)
        if arr.ndim != 3 or arr.shape[2] not in (3, 4):
            raise ValueError("SyntheticRenderBackend 需要 HxWx3/4 图像")
        if arr.shape[2] == 4:
            arr = arr[..., :3]
        self.source = np.ascontiguousarray(arr)
        self.stages = list(stages)

    def _prepare(self, long_edge: int | None) -> np.ndarray:
        """按长边缩放源图；None 表示全分辨率。"""
        img = self.source.copy()
        if long_edge is not None and max(img.shape[:2]) > long_edge:
            h, w = img.shape[:2]
            scale = float(long_edge) / max(h, w)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = cv2.resize(img, (new_w, new_h),
                             interpolation=cv2.INTER_AREA)
        return img

    def _apply_exposure(self, img: np.ndarray, params: dict[str, Any]) -> np.ndarray:
        """把嵌套 exposure.mode 数值当作 EV 线性增益应用。"""
        exposure = params.get("exposure")
        if not isinstance(exposure, dict):
            return img
        mode = exposure.get("mode", "auto")
        if isinstance(mode, (int, float)) and not isinstance(mode, bool):
            if mode != "auto":
                img = img * (2.0 ** float(mode))
        return img

    def _render(
        self,
        params: dict[str, Any],
        long_edge: int | None,
    ) -> np.ndarray:
        from pixo.render import modules as _  # noqa: F401 触发 Stage 注册
        from pixo.render.pipeline.context import DOMAIN_LINEAR_RGB, StageContext
        from pixo.render.pipeline.graph import Pipeline

        img = self._prepare(long_edge)
        img = self._apply_exposure(img, params)
        pipe = Pipeline(stages=self.stages, params=params)
        ctx = StageContext("synthetic", prof=None, config={"stages": dict(params)})
        ctx.set_image(img, DOMAIN_LINEAR_RGB)
        pipe.run(ctx)
        out = ctx.image
        if out.dtype != np.float32 or out.ndim != 3:
            raise LoopError("合成管线输出必须是 HxWx3 float32")
        # 最终应为 gamma 域 0..1；转 8-bit RGB 供 Vision 使用。
        return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    def render_preview(
        self,
        params: dict[str, Any],
        long_edge: int = 512,
    ) -> np.ndarray:
        """渲染 preview。"""
        return self._render(params, int(long_edge))

    def render_full(self, params: dict[str, Any]) -> np.ndarray:
        """渲染全分辨率。"""
        return self._render(params, None)


class RawRenderBackend:
    """真实 RAW 渲染后端：preview 用 RawPreviewSession，full 用导出主线。"""

    def __init__(self, raw_path: str | Path, prof: Any) -> None:
        self.raw_path = Path(raw_path)
        self.prof = prof

    def render_preview(
        self,
        params: dict[str, Any],
        long_edge: int = 1024,
    ) -> np.ndarray:
        """渲染 preview（8-bit）。"""
        from pixo.render.web.session import RawPreviewSession

        session = RawPreviewSession(self.raw_path, self.prof, params=params)
        try:
            return session.render(long_edge=int(long_edge), output_bps=8)
        finally:
            session.close()

    def render_full(self, params: dict[str, Any]) -> np.ndarray:
        """渲染全分辨率（8-bit）。"""
        from pixo.render.web.export import _render_full_quality

        return _render_full_quality(self.raw_path, self.prof, params, output_bps=8)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    """递归合并两个参数 dict，返回新 dict。"""
    out = copy.deepcopy(base)
    for key, value in update.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _resize_masks(
    masks: Mapping[str, np.ndarray],
    shape: tuple[int, int],
) -> dict[str, np.ndarray]:
    """把缓存 mask 调整到指定图像尺寸（最近邻，保持二值）。"""
    height, width = shape
    out: dict[str, np.ndarray] = {}
    for name, mask in masks.items():
        arr = np.asarray(mask)
        if arr.shape == (height, width):
            out[name] = arr
        else:
            resized = cv2.resize(
                arr.astype(np.uint8),
                (width, height),
                interpolation=cv2.INTER_NEAREST,
            )
            out[name] = (resized > 127).astype(np.uint8) * 255
    return out


def _metrics_for_decide(measurement: dict[str, Any]) -> dict[str, Any]:
    """把完整测量报告展平为规则引擎可引用的指标 dict。"""
    if not isinstance(measurement, dict):
        return {}
    global_metrics = measurement.get("global") or {}
    regions = measurement.get("regions") or {}
    metrics: dict[str, Any] = {
        "mean_luminance": global_metrics.get("mean_luminance"),
        "highlight_clip_ratio": global_metrics.get("highlight_clip_ratio"),
        "shadow_clip_ratio": global_metrics.get("shadow_clip_ratio"),
        "contrast": global_metrics.get("contrast"),
        "preview_highlight_clip_estimate": global_metrics.get(
            "preview_highlight_clip_estimate"
        ),
        "preview_overflow_ratio": global_metrics.get(
            "preview_highlight_clip_estimate"
        ),
    }
    for name, region in regions.items():
        if not isinstance(region, dict):
            continue
        metrics[f"{name}_luminance"] = region.get("mean_luminance")
        metrics[f"{name}_area_ratio"] = region.get("area_ratio")
        metrics[f"{name}_highlight_clip_ratio"] = region.get(
            "highlight_clip_ratio"
        )
        metrics[f"{name}_reliable"] = bool(region.get("reliable", False))
    return metrics


def _unreliable_regions(measurement: dict[str, Any]) -> list[str]:
    """返回当前测量中不可靠的区域名。"""
    regions = measurement.get("regions") or {}
    return [
        name
        for name, region in regions.items()
        if not isinstance(region, dict) or not region.get("reliable", False)
    ]


def _flatten_decide_params(params: dict[str, Any]) -> dict[str, Any]:
    """把嵌套管线参数转换为 Decide 使用的扁平参数。

    当前只映射曝光数值；其它参数以原样平铺保留。
    """
    flat: dict[str, Any] = {}
    exposure = params.get("exposure") if isinstance(params.get("exposure"), dict) else {}
    mode = exposure.get("mode", "auto")
    if isinstance(mode, (int, float)) and not isinstance(mode, bool):
        flat["exposure_ev"] = float(mode)
        flat["Exposure"] = float(mode)
    for key, value in params.items():
        if key not in ("exposure", "compose"):
            flat[key] = value
    return flat


def _apply_decide_params(
    params: dict[str, Any],
    decided_params: Mapping[str, Any],
) -> dict[str, Any]:
    """把 Decide 输出的扁平参数映射回渲染 Stage 参数。"""
    out = copy.deepcopy(params)
    for key, value in decided_params.items():
        low = str(key).lower()
        if low in _EXPOSURE_PARAM_ALIASES:
            out.setdefault("exposure", {})["mode"] = float(value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _default_meta_extractor(raw_path: str | Path) -> dict[str, Any]:
    """默认 Meta 提取：调用 pixo.meta.extract。"""
    from pixo.meta import extract

    return extract(raw_path, strip_gps=False)


def _save_image(image: np.ndarray, path: str | Path) -> Path:
    """把 8-bit RGB 图像保存为文件（JPEG/PNG 按后缀）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        ok = cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    else:
        ok = cv2.imwrite(str(path), bgr)
    if not ok:
        raise LoopError(f"无法保存图像: {path}")
    return path


# ---------------------------------------------------------------------------
# 单张闭环
# ---------------------------------------------------------------------------

class SinglePhotoLoop:
    """单张修图闭环编排器。

    参数均可注入，便于单测与未来 service 复用。
    """

    def __init__(
        self,
        *,
        render_backend: Any | None = None,
        renderer: Any | None = None,
        segmenter: Segmenter | None = None,
        measurer: VisionMeasure | None = None,
        meta_extractor: Callable[[str | Path], dict[str, Any]] | None = None,
        rules: Iterable[dict[str, Any]] | None = None,
        store: Any | None = None,
        prof: Any | None = None,
        preview_long_edge: int = 512,
        max_iterations: int = 3,
        prompts: Sequence[str] | None = None,
        confidences: Mapping[str, float] | None = None,
        targets: Mapping[str, Any] | None = None,
        locked_params: Iterable[str] | None = None,
        manual_on_unreliable: bool = True,
        export_path: str | Path | None = None,
    ) -> None:
        self.render_backend = render_backend or renderer
        self.segmenter = segmenter
        self.measurer = measurer or VisionMeasure()
        self.meta_extractor = meta_extractor or _default_meta_extractor
        self.rules = list(rules or [])
        self.store = store
        self.prof = prof
        self.preview_long_edge = int(preview_long_edge)
        self.max_iterations = int(max_iterations)
        self.prompts = list(prompts or ["face", "sky", "plant"])
        self.confidences = dict(confidences or {})
        self.targets = dict(targets or {})
        self.locked_params = list(locked_params or [])
        self.manual_on_unreliable = bool(manual_on_unreliable)
        self.export_path = Path(export_path) if export_path is not None else None

    def _build_backend(
        self,
        *,
        raw_path: str | Path | None,
        image_rgb: np.ndarray | None,
    ) -> Any:
        """按输入选择默认渲染后端。"""
        if self.render_backend is not None:
            return self.render_backend
        if image_rgb is not None:
            return SyntheticRenderBackend(image_rgb)
        if raw_path is not None and self.prof is not None:
            return RawRenderBackend(raw_path, self.prof)
        raise LoopError(
            "缺少渲染后端：请传入 render_backend、image_rgb，"
            "或同时提供 raw_path 与 prof"
        )

    def _add_trace(
        self,
        sm: PhotoStateMachine,
        *,
        event_type: str,
        reason: str = "",
        param: str | None = None,
        value: Any = None,
        old_value: Any = None,
        new_value: Any = None,
        rule_id: str = "",
        formula: str = "",
        metadata: dict[str, Any] | None = None,
        source: str = "single_photo_loop",
    ) -> TraceEvent:
        """简化 Trace 记录。"""
        return sm.add_trace(
            event_type=event_type,
            reason=reason,
            param=param,
            value=value,
            old_value=old_value,
            new_value=new_value,
            rule_id=rule_id,
            formula=formula,
            metadata=metadata or {},
            source=source,
        )

    def _trace_param_updates(
        self,
        sm: PhotoStateMachine,
        before: dict[str, Any],
        after: dict[str, Any],
        rule_ids: Sequence[str],
        iteration: int,
    ) -> None:
        """为每个发生变化的扁平参数记录一条参数级 Trace。"""
        for key in sorted(set(before) | set(after)):
            old_value = before.get(key)
            new_value = after.get(key)
            if old_value == new_value:
                continue
            rule_id = rule_ids[0] if rule_ids else ""
            self._add_trace(
                sm,
                event_type="param_update",
                param=str(key),
                reason="Decide 参数更新",
                value=new_value,
                old_value=old_value,
                new_value=new_value,
                rule_id=rule_id,
                metadata={"iteration": iteration, "rule_ids": list(rule_ids)},
                source="quantitative_decision",
            )

    def _fast_forward_to_final_qc(self, sm: PhotoStateMachine) -> None:
        """从当前迭代状态顺序推进到 FINAL_QC。"""
        next_map = {
            "BASE_RENDERED": "EXPOSURE_ALIGNING",
            "EXPOSURE_ALIGNING": "COLOR_CORRECTING",
            "COLOR_CORRECTING": "STYLE_APPLIED",
            "STYLE_APPLIED": "FINAL_QC",
        }
        guard = 0
        while sm.state not in ("FINAL_QC", "ACCEPTED", "MANUAL_REVIEW", "REJECTED"):
            target = next_map.get(sm.state)
            if target is None:
                raise LoopError(f"无法从 {sm.state} 推进到 FINAL_QC")
            sm.transition(target, reason="进入最终 QC")
            guard += 1
            if guard > 10:
                raise LoopError("状态机推进异常")

    def _run_preview_iterations(
        self,
        sm: PhotoStateMachine,
        backend: Any,
        photo_id: str,
        start_params: dict[str, Any],
        metadata: dict[str, Any],
        max_iterations: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, np.ndarray] | None, str | None]:
        """执行 preview 迭代，返回 (params, measurements, masks_cache, stop_reason)。"""
        params = copy.deepcopy(start_params)
        measurements: list[dict[str, Any]] = []
        masks_cache: dict[str, np.ndarray] | None = None
        improvement_history: list[float] = []
        previous_key = None
        stop_reason: str | None = None

        for iteration in range(1, max_iterations + 1):
            # 状态推进：每次迭代对应一个可前进的 State 阶段。
            if sm.state == "BASE_RENDERED":
                sm.transition(
                    "EXPOSURE_ALIGNING",
                    iteration=iteration,
                    params=params,
                    reason="开始 preview 迭代",
                )
            elif sm.state == "EXPOSURE_ALIGNING" and iteration == 2:
                sm.transition(
                    "COLOR_CORRECTING",
                    iteration=iteration,
                    params=params,
                    reason="进入第二轮 preview 迭代",
                )
            elif sm.state == "COLOR_CORRECTING" and iteration == 3:
                sm.transition(
                    "STYLE_APPLIED",
                    iteration=iteration,
                    params=params,
                    reason="进入第三轮 preview 迭代",
                )

            preview_img = backend.render_preview(
                params, long_edge=self.preview_long_edge
            )
            if masks_cache is None:
                try:
                    masks_cache = self.segmenter.segment(preview_img, list(self.prompts))
                except SegmenterUnavailable as exc:
                    sm.escalate(f"分割模型不可用：{exc}")
                    return params, measurements, None, "segmenter_unavailable"
            masks = _resize_masks(masks_cache, preview_img.shape[:2])
            measurement = self.measurer.measure(
                preview_img,
                masks,
                confidences=self.confidences,
                image_id=photo_id,
                render_version=self._render_version(),
                detection_version=self._detection_version(),
            )
            measurements.append(measurement)

            metrics = _metrics_for_decide(measurement)
            unreliable = _unreliable_regions(measurement)
            key = metrics.get("face_luminance") or metrics.get("mean_luminance")
            if key is not None:
                if previous_key is not None:
                    improvement_history.append(abs(float(key) - float(previous_key)))
                previous_key = float(key)

            flat_params = _flatten_decide_params(params)
            decide_context = {
                "metrics": metrics,
                "params": flat_params,
                "rules": self.rules,
                "targets": self.targets,
                "iteration": iteration,
                "max_iterations": max_iterations,
                "unreliable_regions": unreliable,
                "locked_params": self.locked_params,
                "preview_overflow_ratio": metrics.get(
                    "preview_highlight_clip_estimate"
                ),
                "improvement_history": improvement_history,
                "manual_on_unreliable": self.manual_on_unreliable,
            }
            decision = decide(decide_context, self.rules)
            self._add_trace(
                sm,
                event_type="decide",
                reason=decision.get("reason") or "",
                param=None,
                value={
                    "iteration": iteration,
                    "decision": decision.get("decision"),
                    "reasons": decision.get("reasons", []),
                    "rule_ids": decision.get("rule_ids", []),
                    "params": decision.get("params", {}),
                    "metrics": metrics,
                },
                metadata={"iteration": iteration},
            )

            if decision.get("decision") == "manual_review":
                reason = (
                    decision.get("reasons") or ["Decide 判定需要人工复核"]
                )[0]
                sm.escalate(reason)
                return params, measurements, masks_cache, None

            if decision.get("decision") == "stopped":
                stop_reason = decision.get("reason") or "Decide 终止"
                break

            flat_before = _flatten_decide_params(params)
            params = _apply_decide_params(
                params, decision.get("params") or {}
            )
            flat_after = _flatten_decide_params(params)
            self._trace_param_updates(
                sm,
                flat_before,
                flat_after,
                decision.get("rule_ids") or [],
                iteration,
            )

        return params, measurements, masks_cache, stop_reason

    def _render_version(self) -> str:
        """当前渲染版本标识。"""
        return "pixo_render_0.1"

    def _detection_version(self) -> str:
        """当前检测版本标识。"""
        return "yoloe26l_seg_v1"

    def _run_final_qc(
        self,
        sm: PhotoStateMachine,
        backend: Any,
        photo_id: str,
        params: dict[str, Any],
        masks_cache: dict[str, np.ndarray] | None,
    ) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
        """执行 FINAL_QC：全分辨率渲染 + mask 上采样测量。"""
        full_img = backend.render_full(params)
        full_masks = _resize_masks(masks_cache or {}, full_img.shape[:2])
        full_measurement = self.measurer.measure(
            full_img,
            full_masks,
            confidences=self.confidences,
            image_id=photo_id,
            render_version=self._render_version(),
            detection_version=self._detection_version(),
        )
        return full_img, full_measurement, full_masks

    def _qc_outcome(
        self,
        sm: PhotoStateMachine,
        full_measurement: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """判定 FINAL_QC 是否需要回退/人工。"""
        qc_ratio = float(
            (full_measurement.get("global") or {}).get(
                "highlight_clip_ratio", 0.0
            )
        )
        qc_context = {
            "params": _flatten_decide_params(params),
            "qc_overflow_ratio": qc_ratio,
            "qc_rollback_count": sm.record.qc_rollback_count,
            "unreliable_regions": _unreliable_regions(full_measurement),
            "locked_params": self.locked_params,
        }
        return qc_rollback(qc_context)

    def run(
        self,
        photo_id: str,
        *,
        raw_path: str | Path | None = None,
        image_rgb: np.ndarray | None = None,
        image: np.ndarray | None = None,
        meta: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        compose_params: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        agent_decision: str = "agree",
        max_iterations: int | None = None,
    ) -> LoopResult:
        """执行单张闭环，返回 LoopResult。"""
        if image_rgb is None and image is not None:
            image_rgb = image
        if meta is None and metadata is not None:
            meta = metadata
        backend = self._build_backend(raw_path=raw_path, image_rgb=image_rgb)
        if self.segmenter is None:
            self.segmenter = MockSegmenter()
        max_iter = int(max_iterations or self.max_iterations)

        sm = PhotoStateMachine(photo_id, store=self.store)
        metadata = dict(meta or {})
        if not metadata and raw_path is not None:
            try:
                metadata = self.meta_extractor(raw_path)
            except Exception as exc:  # noqa: BLE001 - Meta 缺失不阻断闭环
                metadata = {"error": str(exc)}
        sm.transition("SCREENED", reason="元数据提取完成", metadata={"meta": metadata})
        self._add_trace(
            sm,
            event_type="meta_extracted",
            reason="Pixo Meta 提取完成",
            value=metadata,
            metadata={"meta": metadata},
        )

        loop_params = copy.deepcopy(params or {})
        if compose_params:
            loop_params = _deep_merge(loop_params, {"compose": copy.deepcopy(compose_params)})
        sm.transition(
            "BASE_RENDERED",
            reason="构图参数确定",
            params=loop_params,
            metadata={"compose_params": compose_params or {}},
        )
        self._add_trace(
            sm,
            event_type="compose_params",
            reason="构图参数确定",
            value=loop_params.get("compose"),
            metadata={"compose_params": compose_params or {}},
        )

        if agent_decision != "agree":
            reason = "用户/Agent 升级人工复核"
            sm.escalate(reason)
            return self._result(
                sm, photo_id, loop_params, [], None, None,
                metadata, None, agent_decision=agent_decision,
                reason=reason,
            )

        params_after, preview_measurements, masks_cache, _stop_reason = (
            self._run_preview_iterations(
                sm, backend, photo_id, loop_params, metadata, max_iter
            )
        )

        if sm.state == "MANUAL_REVIEW":
            return self._result(
                sm, photo_id, params_after, preview_measurements,
                None, None, metadata, None, agent_decision=agent_decision,
                reason="Decide/分割异常转入人工复核",
            )

        self._fast_forward_to_final_qc(sm)

        full_img, full_measurement, _ = self._run_final_qc(
            sm, backend, photo_id, params_after, masks_cache
        )
        qc = self._qc_outcome(sm, full_measurement, params_after)

        if qc.get("decision") == "rollback":
            rolled_params = _apply_decide_params(
                params_after, qc.get("params") or {}
            )
            sm.transition(
                "EXPOSURE_ALIGNING",
                event_type="QC_ROLLBACK",
                reason=(qc.get("reasons") or ["FINAL_QC 超标回退"])[0],
                params=rolled_params,
                measurement=full_measurement,
            )
            self._add_trace(
                sm,
                event_type="qc_rollback",
                reason=(qc.get("reasons") or ["FINAL_QC 超标回退"])[0],
                param="Exposure",
                old_value=_flatten_decide_params(params_after).get(
                    "exposure_ev"
                ),
                new_value=_flatten_decide_params(rolled_params).get(
                    "exposure_ev"
                ),
                metadata={"qc_overflow_ratio": (full_measurement.get("global") or {}).get("highlight_clip_ratio")},
            )
            self._fast_forward_to_final_qc(sm)
            full_img, full_measurement, _ = self._run_final_qc(
                sm, backend, photo_id, rolled_params, masks_cache
            )
            qc2 = self._qc_outcome(sm, full_measurement, rolled_params)
            if qc2.get("decision") == "manual_review" or (
                qc2.get("decision") == "rollback"
            ):
                sm.transition(
                    "MANUAL_REVIEW",
                    reason="FINAL_QC 二次超标，停止自动回退",
                )
                return self._result(
                    sm, photo_id, rolled_params, preview_measurements,
                    full_measurement, full_img, metadata,
                    full_measurement.get("global"), agent_decision=agent_decision,
                    reason="FINAL_QC 二次超标，转人工复核",
                )
            full_measurement = qc2.get("measurement", full_measurement)
            sm.transition(
                "ACCEPTED",
                reason="FINAL_QC 回退后达标",
                params=rolled_params,
                measurement=full_measurement,
            )
            params_after = rolled_params
        elif qc.get("decision") == "manual_review":
            sm.transition(
                "MANUAL_REVIEW",
                reason=(qc.get("reasons") or ["FINAL_QC 不可自动修复"])[0],
            )
            return self._result(
                sm, photo_id, params_after, preview_measurements,
                full_measurement, full_img, metadata,
                full_measurement.get("global"), agent_decision=agent_decision,
                reason="FINAL_QC 转人工复核",
            )
        else:
            sm.transition(
                "ACCEPTED",
                reason="FINAL_QC 达标",
                params=params_after,
                measurement=full_measurement,
            )

        if self.export_path is not None and full_img is not None:
            self.export_path = _save_image(full_img, self.export_path)

        return self._result(
            sm, photo_id, params_after, preview_measurements,
            full_measurement, full_img, metadata,
            full_measurement.get("global"), agent_decision=agent_decision,
            reason="FINAL_QC 达标",
        )

    def _result(
        self,
        sm: PhotoStateMachine,
        photo_id: str,
        params: dict[str, Any],
        measurements: list[dict[str, Any]],
        final_measurement: dict[str, Any] | None,
        final_image: np.ndarray | None,
        metadata: dict[str, Any],
        global_metrics: dict[str, Any] | None,
        *,
        agent_decision: str,
        reason: str,
    ) -> LoopResult:
        """构造最终结果。"""
        compose_geometry = None
        if isinstance(params.get("compose"), dict):
            compose_geometry = params["compose"]
        return LoopResult(
            photo_id=photo_id,
            state=sm.state,
            iteration=sm.record.iteration,
            params=params,
            measurements=measurements,
            final_measurement=final_measurement,
            final_image=final_image,
            trace_events=[e.to_dict() for e in sm.history()],
            decision=sm.state,
            reason=reason,
            qc_rollback_count=sm.record.qc_rollback_count,
            metadata=metadata,
            compose_geometry=compose_geometry,
            agent_decision=agent_decision,
        )


def run_single_photo_loop(
    photo_id: str,
    *,
    image_rgb: np.ndarray | None = None,
    image: np.ndarray | None = None,
    raw_path: str | Path | None = None,
    prof: Any | None = None,
    segmenter: Segmenter | None = None,
    measurer: VisionMeasure | None = None,
    render_backend: Any | None = None,
    renderer: Any | None = None,
    meta: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    compose_params: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    rules: Iterable[dict[str, Any]] | None = None,
    store: Any | None = None,
    max_iterations: int = 3,
    prompts: Sequence[str] | None = None,
    agent_decision: str = "agree",
    **kwargs: Any,
) -> LoopResult:
    """函数式单张闭环入口。"""
    loop = SinglePhotoLoop(
        render_backend=render_backend,
        renderer=renderer,
        segmenter=segmenter,
        measurer=measurer,
        rules=rules,
        store=store,
        prof=prof,
        max_iterations=max_iterations,
        prompts=prompts,
        **kwargs,
    )
    if image_rgb is None and image is not None:
        image_rgb = image
    if meta is None and metadata is not None:
        meta = metadata
    return loop.run(
        photo_id,
        raw_path=raw_path,
        image_rgb=image_rgb,
        meta=meta,
        compose_params=compose_params,
        params=params,
        agent_decision=agent_decision,
    )


__all__ = [
    "SinglePhotoLoop",
    "run_single_photo_loop",
    "SyntheticRenderBackend",
    "RawRenderBackend",
    "LoopResult",
    "LoopError",
]
