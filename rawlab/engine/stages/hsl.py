"""Stage hsl (order=52) —— 人工 HSL 八色段调整 (gamma_rgb → gamma_rgb)。

区别于 DCP 自动 HueSatMap/LookTable (huesat stage): 本 Stage 是**用户可调
人工 HSL**, 8 个色段各自可调色相/饱和/明度。默认关闭 (enabled=False), 由
后续集成/预设显式开启。纯数学位于 engine/hsl.py。
"""
from __future__ import annotations

import json

import numpy as np

from ..core import Stage, StageContext, register_stage
from ..core import DOMAIN_GAMMA_RGB
from ..hsl import hsl_adjust_rgb, DEFAULT_BANDS


@register_stage("hsl", order=52,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class HslStage(Stage):
    name = "hsl"

    param_schema = {
        "enabled": {"type": "bool"},
        "bands": {"type": "float_or_str"},     # 8 band dict 列表 (或 JSON 字符串), None→默认全 0
        "smooth": {"type": "float", "min": 0.0, "max": 1.0},
    }

    def default_params(self):
        return {"enabled": False, "bands": None, "smooth": 1.0}

    def wants(self, ctx: StageContext) -> bool:
        # 仅 enabled=True 时进入 (bands 缺省/全 0 时 process 恒等, 无副作用)
        return bool(self.p(ctx, "enabled", False))

    def _resolve_bands(self, ctx):
        bands = self.p(ctx, "bands", None)
        if bands is None:
            return DEFAULT_BANDS
        if isinstance(bands, str):
            bands = json.loads(bands)
        if not isinstance(bands, (list, tuple)):
            raise ValueError(f"hsl bands 需为 list[dict] 或 JSON 数组 (实际 {type(bands).__name__})")
        return list(bands)

    def process(self, ctx: StageContext) -> None:
        bands = self._resolve_bands(ctx)
        smooth = float(self.p(ctx, "smooth", 1.0))
        img = np.clip(ctx.image, 0.0, 1.0)
        out = hsl_adjust_rgb(img, bands, smooth=smooth)
        ctx.set_image(out, DOMAIN_GAMMA_RGB)
        ctx.results[-1].metrics["hsl_bands"] = len(bands)
