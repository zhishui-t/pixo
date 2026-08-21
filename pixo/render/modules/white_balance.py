"""Stage whitebalance (order=20) —— 白平衡 / 色彩矫正 (linear_cam → linear_rgb)。

权威链路 (DNG 1.4 + Adobe dng_color_spec.cpp, 基座 colorimetric 路径):
    cameraRGB × AsShotNeutral → inv(ColorMatrix × CameraCalibration) → XYZ(场景参考)
    → Bradford (场景白 → D50) → XYZ(D50) → Bradford(D50→D65) → 线性 sRGB
  ColorMatrix1/2 按 1/T 在 CalibrationIlluminant1/2 间插值 (见 engine/color.py)。
  ForwardMatrix 仅作 look 参考; 缺 ColorMatrix 时回退 FM 并告警。

旧管线的修正:
  1. 旧代码直接拿 ForwardMatrix 当 camera→XYZ (误用): FM 是"WB 后相机→XYZ(D50)"
     的观感矩阵, 不是 colorimetric 的 camera→XYZ。现已改用 ColorMatrix×CameraCalibration。
  2. WB_CAL=[0.90,1,1] 拟合补丁删除 (残余中性偏色交给 Stage4 中性轴校准)。
  3. 高光中性化保留: 传感器饱和且近中性的像素渲染为中性白, 消除暖高光。

参数:
  mode  "as_shot"(默认) | "auto"(线性域灰度世界) | "off"(wb=[1,1,1])
  auto_clip  auto 模式的 WB 系数安全范围 (防止极端估计)
  warmth  暖度校正 0..1 (默认 0.9): LR 同 As Shot 渲染的暖黄趋势随 WB 蓝系数
          走 (0376 wb_B=2.287 → 全量暖; 5236 wb_B=1.791 → 零暖), 强度按
          每张照片的 wb_B 插值 (apply_warmth), 不污染中性照片。
  warmth_b0 / warmth_b1  冻结锚点 1.79 / 2.287 (0376/5236 双锚点标定); stage
          仍可覆盖 (向前兼容), 但视为冻结 —— 禁止再拟合 (见"暖度模型约束")。
  warmth_r_slope / warmth_g_slope / warmth_b_slope  三通道斜率, 带界:
          r∈[-0.05,0.05]、g∈[0.05,0.15]、b∈[0.20,0.35] (默认 0.0/0.10/0.26);
          越界 raise ValueError (Stage 参数校验层)。
  warmth_curve  可选分桶暖度曲线 (2026-08 用户反馈轮): [[wb_B, r, g, b], ...]
          —— 按 wb_B 分段线性插值的三通道增益 (替代单一斜率模型, 覆盖
          "部分色温偏黄/偏绿" 的非线性分桶行为); 提供时优先于斜率模型,
          gain = 1 + warmth·(g_knot − 1); 增益带界 [0.5, 1.5], 结点 ≥2 且
          wb_B 严格递增, 越界 raise ValueError。

暖度模型约束 (2026-08 方案 A, 见 dsh-plan-task-p4/research/warmth-model-regularization.md):
  1. 锚点 b0=1.79 / b1=2.287 硬冻结 (0376/5236 双锚点标定; 语料暖尾仅 6 样本
     且成簇, 网格搜索 b0/b1 无数据支撑, 属过拟合仪式);
  2. 三通道斜率带界 (上式): 越界即非法标定, Stage 参数校验层与 apply_warmth
     双重校验, 抛 ValueError;
  3. 键 s = clip((wb_B−b0)/(b1−b0), 0, 1) × warmth, 增益 =
     gain = [1+r_slope·s, 1+g_slope·s, 1−b_slope·s]。
"""
from __future__ import annotations

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_LINEAR_CAM, DOMAIN_LINEAR_RGB
from ..core.color import (cam_to_linear_srgb_matrix, cct_from_wb,
                     interpolate_forward_matrix, temp_tint_to_wb)
from ..core.calibration import DcpProfile


# 暖度模型约束 (2026-08 方案 A, 见 research/warmth-model-regularization.md):
#   - 锚点 b0/b1 硬冻结 (0376/5236 双锚点标定), cal 覆盖仅向前兼容;
#   - 三通道斜率带界: 越界视为非法标定 (Stage 参数校验层 + apply_warmth 双校验)。
#   - 2026-08-17 语料扩充 (90 张 LR 导出) 后放宽: 日光段需要 R 下压 (s=0 基线
#     由 trim 承担), 暖尾需要 R 随 s 回升 (正 r_slope) 且 G 不抬 (偏绿反馈)、
#     B 抑制可更温和 (偏黄反馈) —— 旧界 r[-0.05,0.05]/g[0.05,0.15]/b[0.20,0.35]
#     来自 2 锚点标定, 过窄。
WARMTH_B0_FROZEN = 1.79
WARMTH_B1_FROZEN = 2.287
WARMTH_DAY_BAND = 0.57  # 日光带锥形宽度 (wb_B 1.22~1.79 内线性衰减)

WARMTH_SLOPE_BOUNDS = {
    "r_slope": (-0.05, 0.25),
    "g_slope": (-0.05, 0.15),
    "b_slope": (0.05, 0.35),
    "r_day": (0.0, 0.5),
}


def _check_warmth_slope(key: str, value: float) -> float:
    """斜率带界校验: 越界抛 ValueError (信息含允许范围)。"""
    value = float(value)
    lo, hi = WARMTH_SLOPE_BOUNDS[key]
    if not (lo <= value <= hi):
        raise ValueError(
            f"warmth 斜率 '{key}' 越界: 值 {value!r} 不在允许范围 [{lo}, {hi}]")
    return value


def _check_warmth_curve(curve) -> np.ndarray:
    """warmth_curve 校验 → (n,4) float64 数组 [[wb_B, r, g, b], ...]。

    规则: 结点 ≥2; wb_B 严格递增; 增益带界 [0.5, 1.5]。
    越界 raise ValueError (信息含原因)。
    """
    arr = np.asarray(curve, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 4 or arr.shape[0] < 2:
        raise ValueError(
            f"warmth_curve 需 ≥2 个 [wb_B, r, g, b] 结点 (实际 shape={arr.shape})")
    if not np.all(np.diff(arr[:, 0]) > 0):
        raise ValueError("warmth_curve 结点 wb_B 必须严格递增")
    if arr[:, 1:].min() < 0.5 or arr[:, 1:].max() > 1.5:
        raise ValueError("warmth_curve 增益必须在 [0.5, 1.5] 内")
    return arr


def apply_warmth(wb: np.ndarray, prof, warmth: float = 1.0,
                 cal: dict | None = None) -> np.ndarray:
    """观感暖度/色调校正 (按相机 WB 的 B 系数插值强度, 自适应每张照片)。

    实测依据 (LR 导出为 ground truth, 2026-08):
      - 0376: wb=[1.291, 1, 2.287] (LR 3300K/tint+27) → LR 渲染暖黄 (a+6 b+12);
      - 5236: wb=[1.244, 1, 1.791] (LR 3450K/tint 0)  → LR 渲染中性 (a=0 b=-1)。
    同是钨丝灯, LR 的暖度随 WB 蓝系数走 (蓝系数 = 色温+tint 的综合体现)。
    常量 warm 会把 5236 也做成暖黄 (用户报"黄绿")。
    本实现: 增益 = 两照片间的线性插值, 键 = wb 蓝系数 b = wb_B/wb_G:
      s = clip((b - b0) / (b1 - b0), 0, 1) × warmth
      gain = [1 + r_slope·s, 1 + g_slope·s, 1 - b_slope·s]
    标定常数 (b0/b1/斜率) 由 tools/fit_camera_profile.py 从语料拟合。
    约束 (2026-08 方案 A, 见 research/warmth-model-regularization.md):
      - 锚点 b0=1.79 / b1=2.287 已**冻结** (0376/5236 双锚点, 禁止网格搜索);
        cal 字典仍可覆盖 (stage 参数 warmth_b0/warmth_b1, 向前兼容), 但视为
        冻结, 新数据到位前不得再拟合。
      - 三通道斜率带界: r∈[-0.05,0.25] / g∈[-0.05,0.15] / b∈[0.05,0.35] / r_day∈[0,0.5],
        越界 raise ValueError (默认值 0.0/0.10/0.26 在界内)。
    """
    if warmth <= 0.0:
        return np.asarray(wb, dtype=np.float32).copy()
    cal = cal or {}
    b0 = float(cal.get("b0", WARMTH_B0_FROZEN))
    b1 = float(cal.get("b1", WARMTH_B1_FROZEN))
    r_slope = _check_warmth_slope("r_slope", cal.get("r_slope", 0.0))
    g_slope = _check_warmth_slope("g_slope", cal.get("g_slope", 0.10))
    b_slope = _check_warmth_slope("b_slope", cal.get("b_slope", 0.26))
    r_day = _check_warmth_slope("r_day", cal.get("r_day", 0.25))
    wb = np.asarray(wb, dtype=np.float32)
    b = float(wb[2] / max(float(wb[1]), 1e-9))
    # 分桶暖度曲线 (2026-08 用户反馈轮): 提供时优先于斜率模型 —— 曲线直接
    # 表达"按 wb_B 分段"的非线性增益, 修正斜率模型无法覆盖的分桶偏色
    # (部分色温偏黄 / 偏绿)。gain = 1 + warmth·(g_knot − 1)。
    if cal.get("curve") is not None:
        curve = _check_warmth_curve(cal["curve"])
        gk = np.array([np.interp(b, curve[:, 0], curve[:, c + 1])
                       for c in range(3)], dtype=np.float64)
        gain = (1.0 + float(warmth) * (gk - 1.0)).astype(np.float32)
        return (wb * gain).astype(np.float32)
    s = float(np.clip((b - b0) / max(b1 - b0, 1e-9), 0.0, 1.0)) * float(warmth)
    # 日光带锥形 (2026-08-17 用户实测): 全范围线性 taper 使中段 (1.3~1.4) 过度
    # 降 R (夜景发绿), 改为 wb_B ≤ b0-WARMTH_DAY_BAND (≈1.22) 全量、
    # 之后线性归零到 b0 (1.79)。
    s2 = float(np.clip((b0 - b) / max(WARMTH_DAY_BAND, 1e-9), 0.0, 1.0)) * float(warmth)
    gain = np.array([(1.0 - r_day * s2) * (1.0 + r_slope * s),
                     1.0 + g_slope * s, 1.0 - b_slope * s],
                    dtype=np.float32)
    return (wb * gain).astype(np.float32)


def cct_kelvin_from_wb(wb: np.ndarray, prof: DcpProfile | None = None) -> float:
    """由相机空间 WB 系数求相关色温 K (CIE xy → McCamy, 替代 Tanner Helland 误用)。

    路径: WB 中性点 → inv(ColorMatrix) → CIE xy → McCamy CCT。
    详见 engine.color.cct_from_wb。端点外钳位到 [1000, 50000] K。
    """
    return cct_from_wb(wb, prof)


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


@register_stage("whitebalance", order=20,
                domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_LINEAR_RGB)
class WhiteBalanceStage(Stage):
    name = "whitebalance"

    # mode: "as_shot"|"auto"|"off"|数值向量 [r,g,b] 手动系数 (float_or_str 放行向量)
    # 暖度标定常数: 锚点 b0/b1 已冻结 (1.79/2.287, 0376/5236 双锚点标定), stage
    #   覆盖仅向前兼容 (见模块 docstring "暖度模型约束"); 三通道斜率带界 (方案 A):
    #   r∈[-0.05,0.05]、g∈[0.05,0.15]、b∈[0.20,0.35], 越界 raise ValueError。
    param_schema = {
        "mode": {"type": "float_or_str"},
        "warmth": {"type": "float", "min": 0.0, "max": 2.0},
        # 冻结锚点 (可覆盖, 不再拟合)
        "warmth_b0": {"type": "float"},
        "warmth_b1": {"type": "float"},
        # 斜率带界 (越界抛 ValueError)
        "warmth_r_slope": {"type": "float", "min": -0.05, "max": 0.25},
        "warmth_g_slope": {"type": "float", "min": -0.05, "max": 0.15},
        "warmth_b_slope": {"type": "float", "min": 0.05, "max": 0.35},
        "warmth_r_day": {"type": "float", "min": 0.0, "max": 0.5},
        # 分桶暖度曲线 (可选): [[wb_B, r, g, b], ...] 分段线性增益
        "warmth_curve": {"type": "float_or_str"},
        # 固定线性 RGB 修整增益 [r,g,b] (色彩链路矩阵后乘, 缺省恒等)
        "trim": {"type": "float_or_str"},
        # 手动白平衡 temp(K)/tint (仅 mode=manual 使用)
        "temp": {"type": "float", "min": 1000.0, "max": 50000.0},
        "tint": {"type": "float", "min": -150.0, "max": 150.0},
    }

    def default_params(self):
        return {"mode": "as_shot", "warmth": 0.9,
                "warmth_b0": None, "warmth_b1": None,
                "warmth_r_slope": None, "warmth_g_slope": None,
                "warmth_b_slope": None, "warmth_r_day": None,
                "warmth_curve": None, "temp": None, "tint": None, "trim": None}  # 0.9=对齐 LR 实测渲染(0376: L196/a+6/b+12)

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
        elif mode == "manual":
            temp = self.p(ctx, "temp")
            if temp is None:
                raise ValueError("manual 白平衡模式需要提供 temp 参数")
            tint = float(self.p(ctx, "tint") or 0.0)
            wb = temp_tint_to_wb(prof, float(temp), tint)
            wb = wb / wb[1]  # 归一化 G=1
        else:
            from ..core.io import camera_neutral_wb
            wb = ctx.state.get("camera_wb")
            if wb is None:
                wb = camera_neutral_wb(ctx.raw)
            if mode not in ("as_shot", None):
                # 手动系数: mode = [r, g, b] 列表
                wb = np.array(mode, dtype=np.float32)
                wb = wb / wb[1] if wb[1] > 0 else wb

        # 场景键保留校正前的相机 WB (scene_trim / 后续场景自适应按原场景
        # 光照判键, 不应被观感暖度增益污染)。
        ctx.state["wb_cam"] = np.asarray(wb, dtype=np.float32).copy()
        # 观感暖度校正 (按 WB 蓝系数自适应, 见 apply_warmth 注释):
        #   仅作用于 as_shot/auto (手动模式视为用户显式意图), off 不动。
        warmth = float(self.p(ctx, "warmth", 1.0))
        cct_k = float(cct_from_wb(wb, prof))
        if mode not in ("off", "manual") and not (isinstance(mode, (list, tuple))):
            cal = {}
            for key, pkey in (("b0", "warmth_b0"), ("b1", "warmth_b1"),
                              ("r_slope", "warmth_r_slope"),
                              ("g_slope", "warmth_g_slope"),
                              ("b_slope", "warmth_b_slope"),
                              ("r_day", "warmth_r_day")):
                v = self.p(ctx, pkey, None)
                if v is not None:
                    cal[key] = float(v)
            curve = self.p(ctx, "warmth_curve", None)
            if curve is not None:
                cal["curve"] = curve
            wb = apply_warmth(wb, prof, warmth, cal or None)

        # 基座链路矩阵: camera → 线性 sRGB(D65)
        #   = sRGB @ Bradford(D50→D65) @ Bradford(场景白→D50) @ inv(CM×CC)
        # 缺 CM 时在 color 层回退 FM 并告警。
        m_total = cam_to_linear_srgb_matrix(prof, wb).astype(np.float32)

        # 高光中性化 (2026-08 修复): 传感器饱和像素 (增益前 ≥0.985) 若原本近中性
        #   (min/max ≥ 0.75), 按最亮通道渲染为中性白 —— 与相机预览的高光处理一致,
        #   消除"饱和像素被 WB 染成光源色"的暖高光。有色饱和物 (红灯/霓虹) 保留颜色。
        # DNG SDK Stage3 语义: 未乘 WB 的相机 RGB; CameraToProPhoto 矩阵已含 WB。
        ctx.state["cam_raw"] = cam.astype(np.float32)
        cam_w = cam * wb.astype(np.float32)[np.newaxis, np.newaxis, :]
        sat_mask = ctx.state.get("sat_mask")
        if sat_mask is not None and sat_mask.any():
            # 只在饱和像素上做 min/max，避免全图 axis 归约（2.8MP 下 ~200ms）。
            idx = np.nonzero(sat_mask)
            if len(idx[0]) > 0:
                cam_sat = cam[idx[0], idx[1], :]
                cmax = cam_sat.max(axis=1)
                cmin = cam_sat.min(axis=1)
                near_neutral = ((cmax > 1e-6) &
                                ((cmin / np.maximum(cmax, 1e-6)) >= 0.75))
                white_idx = (idx[0][near_neutral], idx[1][near_neutral])
                if len(white_idx[0]) > 0:
                    lum = cam_w[white_idx[0], white_idx[1], :].max(axis=1)
                    cam_w[white_idx[0], white_idx[1], :] = np.repeat(
                        lum[:, np.newaxis], 3, axis=1)
        # DNG SDK HSM/LookTable 应用域输入: 保存 WB 后相机 RGB (高光中性化后) 供
        # huesat stage 复刻 Camera→ProPhoto(ForwardMatrix) 路径。
        ctx.state["cam_wb"] = cam_w.astype(np.float32)
        try:
            from .._native import matrix_apply3
            rgb = matrix_apply3(cam_w, m_total)
        except Exception:
            rgb = cam_w.reshape(-1, 3) @ m_total.T
            rgb = rgb.reshape(cam.shape)
        rgb = np.clip(rgb, 0.0, None).astype(np.float32)

        # 固定线性 RGB 修整 (preset/标定注入, 缺省恒等): 3 元=对角, 9 元=3×3 行主序
        trim = self.p(ctx, "trim", None)
        if isinstance(trim, (list, tuple)) and len(trim) in (3, 9):
            if len(trim) == 3:
                rgb = rgb * np.asarray(trim, dtype=np.float32)[np.newaxis, np.newaxis, :]
            else:
                m = np.asarray(trim, dtype=np.float32).reshape(3, 3)
                rgb = (rgb.reshape(-1, 3) @ m.T).reshape(rgb.shape).astype(np.float32)

        ctx.set_image(rgb, DOMAIN_LINEAR_RGB)
        ctx.state["wb"] = wb
        ctx.state["wb_mode"] = mode
        ctx.state["cct_k"] = cct_k  # 原始色温 (相机观感标定按此插值, 不受暖度校正影响)
        ctx.results[-1].metrics = {"wb": [round(float(x), 4) for x in wb],
                                   "cct_k": ctx.state["cct_k"]}


# 兼容导出: exposure Stage 的探针仍引用此符号 (T4 将改为共享 engine.color.cam_to_xyz)。
__all__ = ["WhiteBalanceStage", "cct_kelvin_from_wb", "interpolate_forward_matrix",
           "auto_wb_linear"]
