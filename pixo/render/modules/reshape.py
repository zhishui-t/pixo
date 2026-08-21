"""engine.stages.reshape —— 影调重塑层 (Phase 1.5 实装)。

注册 5 个观感 Stage (gamma_rgb → gamma_rgb), order 45..49:
  - dehaze    (45) 去雾/通透     [实装]
  - clarity   (46) 局部对比/质感 [实装]
  - denoise   (47) 降噪          [占位, refine 已有色度降噪]
  - sharpen   (48) 锐化          [占位, refine 已有锐化]
  - vibrance  (49) 自然饱和度    [占位, colorcal 已有 vibrance/saturation]

设计约定:
  - 默认 enabled=False (基座 = 复现相机, 观感层显式开启);
  - "观感增强" 预设 (presets/enhance.json) 显式开启 dehaze/clarity + filmic +
    vibrance/saturation/sharpen, 目标从"像相机"切换为"好看/通透/有质感"。
"""
from __future__ import annotations

import cv2
import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB
from ..core.enhance import clarity as _clarity
from ..core.enhance import dehaze as _dehaze


@register_stage("dehaze", order=45,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class DehazeStage(Stage):
    """去雾/通透 (暗通道先验简化版, engine.enhance.dehaze)。

    参数: enabled(默认 False), strength(默认 0.5), radius(暗通道窗口, 默认 15)。
    """

    param_schema = {
        "enabled": {"type": "bool"},
        "strength": {"type": "float", "min": 0.0, "max": 1.0},
        "radius": {"type": "float", "min": 1.0, "max": 60.0},
    }

    def default_params(self):
        return {"enabled": False, "strength": 0.5, "radius": 15.0}

    def wants(self, ctx: StageContext) -> bool:
        return bool(self.p(ctx, "enabled", False))

    def process(self, ctx: StageContext) -> None:
        s = float(self.p(ctx, "strength"))
        r = int(self.p(ctx, "radius"))
        if s <= 0.0:
            return
        img = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)
        out = _dehaze(img, strength=s, radius=r)
        ctx.set_image(out, DOMAIN_GAMMA_RGB)


@register_stage("clarity", order=46,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class ClarityStage(Stage):
    """清晰度/局部对比 (中频带通增强, engine.enhance.clarity)。

    基座默认开启 (enabled=True, strength=0.3): "质感"是基础画质属性而非风格;
    默认管线已包含本 Stage (DEFAULT_STAGES)。dehaze 仍默认关 (仅真雾照片用)。
    """

    param_schema = {
        "enabled": {"type": "bool"},
        "strength": {"type": "float", "min": 0.0, "max": 1.0},
    }

    def default_params(self):
        return {"enabled": True, "strength": 0.3}

    def wants(self, ctx: StageContext) -> bool:
        return bool(self.p(ctx, "enabled", False))

    def process(self, ctx: StageContext) -> None:
        s = float(self.p(ctx, "strength"))
        if s <= 0.0:
            return
        img = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)
        is_preview = (bool(ctx.config.get("preview")) or bool(ctx.config.get("long_edge"))
                      or bool(ctx.config.get("decode_mode")))
        if is_preview:
            # P1 A/B 微调: 预览 clarity 强度封顶 0.25, 压低低分辨率 r/b p99。
            s = min(s, 0.25)
            # P1 预览：清晰度在降采样分辨率计算后上采样（设计 §4.4 降采样口径）。
            # long1024 用 1/2 保质量；long2048 用 1/4 保性能。
            h, w = img.shape[:2]
            long_edge = int(ctx.config.get("long_edge", 0) or 0)
            div = 2 if long_edge <= 1024 else 4
            small = cv2.resize(img, (max(w // div, 4), max(h // div, 4)),
                               interpolation=cv2.INTER_AREA)
            try:
                from .._native import clarity_apply
                from ..core.enhance import _gray
                g = _gray(small)
                small_blur = cv2.GaussianBlur(g, (0, 0), 0.8)
                large_blur = cv2.GaussianBlur(g, (0, 0), 3.0)
                out_small = clarity_apply(small, s, g, small_blur, large_blur)
            except Exception:
                out_small = _clarity(small, strength=s)
            out = cv2.resize(out_small, (w, h), interpolation=cv2.INTER_LINEAR)
        else:
            # 生产全质量路径：保持原分辨率，不做预览降采样。
            out = _clarity(img, strength=s)
        ctx.set_image(out, DOMAIN_GAMMA_RGB)


@register_stage("denoise", order=47,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class DenoiseStage(Stage):
    """降噪 (占位: refine 已含色度降噪)。"""

    def wants(self, ctx: StageContext) -> bool:
        return False

    def process(self, ctx: StageContext) -> None:
        return


@register_stage("sharpen", order=48,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class SharpenStage(Stage):
    """锐化 (占位: refine 已含灰空间锐化)。"""

    def wants(self, ctx: StageContext) -> bool:
        return False

    def process(self, ctx: StageContext) -> None:
        return


@register_stage("vibrance", order=49,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class VibranceStage(Stage):
    """自然饱和度 (占位: colorcal 已含 vibrance/saturation)。"""

    def wants(self, ctx: StageContext) -> bool:
        return False

    def process(self, ctx: StageContext) -> None:
        return
