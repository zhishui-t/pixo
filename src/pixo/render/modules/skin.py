"""Stage skin (order=55) —— 人像磨皮 (gamma_rgb → gamma_rgb)。

位置 (软件设计 §1 管线图): colorcal(50) 之后、stylize(60) 之前 —— 肤色保护
(colorcal 内已用同一椭圆掩码) 之后、风格化 LUT 之前做边缘保持磨皮。

参数:
  enabled       是否启用 (默认 True)
  strength      磨皮强度 0..1 (默认 0.5)
  color_domain  肤色掩码域: "hsv"(缺省, 旧 cv2-Lab 椭圆, 行为逐位不变) |
                "oklch" (core.skin 拟合 OKLab 椭圆, 设计 §3; colorcal 的
                skin_trim/scene_skin_trim 同参数同掩码联动)

启用条件 (wants):
  - enabled=False → 不执行;
  - scene 状态注入: ctx.state['scene'] = {"id": ...} / 字符串; 仅 portrait 启用,
    其他场景 (landscape/night/street/food/mono) 直通;
  - scene 缺失 (未分类) → 回退到掩码占比门限: 掩码占比 < 0.5% → 直通 (无肤色)。

默认管线 (pipeline.DEFAULT_STAGES) 不包含本 Stage; 由 portrait 预设 / 显式
config["stages"] 加入后接入, 无需改 Pipeline/core。
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB
from ..core.skin import skin_mask, skin_mask_oklab, skin_smooth

_LOGGER = logging.getLogger(__name__)

# 掩码占比门限: 低于此值视为无肤色, 直通 (规格 §1 错误码: 无肤色 → 直通)
_SKIN_RATIO_MIN = 0.005          # 场景已明确 portrait 时的宽松门限
_SKIN_RATIO_NO_SCENE = 0.03      # 未分类 (无 scene 状态) 时的人像级门限


def _mask_fn(color_domain: str):
    """color_domain → 肤色掩码函数 (设计 §3 双轨分派)。

    "hsv" (缺省) → 旧 Lab 椭圆 skin_mask (逐位不变回退);
    "oklch"     → OKLab 椭圆 skin_mask_oklab (拟合常数, core.skin)。
    """
    domain = str(color_domain).strip().lower()
    if domain == "hsv":
        return skin_mask
    if domain == "oklch":
        return skin_mask_oklab
    raise ValueError(f"skin color_domain 需为 'hsv'|'oklch' (实际 {color_domain!r})")


@register_stage("skin", order=55,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class SkinStage(Stage):
    name = "skin"

    param_schema = {
        "enabled": {"type": "bool"},
        "strength": {"type": "float", "min": 0.0, "max": 1.0},
        # 编辑域开关 (设计 §1.2/§3): "hsv"(缺省, 旧 Lab 椭圆, 逐位不变) | "oklch"
        "color_domain": {"type": "str", "choices": ["hsv", "oklch"]},
    }

    def default_params(self):
        return {"enabled": True, "strength": 0.5, "color_domain": "hsv"}

    def wants(self, ctx: StageContext) -> bool:
        if not bool(self.p(ctx, "enabled", True)):
            return False

        # scene 状态注入 (analyze._classify 写入): 仅 portrait 启用
        scene = ctx.state.get("scene")
        scene_id = scene.get("id") if isinstance(scene, dict) else scene
        if scene_id is not None and scene_id != "portrait":
            return False

        # 无肤色 → 直通: 掩码占比门限 (mask 缓存供 process 复用)。
        # 占比判据在 1/4 降采样上做 (skin_mask 全分辨率 Lab 往返 ~0.5s,
        # 判据只需占比); 真正磨皮时 process 再算全分辨率掩码。
        # 场景已明确为 portrait → 宽松门限 0.5%;未分类 (无 scene 状态) →
        # 人像级门限 3% (与 scenes.SKIN_RATIO_MIN 一致), 避免误磨非人像图。
        ratio_min = _SKIN_RATIO_MIN if scene_id == "portrait" else _SKIN_RATIO_NO_SCENE
        # 掩码函数按 color_domain 分派 (非法域在此 raise, 不吞进占比门控)
        mask_fn = _mask_fn(self.p(ctx, "color_domain", "hsv"))
        try:
            import cv2
            img = np.asarray(ctx.image)
            h, w = img.shape[:2]
            small = cv2.resize(np.clip(img, 0, 1), (max(w // 4, 4), max(h // 4, 4)),
                               interpolation=cv2.INTER_AREA)
            m = mask_fn(small)
        except Exception as exc:
            # 门控直通语义不变 (无肤色/掩码失败均视为不需要磨皮), 仅留痕:
            # oklch 域掩码/降采样在此抛异常时不再静默, 便于排查域分派问题
            _LOGGER.warning(
                "[skin] wants 掩码占比门控计算失败, 直通: %s: %s",
                type(exc).__name__, exc)
            return False
        if float(np.asarray(m).mean()) < ratio_min:
            return False
        ctx.state["skin_mask_ratio"] = float(np.asarray(m).mean())
        return True

    def process(self, ctx: StageContext) -> None:
        img = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)
        strength = float(self.p(ctx, "strength"))
        if strength <= 0.0:
            return
        # 掩码按 color_domain 分派 (缺省 hsv → 旧 Lab 椭圆, 逐位不变)
        mask_fn = _mask_fn(self.p(ctx, "color_domain", "hsv"))

        # M6: 优先读 ctx.mode ("preview"/"export", 三渲染入口显式传入);
        # config 键判断保留为向后兼容回退 (直接构造 ctx 的老调用方/测试)。
        # 预览判定结果与旧实现一致: 生产入口 mode=preview ⟺ config 键真值。
        is_preview = (getattr(ctx, "mode", "export") == "preview"
                      or bool(ctx.config.get("preview")) or bool(ctx.config.get("long_edge"))
                      or bool(ctx.config.get("decode_mode")))
        if is_preview:
            # P1 预览：磨皮整体在降采样分辨率计算（掩码 + 引导滤波），再上采样。
            # long1024 用 1/2 保质量；long2048 用 1/4 保性能。
            h, w = img.shape[:2]
            long_edge = int(ctx.config.get("long_edge", 0) or 0)
            div = 2 if long_edge <= 1024 else 4
            small = cv2.resize(img, (max(w // div, 4), max(h // div, 4)),
                               interpolation=cv2.INTER_AREA)
            rgb8 = (small * 255.0 + 0.5).astype(np.uint8)

            m = ctx.state.get("skin_mask")
            if m is not None and m.shape[:2] == small.shape[:2]:
                pass
            elif mask_fn is skin_mask:
                # 旧掩码契约是 uint8 Lab (u8), 保持原量化口径
                m = mask_fn((small * 255.0 + 0.5).astype(np.uint8))
            else:
                # OKLab 掩码走 float [0,1] 契约, 免去量化损失
                m = mask_fn(small)

            out8 = skin_smooth(rgb8, m, strength, half_res=False)
            out = cv2.resize(out8.astype(np.float32) / 255.0, (w, h),
                             interpolation=cv2.INTER_LINEAR)
        else:
            # 生产全质量路径：保持原分辨率，不做预览降采样。
            rgb8 = (img * 255.0 + 0.5).astype(np.uint8)
            m = ctx.state.get("skin_mask")
            if m is not None and m.shape[:2] == img.shape[:2]:
                pass
            elif mask_fn is skin_mask:
                m = mask_fn(rgb8)
            else:
                m = mask_fn(img)
            out8 = skin_smooth(rgb8, m, strength, half_res=False)
            out = out8.astype(np.float32) / 255.0

        ctx.set_image(out, DOMAIN_GAMMA_RGB)
