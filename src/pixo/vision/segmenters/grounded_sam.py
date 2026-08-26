"""pixo.vision.segmenters.grounded_sam —— 开放词汇分割适配器（可选懒加载）。

两段式：GroundingDINO(tiny) 出框 -> SAM(vit-base) 精修掩码。
可选后端：默认关闭（opt-in），仅路由到未知 prompt 且 PIXO_GSAM_ENABLED=1
时才加载——启用会经 transformers 首用自动下载 GroundingDINO+SAM 全套权重
（合计数 GB 磁盘占用），故不做默认开启；
缺失/失败抛 SegmenterUnavailable，由路由器降级零掩码。
第三方推理只存在于本文件（隔离纪律）。
"""
from __future__ import annotations

import os

import numpy as np

from ..base import BaseSegmenter
from .common import LazyBackendMixin, to_binary_mask, zeros_mask
from ..exceptions import SegmenterUnavailable

DEFAULT_DINO = os.environ.get(
    "PIXO_GSAM_DINO", "IDEA-Research/grounding-dino-tiny")
DEFAULT_SAM = os.environ.get("PIXO_GSAM_SAM", "facebook/sam-vit-base")


class GroundedSAMSegmenter(LazyBackendMixin, BaseSegmenter):
    """开放词汇后端：任意文本 prompt（下划线转空格短语）。

    默认关闭（体积后果：DINO+SAM 首用合计下载数 GB 权重）；
    PIXO_GSAM_ENABLED=1 显式开启。
    """

    PROMPT_KEYS = ("*",)

    # 轻量探测：仅检查依赖可 import（不触发 from_pretrained 下载）。
    _PROBE_IMPORTS = ("torch", "transformers")

    def enabled(self) -> bool:
        """默认关闭（"0"）；PIXO_GSAM_ENABLED=1 显式开启。"""
        return os.environ.get("PIXO_GSAM_ENABLED", "0").strip().lower() in (
            {"1", "true", "on", "yes"}
        )

    def _load(self) -> None:
        import torch  # noqa: F401
        from transformers import (
            AutoModelForZeroShotObjectDetection,
            AutoProcessor,
            SamModel,
            SamProcessor,
        )

        self._dino_proc = AutoProcessor.from_pretrained(DEFAULT_DINO)
        self._dino = AutoModelForZeroShotObjectDetection.from_pretrained(
            DEFAULT_DINO)
        self._sam_proc = SamProcessor.from_pretrained(DEFAULT_SAM)
        self._sam = SamModel.from_pretrained(DEFAULT_SAM)
        for m in (self._dino, self._sam):
            m.eval()

    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict:
        if not self.enabled():
            raise SegmenterUnavailable("GroundedSAM 已由环境开关禁用")
        self.validate_image(image_rgb)
        norm = self.normalize_prompts(prompts)
        if not norm:
            return {}
        h, w = image_rgb.shape[:2]
        self._ensure_loaded()

        import torch
        from PIL import Image

        pil = Image.fromarray(image_rgb[..., :3])
        text = [[" ".join(p.split("_")) + "." for p in norm]]
        dinputs = self._dino_proc(images=pil, text=text,
                                  return_tensors="pt")
        with torch.no_grad():
            douts = self._dino(**dinputs)
        results = self._dino_proc.post_process_grounded_object_detection(
            douts, threshold=0.30, text_threshold=0.25)[0]

        boxes = results.get("boxes") if hasattr(results, "get") else None
        labels = [str(l).split("(")[0].strip().lower()
                  for l in (results.get("labels") or [])]             if isinstance(results, dict) else []

        out: dict = {}
        for i, prompt in enumerate(norm):
            phrase = " ".join(prompt.split("_")).lower()
            idx = []
            if boxes is not None and len(boxes):
                for k, l in enumerate(labels):
                    if phrase and (phrase in l or l in phrase):
                        idx.append(k)
            if not idx:
                out[prompt] = zeros_mask(h, w)
                continue
            sel = boxes[idx[:1]]
            sinputs = self._sam_proc([pil], input_boxes=[sel.tolist()],
                                     return_tensors="pt")
            with torch.no_grad():
                souts = self._sam(**sinputs)
            masks = self._sam_proc.image_processor.post_process_masks(
                souts.pred_masks.cpu(),
                sinputs["original_sizes"].tolist(),
                sinputs["reshaped_input_sizes"].tolist())
            m0 = masks[0][0][0]
            m0 = m0.numpy() if hasattr(m0, "numpy") else np.asarray(m0)
            out[prompt] = to_binary_mask(m0.astype(np.uint8), h, w)
        return out
