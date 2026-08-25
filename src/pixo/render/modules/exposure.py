"""Stage exposure (order=10) —— 曝光矫正 (linear_cam 域, 场景参考)。

原理 (替代旧 EXPOSURE_CAL_TABLE 拟合表 + 两轮探测迭代):
  - 曝光锚点定义在**影调级消费的域**: 线性 sRGB (矩阵后)。用 1/4 降采样探针
    做一次 WB×CM×CC×Bradford×sRGB 变换 (与 whitebalance Stage 共享
    engine.color.cam_to_xyz, 消除旧 build_probe_matrix 的重复矩阵合成),
    在该域 log2 中位定标 —— 一次到位, 无迭代、无场景拟合表。
  - 锚点 = 令影调曲线输出中灰 (≈gamma 117) 的线性输入 (curve_anchor_target)。
  - 基线曝光偏移 (DCP BaselineExposureOffset) 与每机 target_offset 常量计入。
  - 高光保护软滚降: EV 上限保证 clip_p 分位不越白电平 (裁切预算 100-clip_p %),
    叠加 soft_highlight_rolloff 肩部承接 —— 高光平滑滚降而非硬裁。

参数:
  mode           "auto"(默认) | "off" | ev 数值
  target         显式锚点 log2 (None = 由 DCP 曲线反推)
  target_offset  每机校准偏移 (EV, 单个常量)
  clip_p         高光保护分位 (默认 98 → 裁切预算 2%)
  max_ev         单次修正上限 (默认 2.5)
  rolloff_knee   软滚降肩部起点 (线性值, 默认 0.9)
  vignette       抗暗角强度 k ∈ [0, 0.5] (默认 0): 线性域径向增益
                 g(r)=1+k·r² (r=归一化半径, 角落最大) —— 补偿 LR 内置镜头
                 配置文件去除的光学暗角 (镜头暗角是线性域乘性量, 标量径向
                 增益与 WB×CM 矩阵链可交换, 故在此域应用物理正确)。
  subject_mode   "box" 主体框优先 (face_boxes 优先于 subject_boxes, 框面积<1%忽略) | "full"
  baseline_ev_curve  仅 baseline 模式: [[wb_B, ev], ...] 分段线性曝光补偿
                     (问题清单 A2/B3; 锚点 1.79/2.287 结点为 0, 幅度 ≤1EV)
  baseline_scene_ev  仅 baseline 模式: [[wb_lo,wb_hi,logmed_lo,logmed_hi,ev], ...]
                     按 (wb_B, 场景亮度) 窗口追加曝光补偿 (幅度 ≤1EV)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..pipeline.graph import Stage, StageContext, DOMAIN_LINEAR_CAM, register_stage
from ..core.curves import curve_anchor_target

LOG2_GRAY = float(np.log2(0.18))  # ≈ -2.474 (无 DCP 时的回退锚点)

# 每机曝光标定文件 (tools/fit_target_offset.py --write 生成):
#   {"cal_table": [[m_log2, ev], ...]} —— 场景自适应表: 线性中位亮度 → 所需 EV。
#   相机预览曝光是场景自适应的 (暗场景保暗), 单常量无法复现; 表结点 ≥3 时
#   曝光 Stage 查表 (否则回退锚点 + target_offset)。
_CAL_FILE = Path(__file__).resolve().parent.parent / "target_offset.json"
_cached_offset: float | None = None
_cached_table: tuple | None = None


def _load_target_offset() -> float:
    """读每机 target_offset 标定 (文件不存在 → 0.0)。"""
    global _cached_offset
    if _cached_offset is None:
        try:
            if _CAL_FILE.exists():
                _cached_offset = float(json.loads(
                    _CAL_FILE.read_text(encoding="utf-8")).get("target_offset", 0.0))
            else:
                _cached_offset = 0.0
        except Exception:
            _cached_offset = 0.0
    return _cached_offset


def _load_cal_table() -> tuple | None:
    """读场景自适应表 → (xs, ys) 严格递增 float 数组; 无表/非法 → None。"""
    global _cached_table
    if _cached_table is None:
        _cached_table = False
        try:
            if _CAL_FILE.exists():
                tbl = json.loads(_CAL_FILE.read_text(encoding="utf-8")).get("cal_table")
                if tbl and len(tbl) >= 3:
                    xs = np.array([t[0] for t in tbl], dtype=np.float64)
                    ys = np.array([t[1] for t in tbl], dtype=np.float64)
                    if np.all(np.diff(xs) > 0):
                        _cached_table = (xs, ys)
        except Exception:
            _cached_table = False
    return _cached_table if _cached_table else None


def _luma_proxy(cam_rgb: np.ndarray) -> np.ndarray:
    """相机空间亮度代理 (仅 prof=None 回退时用于曝光决策)。"""
    return (0.25 * cam_rgb[:, :, 0] + 0.5 * cam_rgb[:, :, 1]
            + 0.25 * cam_rgb[:, :, 2]).astype(np.float32)


def _vignette_lift_linear(img: np.ndarray, k: float) -> np.ndarray:
    """抗暗角径向增益 (线性域): g(r) = 1 + k·r², r 归一化到角落 = 1。

    k=0 → 恒等。镜头暗角是线性域乘性量; 标量径向增益与后续 WB×CM 线性
    矩阵链可交换, 在相机线性域应用物理正确 (LR 的内置镜头配置文件在同域
    处理 vignetting)。
    """
    if k <= 0.0:
        return img
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # 偶数尺寸时 h//2 / w//2 恰是中央像素: 用 h/2 / w/2 作光心可保证中心
    # 像素增益严格为 1 (旧 (h-1)/2 在偶数尺寸下偏 0.5px, 中心被误提亮)。
    cx, cy = w / 2.0, h / 2.0
    r2 = ((xx - cx) / max(cx, 1.0)) ** 2 + ((yy - cy) / max(cy, 1.0)) ** 2
    r2 = np.clip(r2 / 2.0, 0.0, 1.0)       # 角点 r²=2 → 归一化 1
    g = (1.0 + float(k) * r2).astype(np.float32)
    return (img * g[..., np.newaxis]).astype(np.float32)


def soft_highlight_rolloff(img: np.ndarray, knee: float = 0.9) -> np.ndarray:
    """高光软滚降 (线性域): knee 之后平滑压向白电平 1.0, 肩部承接、不硬裁。

    y = x                                        , x <= knee
        knee + (1-knee)·tanh((x-knee)/(1-knee))  , x > knee
    单调、C1 连续、渐近 1.0: 高光平滑滚降而非硬切, 且不会真正触及 1.0
    (完全饱和交还给后续 gamma 域处理)。knee 以下不变。
    """
    img = np.asarray(img, dtype=np.float32)
    knee = float(knee)
    if knee >= 1.0 or knee < 0.0:
        return img
    above = img > knee
    if not np.any(above):
        return img
    x = img[above]
    out = img.copy()
    out[above] = knee + (1.0 - knee) * np.tanh((x - knee) / (1.0 - knee))
    # 防浮点舍入使 tanh 渐近越过白电平 (硬约束不越 1.0)
    return np.minimum(out, np.float32(1.0))


_BASELINE_EV_BOUND = 1.0  # baseline_ev_curve 单结点补偿上限 (EV)


def _check_baseline_ev_curve(curve) -> np.ndarray:
    """baseline_ev_curve 校验 → (n,2) [[wb_B, ev], ...]。

    规则: 结点 ≥2; wb_B 严格递增; ev ∈ [-1, 1]。非法抛 ValueError。
    """
    arr = np.asarray(curve, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2 or arr.shape[0] < 2:
        raise ValueError(
            f"baseline_ev_curve 需 ≥2 个 [wb_B, ev] 结点 (实际 shape={arr.shape})")
    if not np.all(np.diff(arr[:, 0]) > 0):
        raise ValueError("baseline_ev_curve 结点 wb_B 必须严格递增")
    if arr[:, 1].min() < -_BASELINE_EV_BOUND or arr[:, 1].max() > _BASELINE_EV_BOUND:
        raise ValueError(f"baseline_ev_curve 的 ev 必须在 [-{_BASELINE_EV_BOUND}, "
                         f"{_BASELINE_EV_BOUND}] 内")
    return arr


def _baseline_curve_ev(wb_b: float, curve: np.ndarray) -> float:
    """按相机 WB 蓝系数 wb_B 查 baseline_ev_curve (分段线性, 端点钳位)。"""
    return float(np.interp(float(wb_b), curve[:, 0], curve[:, 1]))


def _check_baseline_scene_ev(windows) -> np.ndarray:
    """baseline_scene_ev 校验 → (n,5) [[wb_lo, wb_hi, logmed_lo, logmed_hi, ev], ...]。

    窗口语义: 相机 WB 蓝系数 ∈ [wb_lo, wb_hi] 且场景 log2 中位亮度 ∈
    [logmed_lo, logmed_hi] 时, baseline 模式追加 ev (EV)。ev 带界 [-1,1]。
    """
    arr = np.asarray(windows, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 5 or arr.shape[0] < 1:
        raise ValueError(
            f"baseline_scene_ev 需 ≥1 个 [wb_lo, wb_hi, logmed_lo, logmed_hi, ev] "
            f"窗口 (实际 shape={arr.shape})")
    if np.any(arr[:, 0] > arr[:, 1]) or np.any(arr[:, 2] > arr[:, 3]):
        raise ValueError("baseline_scene_ev 窗口下界必须 ≤ 上界")
    if arr[:, 4].min() < -_BASELINE_EV_BOUND or arr[:, 4].max() > _BASELINE_EV_BOUND:
        raise ValueError(f"baseline_scene_ev 的 ev 必须在 [-{_BASELINE_EV_BOUND}, "
                         f"{_BASELINE_EV_BOUND}] 内")
    return arr


def _baseline_scene_ev(wb_b: float, logmed: float, windows: np.ndarray) -> float:
    """按 (wb_B, 场景 log2 中位亮度) 窗口累加 baseline 曝光补偿。"""
    ev = 0.0
    for wb_lo, wb_hi, med_lo, med_hi, win_ev in windows:
        if wb_lo <= wb_b <= wb_hi and med_lo <= logmed <= med_hi:
            ev += float(win_ev)
    return float(ev)


def _probe_linear_srgb(ctx: StageContext, cam: np.ndarray) -> np.ndarray:
    """1/4 降采样探针: 相机RGB → 线性 sRGB (与 whitebalance Stage 同链路), 返回亮度。

    共享 engine.color.cam_to_xyz, 消除旧 build_probe_matrix 的重复矩阵合成
    (旧实现误用 ForwardMatrix 且手工拼 XYZ→sRGB/Bradford 矩阵)。
    """
    from ..core.color import cam_to_xyz
    from .white_balance import auto_wb_linear
    from ..core.io import camera_neutral_wb

    small = cam[::4, ::4]
    if ctx.prof is None:
        return _luma_proxy(small)

    wb_mode = ctx.params_for("whitebalance").get("mode", "as_shot")
    if wb_mode == "off":
        wb = np.ones(3, dtype=np.float32)
    elif wb_mode == "auto":
        wb = auto_wb_linear(small)
    elif wb_mode == "manual":
        # 手动白平衡 (temp/tint): 与 whitebalance Stage 同链路的物理正解
        from ..core.color import temp_tint_to_wb
        wbp = ctx.params_for("whitebalance")
        temp = wbp.get("temp")
        if temp is None:
            raise ValueError("whitebalance mode=manual 需要 temp 参数")
        wb = temp_tint_to_wb(ctx.prof, float(temp), float(wbp.get("tint") or 0.0))
        wb = wb / wb[1] if wb[1] > 0 else wb
    else:
        wb = ctx.state.get("camera_wb")
        if wb is None:
            wb = camera_neutral_wb(ctx.raw)
        if isinstance(wb_mode, (list, tuple)):
            # 数值向量手动系数 [r,g,b]
            wb = np.array(wb_mode, dtype=np.float32)
            wb = wb / wb[1] if wb[1] > 0 else wb
        elif wb_mode not in ("as_shot", None):
            raise ValueError(
                f"exposure probe: 未知 whitebalance mode {wb_mode!r}")

    rgb = cam_to_xyz(small, wb, ctx.prof)
    y = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1]
         + 0.0722 * rgb[:, :, 2]).astype(np.float32)
    return y


@register_stage("exposure", order=10,
                domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_LINEAR_CAM)
class ExposureStage(Stage):
    name = "exposure"

    param_schema = {
        "mode": {"type": "float_or_str"},                       # "auto"|"off"|数值
        "target": {"type": "float"},                            # 显式锚点 log2
        "target_offset": {"type": "float"},
        "clip_p": {"type": "float", "min": 50.0, "max": 100.0},
        "max_ev": {"type": "float", "min": 0.1, "max": 6.0},
        "rolloff_knee": {"type": "float", "min": 0.0, "max": 1.0},
        "vignette": {"type": "float", "min": 0.0, "max": 0.5},
        "subject_mode": {"type": "str", "choices": ["box", "full"]},
        "baseline_ev_curve": {"type": "float_or_str"},
        "baseline_scene_ev": {"type": "float_or_str"},
        # 低光保护 (无 cal_table 回退时生效): 暗场景正向提亮收敛;
        # knee=膝点 (中灰以下 log2 档数, 低于它才开始衰减, 保护普通暗场景);
        # keep=最深场景保留的正向 EV 比例; range=膝点以下的衰减跨度。
        "low_key_keep": {"type": "float", "min": 0.0, "max": 1.0},
        "low_key_range": {"type": "float", "min": 0.5, "max": 6.0},
        "low_key_knee": {"type": "float", "min": 0.0, "max": 4.0},
    }

    def default_params(self):
        return {"mode": "auto", "target": None, "target_offset": _load_target_offset(),
                "clip_p": 98.0, "max_ev": 2.5, "rolloff_knee": 0.9,
                "vignette": 0.0, "subject_mode": "box",
                "baseline_ev_curve": None, "baseline_scene_ev": None,
                "low_key_keep": 0.15, "low_key_range": 2.0,
                "low_key_knee": 1.5}

    def process(self, ctx: StageContext) -> None:
        mode = self.p(ctx, "mode")
        if mode == "off":
            return
        if mode == "baseline":
            # LR As Shot 忠实模式: 应用 DCP BaselineExposureOffset + 有界
            # baseline_ev_curve (问题清单 A2/B3): 按相机 WB 蓝系数补偿
            # "暖尾人脸过亮 / 亮暖场景过暗", 曲线两端钳位、幅度 ≤1EV;
            # 0376(wb_B=2.287) 与 5236(wb_B=1.791) 锚点结点均为 0。
            ev = float(getattr(ctx.prof, "baseline_exposure_offset", 0.0) or 0.0)
            curve_ev = 0.0
            scene_ev = 0.0
            wb = None
            curve = self.p(ctx, "baseline_ev_curve", None)
            scene_windows = self.p(ctx, "baseline_scene_ev", None)
            if (curve is not None or scene_windows is not None) and ctx.raw is not None:
                try:
                    from ..core.io import camera_neutral_wb
                    wb = ctx.state.get("camera_wb")
                    if wb is None:
                        wb = camera_neutral_wb(ctx.raw)
                except Exception:
                    wb = None
            if curve is not None and wb is not None:
                curve_arr = _check_baseline_ev_curve(curve)
                curve_ev = _baseline_curve_ev(float(wb[2] / max(float(wb[1]), 1e-9)),
                                              curve_arr)
            if scene_windows is not None and wb is not None:
                scene_arr = _check_baseline_scene_ev(scene_windows)
                try:
                    wb_b = float(wb[2] / max(float(wb[1]), 1e-9))
                    y = _probe_linear_srgb(ctx, ctx.image)
                    logmed = float(np.median(np.log2(np.maximum(y, 1e-6))))
                    scene_ev = _baseline_scene_ev(wb_b, logmed, scene_arr)
                except Exception:
                    scene_ev = 0.0
            ev += curve_ev + scene_ev
            ctx.state["ev_mode"] = "baseline"
            ctx.state["baseline_curve_ev"] = curve_ev
            ctx.state["baseline_scene_ev"] = scene_ev
        elif isinstance(mode, (int, float)) and mode != "auto":
            ev = float(mode)
        else:
            ev = self._auto_ev(ctx)
        ev = float(np.clip(ev, -float(self.p(ctx, "max_ev")), float(self.p(ctx, "max_ev"))))
        # 记录增益前的传感器饱和掩码 (供 WB 级做高光中性化):
        #   曝光增益会把大量像素推过 1.0, 但真正"传感器饱和"的只有增益前就贴顶的像素
        ctx.state["sat_mask"] = (ctx.image >= 0.985).any(axis=2)
        img = ctx.image
        # 抗暗角 (线性域径向增益): 光学暗角发生在采集端, 先于一切增益/滚降;
        # 标量径向因子与 WB×CM 线性链可交换, 故放曝光增益之前语义正确。
        vignette = float(self.p(ctx, "vignette"))
        rolloff_knee = float(self.p(ctx, "rolloff_knee"))
        try:
            from .._native import exposure_apply
            img = exposure_apply(img, ev=ev, rolloff_knee=rolloff_knee,
                                 vignette=vignette)
        except Exception:
            if vignette > 0.0:
                img = _vignette_lift_linear(img, vignette)
            if ev != 0.0:
                img = img * (2.0 ** ev)
            # 高光保护软滚降: 肩部承接, 不硬裁
            img = soft_highlight_rolloff(img, knee=rolloff_knee)
        ctx.set_image(img.astype(np.float32), DOMAIN_LINEAR_CAM)
        ctx.state["ev"] = ev
        ctx.results[-1].metrics["ev"] = ev
        if ctx.state.get("ev_mode") == "baseline":
            ctx.results[-1].metrics["baseline_curve_ev"] = ctx.state.get(
                "baseline_curve_ev", 0.0)
            ctx.results[-1].metrics["baseline_scene_ev"] = ctx.state.get(
                "baseline_scene_ev", 0.0)

    def _subject_box(self, ctx: StageContext):
        """曝光加权框选择: face_boxes 优先, 无脸用最大主体框; 框面积 <1% 忽略。

        返回归一化 [l, t, r, b] 或 None (无可用框 → 调用方回退全图中位)。
        """
        if self.p(ctx, "subject_mode") != "box":
            return None
        # face 优先: 有 face_boxes 用脸框, 否则回退 subject_boxes (含空列表)
        boxes = ctx.state.get("face_boxes") or ctx.state.get("subject_boxes")
        if not boxes:
            return None
        # 框面积 <1% (归一化) 忽略 —— 噪点框/极小目标不应主导测光
        valid = [b for b in boxes if (b[2] - b[0]) * (b[3] - b[1]) >= 0.01]
        if not valid:
            return None
        return max(valid, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))

    def _auto_ev(self, ctx: StageContext) -> float:
        # 探针: 影调级消费的线性 sRGB 域亮度 (1/4 降采样)
        y = _probe_linear_srgb(ctx, ctx.image)
        region = None
        box = self._subject_box(ctx)
        if box is not None:
            h, w = y.shape[:2]
            l, t, r, b = box
            y0, y1 = int(t * h), max(int(t * h) + 1, int(b * h))
            x0, x1 = int(l * w), max(int(l * w) + 1, int(r * w))
            region = y[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
        src = region if region is not None and region.size > 64 else y
        logy = np.log2(np.maximum(src, 1e-6))
        # 锚点: 由 DCP 影调曲线反推 (曲线输出中灰 ≈117 对应的线性输入)
        explicit = self.p(ctx, "target", None)
        anchor = float(explicit) if explicit is not None else curve_anchor_target(ctx.prof)
        offset = float(self.p(ctx, "target_offset"))
        target = anchor
        ev = target - float(np.median(logy))
        # 基线曝光偏移 (DCP BaselineExposureOffset): 符号按 T2 结论 ev += offset
        #   (负值使整体更暗; 见 dcp.py 0xC7A5 注释)。
        ev += float(getattr(ctx.prof, "baseline_exposure_offset", 0.0) or 0.0)
        # 场景自适应曝光 (对齐相机行为, ADR-06): 相机预览暗场景保暗、亮场景
        # 护高光 —— 单常量锚定把夜景提亮过头 (实测 d_med +20~+31)。有标定表
        # 时按线性中位查表取代中灰锚定。
        med = float(np.median(logy))
        table = _load_cal_table()
        if table is not None:
            xs, ys = table
            ev = float(np.interp(med, xs, ys))
            ctx.state["ev_mode"] = "cal_table"
        else:
            ctx.state["ev_mode"] = "anchor"
        # 高光保护: 提亮后 clip_p 分位不越过白电平 (裁切预算 = 100-clip_p %),
        # 溢出交给 soft_highlight_rolloff 肩部滚降, 不再用"减半"启发式。
        clip_p = float(self.p(ctx, "clip_p"))
        p_hi = float(np.percentile(y, clip_p))
        if p_hi > 0:
            ev_hi = np.log2(1.0 / p_hi)
            ev = min(ev, ev_hi)
        # 低光保护 (ADR-06 暗场景保暗): 相机预览对暗场景保暗而非拉到中灰,
        # 中灰锚定的正向 EV 按场景暗度 smoothstep 收敛 —— med 越低保留越少,
        # 深 low_key_range 档后仅剩 low_key_keep (默认 0.15); 负向 EV 不衰减。
        # 场景自适应标定表存在时走查表路径, 不经过本启发式。
        if table is None and ev > 0.0:
            span = max(float(self.p(ctx, "low_key_range")), 1e-6)
            knee = float(self.p(ctx, "low_key_knee"))
            t = min(max((LOG2_GRAY - knee - med) / span, 0.0), 1.0)
            keep = 1.0 - (1.0 - float(self.p(ctx, "low_key_keep"))) * (
                t * t * (3.0 - 2.0 * t))
            ev *= keep
            ctx.state["ev_low_key_keep"] = float(keep)
        # 用户/规则曝光偏移在自动曝光与高光保护决策之后施加，
        # 确保负向 offset 也能如实压高光、正向 offset 可主动提亮。
        ev += offset
        return ev
