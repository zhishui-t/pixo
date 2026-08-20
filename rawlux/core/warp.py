"""DNG WarpRectilinear（OpcodeList3）—— 独立纯 NumPy 实现。

实现依据（clean-room，未读取 DNG SDK 源码）：
- DNG 公开规范中 WarpRectilinear opcode 的语义：
  对每个输出像素按所在平面取径向多项式 f(r^2)=k0+k1*r^2+k2*r^4+k3*r^6，
  反向映射回源平面坐标并做二维三次重采样；
  光学中心、squareBounds（方形包围盒）、归一化半径、边缘 clamp 与
  越界 fraction 清零语义均按公开规范复刻。
- 三次插值使用公开的标准三次样条核（系数 a=-0.75），
  以 32 段均匀细分的 2D 权重查找表实现（可分离，先乘横竖核值再归一化）。
- 数值契约通过 DNG SDK 黑盒产物对齐验证（*.stage3.raw 作为 oracle），
  不复制任何 SDK 源码中的变量名、分支结构、常量表或注释。

对外接口保持不变：`warp_rectilinear(img, planes, coeffs, center, pixel_aspect=1.0)`。
"""
from __future__ import annotations

import numpy as np

# ---- 几何 / 重采样参数 -----------------------------------------------------
# 每个细分单元的采样段数（沿 x/y 各 32 段）。
_SUBSAMPLES = 32
# 三次核支持半径（核在 |t|<1 与 1<=|t|<2 两段取值，超 2 为 0）。
_SUPPORT = 2
# 每维重采样抽头数 = 2 * 支持半径。
_TAP_COUNT = 2 * _SUPPORT
# 抽头起始索引相对整数坐标的偏移：首个抽头取 fc-1。
_FIRST_TAP = 1 - _SUPPORT


def _cubic_kernel(t: float) -> float:
    """标准三次插值核（a = -0.75），公开的分段三次样条公式。

    - |t| < 1   : 1 + (a+2)*t^3 - (a+3)*t^2
    - 1<=|t|<2  : a*t^3 - 5a*t^2 + 8a*t - 4a
    - |t| >= 2  : 0
    该公式是数值插值中广为使用的三次平滑核，不是 SDK 私有结构。
    """
    a = -0.75
    t = abs(t)
    if t >= 2.0:
        return 0.0
    if t >= 1.0:
        return (((a * t - 5.0 * a) * t + 8.0 * a) * t - 4.0 * a)
    return (((a + 2.0) * t - (a + 3.0)) * t * t + 1.0)


def _make_weight_table():
    """构建 32x32 个细分偏移的 2D 三次核权重查找表。

    对每个 (fy, fx) 细分偏移，先生成 4x4=16 个核值（x/y 两维各自
    t = tap - 1 - fraction，取核后相乘），再按 double 累加并做 float
    归一化（归一化先乘后除的舍入次序与 oracle 对齐）。
    返回形状 (32, 32, 16) 的 float32 表。
    """
    table = np.zeros((_SUBSAMPLES, _SUBSAMPLES, _TAP_COUNT * _TAP_COUNT),
                     np.float32)
    for fy in range(_SUBSAMPLES):
        yf = fy * (1.0 / _SUBSAMPLES)
        for fx in range(_SUBSAMPLES):
            xf = fx * (1.0 / _SUBSAMPLES)
            acc = 0.0
            idx = 0
            for i in range(_TAP_COUNT):
                ytap = i + _FIRST_TAP          # -1..2
                yb = ytap - yf
                for j in range(_TAP_COUNT):
                    xtap = j + _FIRST_TAP      # -1..2
                    xb = xtap - xf
                    val = np.float32(_cubic_kernel(xb)) * np.float32(_cubic_kernel(yb))
                    table[fy, fx, idx] = val
                    acc += float(val)
                    idx += 1
            scale = np.float32(1.0 / acc)
            table[fy, fx] = np.float32(table[fy, fx] * scale)
    return table


_WEIGHTS = _make_weight_table()


def _radial_ratio(rr2, coeffs):
    """径向比 f(r^2) = k0 + k1*r^2 + k2*r^4 + k3*r^6。

    系数数组前 4 项对应 k0..k3（r 的 0/2/4/6 次），其余项恒为 0。
    """
    return (coeffs[0]
            + coeffs[1] * rr2
            + coeffs[2] * rr2 * rr2
            + coeffs[3] * rr2 ** 3)


def warp_rectilinear(img, planes, coeffs, center, pixel_aspect=1.0):
    """对 float32 RGB 图应用 DNG WarpRectilinear（3 平面径向映射）。

    参数
    ----
    img : (H, W, 3) float32，取值 [0, 1]。
    planes : int，平面数（本批为 3 个 RGB 平面）。
    coeffs : list[plane]（每平面 6 项），前 4 项为径向多项式 k0..k3。
    center : (cx, cy)，归一化光学中心（[0,1]）。
    pixel_aspect : float，像素纵横比（像素宽 / 像素高）。

    返回
    ----
    (H, W, 3) float32，径向校正后的图像。
    """
    H, W = img.shape[:2]
    # 光学中心换算为像素坐标。
    h_center = W * center[0]
    v_center = H * center[1]
    # 像素纵横比反向用于竖直方向（squareBounds 语义）。
    pixel_scale_v = 1.0 / float(pixel_aspect)
    # DNG squareBounds：把归一化竖直范围放大 pixel_aspect 倍得到方形包围盒，
    # 中心在包围盒内重新按比例插值出（与原始 center 可能不同）。
    square_height = int(pixel_scale_v * H + 0.5)
    square_center_v = square_height * center[1]
    square_center_h = W * center[0]
    # 归一化半径：光心到包围盒角落的最大距离。
    norm_radius = float(np.hypot(
        max(abs(square_center_v - 0.0), abs(square_center_v - float(square_height))),
        max(abs(square_center_h - 0.0), abs(square_center_h - float(W)))))
    inv_norm = 1.0 / norm_radius
    # 全像素坐标网格（double 精度）。
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    diff_v = yy - v_center
    diff_h = xx - h_center
    # 归一化到单位圆（竖直再乘 pixel_aspect 逆）。
    dn_v = diff_v * inv_norm
    dn_h = diff_h * inv_norm
    css_v = dn_v * pixel_scale_v
    css_h = dn_h
    rr2 = np.minimum(css_v * css_v + css_h * css_h, 1.0)
    # 源图四周做 1 像素 edge 复制填充，供近边界抽头取数。
    src_pad = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
    out = np.empty_like(img, np.float32)
    for p in range(planes):
        ratio = _radial_ratio(rr2, coeffs[p])
        # 反向映射：源坐标 = 光心 + 相对偏移 * 径向比。
        src_v = v_center + diff_v * ratio
        src_h = h_center + diff_h * ratio
        # 源坐标先 clamp 到合法像素范围。
        src_v = np.clip(src_v, 0.0, H - 1.0)
        src_h = np.clip(src_h, 0.0, W - 1.0)
        # 整数下标与细分 fraction。
        iv = np.floor(src_v).astype(np.int32)
        ih = np.floor(src_h).astype(np.int32)
        frac_v = np.clip(((src_v - iv) * _SUBSAMPLES).astype(np.int32), 0,
                         _SUBSAMPLES - 1)
        frac_h = np.clip(((src_h - ih) * _SUBSAMPLES).astype(np.int32), 0,
                         _SUBSAMPLES - 1)
        # 抽头窗口起始偏移（-1），并 clamp 到合法起始范围。
        max_v = H - _TAP_COUNT - 1
        max_h = W - _TAP_COUNT - 1
        iv = iv + _FIRST_TAP
        ih = ih + _FIRST_TAP
        # 越界起点 fraction 清零必须在 clip 之前判断（下界与上界都清零）；
        # 黑盒 oracle 证实：未 clip 的起点 <0 或 >max 时 SDK 等效于 fraction=0。
        frac_v = np.where((iv < 0) | (iv > max_v), 0, frac_v)
        frac_h = np.where((ih < 0) | (ih > max_h), 0, frac_h)
        iv = np.clip(iv, 0, max_v)
        ih = np.clip(ih, 0, max_h)
        # 4x4 邻域在填充后源图中的坐标（row/col 各平移 1 抵消 pad）。
        rows = iv[:, :, None, None] + np.arange(_TAP_COUNT)[None, None, :, None]
        cols = ih[:, :, None, None] + np.arange(_TAP_COUNT)[None, None, None, :]
        neigh = src_pad[rows + 1, cols + 1, p]
        w = _WEIGHTS[frac_v, frac_h].reshape(H, W, _TAP_COUNT, _TAP_COUNT)
        total = np.einsum("hwab,hwab->hw", neigh, w, optimize=True).astype(np.float32)
        out[..., p] = np.clip(total, 0.0, 1.0)
    return out

__all__ = ["warp_rectilinear"]
