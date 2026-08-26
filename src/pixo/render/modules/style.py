"""Stage stylize (order=60) —— 风格化 (gamma_rgb → gamma_rgb)。

复用 render.core.lut.LUT3D (sRGB gamma 域查表, 性能已验证 0.21s)。
LUT 通过 params["lut"] 传入 (LUT3D 实例) 或 params["lut_path"] 惰性加载。

参数:
  lut         LUT3D 实例 (优先)
  lut_path    .cube 路径 (无实例时加载)
  lut_strength  强度 0..1 (0=不套)
"""
from __future__ import annotations

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB


@register_stage("stylize", order=60,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class StylizeStage(Stage):
    name = "stylize"

    param_schema = {
        # lut 为 LUT3D 实例 (内存对象, 非 JSON 标量), 类型 any = 宽松放行
        # (仅声明占位, 使 get_param_schema("stylize") 覆盖全部 process 读取键)。
        "lut": {"type": "any"},
        "lut_path": {"type": "str"},
        "lut_strength": {"type": "float", "min": 0.0, "max": 1.0},
    }

    def default_params(self):
        return {"lut": None, "lut_path": None, "lut_strength": 1.0}

    def _get_lut(self, ctx: StageContext):
        lut = self.p(ctx, "lut")
        if lut is not None:
            return lut
        path = self.p(ctx, "lut_path")
        if not path:
            return None
        # 统一走 core.lut 的共享 LUT 缓存（锁 + 上限 4 表的 LRU）：
        # 此前类属性 _loaded 与 core 侧 _cache 双套无锁无上限（各 ~50MB/表）。
        from ..core.lut import load_lut_path
        return load_lut_path(path)

    def wants(self, ctx: StageContext) -> bool:
        return self._get_lut(ctx) is not None

    def process(self, ctx: StageContext) -> None:
        lut = self._get_lut(ctx)
        strength = float(self.p(ctx, "lut_strength"))
        if lut is None or strength <= 0.0:
            return
        u8 = (np.clip(ctx.image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        out8 = lut.apply(u8, strength=strength)
        ctx.set_image(out8.astype(np.float32) / 255.0, DOMAIN_GAMMA_RGB)
