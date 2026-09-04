"""Stage hsl (order=52) —— 人工 HSL 八色段调整 (gamma_rgb → gamma_rgb)。

区别于 DCP 自动 HueSatMap/LookTable (huesat stage): 本 Stage 是**用户可调
人工 HSL**, 8 个色段各自可调色相/饱和/明度。默认关闭 (enabled=False), 由
后续集成/预设显式开启。纯数学位于 engine/hsl.py。
"""
from __future__ import annotations

import json

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB
from ..core.hsl import hsl_adjust_rgb, DEFAULT_BANDS
from ..core.hsl_oklch import oklch_adjust_rgb, DEFAULT_BANDS_OKLCH


@register_stage("hsl", order=52,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class HslStage(Stage):
    name = "hsl"

    param_schema = {
        "enabled": {"type": "bool"},
        "bands": {"type": "float_or_str"},     # 8 band dict 列表 (或 JSON 字符串), None→默认全 0
        "smooth": {"type": "float", "min": 0.0, "max": 1.0},
        # 编辑域 (设计 §1.2/§2.2): "hsv"(缺省, 旧内核) | "oklch"。决定**无 domain 键**
        # band 的归属; band 级 "domain" 键逐段覆盖。缺省值保证存量卡逐位不变 (A1)。
        "color_domain": {"type": "str", "choices": ["hsv", "oklch"]},
    }

    def default_params(self):
        return {"enabled": False, "bands": None, "smooth": 1.0, "color_domain": "hsv"}

    def wants(self, ctx: StageContext) -> bool:
        # 仅 enabled=True 时进入 (bands 缺省/全 0 时 process 恒等, 无副作用)
        return bool(self.p(ctx, "enabled", False))

    def _resolve_bands(self, ctx, domain: str = "hsv"):
        bands = self.p(ctx, "bands", None)
        if bands is None:
            return DEFAULT_BANDS_OKLCH if domain == "oklch" else DEFAULT_BANDS
        if isinstance(bands, str):
            bands = json.loads(bands)
        if not isinstance(bands, (list, tuple)):
            raise ValueError(f"hsl bands 需为 list[dict] 或 JSON 数组 (实际 {type(bands).__name__})")
        return list(bands)

    def process(self, ctx: StageContext) -> None:
        domain = str(self.p(ctx, "color_domain", "hsv")).strip().lower()
        if domain not in ("hsv", "oklch"):
            raise ValueError(f"hsl color_domain 需为 'hsv'|'oklch' (实际 {domain!r})")
        bands = self._resolve_bands(ctx, domain)
        smooth = float(self.p(ctx, "smooth", 1.0))
        img = np.clip(ctx.image, 0.0, 1.0)
        hsv_bands, oklch_bands = _split_bands_by_domain(bands, domain)
        if not oklch_bands:
            # 旧 hsv 路径原样 (含空列表/全 0 快路径逐位 no-op) —— 存量卡零迁移 (A1)
            out = hsl_adjust_rgb(img, hsv_bands, smooth=smooth)
        else:
            if hsv_bands:
                img = hsl_adjust_rgb(img, hsv_bands, smooth=smooth)
            out = oklch_adjust_rgb(img, oklch_bands, smooth=smooth)
        ctx.set_image(out, DOMAIN_GAMMA_RGB)
        ctx.results[-1].metrics["hsl_bands"] = len(bands)


def _split_bands_by_domain(bands, default_domain: str):
    """按 band 级 domain 键 (缺省用 Stage 级 color_domain) 分组; 非法值 raise。"""
    hsv, oklch = [], []
    for band in bands:
        d = str(band.get("domain", default_domain)).strip().lower()
        if d == "hsv":
            hsv.append(band)
        elif d == "oklch":
            oklch.append(band)
        else:
            raise ValueError(f"hsl band domain 需为 'hsv'|'oklch' (实际 {d!r})")
    return hsv, oklch
