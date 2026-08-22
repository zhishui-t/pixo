"""Stage calibration (order=51) —— 用户可调 RGB 校准 (gamma_rgb → gamma_rgb)。

与 colorcal (场景自适应中性轴校准, order=50) 解耦的**独立用户校准** Stage:
  shadow_tint + 三原色 (red/green/blue) hue/sat。默认关闭 (enabled=False)。
纯数学位于 engine/usercal.py。
"""
from __future__ import annotations

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB
from ..core.usercal import apply_usercal_rgb


@register_stage("calibration", order=51,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class CalibrationStage(Stage):
    name = "calibration"

    param_schema = {
        "enabled": {"type": "bool"},
        "shadow_tint": {"type": "float", "min": -100.0, "max": 100.0},
        "red_hue": {"type": "float", "min": -180.0, "max": 180.0},
        "red_sat": {"type": "float", "min": -100.0, "max": 100.0},
        "green_hue": {"type": "float", "min": -180.0, "max": 180.0},
        "green_sat": {"type": "float", "min": -100.0, "max": 100.0},
        "blue_hue": {"type": "float", "min": -180.0, "max": 180.0},
        "blue_sat": {"type": "float", "min": -100.0, "max": 100.0},
    }

    def default_params(self):
        return {"enabled": False, "shadow_tint": 0.0,
                "red_hue": 0.0, "red_sat": 0.0,
                "green_hue": 0.0, "green_sat": 0.0,
                "blue_hue": 0.0, "blue_sat": 0.0}

    def wants(self, ctx: StageContext) -> bool:
        if not bool(self.p(ctx, "enabled", False)):
            return False
        params = ("shadow_tint", "red_hue", "red_sat",
                  "green_hue", "green_sat", "blue_hue", "blue_sat")
        return any(float(self.p(ctx, k)) != 0.0 for k in params)

    def process(self, ctx: StageContext) -> None:
        out = apply_usercal_rgb(
            ctx.image,
            shadow_tint=self.p(ctx, "shadow_tint"),
            red_hue=self.p(ctx, "red_hue"), red_sat=self.p(ctx, "red_sat"),
            green_hue=self.p(ctx, "green_hue"), green_sat=self.p(ctx, "green_sat"),
            blue_hue=self.p(ctx, "blue_hue"), blue_sat=self.p(ctx, "blue_sat"),
        )
        ctx.set_image(out, DOMAIN_GAMMA_RGB)
