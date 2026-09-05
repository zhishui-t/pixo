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
  color_domain  "hsv"(缺省, DCP HSM 的 HSV 三线性链, 行为不变) | "oklch"
                (OKLCh 域连续形变, core.huesat_oklch; t17 点云接线)。
                use_dng_huesat_path (DNG SDK 基准复刻) 优先级更高, 不受本参数
                影响 —— oklch 分派只替代常规 gamma 分支。
  oklch_points_file  点云 JSON 路径; 空 (缺省) = 按 DCP 名自动推导
                configs/color/hsm_oklch_<slug>.json (slug = 名字非字母数字
                转下划线), 文件不存在 → 回退 hsv 链并告警一次。
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

import pathlib

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_LINEAR_RGB
from ..core.huesat import (apply_hue_sat_map, apply_look_table,
                     apply_hue_sat_map_prophoto, apply_look_table_prophoto,
                     apply_local_warm_sat, get_hue_sat_table, get_look_table)
from ..core.huesat_oklch import OklchDeform, apply_oklch_deform,     is_identity_deform, load_oklch_deform

# oklch 点云 spec 缓存 (路径 → OklchDeform; 栅格化按内容哈希进程内复用)
_OKLCH_SPEC_CACHE: dict = {}
_OKLCH_MISSING_WARNED: set = set()


def _resolve_oklch_spec(prof, file_param: str | None) -> OklchDeform | None:
    """color_domain=oklch 的点云解析: 显式路径 → 按 DCP 名推导缺省路径;
    文件缺失/非法 → None (回退 hsv 链, 每路径只告警一次)。"""
    import re as _re
    candidates: list[str] = []
    if file_param:
        candidates.append(str(file_param))
    name = str(getattr(prof, "name", "") or "")
    if name:
        stem = _re.sub(r"\.[a-z]+$", "", name, flags=_re.I)
        slug = _re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
        candidates.append(str(
            pathlib.Path(__file__).resolve().parents[3] / "configs" / "color"
            / f"hsm_oklch_{slug}.json"))
    from ..core.calibration_store import load_json
    for cand in candidates:
        p = pathlib.Path(cand)
        if not p.is_file():
            continue
        spec = _OKLCH_SPEC_CACHE.get(cand)
        if spec is None:
            spec = load_oklch_deform(p)
            _OKLCH_SPEC_CACHE[cand] = spec
        return spec
    if candidates and candidates[0] not in _OKLCH_MISSING_WARNED:
        _OKLCH_MISSING_WARNED.add(candidates[0])
        import logging
        logging.getLogger(__name__).warning(
            "[huesat] color_domain=oklch 但点云文件不存在: %s (回退 hsv 链)",
            candidates[0])
    return None


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
        "color_domain": {"type": "str", "choices": ["hsv", "oklch"]},
        "oklch_points_file": {"type": "str"},
    }

    def default_params(self):
        return {"enabled": False, "strength": 1.0, "color_domain": "hsv",
                "oklch_points_file": ""}

    def wants(self, ctx: StageContext) -> bool:
        prof = ctx.prof
        if float(self.p(ctx, "warm_highlight_sat", 1.0)) > 1.0:
            return prof is not None
        if not bool(self.p(ctx, "enabled")):
            return False
        if prof is None:
            return False
        if self._oklch_domain(ctx, prof):
            spec = _resolve_oklch_spec(prof, self.p(ctx, "oklch_points_file",
                                                    None))
            return spec is not None and not is_identity_deform(spec)
        hs_table, _, _ = get_hue_sat_table(prof)
        lt_table, _, _ = get_look_table(prof)
        return hs_table is not None or lt_table is not None

    def _oklch_domain(self, ctx: StageContext, prof) -> bool:
        """color_domain=oklch 且非 DNG 基准路径 (该路径为相机基准复刻,
        不受 color_domain 影响)。非法值 raise (与 hsl Stage 同口径)。"""
        domain = str(self.p(ctx, "color_domain", "hsv")).strip().lower()
        if domain not in ("hsv", "oklch"):
            raise ValueError(
                f"huesat color_domain 需为 'hsv'|'oklch' (实际 {domain!r})")
        return domain == "oklch" and not bool(
            ctx.state.get("use_dng_huesat_path", False))

    def process(self, ctx: StageContext) -> None:
        strength = float(self.p(ctx, "strength"))
        warm_scale = float(self.p(ctx, "warm_highlight_sat", 1.0))
        img = ctx.image
        cam_raw = ctx.state.get("cam_raw", ctx.state.get("cam_wb"))
        has_fm = bool(getattr(ctx.prof, "forward_matrix1", None))
        use_dng_path = bool(ctx.state.get("use_dng_huesat_path", False))
        oklch_branch = (self._oklch_domain(ctx, ctx.prof)
                        and ctx.prof is not None)
        oklch_spec = (_resolve_oklch_spec(ctx.prof, self.p(
            ctx, "oklch_points_file", None)) if oklch_branch else None)
        if oklch_branch and oklch_spec is None:
            oklch_branch = False      # 点云缺失已告警, 回退 hsv 链
        if (use_dng_path and cam_raw is not None and ctx.prof is not None
                and has_fm):
            # DNG SDK 同源应用域: 未乘 WB 的相机 RGB → ForwardMatrix ProPhoto。
            # SDK 顺序: HueSatMap -> ExposureRamp -> LookTable -> RGBTone -> final。
            from ..core.color import (cam_wb_to_prophoto,
                                 linear_prophoto_to_srgb)
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
            img = linear_prophoto_to_srgb(pp)
        elif (oklch_branch and bool(self.p(ctx, "enabled"))):
            # OKLCh 域连续形变 (t17 点云): 输入线性 sRGB → gamma 域 →
            # OKLCh 形变 → gamma → 解码回线性 (stage 域接口不变)。
            from ..core.tone import srgb_decode, srgb_encode
            gamma = srgb_encode(np.clip(np.asarray(img, np.float64), 0.0, None))
            deformed = apply_oklch_deform(gamma, oklch_spec, strength=strength)
            img = srgb_decode(deformed)
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
