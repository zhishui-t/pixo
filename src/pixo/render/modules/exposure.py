"""Stage exposure (order=10) —— 曝光矫正 (linear_cam 域, 场景参考)。

原理 (替代旧 EXPOSURE_CAL_TABLE 拟合表 + 两轮探测迭代):
  - 曝光锚点定义在**影调级消费的域**: 线性 sRGB (矩阵后)。用固定 256 长边
    面积均值探针 (tier 无关, 见 _probe_sample) 做一次 WB×CM×CC×Bradford×sRGB
    变换 (与 whitebalance Stage 共享 engine.color.cam_to_xyz, 消除旧
    build_probe_matrix 的重复矩阵合成), 在该域 log2 中位定标 —— 一次到位,
    无迭代、无场景拟合表。
  - 锚点 = 令影调曲线输出中灰 (≈gamma 117) 的线性输入 (curve_anchor_target)。
  - 基线曝光偏移 (DCP BaselineExposureOffset) 与每机 target_offset 常量计入。
  - 高光保护软滚降: EV 上限保证 clip_p 分位不越白电平 (裁切预算 100-clip_p %),
    叠加 soft_highlight_rolloff 肩部承接 —— 高光平滑滚降而非硬裁。

参数:
  mode           "auto"(默认) | "off" | ev 数值
  target         显式锚点 log2 (None = 由 DCP 曲线反推)
  target_offset  每机校准偏移 (EV, 单个常量)
  clip_p         高光保护分位 (默认 98 → 裁切预算 2%)
  highlight_budget 高光裁切预算 τ (默认 0.02): 允许进肩部/白区的探针比例,
                 约束 ev ≤ log2((1-τ)/p99)。分位取 p99 而非 p98: 实测
                 0355/5236/0352 三样张 p98→p99 跳变最高 +40% (5236
                 0.178→0.250), p99 对镜面/灯光尖峰更敏感, 作裁切预算
                 哨兵漏报更少; 与 clip_p 软帽取 min 叠加。注意平顶高光
                 场景 (大片均匀亮部) 两种分位帽都不绑定, 该类过冲由
                 标定表重拟合 (中位匹配) 负责 —— 见 tech_debt#9 诊断。
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

import logging
from pathlib import Path

import numpy as np

from ..pipeline.graph import Stage, StageContext, DOMAIN_LINEAR_CAM, register_stage
from ..core.curves import curve_anchor_target
from ..core import calibration_store

_LOGGER = logging.getLogger(__name__)

LOG2_GRAY = float(np.log2(0.18))  # ≈ -2.474 (无 DCP 时的回退锚点)

# t100 spike 高光钳界放宽 (仅标定表路径生效; 锚定回退路径已有两道闸保护组):
#   RAW 探针 p99 ≥ 1.0（传感器真实饱和, 相机自身 clip 必 >10% —— DSC_0707
#   实测 cam=10.4%）且场景中位偏暗 (med_log2 ≤ -3.3, 亮点集中型 spike; 平顶
#   亮景 med 高不触发) 时, 标定表 EV 对这类尖峰场景偏保守 (0707 dL=-9, 我们
#   比相机少钳 3.3pt), 允许有界提亮向相机对齐 (实测 +0.15 EV: 0707 dL
#   -9.1→-3.5 入带, clip 7.0→8.0% 仍低于相机 10.4% 不越钳)。
_SPIKE_P99_MIN = 1.0    # 探针 p99 饱和阈值 (线性域)
_SPIKE_MED_MAX = -3.3   # 场景中位 log2 上限 (spike 判别: 亮点集中)
_SPIKE_EV_LIFT = 0.15   # 有界提亮幅度 (EV), max_ev 内钳位

# 每机曝光标定文件 (tools/fit_target_offset.py --write 生成):
#   {"cal_table": [[m_log2, ev], ...]} —— 场景自适应表: 线性中位亮度 → 所需 EV。
#   相机预览曝光是场景自适应的 (暗场景保暗), 单常量无法复现; 表结点 ≥3 时
#   曝光 Stage 查表 (否则回退锚点 + target_offset)。
# 文件读取统一走 core.calibration_store (mtime+size 失效 + 负缓存 + 线程安全);
# _cached_offset/_cached_table 保留为模块级 memo (兼容既有测试对这两个符号的
# 重置用法), memo 失效时以 refresh=True 强制读盘 —— 与旧实现"memo 置空即重读
# 磁盘"的语义一致。
_CAL_FILE = Path(__file__).resolve().parent.parent / "target_offset.json"
_cached_offset: float | None = None
_cached_table: tuple | None = None
# mode 非法类型 (bool/容器等) 的一次性告警去重 (按类型名; _reset_caches 清空)。
_MODE_TYPE_WARNED: set = set()


def _reset_caches() -> None:
    """测试隔离钩子: 还原本模块缓存初始态, 并一并重置 calibration_store。"""
    global _cached_offset, _cached_table
    _cached_offset = None
    _cached_table = None
    _MODE_TYPE_WARNED.clear()
    calibration_store.reset()


def _load_target_offset() -> float:
    """读每机 target_offset 标定 (文件不存在 → 0.0)。"""
    global _cached_offset
    if _cached_offset is None:
        doc = calibration_store.load_json(_CAL_FILE, refresh=True)
        try:
            _cached_offset = 0.0 if doc is None else float(
                doc.get("target_offset", 0.0))
        except Exception:
            _cached_offset = 0.0
    return _cached_offset


def _load_cal_table() -> tuple | None:
    """读场景自适应曝光标定表; 无表/非法 → None。

    支持两种格式 (各行长度须一致):
      一维 [[m_log2, ev], ...]        → 返回 (xs, ys), med 列严格递增;
      二维 [[m_log2, wb_B, ev], ...]  → 返回 (xs, ws, ys)。
    二维语义: wb_B = 蓝/绿白平衡比 (camera_wb[2]/camera_wb[1]) —— 同一亮
    度下钨丝灯/日光场景所需补偿 EV 不同, 以此作第二插值键。加载时按
    (med, wb) 排序规范化 (同 med 分段内 wb 升序即可, 不要求全表严格),
    相同 med 结点折叠取均值以保证 med 主键插值合法。结点 <3 或含非有限
    值 → None。
    """
    global _cached_table
    if _cached_table is None:
        _cached_table = False
        doc = calibration_store.load_json(_CAL_FILE, refresh=True)
        if doc is not None:
            try:
                tbl = doc.get("cal_table")
                if tbl and len(tbl) >= 3:
                    widths = {len(t) for t in tbl}
                    if widths == {2}:
                        rows = sorted((float(t[0]), float(t[1])) for t in tbl)
                        xs = np.array([r[0] for r in rows], dtype=np.float64)
                        ys = np.array([r[1] for r in rows], dtype=np.float64)
                        if (np.all(np.diff(xs) > 0)
                                and np.all(np.isfinite(xs))
                                and np.all(np.isfinite(ys))):
                            _cached_table = (xs, ys)
                    elif widths == {3}:
                        arr = np.array(
                            sorted((float(t[0]), float(t[1]), float(t[2])) for t in tbl),
                            dtype=np.float64)
                        if np.all(np.isfinite(arr)):
                            xs, ws, ys = [], [], []
                            for x in np.unique(arr[:, 0]):
                                sel = arr[arr[:, 0] == x]
                                xs.append(float(x))
                                ws.append(float(sel[:, 1].mean()))
                                ys.append(float(sel[:, 2].mean()))
                            _cached_table = (np.array(xs), np.array(ws), np.array(ys))
            except Exception:
                _cached_table = False
    return _cached_table if _cached_table else None


def _cal_ev(med: float, table: tuple, wb_b: float | None) -> float:
    """查标定表 EV。

    一维表: 对 med 全表线性插值。
    二维表 (最简正确版):
      1) med 主键: 全表对 med 线性插值得基准 EV;
      2) wb 二次: 若给出 wb_b 且 |结点med - med| <= 0.3 的邻域结点 >=2 个,
         在邻域内按 wb_B 线性插值取代基准 (wb 越界由 np.interp 端点钳制,
         不外推); 邻域不足或未给 wb_b → 保持 med 主键结果。
    """
    if len(table) == 2:
        xs, ys = table
        return float(np.interp(med, xs, ys))
    xs, ws, ys = table
    ev = float(np.interp(med, xs, ys))
    if wb_b is None:
        return ev
    near = np.abs(xs - med) <= 0.3
    if int(near.sum()) >= 2:
        wl, yl = ws[near], ys[near]
        order = np.argsort(wl, kind="stable")
        return float(np.interp(wb_b, wl[order], yl[order]))
    return ev


def _luma_proxy(cam_rgb: np.ndarray) -> np.ndarray:
    """相机空间亮度代理 (仅 prof=None 回退时用于曝光决策)。"""
    return (0.25 * cam_rgb[:, :, 0] + 0.5 * cam_rgb[:, :, 1]
            + 0.25 * cam_rgb[:, :, 2]).astype(np.float32)


# 探针固定网格长边: ≈ 默认预览档 1024 的 1/4 (旧 ::4 跨步在默认档的
# 有效探针分辨率), 保持"1/4 探针"的分辨率语义不变。
_PROBE_LONG_EDGE = 256


def _probe_sample(cam: np.ndarray) -> np.ndarray:
    """探针取样: 任意 tier 图 → 固定 256 长边网格的面积均值块。

    跨 tier 一致性来源 (修复 tier 间曝光决策口径漂移): 旧实现直接在
    **当前 tier 图**上 cam[::4,::4] 跨步取点, 采样网格随 tier 尺度变化 ——
    同一 RAW 在 512/1024/2048/全尺寸档取到的是不同物理位置、不同 resize
    深度的点样本, 逐点噪声/高频未被同等平均, 中位/分位统计随档漂移,
    EV 决策在 preview 与 export 间不一致 (用户预览调好的画面导出后
    曝光漂移)。面积均值块近似是 resize 不变量 (INTER_AREA 块均值对
    resize 级联近似可交换: decode→tier→probe ≈ decode→probe), 因此把
    探针网格**钉死在帧坐标** (长边 256): 任何 tier 的探针都逼近同一组
    物理块的面积均值, 统计量与 tier 无关 (实测 med 档间散度 ~0.015
    log2 → ~0.001; 默认 1024 档 EV 不变, 详见
    tests/unit/test_exposure_tier_consistency.py)。

    输入长边 ≤ 256 (单测小图/低分辨率) 时回退旧 ::4 跨步取样, 兼容既有
    调用方; cv2 不可用时同样回退 (保持探针可用性优先于跨档一致性)。
    """
    h, w = cam.shape[:2]
    long_edge = max(h, w)
    if long_edge <= _PROBE_LONG_EDGE:
        return cam[::4, ::4]
    scale = _PROBE_LONG_EDGE / float(long_edge)
    try:
        import cv2
        return cv2.resize(np.ascontiguousarray(cam),
                          (max(1, int(round(w * scale))),
                           max(1, int(round(h * scale)))),
                          interpolation=cv2.INTER_AREA)
    except Exception:
        return cam[::4, ::4]


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
    """固定网格面积均值探针: 相机RGB → 线性 sRGB (与 whitebalance Stage 同
    链路), 返回亮度。

    取样经 _probe_sample 规范到帧坐标固定网格 (tier 无关, 一致性来源见其
    docstring); 共享 engine.color.cam_to_xyz, 消除旧 build_probe_matrix 的
    重复矩阵合成 (旧实现误用 ForwardMatrix 且手工拼 XYZ→sRGB/Bradford 矩阵)。
    """
    from ..core.color import cam_to_xyz
    from .white_balance import auto_wb_linear
    from ..core.io import camera_neutral_wb

    small = _probe_sample(cam)
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
        # 高光裁切预算 τ ∈ [0, 0.2]: 0 关闭预算约束
        "highlight_budget": {"type": "float", "min": 0.0, "max": 0.2},
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
                "clip_p": 98.0, "highlight_budget": 0.02,
                "max_ev": 2.5, "rolloff_knee": 0.9,
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
        elif (isinstance(mode, (int, float)) and not isinstance(mode, bool)
              and mode != "auto"):
            # L2 bool 陷阱: bool 是 int 子类, 不排除会把 mode=True 误当
            # ev=1.0; bool 与其他非法类型 (容器等) 落入 auto 分支并一次性告警。
            ev = float(mode)
        else:
            if (isinstance(mode, bool)
                    or not isinstance(mode, (int, float, str, type(None)))):
                tname = type(mode).__name__
                if tname not in _MODE_TYPE_WARNED:
                    _MODE_TYPE_WARNED.add(tname)
                    _LOGGER.warning(
                        "[exposure] mode 类型非法: %s=%r (合法: \"auto\"|\"off\"|"
                        "\"baseline\"|EV 数值), 回退 auto", tname, mode)
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
        # 探针: 影调级消费的线性 sRGB 域亮度 (固定网格面积均值, tier 无关)
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
            wb_b = None
            if len(table) == 3:
                wb = ctx.state.get("camera_wb")
                if wb is not None:
                    try:
                        wb_b = float(wb[2]) / max(float(wb[1]), 1e-9)
                    except Exception:
                        wb_b = None
            ev = _cal_ev(med, table, wb_b)
            ctx.state["ev_mode"] = (
                "cal_table_2d" if len(table) == 3 and wb_b is not None else "cal_table")
            # t100 spike 高光钳界放宽: 探针 p99 真实饱和 + 中位偏暗的尖峰景,
            # 相机同景必大量 clip (DSC_0707 cam=10.4%), 表 EV 偏保守 → 有界提亮。
            # 判定用全图探针 (与 exposure 测光相关), p99/med 均取线性 sRGB 域。
            p99_y = float(np.percentile(y, 99.0))
            if p99_y >= _SPIKE_P99_MIN and med <= _SPIKE_MED_MAX:
                ev = min(ev + _SPIKE_EV_LIFT, float(self.p(ctx, "max_ev")))
                ctx.state["ev_spike_lift"] = True
        else:
            ctx.state["ev_mode"] = "anchor"
        # 无标定表回退保护组 (table is None 才生效; 标定表路径的均值匹配
        # 拟合已内含高光感知目标, 运行时哨兵不得二次钳制 —— corpus_xiamen高调案例
        # 0847: 探针 p98=p99≈1.0 时两道闸曾把合法提亮钳死致 dL=-55,
        # 相机同景容纳 clip 17.9%):
        #   低光保护 (ADR-06 暗场景保暗): 正向 EV 按场景暗度 smoothstep 收敛;
        #   高光两道闸 (tech_debt#9): 软帽 log2(1/p_clip_p) 与高光预算
        #   log2((1-τ)/p99) 取 min, 防锚定模式失控提亮 (分位选 p99 依据见
        #   模块 docstring)。
        if table is None:
            clip_p = float(self.p(ctx, "clip_p"))
            p_hi = float(np.percentile(y, clip_p))
            if p_hi > 0:
                ev = min(ev, np.log2(1.0 / p_hi))
            tau = float(self.p(ctx, "highlight_budget"))
            if tau > 0.0:
                p_b = float(np.percentile(y, 99.0))
                if p_b > 0:
                    ev = min(ev, np.log2(max(1.0 - tau, 0.0)
                                         / max(p_b, 1e-9)))
            if ev > 0.0:
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
