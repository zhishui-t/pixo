"""Stage 3 —— 影调重塑 (linear_rgb → gamma_rgb)。

设计 (替代旧管线"每通道拟合 tone LUT + S曲线 + 对比度校准"三层打架):
  - **单一亮度曲线**: RGB 三通道共用一条 filmic 曲线 (1/2.2 幂基 + 肩部软压缩
    + 可选对比度/阴影提升)。三通道同曲线 ⇒ 中性灰在任何亮度层级都保持中性,
    直接消除旧管线"每通道 LUT 导致中性随亮度漂移"的问题 (验收指标 a±7.2 的主因)。
  - 显示亮度校正 (brightness) 与场景曝光 (Stage1) 分离: brightness 是每机常量,
    校准一次;场景曝光只归 Stage1。

参数:
  gamma      幂基 (默认 2.2)
  contrast   对比度 0..1 (0=纯幂曲线)
  toe        阴影提升 0..1 (0=关闭)
  shoulder   高光肩部起点 (线性值 0..1, 默认 0.35; 越高越晚压缩)
  brightness 显示亮度增益 (EV, 线性域预乘, 每机校准常量)
"""
from __future__ import annotations

import numpy as np

from ..core import Stage, StageContext, register_stage
from ..core import DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB
from ..curves import make_filmic_lut, apply_lut1d, parse_profile_curve, curve_lut_from_points

_LUT_CACHE = {}
_PROFILE_CACHE = {}


def _get_lut(gamma: float, contrast: float, toe: float, shoulder: float) -> np.ndarray:
    key = ("p", round(gamma, 3), round(contrast, 4), round(toe, 4), round(shoulder, 4))
    lut = _LUT_CACHE.get(key)
    if lut is None:
        lut = make_filmic_lut(4096, contrast=contrast, toe=toe, shoulder=shoulder)
        _LUT_CACHE[key] = lut
    return lut


def _get_profile_lut(prof) -> np.ndarray | None:
    """DCP 影调曲线 LUT (缓存; 无曲线返回 None)。"""
    if prof is None:
        return None
    lut = _PROFILE_CACHE.get(id(prof))
    if lut is None:
        parsed = parse_profile_curve(getattr(prof, "profile_tone_curve", None))
        lut = curve_lut_from_points(*parsed) if parsed else None
        _PROFILE_CACHE[id(prof)] = lut
    return lut


@register_stage("tone", order=3,
                domain_in=DOMAIN_LINEAR_RGB, domain_out=DOMAIN_GAMMA_RGB)
class ToneStage(Stage):
    name = "tone"

    def default_params(self):
        return {"gamma": 2.2, "contrast": 0.12, "toe": 0.0, "shoulder": 0.35,
                "brightness": 0.0, "profile_curve": False}

    def process(self, ctx: StageContext) -> None:
        gamma = float(self.p(ctx, "gamma"))
        contrast = float(self.p(ctx, "contrast"))
        toe = float(self.p(ctx, "toe"))
        shoulder = float(self.p(ctx, "shoulder"))
        brightness = float(self.p(ctx, "brightness"))
        use_profile = bool(self.p(ctx, "profile_curve"))
        x = ctx.image * (2.0 ** brightness)
        profile_lut = _get_profile_lut(ctx.prof) if use_profile else None
        if profile_lut is not None:
            # 基曲线 = DCP 影调曲线 (Adobe 标定); 肩部软压缩覆盖 >0.9 区域
            base = profile_lut
            if shoulder > 0.0:
                soft = make_filmic_lut(4096, contrast=0.0, toe=0.0,
                                       shoulder=shoulder * 0.6)
                # 高光区向软压缩曲线过渡 (smoothstep 0.85→1.0)
                xx = np.linspace(0.0, 1.0, 4096, dtype=np.float64)
                w = np.clip((xx - 0.85) / 0.15, 0.0, 1.0)
                w = (w * w * (3.0 - 2.0 * w)).astype(np.float32)
                base = (base * (1.0 - w) + soft * w).astype(np.float32)
            y = apply_lut1d(x, base)
        else:
            lut = _get_lut(gamma, contrast, toe, shoulder)
            y = apply_lut1d(x, lut)
        ctx.set_image(np.clip(y, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)
        ctx.state["tone_brightness"] = brightness
        ctx.state["tone_profile_curve"] = profile_lut is not None
