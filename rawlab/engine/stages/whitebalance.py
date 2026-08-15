"""Stage 2 —— 色彩矫正 / 白平衡 (linear_cam → linear_rgb)。

权威链路 (Adobe dng_color_spec.cpp):
    cameraRGB × AsShotNeutral → ForwardMatrix → XYZ(D50)
    → Bradford(D50→D65) → 线性 sRGB

旧管线的三个问题及修复:
  1. 固定用 FM1 (StdA 校准): 正确做法是按 AsShot WB 的色温在 FM1/FM2 间插值
     (本相机 FM2==FM1, 插值退化为恒等; 代码保留, 换机可用)。
  2. WB_CAL=[0.90,1,1] 拟合补丁: 全局乘 WB 会同时污染饱和色, 删除。
     残余中性偏色交给 Stage4 (colorcal) 的"中性轴校准"(只动低色度区)。
  3. 高光品红: 白平衡前把相机 RGB 钳到白电平 (1.0), 高光呈中性白而非品红。

参数:
  mode  "as_shot"(默认) | "auto"(线性域灰度世界) | "off"(wb=[1,1,1])
  auto_clip  auto 模式的 WB 系数安全范围 (防止极端估计)
"""
from __future__ import annotations

import numpy as np

from ..core import Stage, StageContext, register_stage
from ..core import DOMAIN_LINEAR_CAM, DOMAIN_LINEAR_RGB
from rawlab.dcp import BRADFORD_D50_TO_D65, XYZ_D65_TO_SRGB, DcpProfile


def cct_kelvin_from_wb(wb: np.ndarray) -> float:
    """由相机空间 WB 系数近似色温 K (Tanner Helland 经验反演, 线性域近似)。

    输入 wb 为乘数 (G=1); 中性相机响应 ∝ 1/wb。仅用于 FM 插值权重,
    误差在数百 K 量级, 对插值影响微小; 端点外钳位。
    """
    r, g, b = 1.0 / max(wb[0], 1e-6), 1.0, 1.0 / max(wb[2], 1e-6)
    m = max(r, g, b)
    r, g, b = r / m, g / m, b / m
    if r < 1e-6:
        return 6500.0
    # 经验公式 (Helland 近似, 线性域直接用)
    n = (r - 0.3320) / (0.1858 - r)
    t = 449.0 * (n ** 3) + 3525.0 * (n ** 2) + 6823.3 * n + 5520.33
    return float(np.clip(t, 2000.0, 12000.0))


def interpolate_forward_matrix(prof: DcpProfile, wb: np.ndarray) -> np.ndarray:
    """按 AsShot 色温插值 ForwardMatrix1/2 (DNG 1/T 规则)。

    blend=0 → FM1 (校准照明体1, 典型 StdA 2856K); blend=1 → FM2 (D65 6500K)。
    两矩阵相同 (如 Nikon Z5 II Camera Standard) 时直接返回, 避免无谓计算。
    """
    fm1 = prof.matrix3(prof.forward_matrix1)
    fm2 = prof.matrix3(prof.forward_matrix2)
    if fm1 is None:
        raise ValueError("DCP 无 ForwardMatrix1")
    fm1 = np.array(fm1, dtype=np.float32)
    if fm2 is None or np.max(np.abs(np.array(fm2) - fm1)) < 1e-4:
        return fm1
    t = cct_kelvin_from_wb(wb)
    t1, t2 = 2856.0, 6500.0
    blend = (1.0 / t - 1.0 / t1) / (1.0 / t2 - 1.0 / t1)
    blend = float(np.clip(blend, 0.0, 1.0))
    return (fm1 + blend * (np.array(fm2, dtype=np.float32) - fm1)).astype(np.float32)


def auto_wb_linear(cam_rgb: np.ndarray, clip_range=(0.5, 2.0)) -> np.ndarray:
    """线性域灰度世界 WB: 通道稳健均值 (p10-p90) 比值的倒数, 归一化 G=1。

    输出 WB 乘数; 系数裁剪到 clip_range (r/b 相对 G) 防极端场景误判。
    """
    wb = np.ones(3, dtype=np.float64)
    for c in range(3):
        ch = cam_rgb[:, :, c]
        lo, hi = np.percentile(ch, 10), np.percentile(ch, 90)
        m = ch[(ch >= lo) & (ch <= hi)]
        wb[c] = float(m.mean()) if m.size else 0.0
    g = wb[1]
    if g <= 0:
        return np.ones(3, dtype=np.float32)
    wb = g / wb
    lo, hi = clip_range
    wb[0] = float(np.clip(wb[0], lo, hi))
    wb[2] = float(np.clip(wb[2], lo, hi))
    return wb.astype(np.float32)


@register_stage("whitebalance", order=2,
                domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_LINEAR_RGB)
class WhiteBalanceStage(Stage):
    name = "whitebalance"

    def default_params(self):
        return {"mode": "as_shot"}

    def process(self, ctx: StageContext) -> None:
        prof = ctx.prof
        if prof is None:
            raise ValueError("whitebalance Stage 需要 DCP profile (ctx.prof)")
        mode = self.p(ctx, "mode")
        cam = ctx.image
        if mode == "off":
            wb = np.ones(3, dtype=np.float32)
        elif mode == "auto":
            wb = auto_wb_linear(cam)
        else:
            from rawlab.engine.decode import camera_neutral_wb
            wb = camera_neutral_wb(ctx.raw)
            if mode not in ("as_shot", None):
                # 手动系数: mode = [r, g, b] 列表
                wb = np.array(mode, dtype=np.float32)
                wb = wb / wb[1] if wb[1] > 0 else wb

        fm = interpolate_forward_matrix(prof, wb)
        m_total = (np.array(XYZ_D65_TO_SRGB, dtype=np.float32)
                   @ np.array(BRADFORD_D50_TO_D65, dtype=np.float32) @ fm)

        # 高光中性化 (2026-08 修复): 传感器饱和像素 (增益前 ≥0.985) 若原本近中性
        #   (min/max ≥ 0.75), 按最亮通道渲染为中性白 —— 与相机预览的高光处理一致,
        #   消除"饱和像素被 WB 染成光源色"的暖高光。有色饱和物 (红灯/霓虹) 保留颜色。
        cam_w = cam * wb.astype(np.float32)[np.newaxis, np.newaxis, :]
        sat_mask = ctx.state.get("sat_mask")
        if sat_mask is not None and sat_mask.any():
            cmax = cam.max(axis=2, keepdims=True)
            cmin = cam.min(axis=2, keepdims=True)
            near_neutral = (cmax > 1e-6) & ((cmin / np.maximum(cmax, 1e-6)) >= 0.75)
            white = sat_mask & near_neutral[..., 0]
            if white.any():
                lum = cam_w.max(axis=2, keepdims=True)
                cam_w = np.where(white[..., np.newaxis],
                                 np.repeat(lum, 3, axis=2), cam_w)
        rgb = cam_w.reshape(-1, 3) @ m_total.T
        rgb = np.clip(rgb, 0.0, None).reshape(cam.shape).astype(np.float32)

        ctx.set_image(rgb, DOMAIN_LINEAR_RGB)
        ctx.state["wb"] = wb
        ctx.state["wb_mode"] = mode
        ctx.state["fm"] = fm
        ctx.state["cct_k"] = float(cct_kelvin_from_wb(wb))
        ctx.results[-1].metrics = {"wb": [round(float(x), 4) for x in wb],
                                   "cct_k": ctx.state["cct_k"]}
