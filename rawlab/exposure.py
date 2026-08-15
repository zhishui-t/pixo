"""曝光修正闭环 (阶段2) —— 确定性规则, 不依赖 LLM。

流程: 渲染(half_size) → 主体亮度分析 → ΔEV 计算 → 重新渲染验证 → 收敛。

决策规则 (计划书 §阶段2):
  - 主体亮度 L_sub: 人脸优先, 无脸用全图中位亮度
  - 目标亮度 L_tar = 115 (0-255 sRGB)
  - ΔEV = log2((L_tar / L_cur) ^ 2.2)     # gamma 域测量, 换算线性域
  - 高光溢出 >3% (像素 >250) → 负向修正减半 (压高光保护)
  - 迭代 ≤3 轮, 每轮 |ΔL| < 8 停止
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class ExposureStats:
    """单张渲染图的曝光分析结果。"""
    luma_median: float = 0.0        # 全图中位亮度 (0-255)
    luma_mean: float = 0.0          # 全图均值亮度
    subject_luma: float = 0.0       # 主体亮度 (人脸优先, 无脸=中位)
    highlight_pct: float = 0.0      # 高光溢出占比 (像素>250)
    shadow_pct: float = 0.0         # 暗部裁切占比 (像素<5)
    luma_p95: float = 0.0           # 亮度 95 分位 (高光保护预测用)
    face_found: bool = False
    subject_used: bool = False      # 是否用主体框而非全图中位

    def summary(self) -> str:
        return (f"L_med={self.luma_median:.0f} L_sub={self.subject_luma:.0f} "
                f"hclip={self.highlight_pct*100:.1f}% sclip={self.shadow_pct*100:.1f}%")


def zone_metrics(rgb8: np.ndarray, grid: int = 6) -> Dict:
    """6×6 分区曝光分析 (用户要求: 分区小一点)。

    每格输出: 中位亮度 / 均值 / 高光溢出占比 / 暗部占比。
    返回 {"grid": 6, "zones": [[...]], "map": 每格中位亮度 6x6}
    """
    h, w = rgb8.shape[:2]
    gray = cv2.cvtColor(rgb8, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gz, zones, map2d = [], [], []
    for gy in range(grid):
        row_z, row_m = [], []
        for gx in range(grid):
            y0, y1 = int(h * gy / grid), int(h * (gy + 1) / grid)
            x0, x1 = int(w * gx / grid), int(w * (gx + 1) / grid)
            cell = gray[y0:y1, x0:x1]
            med = float(np.median(cell))
            hi = float((cell > 250).mean())
            lo = float((cell < 5).mean())
            row_z.append({"med": round(med, 1), "mean": round(float(cell.mean()), 1),
                          "hi": round(hi, 4), "lo": round(lo, 4)})
            row_m.append(med)
        zones.append(row_z)
        map2d.append(row_m)
    return {"grid": grid, "zones": zones, "map": map2d}


def exposure_stats_from_zones(zone_map: List[List[float]], target: float = 115.0) -> float:
    """由 6×6 分区亮度推导曝光修正 EV。

    取分区亮度中位数 (稳健, 抗主体偏移), 用中位数作为"画面整体亮度"。
    """
    meds = np.array(zone_map, dtype=np.float32)
    l_cur = float(np.median(meds))
    if l_cur <= 0:
        return 0.0
    ev = math.log2((target / l_cur) ** 2.2)
    return ev


def analyze_exposure(rgb8: np.ndarray,
                     subject_boxes: Optional[List[List[float]]] = None,
                     face_boxes: Optional[List[List[float]]] = None) -> ExposureStats:
    """分析渲染图 (8bit RGB) 的曝光指标。

    subject_boxes / face_boxes: 归一化 [l, t, r, b] 列表 (来自 YOLOE/人脸检测)。
    主体亮度 = 人脸框优先 (平均), 无人脸用最大主体框, 都无 → 全图中位。
    """
    h, w = rgb8.shape[:2]
    gray = cv2.cvtColor(rgb8, cv2.COLOR_RGB2GRAY).astype(np.float32)

    stats = ExposureStats()
    stats.luma_median = float(np.median(gray))
    stats.luma_mean = float(gray.mean())
    stats.highlight_pct = float((gray > 250).mean())
    stats.shadow_pct = float((gray < 5).mean())
    stats.luma_p95 = float(np.percentile(gray, 95))

    def box_luma(box: List[float]) -> float:
        l, t, r, b = box
        y0, y1 = int(t * h), max(int(t * h) + 1, int(b * h))
        x0, x1 = int(l * w), max(int(l * w) + 1, int(r * w))
        y0, y1 = max(0, y0), min(h, y1)
        x0, x1 = max(0, x0), min(w, x1)
        if y1 <= y0 or x1 <= x0:
            return 0.0
        return float(gray[y0:y1, x0:x1].mean())

    if face_boxes:
        lumas = [box_luma(b) for b in face_boxes]
        lumas = [v for v in lumas if v > 0]
        if lumas:
            stats.subject_luma = float(np.mean(lumas))
            stats.face_found = True
            stats.subject_used = True
            return stats

    if subject_boxes:
        # 取最大面积主体框
        big = max(subject_boxes, key=lambda b: (b[2]-b[0]) * (b[3]-b[1]))
        v = box_luma(big)
        if v > 0:
            stats.subject_luma = v
            stats.subject_used = True
            return stats

    stats.subject_luma = stats.luma_median
    return stats


def compute_exposure_ev(stats: ExposureStats,
                        target_luma: float = 115.0,
                        highlight_trigger: float = 0.03,
                        max_ev: float = 2.0) -> float:
    """计算曝光修正量 ΔEV。

    主体亮度在 sRGB gamma 域测量, ΔEV = log2((L_tar/L_cur)^2.2):
      线性域亮度比 = (L_tar/L_cur)^2.2, EV = log2(线性比)。
    高光保护:
      - 负向修正 (压暗) 时若高光已溢出 → 减半 (防过暗)
      - 正向修正 (提亮) 时, 高光溢出像素会随提亮放大 → 限制提亮量
        (近似: 提亮 ev 后溢出 = 原像素中 > 250/2^ev 的占比, 超阈值则限 EV)
    """
    l_cur = stats.subject_luma
    if l_cur <= 0:
        return 0.0
    linear_ratio = (target_luma / l_cur) ** 2.2
    ev = math.log2(linear_ratio)
    if ev < 0 and stats.highlight_pct > highlight_trigger:
        ev = ev / 2.0
    # 正向提亮: 用 p95 预测提亮后的高光溢出, 超阈值则限 EV (不归零)
    #   2026-08-14 修复: p95 略低于 250 时 (如 245), 限制到"不爆"的 EV
    #   而非 max(ev_limit, 0)=0 卡死 (L=91 提不上去)。
    if ev > 0 and stats.luma_p95 > 200:
        # 目标: 提亮后 p95 不超 250 → ev <= log2(250/p95)
        ev_hi = math.log2(250.0 / max(stats.luma_p95, 1.0))
        if ev_hi < ev:
            # 允许小幅提亮: 至少 0.2EV (p95 到 250 只影响极小比例高光)
            ev = max(ev_hi, 0.2)
    return float(max(-max_ev, min(max_ev, ev)))


def run_exposure_loop(render_fn, raw_path: str,
                      subject_boxes: Optional[List[List[float]]] = None,
                      face_boxes: Optional[List[List[float]]] = None,
                      target_luma: float = 115.0,
                      max_rounds: int = 3,
                      tolerance: float = 8.0,
                      max_ev: float = 2.0) -> Dict:
    """曝光迭代闭环。

    render_fn(raw_path, ev) -> 8bit RGB 渲染图
    每轮: 渲染 → 分析 → ΔEV → 累计 → 重新渲染, 直到 |ΔL| < tolerance。
    """
    history: List[Dict] = []
    total_ev = 0.0
    converged = False
    final_stats: Optional[ExposureStats] = None

    for rnd in range(1, max_rounds + 1):
        rgb = render_fn(raw_path, total_ev)
        st = analyze_exposure(rgb, subject_boxes, face_boxes)
        ev = compute_exposure_ev(st, target_luma, max_ev=max_ev)
        delta_l = st.subject_luma - target_luma
        history.append({
            "round": rnd, "ev": round(total_ev, 3),
            "subject_luma": round(st.subject_luma, 1),
            "delta_ev": round(ev, 3),
            "delta_l": round(delta_l, 1),
            "highlight_pct": round(st.highlight_pct, 4),
        })
        if abs(delta_l) < tolerance:
            converged = True
            final_stats = st
            break
        total_ev += ev
        final_stats = st

    return {
        "converged": converged,
        "final_ev": round(total_ev, 3),
        "rounds": len(history),
        "history": history,
        "final_stats": final_stats,
    }
