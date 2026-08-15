"""Stage 6 —— 精修 (gamma_rgb → gamma_rgb, 显示域轻量打磨)。

全部可关、默认轻量, 不引入大成本算子:
  - 高光去色: 接近白的像素色度向中性回拉 (修复高光染色/品红边)。
  - 轻锐化: 亮度通道 unsharp mask (幅度小, 不产生晕边)。
  - 色度降噪: Lab a/b 小半径高斯 (去彩噪, 不碰亮度细节)。

参数:
  highlight_desat  高光去色强度 0..1 (默认 0.6)
  sharpen          锐化幅度 0..1 (默认 0.25)
  chroma_denoise   色度降噪 sigma (默认 0.8, 0=关)
"""
from __future__ import annotations

import cv2
import numpy as np

from ..core import Stage, StageContext, register_stage
from ..core import DOMAIN_GAMMA_RGB


@register_stage("refine", order=6,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class RefineStage(Stage):
    name = "refine"

    def default_params(self):
        return {"highlight_desat": 0.6, "sharpen": 0.25, "chroma_denoise": 0.8}

    def process(self, ctx: StageContext) -> None:
        img = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)
        hd = float(self.p(ctx, "highlight_desat"))
        sh = float(self.p(ctx, "sharpen"))
        cd = float(self.p(ctx, "chroma_denoise"))

        if hd > 0.0:
            img = self._highlight_desat(img, hd)
        if cd > 0.0 or sh > 0.0:
            u8 = (img * 255.0 + 0.5).astype(np.uint8)
            lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
            if cd > 0.0:
                a = cv2.GaussianBlur(lab[:, :, 1], (0, 0), cd)
                b = cv2.GaussianBlur(lab[:, :, 2], (0, 0), cd)
                lab[:, :, 1] = a
                lab[:, :, 2] = b
            if sh > 0.0:
                L = lab[:, :, 0]
                blur = cv2.GaussianBlur(L, (0, 0), 1.2)
                L = np.clip(L + sh * 12.0 * (L - blur), 0, 255)
                lab[:, :, 0] = L
            out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
            img = out.astype(np.float32) / 255.0
        ctx.set_image(np.clip(img, 0.0, 1.0), DOMAIN_GAMMA_RGB)

    @staticmethod
    def _highlight_desat(img: np.ndarray, strength: float) -> np.ndarray:
        L = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
        w = np.clip((L - 0.88) / 0.12, 0.0, 1.0)
        w = (w * w * (3.0 - 2.0 * w)) * strength
        w = w[:, :, np.newaxis]
        return (img * (1.0 - w) + L[:, :, np.newaxis] * w).astype(np.float32)
