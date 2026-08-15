"""Stage 1 —— 曝光矫正 (linear_cam 域, 场景参考)。

原理 (替代旧 EXPOSURE_CAL_TABLE 拟合表 + 两轮探测迭代):
  - 曝光锚点定义在**影调级消费的域**: 线性 sRGB (矩阵后)。用 1/4 降采样探针
    做一次轻量 WB×FM×Bradford×sRGB 变换, 在该域 log2 中位定标 —— 一次到位,
    无迭代、无场景拟合表, 且与 Stage2/3 解耦 (换曲线锚点自动跟随)。
  - 锚点 = 令影调曲线输出 0.45 (≈gamma 117) 的线性输入 (curve_anchor_target)。
  - 高光保护: 探针域 p99.9 不越白电平 (留 2% 余量), 溢出交给 Stage3 肩部。
  - 基线曝光偏移 (DCP BaselineExposureOffset, 本机 -0.15EV) 计入。

参数:
  mode          "auto"(默认) | "off" | ev 数值
  target        显式锚点 log2 (None = 由 DCP 曲线反推)
  target_offset 校准偏移 (EV), 每机一个常量
  clip_p        高光保护分位 (默认 99.9)
  max_ev        单次修正上限 (默认 2.5)
  subject_mode  "box" 主体框优先 | "full"
"""
from __future__ import annotations

import numpy as np

from ..core import Stage, StageContext, DOMAIN_LINEAR_CAM, register_stage
from ..curves import curve_anchor_target
from rawlab.dcp import BRADFORD_D50_TO_D65, XYZ_D65_TO_SRGB

LOG2_GRAY = float(np.log2(0.18))  # ≈ -2.474 (无 DCP 时的回退锚点)


def _luma_proxy(cam_rgb: np.ndarray) -> np.ndarray:
    """相机空间亮度代理 (仅 prof=None 回退时用于曝光决策)。"""
    return (0.25 * cam_rgb[:, :, 0] + 0.5 * cam_rgb[:, :, 1]
            + 0.25 * cam_rgb[:, :, 2]).astype(np.float32)


def build_probe_matrix(ctx: StageContext) -> tuple[np.ndarray, np.ndarray] | None:
    """构建曝光探针所需的 (wb, m_total): 与 Stage2 完全相同的线性变换。"""
    prof = ctx.prof
    if prof is None:
        return None
    from .whitebalance import interpolate_forward_matrix, auto_wb_linear
    from rawlab.engine.decode import camera_neutral_wb
    from ..core import StageParams

    wb_mode = ctx.params_for("whitebalance").get("mode", "as_shot")
    if wb_mode == "off":
        wb = np.ones(3, dtype=np.float32)
    elif wb_mode == "auto":
        # auto WB 依赖全图统计, 用降采样探针图本身估计
        return "auto", None  # 由 _probe 处理
    else:
        wb = camera_neutral_wb(ctx.raw)
        if wb_mode not in ("as_shot", None):
            wb = np.array(wb_mode, dtype=np.float32)
            wb = wb / wb[1] if wb[1] > 0 else wb
    fm = interpolate_forward_matrix(prof, wb)
    m_total = (np.array(XYZ_D65_TO_SRGB, dtype=np.float32)
               @ np.array(BRADFORD_D50_TO_D65, dtype=np.float32) @ fm)
    return wb.astype(np.float32), m_total.astype(np.float32)


def _probe_linear_srgb(ctx: StageContext, cam: np.ndarray) -> np.ndarray:
    """1/4 降采样探针: 相机RGB → 线性 sRGB (与 Stage2 同变换), 返回 sRGB 亮度。"""
    small = cam[::4, ::4]
    r = build_probe_matrix(ctx)
    if r is None:
        return _luma_proxy(small)
    if isinstance(r[0], str) and r[0] == "auto":
        from .whitebalance import auto_wb_linear, interpolate_forward_matrix
        wb = auto_wb_linear(small)
        fm = interpolate_forward_matrix(ctx.prof, wb)
        m_total = (np.array(XYZ_D65_TO_SRGB, dtype=np.float32)
                   @ np.array(BRADFORD_D50_TO_D65, dtype=np.float32) @ fm)
    else:
        wb, m_total = r
    rgb = np.minimum(small, 1.0).reshape(-1, 3) * wb[np.newaxis, :]
    rgb = np.clip(rgb @ m_total.T, 0.0, None).reshape(small.shape)
    y = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1]
         + 0.0722 * rgb[:, :, 2]).astype(np.float32)
    return y


@register_stage("exposure", order=1,
                domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_LINEAR_CAM)
class ExposureStage(Stage):
    name = "exposure"

    def default_params(self):
        return {"mode": "auto", "target": None, "target_offset": 0.0,
                "clip_p": 98.0, "max_ev": 2.5, "subject_mode": "box"}

    def process(self, ctx: StageContext) -> None:
        mode = self.p(ctx, "mode")
        if mode == "off":
            return
        if isinstance(mode, (int, float)) and mode != "auto":
            ev = float(mode)
        else:
            ev = self._auto_ev(ctx)
        ev = float(np.clip(ev, -float(self.p(ctx, "max_ev")), float(self.p(ctx, "max_ev"))))
        # 记录增益前的传感器饱和掩码 (供 WB 级做高光中性化):
        #   曝光增益会把大量像素推过 1.0, 但真正"传感器饱和"的只有增益前就贴顶的像素
        ctx.state["sat_mask"] = (ctx.image >= 0.985).any(axis=2)
        if ev != 0.0:
            ctx.set_image(ctx.image * (2.0 ** ev), DOMAIN_LINEAR_CAM)
        ctx.state["ev"] = ev
        ctx.results[-1].metrics["ev"] = ev

    def _auto_ev(self, ctx: StageContext) -> float:
        # 探针: 影调级消费的线性 sRGB 域亮度 (1/4 降采样)
        y = _probe_linear_srgb(ctx, ctx.image)
        region = None
        boxes = ctx.state.get("subject_boxes")
        if boxes and self.p(ctx, "subject_mode") == "box":
            h, w = y.shape[:2]
            big = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            l, t, r, b = big
            y0, y1 = int(t * h), max(int(t * h) + 1, int(b * h))
            x0, x1 = int(l * w), max(int(l * w) + 1, int(r * w))
            region = y[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
        src = region if region is not None and region.size > 64 else y
        logy = np.log2(np.maximum(src, 1e-6))
        # 锚点: 由 DCP 影调曲线反推 (曲线输出 0.45 ≈ gamma 117 对应的线性输入)
        explicit = self.p(ctx, "target", None)
        anchor = float(explicit) if explicit is not None else curve_anchor_target(ctx.prof)
        target = anchor + float(self.p(ctx, "target_offset"))
        ev = target - float(np.median(logy))
        # 基线曝光偏移 (DCP BaselineExposureOffset, 本机 -0.15EV)
        if ctx.prof is not None and getattr(ctx.prof, "baseline_exposure_offset", 0.0):
            ev += float(ctx.prof.baseline_exposure_offset)
        # 高光保护: 提亮后 clip_p 分位不越过白电平 (高光裁切预算 = 100-clip_p %,
        # 与 L1 验收一致; 溢出交给 Stage3 肩部/滚降, 不再用"减半"启发式)
        clip_p = float(self.p(ctx, "clip_p"))
        p_hi = float(np.percentile(y, clip_p))
        if p_hi > 0:
            ev_hi = np.log2(1.0 / p_hi)
            ev = min(ev, ev_hi)
        return ev
