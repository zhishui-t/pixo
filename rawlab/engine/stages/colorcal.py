"""Stage 4 —— 色彩校准 (gamma_rgb → gamma_rgb, Lab 域)。

原则 (替代旧管线 HSV +12 饱和 / WB_CAL=0.9 全局补丁):
  - **中性轴校准**: neutral_a/neutral_b 只作用于低色度区 (高斯权重按 C 衰减),
    修正系统性中性偏色, 但不污染饱和色 (WB_CAL 的教训)。
  - 饱和度/自然饱和度/色相旋转都在 Lab 域做, 可独立控制、可关闭。
  - 肤色保护: 肤色带内的饱和度增益自动衰减 (保肤自然)。

参数:
  saturation    饱和度增益 (0=不变, 0.2=+20%)
  vibrance      自然饱和度 (低饱和区多增, 高饱和区少增, 防溢出)
  hue           色相旋转角度 (度, 默认 0)
  neutral_a     中性轴 a 偏移 (标量, 只动低色度区)
  neutral_b     中性轴 b 偏移 (标量)
  neutral_a_curve  按亮度分段的 a 校正曲线 (7 点, 对应 L 中心 [8,32,72,128,184,224,248])
  neutral_b_curve  同上 b; 每机标定一次 (校准数据见 engine/calibration.py)
  neutral_sigma 中性区高斯半径 (C* 单位, 默认 14)
  skin_protect  肤色保护强度 0..1 (默认 0.7)
  gamut_soft    超出 sRGB 色域的软压缩 (默认 0.5)
"""
from __future__ import annotations

import cv2
import numpy as np

from ..core import Stage, StageContext, register_stage
from ..core import DOMAIN_GAMMA_RGB

_NEUTRAL_CENTERS = np.array([8, 32, 72, 128, 184, 224, 248], dtype=np.float32)


@register_stage("colorcal", order=4,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class ColorCalStage(Stage):
    name = "colorcal"

    def default_params(self):
        return {"saturation": 0.0, "vibrance": 0.0, "hue": 0.0,
                "neutral_a": 0.0, "neutral_b": 0.0,
                "neutral_a_curve": None, "neutral_b_curve": None,
                "neutral_sigma": 14.0,
                "skin_protect": 0.7, "gamut_soft": 0.5}

    def _neutral_curves(self, ctx: StageContext):
        """中性校正曲线: 参数显式给定 > 每机标定数据 (engine.calibration) > None。"""
        a_curve = self.p(ctx, "neutral_a_curve", None)
        b_curve = self.p(ctx, "neutral_b_curve", None)
        if a_curve is None and b_curve is None and ctx.prof is not None:
            try:
                from ..calibration import camera_neutral_trim
                a_curve, b_curve = camera_neutral_trim(ctx.prof)
            except Exception:
                pass
        return a_curve, b_curve

    def process(self, ctx: StageContext) -> None:
        sat = float(self.p(ctx, "saturation"))
        vib = float(self.p(ctx, "vibrance"))
        hue = float(self.p(ctx, "hue"))
        na = float(self.p(ctx, "neutral_a"))
        nb = float(self.p(ctx, "neutral_b"))
        sigma = float(self.p(ctx, "neutral_sigma"))
        skin = float(self.p(ctx, "skin_protect"))
        a_curve, b_curve = self._neutral_curves(ctx)

        # 全默认 → 直通 (省一次 Lab 往返 ~1s)
        if (sat == 0.0 and vib == 0.0 and hue == 0.0 and na == 0.0 and nb == 0.0
                and a_curve is None and b_curve is None):
            return

        img = np.clip(ctx.image, 0.0, 1.0)
        u8 = (img * 255.0 + 0.5).astype(np.uint8)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
        C = np.sqrt((a - 128.0) ** 2 + (b - 128.0) ** 2)

        # 1) 中性轴校准: 标量 + 按亮度分段曲线, 高斯权重按 C 衰减 (不动饱和色)
        if na != 0.0 or nb != 0.0 or a_curve is not None or b_curve is not None:
            w = np.exp(-(C ** 2) / (2.0 * sigma * sigma))
            if a_curve is not None or b_curve is not None:
                a_off = (np.interp(L, _NEUTRAL_CENTERS, a_curve).astype(np.float32)
                         if a_curve is not None else 0.0)
                b_off = (np.interp(L, _NEUTRAL_CENTERS, b_curve).astype(np.float32)
                         if b_curve is not None else 0.0)
                a = a + (na + a_off) * w
                b = b + (nb + b_off) * w
            else:
                a = a + na * w
                b = b + nb * w

        # 2) 色相旋转
        if hue != 0.0:
            rad = np.deg2rad(hue)
            ca, cb = a - 128.0, b - 128.0
            a = 128.0 + ca * np.cos(rad) - cb * np.sin(rad)
            b = 128.0 + ca * np.sin(rad) + cb * np.cos(rad)

        # 3) 饱和度 + 自然饱和度 (肤色保护)
        gain = 1.0 + sat
        if vib != 0.0:
            # 自然饱和度: 按现有色度反向加权 (低饱和多增)
            gain = gain + vib * np.clip(1.0 - C / 128.0, 0.0, 1.0)
        if skin > 0.0:
            # 肤色带: a 偏高且 b 略正 (Lab 128 中心), 保护系数衰减增益
            skin_mask = np.clip(((a - 140.0) / 20.0) * ((b - 128.0) / 25.0), 0.0, 1.0)
            gain = 1.0 + (gain - 1.0) * (1.0 - skin * skin_mask)
        a = 128.0 + (a - 128.0) * gain
        b = 128.0 + (b - 128.0) * gain

        lab2 = np.stack([L, a, b], axis=-1)
        lab2 = np.clip(lab2, 0, 255).astype(np.uint8)
        out = cv2.cvtColor(lab2, cv2.COLOR_LAB2RGB)

        # 4) 色域软压缩: 越界通道按比例向灰回拉 (防 Lab 往返导致的硬裁)
        out = out.astype(np.float32) / 255.0
        gs = float(self.p(ctx, "gamut_soft"))
        if gs > 0.0:
            over = np.maximum(out - 1.0, 0.0)
            scale = 1.0 / (1.0 + gs * over.sum(axis=-1, keepdims=True))
            out = out * scale
        ctx.set_image(np.clip(out, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)
