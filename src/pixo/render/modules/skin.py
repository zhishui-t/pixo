"""Stage skin (order=55) —— 人像磨皮 (gamma_rgb → gamma_rgb)。

位置 (软件设计 §1 管线图): colorcal(50) 之后、stylize(60) 之前 —— 肤色保护
(colorcal 内已用同一椭圆掩码) 之后、风格化 LUT 之前做边缘保持磨皮。

参数:
  enabled   是否启用 (默认 True)
  strength  磨皮强度 0..1 (默认 0.5)

启用条件 (wants):
  - enabled=False → 不执行;
  - scene 状态注入: ctx.state['scene'] = {"id": ...} / 字符串; 仅 portrait 启用,
    其他场景 (landscape/night/street/food/mono) 直通;
  - scene 缺失 (未分类) → 回退到掩码占比门限: 掩码占比 < 0.5% → 直通 (无肤色)。

默认管线 (pipeline.DEFAULT_STAGES) 不包含本 Stage; 由 portrait 预设 / 显式
config["stages"] 加入后接入, 无需改 Pipeline/core。
"""
from __future__ import annotations

import cv2
import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB
from ..core.skin import skin_mask, skin_smooth

# 掩码占比门限: 低于此值视为无肤色, 直通 (规格 §1 错误码: 无肤色 → 直通)
_SKIN_RATIO_MIN = 0.005          # 场景已明确 portrait 时的宽松门限
_SKIN_RATIO_NO_SCENE = 0.03      # 未分类 (无 scene 状态) 时的人像级门限


@register_stage("skin", order=55,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class SkinStage(Stage):
    name = "skin"

    param_schema = {
        "enabled": {"type": "bool"},
        "strength": {"type": "float", "min": 0.0, "max": 1.0},
    }

    def default_params(self):
        return {"enabled": True, "strength": 0.5}

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
        try:
            import cv2
            img = np.asarray(ctx.image)
            h, w = img.shape[:2]
            small = cv2.resize(np.clip(img, 0, 1), (max(w // 4, 4), max(h // 4, 4)),
                               interpolation=cv2.INTER_AREA)
            m = skin_mask(small)
        except Exception:
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
            else:
                m = skin_mask(rgb8)

            out8 = skin_smooth(rgb8, m, strength, half_res=False)
            out = cv2.resize(out8.astype(np.float32) / 255.0, (w, h),
                             interpolation=cv2.INTER_LINEAR)
        else:
            # 生产全质量路径：保持原分辨率，不做预览降采样。
            rgb8 = (img * 255.0 + 0.5).astype(np.uint8)
            m = ctx.state.get("skin_mask")
            if m is not None and m.shape[:2] == img.shape[:2]:
                pass
            else:
                m = skin_mask(rgb8)
            out8 = skin_smooth(rgb8, m, strength, half_res=False)
            out = out8.astype(np.float32) / 255.0

        ctx.set_image(out, DOMAIN_GAMMA_RGB)
