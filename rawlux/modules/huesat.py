"""Stage huesat (order=25) —— DCP HueSatMap + LookTable 应用 (linear_rgb → linear_rgb)。

基座的一部分: HueSatMap 是 Adobe Camera 渲染链路中"相机观感"的主要载体
(色相偏移/饱和度/明度重映射)。LookTable 在多数 DCP 中缺失 (本机无),
有数据时同域应用。

域修复 (2026-08, 见 dsh-plan-task-p4/research/hsmap-domain.md):
  Adobe DNG SDK 在**线性 ProPhoto(D50)、影调曲线之前**应用 HueSatMap/LookTable,
  而非旧实现的 gamma_rgb (sRGB 编码、tone 之后)。故:
  - order 从 40 → 25 (tone=30 之前, 影调曲线之前);
  - domain_in/out 从 gamma_rgb → linear_rgb (阶段内做 sRGB↔ProPhoto 往返)。

参数:
  enabled   启用 (默认 False, 见下; 无数据时自动直通)
  strength  强度 0..1 (0=不套, 1=完整效果; 线性混合到恒等)
  warm_highlight_sat  局部暖色高光饱和 (sat_scale, 1.0=关; >1 增强, 默认 1.0)
                      —— 问题清单 A1: 烟花/暖灯橙黄局部补饱和, 不写死全局
                      HueSatMap (5236 高光锚点安全)。

默认关闭的依据 (2026-08-16 A/B 实测, 6 张室内 NEF vs 相机预览):
  开启 HueSatMap 后 L2 反而变差: d_a +2.33→+4.67, d_b -2.50→-4.17,
  中性区 neu_b -8.5→-15.0。原因: 基座目标 = 复现**相机预览** (机内
  Picture Control 链路), 而 DCP HueSatMap 是 **Adobe Camera Raw 的观感**
  (hue twist ±37°, 饱和/明度重映射), 两者并不等价。HueSatMap 保留为
  "Adobe look" 可选开关 (后续作为 preset 提供), 基座默认关闭。
"""
from __future__ import annotations

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_LINEAR_RGB
from ..core.huesat import (apply_hue_sat_map, apply_look_table,
                     apply_hue_sat_map_prophoto, apply_look_table_prophoto,
                     apply_local_warm_sat, get_hue_sat_table, get_look_table)


@register_stage("huesat", order=25,
                domain_in=DOMAIN_LINEAR_RGB, domain_out=DOMAIN_LINEAR_RGB)
class HueSatStage(Stage):
    name = "huesat"

    param_schema = {
        "enabled": {"type": "bool"},
        "strength": {"type": "float", "min": 0.0, "max": 1.0},
        "warm_highlight_sat": {"type": "float", "min": 1.0, "max": 5.0},
        "warm_sat_spot_scale": {"type": "float", "min": 1.0, "max": 5.0},
        "warm_sat_hue_center": {"type": "float", "min": 0.0, "max": 360.0},
        "warm_sat_hue_halfwidth": {"type": "float", "min": 1.0, "max": 90.0},
        "warm_sat_val_min": {"type": "float", "min": 0.0, "max": 1.0},
        "warm_sat_coverage_max": {"type": "float", "min": 0.0, "max": 1.0},
    }

    def default_params(self):
        return {"enabled": False, "strength": 1.0}

    def wants(self, ctx: StageContext) -> bool:
        prof = ctx.prof
        if float(self.p(ctx, "warm_highlight_sat", 1.0)) > 1.0:
            return prof is not None
        if not bool(self.p(ctx, "enabled")):
            return False
        if prof is None:
            return False
        hs_table, _, _ = get_hue_sat_table(prof)
        lt_table, _, _ = get_look_table(prof)
        return hs_table is not None or lt_table is not None

    def process(self, ctx: StageContext) -> None:
        strength = float(self.p(ctx, "strength"))
        warm_scale = float(self.p(ctx, "warm_highlight_sat", 1.0))
        img = ctx.image
        cam_raw = ctx.state.get("cam_raw", ctx.state.get("cam_wb"))
        has_fm = bool(getattr(ctx.prof, "forward_matrix1", None))
        use_dng_path = bool(ctx.state.get("use_dng_huesat_path", False))
        if (use_dng_path and cam_raw is not None and ctx.prof is not None
                and has_fm):
            # DNG SDK 同源应用域: 未乘 WB 的相机 RGB → ForwardMatrix ProPhoto。
            # SDK 顺序: HueSatMap -> ExposureRamp -> LookTable -> RGBTone -> final。
            from ..core.color import (cam_wb_to_prophoto,
                                 dng_linear_prophoto_to_srgb)
            from ..core.tone import apply_rgb_tone, exposure_ramp
            pp = cam_wb_to_prophoto(cam_raw, ctx.prof, ctx.state.get("wb"))
            if bool(self.p(ctx, "enabled")):
                pp = apply_hue_sat_map_prophoto(pp, ctx.prof, strength=strength)
            baseline_ev = ctx.state.get("dng_baseline_ev")
            if baseline_ev is not None:
                pp = exposure_ramp(pp, float(baseline_ev))
            if bool(self.p(ctx, "enabled")):
                pp = apply_look_table_prophoto(pp, ctx.prof, strength=strength)
            ctx.state["dng_prophoto_pre_tone"] = pp
            tone_table = ctx.state.get("dng_tone_table")
            if bool(ctx.state.get("dng_apply_tone")) and tone_table is not None:
                pp = apply_rgb_tone(pp, tone_table)
            img = dng_linear_prophoto_to_srgb(pp)
        elif bool(self.p(ctx, "enabled")) and ctx.prof is not None:
            img = apply_hue_sat_map(img, ctx.prof, strength=strength)
            img = apply_look_table(img, ctx.prof, strength=strength)
        if warm_scale > 1.0:
            img = apply_local_warm_sat(
                img, sat_scale=warm_scale,
                spot_sat_scale=self.p(ctx, "warm_sat_spot_scale", None),
                hue_center=float(self.p(ctx, "warm_sat_hue_center", 22.5)),
                hue_halfwidth=float(self.p(ctx, "warm_sat_hue_halfwidth", 17.5)),
                val_min=float(self.p(ctx, "warm_sat_val_min", 0.6)),
                coverage_max=float(self.p(ctx, "warm_sat_coverage_max", 0.0015)))
        # 线性域: 只钳下界, 高光 (>1) 留给 tone (影调曲线) 收口
        ctx.set_image(np.clip(img, 0.0, None).astype(np.float32), DOMAIN_LINEAR_RGB)
        hs_table = dims = lt_table = ldims = None
        if ctx.prof is not None:
            hs_table, dims, _ = get_hue_sat_table(ctx.prof)
            lt_table, ldims, _ = get_look_table(ctx.prof)
        ctx.results[-1].metrics = {
            "hue_sat": bool(hs_table is not None),
            "hue_sat_dims": list(dims) if dims else None,
            "look_table": bool(lt_table is not None),
            "local_warm_sat": warm_scale,
        }
