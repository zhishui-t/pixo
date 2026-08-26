"""pixo.vision.segmenters.uniface_face —— 人脸解析适配器（UniFace/BiSeNet 位）。

契约位为 UniFace(BiSeNet)；当前实现经 HF face-parsing（SegFormer 头部解析，
jonathandinu/face-parsing）达成同语义输出。其权重源自 CelebAMask-HQ 训练，
许可为非商业——仅限内部研发使用，已登记 model_licenses.json。
第三方推理(import torch/transformers)只存在于本文件（隔离纪律）。

输出：prompt "face" -> 二值 0/255 掩码（头部区域，含皮肤/眉眼口鼻）。
"""
from __future__ import annotations

import os

import numpy as np

from ..base import BaseSegmenter
from ..exceptions import PromptNotSupportedError, SegmenterUnavailable
from .common import LazyBackendMixin, to_binary_mask

DEFAULT_CKPT = os.environ.get(
    "PIXO_UNIFACE_MODEL", "jonathandinu/face-parsing"
)
SUPPORTED = ("face",)


class UniFaceSegmenter(LazyBackendMixin, BaseSegmenter):
    """人脸分割适配器：prompt 路由表中的 face 后端。"""

    PROMPT_KEYS = SUPPORTED

    # 轻量探测：仅检查依赖可 import（不触发 from_pretrained）。
    _PROBE_IMPORTS = ("torch", "transformers")

    def __init__(self, ckpt: str | None = None) -> None:
        self.ckpt = ckpt or DEFAULT_CKPT
        self._model = None
        self._proc = None

    def _load(self) -> None:
        import torch  # noqa: F401  本文件内允许（隔离纪律）
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

        self._proc = SegformerImageProcessor.from_pretrained(self.ckpt)
        self._model = SegformerForSemanticSegmentation.from_pretrained(self.ckpt)
        self._model.eval()

    def _supported(self, prompts: list[str]) -> list[str]:
        norm = self.normalize_prompts(prompts)
        kept = [p for p in norm if p.lower() in SUPPORTED]
        dropped = [p for p in norm if p.lower() not in SUPPORTED]
        if dropped and not kept:
            raise PromptNotSupportedError(
                f"UniFace 仅支持 {SUPPORTED}，收到 {dropped}"
            )
        return kept

    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict:
        self.validate_image(image_rgb)
        kept = self._supported(self.normalize_prompts(prompts))
        if not kept:
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
        # face-parsing: 0=background；其余类别(皮肤/五官)合并为人脸区
        raw = (seg != 0).astype(np.uint8) * 255
        return {"face": to_binary_mask(raw, h, w)}
