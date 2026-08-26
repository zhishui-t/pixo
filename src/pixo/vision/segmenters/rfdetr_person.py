"""pixo.vision.segmenters.rfdetr_person —— 人物实例分割适配器。

RF-DETR-Seg 2XL（roboflow，Apache-2.0；权重经 pip 包首用自动下载，
已登记 model_licenses.json）。负责 prompt 路由表中的 person/subject。
第三方推理(import rfdetr)只存在于本文件（隔离纪律）。
"""
from __future__ import annotations

import logging

import numpy as np

from ..base import BaseSegmenter
from .common import LazyBackendMixin, to_binary_mask

_LOG = logging.getLogger(__name__)

SUPPORTED = ("person", "subject")


class RFDetrPersonSegmenter(LazyBackendMixin, BaseSegmenter):
    """人物分割适配器：person/subject 共享最大面积实例掩码。"""

    PROMPT_KEYS = SUPPORTED

    # 轻量探测：仅检查依赖可 import（不触发权重下载）。
    _PROBE_IMPORTS = ("rfdetr",)

    def __init__(self, model_uri: str | None = None,
                 threshold: float = 0.5) -> None:
        self.model_uri = model_uri
        self.threshold = float(threshold)
        self._model = None
        self._detect_warned = False

    def _load(self) -> None:
        # t102 修复: 顶层没有 RFDETRSeg（仅 variants 出口），
        # 用与 model_licenses 登记一致的 RFDETRSeg2XLarge；
        # 构造只认 ModelConfig 字段（pretrained 非法 kwarg），
        # 官方权重经 pretrain_weights 默认值自动下载。
        from rfdetr import RFDETRSeg2XLarge  # 懒加载：仅真实使用时导入

        kwargs: dict = {}
        if self.model_uri:
            kwargs["pretrain_weights"] = self.model_uri  # 自定义权重走 URI/路径
        self._model = RFDETRSeg2XLarge(**kwargs)

    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict:
        self.validate_image(image_rgb)
        norm = [p for p in self.normalize_prompts(prompts)
                if p.lower() in SUPPORTED]
        unsupported = [p for p in self.normalize_prompts(prompts)
                       if p.lower() not in SUPPORTED]
        if unsupported and not norm:
            from ..exceptions import PromptNotSupportedError
            raise PromptNotSupportedError(
                f"RF-DETR 仅支持 {SUPPORTED}，收到 {unsupported}")
        if not norm:
            return {}

        h, w = image_rgb.shape[:2]
        self._ensure_loaded()

        detections = self._model.predict(image_rgb[..., :3],
                                         threshold=self.threshold)
        mask = None
        masks = getattr(detections, "mask", None)
        if masks is not None and len(masks):
            areas = []
            for m in masks:
                a = int((np.asarray(m) > 0).sum())
                areas.append(a)
            mask = masks[int(np.argmax(areas))]
        if mask is None:
            from .common import zeros_mask
            empty = zeros_mask(h, w)
            return {p: empty for p in norm}

        binary = to_binary_mask(mask, h, w)
        return {p: binary for p in norm}

    def detect_boxes(self, image_rgb: np.ndarray,
                     prompts: list[str]) -> dict[str, list[list[float]]]:
        """原生检测框直供（t92）：归一化 [x0,y0,x1,y1] ∈[0,1]。

        取最大面积实例的 xyxy，按请求的 person/subject 键返回（与
        segment 的最大实例掩码语义一致）。模型不可用/无检出返回空 dict
        （best-effort 语义保留；失败仅每实例一次 warning，不抛）。
        """
        self.validate_image(image_rgb)
        norm = [q for q in self.normalize_prompts(prompts)
                if q.lower() in SUPPORTED]
        if not norm:
            return {}
        try:
            self._ensure_loaded()
            detections = self._model.predict(image_rgb[..., :3],
                                             threshold=self.threshold)
        except Exception as exc:  # noqa: BLE001 - 原生框 best-effort 回退
            if not self._detect_warned:
                self._detect_warned = True
                _LOG.warning(
                    "[pixo.vision.segmenters] RFDetrPersonSegmenter "
                    "detect_boxes 失败，回退 mask_bbox "
                    "(%s: %s)", type(exc).__name__, exc)
            return {}

        xyxy = getattr(detections, "xyxy", None)
        if xyxy is None:
            data = getattr(detections, "data", None) or {}
            xyxy = data.get("xyxy")
        if xyxy is None:
            return {}
        boxes = np.asarray(xyxy, dtype=np.float64)
        if boxes.ndim != 2 or boxes.shape[0] == 0:
            return {}

        h, w = image_rgb.shape[:2]
        masks = getattr(detections, "mask", None)
        areas = []
        for i in range(boxes.shape[0]):
            if masks is not None and i < len(masks):
                areas.append(int((np.asarray(masks[i]) > 0).sum()))
            else:
                x0, y0, x1, y1 = boxes[i]
                areas.append(float(max(x1 - x0, 0.0) * max(y1 - y0, 0.0)))
        best = int(np.argmax(areas))
        x0, y0, x1, y1 = boxes[best]
        rect = [min(max(x0 / w, 0.0), 1.0),
                min(max(y0 / h, 0.0), 1.0),
                min(max(x1 / w, 0.0), 1.0),
                min(max(y1 / h, 0.0), 1.0)]
        return {q: [rect] for q in norm}
