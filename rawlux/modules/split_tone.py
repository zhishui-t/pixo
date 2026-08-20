"""Stage split_tone (order=54) —— 分离色调 (gamma_rgb → gamma_rgb)。

用户可调阴影/高光双色染色 (split toning)。默认关闭 (enabled=False), 由集成/
预设显式开启。纯数学位于 engine/split_tone.py (split_tone_rgb)。
"""
from __future__ import annotations

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB
from ..core.split_tone import split_tone_rgb


@register_stage("split_tone", order=54,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class SplitToneStage(Stage):
    name = "split_tone"

    param_schema = {
        "enabled": {"type": "bool"},
        "shadows_hue": {"type": "float", "min": 0.0, "max": 360.0},
        "shadows_sat": {"type": "float", "min": 0.0, "max": 100.0},
        "highlights_hue": {"type": "float", "min": 0.0, "max": 360.0},
        "highlights_sat": {"type": "float", "min": 0.0, "max": 100.0},
        "balance": {"type": "float", "min": 0.0, "max": 1.0},
        "strength": {"type": "float", "min": 0.0, "max": 1.0},
    }

    def default_params(self):
        return {"enabled": False,
                "shadows_hue": 45.0, "shadows_sat": 0.0,
                "highlights_hue": 210.0, "highlights_sat": 0.0,
                "balance": 0.5, "strength": 1.0}

    def wants(self, ctx: StageContext) -> bool:
        # 仅 enabled=True 时进入 (全 0 饱和时 process 恒等, 无副作用)
        return bool(self.p(ctx, "enabled", False))

    def process(self, ctx: StageContext) -> None:
        img = np.asarray(ctx.image, dtype=np.float32)
        out = split_tone_rgb(
            img,
            float(self.p(ctx, "shadows_hue", 45.0)),
            float(self.p(ctx, "shadows_sat", 0.0)),
            float(self.p(ctx, "highlights_hue", 210.0)),
            float(self.p(ctx, "highlights_sat", 0.0)),
            balance=float(self.p(ctx, "balance", 0.5)),
            strength=float(self.p(ctx, "strength", 1.0)),
        )
        ctx.set_image(out, DOMAIN_GAMMA_RGB)
        ctx.results[-1].metrics["split_tone_enabled"] = True
        ctx.results[-1].metrics["split_tone_balance"] = float(self.p(ctx, "balance", 0.5))


__all__ = ["SplitToneStage"]
