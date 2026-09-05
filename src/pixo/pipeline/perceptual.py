"""感知差异度量 —— JND 早停的 ΔE2000 底座（纯 numpy，零 torch 纪律）。

``linear_srgb_to_lab`` / ``delta_e_2000`` 自 scripts/eval_rp_ccm_ab.py 抽取
为 src 可复用实现（该脚本改为引用本模块，单一实现防漂移）。用途：

  - :class:`SinglePhotoLoop` JND 感知收敛早停：连续 N 轮预览间 median
    ΔE2000 低于人眼察觉阈值（即使美学分未达上限）强制终止，防过度修图；
  - 评估脚本的双轨 ΔE2000 报告（scripts/eval_rp_ccm_ab.py）。

实现逐项对齐 Sharma, Wu & Dalal 2005 式 (1)-(15)（含 G/T/RT 项）；文献
公开校验对见 tests/unit/test_perceptual_convergence.py 与脚本 selftest。
"""
from __future__ import annotations

import numpy as np

from ..render.core.calibration import SRGB_TO_XYZ_D65

__all__ = [
    "gamma_srgb_to_linear",
    "linear_srgb_to_lab",
    "delta_e_2000",
    "delta_e_median",
    "JndConvergenceTracker",
]

_EPS_K = 216.0 / 24389.0    # CIE Lab 常数 (6/29)³
_KAPPA = 24389.0 / 27.0     # CIE Lab 常数
# sRGB(D65) 线性 → XYZ(D65) (行向量语义) 与 Lab 参考白
_M_SRGB_TO_XYZ = np.asarray(SRGB_TO_XYZ_D65, dtype=np.float64)
_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)


def gamma_srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """gamma sRGB (.., 3) → linear sRGB。负输入按 0 处理（与
    render.core.oklab._srgb_to_linear 同式，避免负底幂 NaN）。出口 float64。"""
    c = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, None)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_srgb_to_lab(lin: np.ndarray) -> np.ndarray:
    """线性 sRGB (...,3) → CIELAB (D65 参考白)。出口 float64。"""
    xyz = np.asarray(lin, dtype=np.float64) @ _M_SRGB_TO_XYZ.T / _D65
    f = np.where(xyz > _EPS_K, np.cbrt(xyz), (_KAPPA * xyz + 16.0) / 116.0)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116.0 * fy - 16.0,
                     500.0 * (fx - fy),
                     200.0 * (fy - fz)], axis=-1)


def delta_e_2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 色差 (Sharma, Wu & Dalal 2005, DST 权重沿用公式原论文)。

    lab1/lab2: (...,3) 同形; 返回 (...,) ΔE00。实现逐项对齐 Sharma 2005
    式 (1)-(15) (含 G/apa/T/RT 项), 角度量全部以度计算后转弧度进三角函数。
    """
    l1, a1, b1 = np.asarray(lab1, np.float64)[..., 0], \
                 np.asarray(lab1, np.float64)[..., 1], \
                 np.asarray(lab1, np.float64)[..., 2]
    l2, a2, b2 = np.asarray(lab2, np.float64)[..., 0], \
                 np.asarray(lab2, np.float64)[..., 1], \
                 np.asarray(lab2, np.float64)[..., 2]
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    cbar = 0.5 * (c1 + c2)
    cbar7 = cbar ** 7
    g = 0.5 * (1.0 - np.sqrt(cbar7 / (cbar7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    h1p = np.where((a1p == 0.0) & (b1 == 0.0), 0.0, h1p)
    h2p = np.where((a2p == 0.0) & (b2 == 0.0), 0.0, h2p)

    dlp = l2 - l1
    dcp = c2p - c1p
    dh = h2p - h1p
    dh = np.where(c1p * c2p == 0.0, 0.0,
                  np.where(np.abs(dh) <= 180.0, dh,
                           np.where(dh > 180.0, dh - 360.0, dh + 360.0)))
    dhp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2.0)

    lbarp = 0.5 * (l1 + l2)
    cbarp = 0.5 * (c1p + c2p)
    hsum = h1p + h2p
    hbarp = np.where(c1p * c2p == 0.0, hsum,
                     np.where(np.abs(h1p - h2p) <= 180.0, 0.5 * hsum,
                              np.where(hsum < 360.0, 0.5 * (hsum + 360.0),
                                       0.5 * (hsum - 360.0))))
    t = (1.0 - 0.17 * np.cos(np.radians(hbarp - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hbarp))
         + 0.32 * np.cos(np.radians(3.0 * hbarp + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hbarp - 63.0)))
    dtheta = 30.0 * np.exp(-(((hbarp - 275.0) / 25.0) ** 2))
    cbarp7 = cbarp ** 7
    rc = 2.0 * np.sqrt(cbarp7 / (cbarp7 + 25.0 ** 7))
    sl = 1.0 + 0.015 * (lbarp - 50.0) ** 2 / np.sqrt(20.0 + (lbarp - 50.0) ** 2)
    sc = 1.0 + 0.045 * cbarp
    sh = 1.0 + 0.015 * cbarp * t
    rt = -np.sin(np.radians(2.0 * dtheta)) * rc
    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp / sh) ** 2
                   + rt * (dcp / sc) * (dhp / sh))


def delta_e_median(rgb_a: np.ndarray, rgb_b: np.ndarray) -> float:
    """两幅同形 gamma sRGB 图 (H,W,3) 的 median ΔE2000（标量 float）。

    入参为显示域 gamma sRGB（render_preview 出口域）；内部转 linear →
    Lab 再逐像素 ΔE2000 取中位数（中位数对高光裁切等局部极端差异稳健，
    作"整图是否人眼可察"的保守统计量）。
    """
    a = np.asarray(rgb_a)
    b = np.asarray(rgb_b)
    if a.shape != b.shape:
        raise ValueError(f"两图需同形，实际 {a.shape} vs {b.shape}")
    lab_a = linear_srgb_to_lab(gamma_srgb_to_linear(a))
    lab_b = linear_srgb_to_lab(gamma_srgb_to_linear(b))
    return float(np.median(delta_e_2000(lab_a, lab_b)))


class JndConvergenceTracker:
    """连续 ``window`` 次 median ΔE 低于 ``threshold`` 判收敛。

    任一次 ≥ 阈值即清零计数（收敛判定要求**连续**低于阈值的窗口）；
    ``history`` 留存逐次 ΔE 供 trace 观测。
    """

    def __init__(self, threshold: float, window: int) -> None:
        if not (float(threshold) > 0.0):
            raise ValueError(f"jnd_threshold 须为正数，实际 {threshold!r}")
        if int(window) < 1:
            raise ValueError(f"jnd_window 须 ≥1，实际 {window!r}")
        self.threshold = float(threshold)
        self.window = int(window)
        self.count = 0
        self.history: list[float] = []

    @property
    def converged(self) -> bool:
        return self.count >= self.window

    def update(self, delta_median: float) -> bool:
        """喂入一次迭代间 ΔE median，返回是否已达收敛窗口。"""
        value = float(delta_median)
        if not np.isfinite(value):
            # 非有限值视为"不可比"（渲染异常）：清零不计数，不误判收敛
            self.count = 0
            self.history.append(value)
            return False
        self.history.append(value)
        if value < self.threshold:
            self.count += 1
        else:
            self.count = 0
        return self.converged
