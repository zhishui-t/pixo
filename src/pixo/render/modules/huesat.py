"""Stage huesat (order=25) —— DCP HueSatMap/LookTable 的 OKLCh 形变应用
(linear_rgb → linear_rgb) + 局部暖色高光饱和。

HSM/Look 语义载体: OKLCh 域连续形变 (core.huesat_oklch, t17 点云接线;
路线图阶段二起用 OKLCh 连续形变替代 DCP HSM)。点云经
scripts/convert_hsm_to_oklch.py 从 DCP 表数据离线转译
(configs/color/hsm_oklch_<slug>.json, slug = DCP 名 token 匹配)。

R11 A 轨退役: 旧 "hsv" 域执行链 (HSV 三线性查表 + DNG SDK 基准复刻
分支) 已整体删除 —— color_domain 现仅 "oklch" 有效; "hsv" 取值保留于
schema 仅为历史配置兼容, 语义 = HSM 不应用 (warn-once 后 no-op)。
无匹配点云/DCP 无表: 同为显式 no-op (warn-once), 不再回退任何旧链。

域修复 (2026-08, 见 dsh-plan-task-p4/research/hsmap-domain.md):
  HueSatMap 应在**线性 ProPhoto(D50)、影调曲线之前**应用; 本 stage 的
  底座渲染路径 (pipeline/base.py) 即该口径 (prophoto 包装 → core/tone.py
  clean-room 4096 表插值)。本 Stage 的 oklch 分支: 线性 sRGB → gamma 域 →
  OKLCh 形变 → 解码回线性 (域接口不变)。

参数:
  enabled   启用 (默认 False; 无点云/无表时自动直通)
  strength  强度 0..1 (0=不套, 1=完整效果; 线性混合到恒等)
  color_domain  "oklch"(有效执行域) | "hsv"(历史取值, no-op)
  oklch_points_file  点云 JSON 路径; 空 (缺省) = 按 DCP 名自动推导
                configs/color/hsm_oklch_<slug>.json; 无匹配 → warn-once
                + no-op (R11 起不再回退旧链)。
  warm_highlight_sat  局部暖色高光饱和 (sat_scale, 1.0=关; >1 增强, 默认 1.0)
                      —— 问题清单 A1: 烟花/暖灯橙黄局部补饱和, 不写死全局
                      HueSatMap (5236 高光锚点安全)。

默认关闭的依据 (2026-08-16 A/B 实测, 6 张室内 NEF vs 相机预览):
  开启 HueSatMap 后 L2 反而变差: d_a +2.33→+4.67, d_b -2.50→-4.17,
  中性区 neu_b -8.5→-15.0。原因: 基座目标 = 复现**相机预览** (机内
  Picture Control 链路), 而 DCP HueSatMap 是 **Adobe Camera Raw 的观感**
  (hue twist ±37°, 饱和/明度重映射), 两者并不等价。HueSatMap 保留为
  可选 look 开关, 基座默认关闭。
"""
from __future__ import annotations

import pathlib

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_LINEAR_RGB
from ..core.huesat import (apply_local_warm_sat, get_hue_sat_table,
                           get_look_table)
from ..core.huesat_oklch import (OklchDeform, apply_oklch_deform,
                                 is_identity_deform, load_oklch_deform)

# oklch 点云 spec 缓存 (路径 → OklchDeform; 栅格化按内容哈希进程内复用)
_OKLCH_SPEC_CACHE: dict = {}
_OKLCH_MISSING_WARNED: set = set()


def _slug_tokens(s: str) -> list:
    import re as _re
    return [t for t in _re.split(r"[^a-z0-9]+", s.lower()) if t]


def _is_subseq(small: list, big: list) -> bool:
    """token 子序列判定 (prof.name 的 slug tokens ⊆ 文件名 tokens; t17 点云
    文件名来自 DCP 文件名, 比 prof.name 多厂商标记词, 如 LR Baseline vs
    LR Adobe Standard Baseline)。"""
    it = iter(big)
    return all(tok in it for tok in small)


def _default_oklch_points(prof) -> list:
    """按 DCP 名推导点云候选: configs/color/hsm_oklch_*.json 中文件名 token
    包含 prof.name token 子序列者 (多候选取 token 数最多 —— 名字最长者
    最特异)。"""
    slug = "_".join(_slug_tokens(str(getattr(prof, "name", "") or "")))
    if not slug:
        return []
    root = pathlib.Path(__file__).resolve().parents[4] / "configs" / "color"
    prof_toks = _slug_tokens(str(getattr(prof, "name", "")))
    matches = []
    for f in sorted(root.glob("hsm_oklch_*.json")):
        file_toks = _slug_tokens(f.stem.replace("hsm_oklch_", ""))
        if _is_subseq(prof_toks, file_toks):
            matches.append((len(file_toks), f))
    matches.sort(key=lambda t: (-t[0], t[1].name))
    return [str(f) for _, f in matches]


def _resolve_oklch_spec(prof, file_param: str | None) -> OklchDeform | None:
    """color_domain=oklch 的点云解析: 显式路径 → 按 DCP 名 token 子序列
    匹配缺省路径; 无匹配 → None (HSM 不应用, warn-once; R11 起不再回退
    旧链 —— 全部含表 DCP 均有点云, 此路径仅防御性存在)。"""
    candidates: list = []
    if file_param:
        candidates.append(str(file_param))
    else:
        candidates.extend(_default_oklch_points(prof))
    if not candidates:
        prof_key = str(getattr(prof, "name", "") or "<noname>")
        if prof_key not in _OKLCH_MISSING_WARNED:
            _OKLCH_MISSING_WARNED.add(prof_key)
            import logging
            logging.getLogger(__name__).warning(
                "[huesat] color_domain=oklch 但未找到匹配的 HSM→OKLCh 点云"
                " (prof=%r; HSM 不应用)", prof_key)
        return None
    for cand in candidates:
        p = pathlib.Path(cand)
        if not p.is_file():
            continue
        spec = _OKLCH_SPEC_CACHE.get(cand)
        if spec is None:
            spec = load_oklch_deform(p)
            _OKLCH_SPEC_CACHE[cand] = spec
        return spec
    if tuple(candidates) not in _OKLCH_MISSING_WARNED:
        _OKLCH_MISSING_WARNED.add(tuple(candidates))
        import logging
        logging.getLogger(__name__).warning(
            "[huesat] color_domain=oklch 但点云文件不存在: %s (HSM 不应用)",
            candidates[0])
    return None


def _warn_hsv_retired(ctx: StageContext) -> None:
    """color_domain="hsv" (退役域) warn-once: A 轨已删, HSM 不应用。"""
    if "hsv" not in _OKLCH_MISSING_WARNED:
        _OKLCH_MISSING_WARNED.add("hsv")
        import logging
        logging.getLogger(__name__).warning(
            "[huesat] color_domain='hsv' 执行链已删除 (R11 A 轨退役); "
            "HSM 不应用, 请改用 'oklch'")


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
        # "hsv" 为退役取值 (历史配置兼容, no-op); 有效执行域仅 "oklch"
        "color_domain": {"type": "str", "choices": ["hsv", "oklch"]},
        "oklch_points_file": {"type": "str"},
    }

    def default_params(self):
        return {"enabled": False, "strength": 1.0, "color_domain": "oklch",
                "oklch_points_file": ""}

    def wants(self, ctx: StageContext) -> bool:
        prof = ctx.prof
        if float(self.p(ctx, "warm_highlight_sat", 1.0)) > 1.0:
            return prof is not None
        if not bool(self.p(ctx, "enabled")):
            return False
        if prof is None:
            return False
        # 非法域 fail-fast (先于无表短路: 配置错误不允许静默)
        domain_oklch = self._oklch_domain(ctx)
        # DCP 无表 (如 Preview 系): B 轨无从形变 → 静默 no-op (与 A 轨时代
        # "无表直通" 同语义, 不告警)
        hs_table, _, _ = get_hue_sat_table(prof)
        lt_table, _, _ = get_look_table(prof)
        if hs_table is None and lt_table is None:
            return False
        if domain_oklch:
            spec = _resolve_oklch_spec(prof, self.p(ctx, "oklch_points_file",
                                                    None))
            # 点云缺失/恒等: 显式 no-op (warn-once), 不回退任何旧链
            return spec is not None and not is_identity_deform(spec)
        # color_domain="hsv": A 轨已退役 → HSM 不应用 (warn-once)
        _warn_hsv_retired(ctx)
        return False

    def _oklch_domain(self, ctx: StageContext) -> bool:
        """color_domain 是否为有效执行域 "oklch"。非法值 raise (与 hsl
        Stage 同口径); "hsv" 为退役取值 (返回 False, wants 告警)。"""
        domain = str(self.p(ctx, "color_domain", "oklch")).strip().lower()
        if domain not in ("hsv", "oklch"):
            raise ValueError(
                f"huesat color_domain 需为 'hsv'|'oklch' (实际 {domain!r})")
        return domain == "oklch"

    def process(self, ctx: StageContext) -> None:
        strength = float(self.p(ctx, "strength"))
        warm_scale = float(self.p(ctx, "warm_highlight_sat", 1.0))
        img = ctx.image
        oklch_applied = False
        enabled = bool(self.p(ctx, "enabled"))
        if enabled and ctx.prof is not None and self._oklch_domain(ctx):
            spec = _resolve_oklch_spec(ctx.prof, self.p(
                ctx, "oklch_points_file", None))
            if spec is not None and not is_identity_deform(spec):
                # OKLCh 域连续形变 (t17 点云): 输入线性 sRGB → gamma 域 →
                # OKLCh 形变 → gamma → 解码回线性 (stage 域接口不变)。
                # R30: srgb_* 由 core/curves 提供 (core/tone 随 DNG 复刻线退役)
                from ..core.curves import srgb_decode, srgb_encode
                gamma = srgb_encode(np.clip(np.asarray(img, np.float64), 0.0, None))
                deformed = apply_oklch_deform(gamma, spec, strength=strength)
                img = srgb_decode(deformed)
                oklch_applied = True
        elif enabled:
            # color_domain="hsv" (退役域) 或无 prof: 显式告警, HSM 不应用
            # (R11 A 轨退役; 点云缺失场景在 oklch 分支内已 warn-once)
            _warn_hsv_retired(ctx)
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
            "hue_sat": bool(hs_table is not None and not oklch_applied),
            "hue_sat_dims": list(dims) if dims else None,
            "look_table": bool(lt_table is not None and not oklch_applied),
            "local_warm_sat": warm_scale,
            "color_domain": "oklch" if oklch_applied else "none",
        }
