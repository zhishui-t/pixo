"""Stage split_tone (order=54) —— 分离色调 (gamma_rgb → gamma_rgb)。

用户可调阴影/高光双色染色 (split toning)。默认关闭 (enabled=False), 由集成/
预设显式开启。纯数学位于 engine/split_tone.py (split_tone_rgb) 与
engine/split_tone_oklab.py (split_tone_oklab_rgb, 设计 §2.3)。

编辑域开关 (设计 §1.2, 与 HslStage 同枚举): color_domain = "hsv"(缺省, 旧
内核, 存量预设/卡片逐位不变) | "oklch" (OKLab 域染色, 近白自然低 C)。参数名
不变, UI/胶片卡零改动。
"""
from __future__ import annotations

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB
from ..core.split_tone import split_tone_rgb
from ..core.split_tone_oklab import split_tone_oklab_rgb


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
        # 编辑域 (设计 §1.2/§2.3): "hsv"(缺省, 旧内核) | "oklch"
        "color_domain": {"type": "str", "choices": ["hsv", "oklch"]},
    }

    def default_params(self):
        return {"enabled": False,
                "shadows_hue": 45.0, "shadows_sat": 0.0,
                "highlights_hue": 210.0, "highlights_sat": 0.0,
                "balance": 0.5, "strength": 1.0,
                "color_domain": "hsv"}

    def wants(self, ctx: StageContext) -> bool:
        # 仅 enabled=True 时进入 (全 0 饱和时 process 恒等, 无副作用)
        return bool(self.p(ctx, "enabled", False))

    def process(self, ctx: StageContext) -> None:
        domain = str(self.p(ctx, "color_domain", "hsv")).strip().lower()
        if domain not in ("hsv", "oklch"):
            raise ValueError(
                f"split_tone color_domain 需为 'hsv'|'oklch' (实际 {domain!r})")
        img = np.asarray(ctx.image, dtype=np.float32)
        shadows_hue = float(self.p(ctx, "shadows_hue", 45.0))
        shadows_sat = float(self.p(ctx, "shadows_sat", 0.0))
        highlights_hue = float(self.p(ctx, "highlights_hue", 210.0))
        highlights_sat = float(self.p(ctx, "highlights_sat", 0.0))
        if domain == "oklch":
            out = split_tone_oklab_rgb(
                img, shadows_hue, shadows_sat, highlights_hue, highlights_sat,
                balance=float(self.p(ctx, "balance", 0.5)),
                strength=float(self.p(ctx, "strength", 1.0)))
        else:
            # 旧 hsv 路径原样 (数值逐位不变 —— 存量预设零迁移, A1 同纪律)
            out = split_tone_rgb(
                img, shadows_hue, shadows_sat, highlights_hue, highlights_sat,
                balance=float(self.p(ctx, "balance", 0.5)),
                strength=float(self.p(ctx, "strength", 1.0)))
        ctx.set_image(out, DOMAIN_GAMMA_RGB)
        ctx.results[-1].metrics["split_tone_enabled"] = True
        ctx.results[-1].metrics["split_tone_balance"] = float(self.p(ctx, "balance", 0.5))


__all__ = ["SplitToneStage"]
