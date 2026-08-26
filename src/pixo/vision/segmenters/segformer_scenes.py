"""pixo.vision.segmenters.segformer_scenes —— 场景语义分割适配器。

SegFormer-B1（ADE20K 微调权重，默认 nvidia/segformer-b1-finetuned-ade-512-512，
代码 Apache-2.0 / 权重随 ADE 派生口径——已登记 model_licenses.json）。
负责 prompt 路由表中的 sky/plant/mountain（及 tree/grass 别名）。
第三方推理(import torch/transformers)只存在于本文件（隔离纪律）。
"""
from __future__ import annotations

import os

import numpy as np

from ..base import BaseSegmenter
from ..exceptions import PromptNotSupportedError
from .common import LazyBackendMixin, to_binary_mask

DEFAULT_CKPT = os.environ.get(
    "PIXO_SEGFORMER_MODEL", "nvidia/segformer-b1-finetuned-ade-512-512"
)

# ADE20K 类别 id → 支持的 prompt（并集语义）
ADE = {
    "sky": {2},
    "tree": {4},
    "grass": {9},
    "plant": {17, 4},
    "mountain": {16},
}
SUPPORTED = tuple(ADE)


class SegFormerSceneSegmenter(LazyBackendMixin, BaseSegmenter):
    """场景分割适配器：sky/plant/mountain/tree/grass 后端。"""

    PROMPT_KEYS = SUPPORTED

    # 轻量探测：仅检查依赖可 import（不触发 from_pretrained）。
    _PROBE_IMPORTS = ("torch", "transformers")

    def __init__(self, ckpt: str | None = None) -> None:
        self.ckpt = ckpt or DEFAULT_CKPT
        self._model = None
        self._proc = None

    def _load(self) -> None:
        import torch  # noqa: F401
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

        self._proc = SegformerImageProcessor.from_pretrained(self.ckpt)
        self._model = SegformerForSemanticSegmentation.from_pretrained(self.ckpt)
        self._model.eval()

    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict:
        self.validate_image(image_rgb)
        norm = self.normalize_prompts(prompts)
        wanted = {}
        for p in norm:
            key = p.lower()
            if key in ADE:
                wanted[p] = ADE[key]
            elif key in {"plant_life", "vegetation"}:
                wanted[p] = ADE["plant"] | ADE["tree"]
            else:
                raise PromptNotSupportedError(
                    f"SegFormer 场景后端不支持 prompt={p!r}"
                )
        if not wanted:
            return {}
        h, w = image_rgb.shape[:2]
        self._ensure_loaded()

        import torch

        inputs = self._proc(images=image_rgb[..., :3], return_tensors="pt")
        with torch.no_grad():
            logits = self._model(**inputs).logits
        up = torch.nn.functional.interpolate(
            logits, size=(h, w), mode="bilinear", align_corners=False)
        seg = up.argmax(dim=1)[0].cpu().numpy()

        out: dict = {}
        for prompt, ids in wanted.items():
            raw = np.isin(seg, list(ids)).astype(np.uint8) * 255
            out[prompt] = to_binary_mask(raw, h, w)
        return out
