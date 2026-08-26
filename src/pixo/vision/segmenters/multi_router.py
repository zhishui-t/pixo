"""pixo.vision.segmenters.multi_router —— prompt 路由多模型 Segmenter。

契约不变：segment(image_rgb, prompts) -> dict[str, 0/255 uint8 mask]。
路由：face->uniface | person/subject->rfdetr |
sky/plant/mountain/tree/grass->segformer | 其余->grounded_sam(可选)。
降级语义：后端不可用时其 prompt 返回全零掩码并告警一次（契约形状保持）。
测试可经 backends= 注入假件；不注入则按需实例化真实适配器。
"""
from __future__ import annotations

import numpy as np

from ..base import BaseSegmenter
from .common import warmup_enabled, zeros_mask


def route_of(prompt_lower: str) -> str:
    table = {
        "face": "uniface",
        "person": "rfdetr", "subject": "rfdetr",
        "sky": "segformer", "plant": "segformer",
        "mountain": "segformer", "tree": "segformer", "grass": "segformer",
        "hair": "sapiens", "skin": "sapiens",
        "clothes": "sapiens", "body": "sapiens",
    }
    return table.get(prompt_lower, "gsam")


class MultiModelSegmenter(BaseSegmenter):
    """按 prompt 路由的多模型 Segmenter（t90）。"""

    def __init__(self, backends: dict | None = None) -> None:
        self.backends: dict = dict(backends or {})
        self._warned_backends: set = set()

    def _get(self, name: str):
        if name in self.backends:
            return self.backends[name]
        if name == "uniface":
            from .uniface_face import UniFaceSegmenter
            self.backends[name] = UniFaceSegmenter()
        elif name == "rfdetr":
            from .rfdetr_person import RFDetrPersonSegmenter
            self.backends[name] = RFDetrPersonSegmenter()
        elif name == "segformer":
            from .segformer_scenes import SegFormerSceneSegmenter
            self.backends[name] = SegFormerSceneSegmenter()
        elif name == "gsam":
            from .grounded_sam import GroundedSAMSegmenter
            self.backends[name] = GroundedSAMSegmenter()
        elif name == "sapiens":
            from .sapiens_body import SapiensBodySegmenter
            self.backends[name] = SapiensBodySegmenter()
        else:  # pragma: no cover
            raise KeyError(name)
        return self.backends[name]

    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned_backends:
            self._warned_backends.add(key)
            print(f"[pixo.vision.segmenters] {msg}")

    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict:
        self.validate_image(image_rgb)
        # t91：prompt 键规范化小写——路由(route_of)与输出掩码键统一契约，
        # 各后端收到的均为小写规范化键（如 HAIR->hair）。
        norm = [p.lower() for p in self.normalize_prompts(prompts)]
        h, w = image_rgb.shape[:2]

        groups: dict[str, list[str]] = {}
        for p in norm:
            groups.setdefault(route_of(p.lower()), []).append(p)

        out: dict = {}
        for backend_name, plist in groups.items():
            try:
                backend = self._get(backend_name)
                out.update(backend.segment(image_rgb, plist))
            except Exception as exc:  # noqa: BLE001 - 后端级降级
                self._warn_once(
                    f"backend:{backend_name}",
                    f"后端 {backend_name} 不可用，{len(plist)} 个 prompt "
                    f"零掩码降级 ({type(exc).__name__}: {exc})")
                for p in plist:
                    out[p] = zeros_mask(h, w)

        for p in norm:
            if p not in out:
                self._warn_once(f"missing:{p}",
                                f"prompt {p!r} 无后端返回，零掩码降级")
                out[p] = zeros_mask(h, w)
        return out

    def detect_boxes(self, image_rgb: np.ndarray,
                     prompts: list[str]) -> dict[str, list[list[float]]]:
        """原生框直供（t92）：仅路由到具备检测头的后端（当前=rfdetr）。

        返回 {prompt: [[x0,y0,x1,y1] 归一化]}；无后端支持/失败的 prompt
        不出现在结果中——调用方据此回退 mask_bbox。
        """
        self.validate_image(image_rgb)
        norm = self.normalize_prompts(prompts)
        groups: dict[str, list[str]] = {}
        for p in norm:
            route = route_of(p.lower())
            if route == "rfdetr":
                groups.setdefault("rfdetr", []).append(p)
        out: dict = {}
        for name, plist in groups.items():
            try:
                backend = self._get(name)
                det = getattr(backend, "detect_boxes", None)
                if callable(det):
                    res = det(image_rgb, plist)
                    if isinstance(res, dict):
                        out.update(res)
            except Exception:  # noqa: BLE001 - 原生框失败静默回退
                continue
        return out

    def warmup(self, image: np.ndarray | None = None) -> dict:
        """预热全部已实例化后端（各后端自身受 PIXO_SEGMENTER_WARMUP 门控）。"""
        if not warmup_enabled():
            return {"skipped": True}
        report = {}
        for name in sorted(list(self.backends)):
            b = self.backends[name]
            if hasattr(b, "warmup"):
                report[name] = b.warmup(image)
            else:
                report[name] = {"warmed": False, "reason": "no-warmup-api"}
        return report

    def health(self) -> dict:
        out = {}
        for name, b in self.backends.items():
            entry = {"available": True}
            if hasattr(b, "warmup_health"):
                entry.update(b.warmup_health())
            if getattr(b, "_degraded", False):
                entry["available"] = False
                entry["error"] = getattr(b, "_error", None)
            out[name] = entry
        return out
