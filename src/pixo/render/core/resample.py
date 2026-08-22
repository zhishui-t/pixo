"""render.core.resample —— Stage3 双程立方重采样 (原生实现)。"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Stage3 -> final-size bicubic resize (clean-room re-implementation)
#
# 依据公开资料 (Keys 1981 "Cubic Convolution Interpolation"; 128 相位可分离
# 双程立方卷积; DNG 规范对 16-bit 采样像素走定点累加路径):
#   - 立方卷积核系数 a = -0.75
#   - 每 1/128 子像素相位生成 4 个抽头权重并归一化使权重和 = 1
#   - 16-bit 输入走定点路径 (权重放大 2^14, 整数累加, 最后右移 14)
#   - 其余输入走 float32 路径
# 数值契约经 K:\dsh-share\dng_verify 黑盒 oracle 校准。
# ---------------------------------------------------------------------------

def _bicubic_weights(x: float) -> float:
    """Keys 立方卷积核 (a=-0.75): 输入为与抽头中心的绝对距离。"""
    a = -0.75
    x = abs(x)
    if x >= 2.0:
        return 0.0
    if x >= 1.0:
        return (((a * x - 5.0 * a) * x + 8.0 * a) * x - 4.0 * a)
    return (((a + 2.0) * x - (a + 3.0)) * x * x + 1.0)


_PHASES = 128           # 每像素子像素相位数 (1/128)
_TAP_COUNT = 4          # 每相位抽头数
_FX_SCALE = 14          # 定点累加位数 (权重 2^14)


def _float_tap_table() -> np.ndarray:
    """(128,4) float32 权重表: 裸权重 -> float32 -> double 求和 -> float32 倒数 -> 再相乘归一化。"""
    tbl = np.zeros((_PHASES, _TAP_COUNT), np.float32)
    for p in range(_PHASES):
        f32 = [np.float32(_bicubic_weights(off - p / float(_PHASES)))
               for off in (-1.0, 0.0, 1.0, 2.0)]
        total = sum(float(v) for v in f32)              # double 累加
        inv = np.float32(1.0 / total)                   # float32 倒数
        for j in range(_TAP_COUNT):
            tbl[p, j] = np.float32(f32[j] * inv)
    return tbl


_W_FLOAT = _float_tap_table()


def _fixed16_tap_table() -> np.ndarray:
    """由 float32 权重表转 2^14 定点整数, 并修正让每行四抽头之和恰为 2^14。"""
    tbl = np.zeros((_PHASES, _TAP_COUNT), np.int64)
    for p in range(_PHASES):
        q = []
        for j in range(_TAP_COUNT):
            v = float(np.float64(_W_FLOAT[p, j])) * (1 << _FX_SCALE)
            q.append(int(v + 0.5) if v > 0 else int(v - 0.5))
        tbl[p] = q
        leftover = (1 << _FX_SCALE) - int(tbl[p].sum())
        center = 2 if p >= (_PHASES >> 1) else 1
        tbl[p, center] += leftover
    return tbl


_W_FIXED = _fixed16_tap_table()


def _round_to_int(v: np.ndarray) -> np.ndarray:
    """四舍五入到最近整数, 负值对称四舍五入。"""
    return np.where(v > 0, np.floor(v + 0.5), np.ceil(v - 0.5)).astype(np.int64)


def _subpixel_coords(dst_count: int, src_origin: int, src_count: int) -> np.ndarray:
    """输出像素位置 -> 源坐标(以 1/128 为单位), 中心对齐。"""
    i = np.arange(dst_count, dtype=np.float64)
    y = (i + 0.5) * src_count / dst_count - 0.5 + src_origin
    return _round_to_int(y * float(_PHASES)).astype(np.int64)


def _resample_u16(u16: np.ndarray, src_bounds, dst_size) -> np.ndarray:
    """16-bit 定点双程重采样; u16 (H,W,3) uint16, 返回 (dst_h,dst_w,3) 归一化 float。
    第一程沿行方向, 第二程沿列方向; 抽头越界时钳位到最近源像素。"""
    SH, SW = u16.shape[:2]
    t, l, b, r = src_bounds
    src_h, src_w = b - t, r - l
    dw, dh = dst_size

    rc = _subpixel_coords(dh, t, src_h)
    cc = _subpixel_coords(dw, l, src_w)
    ry = np.right_shift(rc, 7).astype(np.int32)
    rp = (rc & (_PHASES - 1)).astype(np.int32)
    cx = np.right_shift(cc, 7).astype(np.int32)
    cp = (cc & (_PHASES - 1)).astype(np.int32)

    mid = np.full((dh, SW, 3), (1 << (_FX_SCALE - 1)), np.int64)   # 舍入偏置 2^13
    for k in range(_TAP_COUNT):
        row = np.clip(ry - 1 + k, 0, SH - 1)
        mid += _W_FIXED[rp, k][:, None, None] * u16[row].astype(np.int64)
    mid = np.clip(np.right_shift(mid, _FX_SCALE), 0, 65535)

    acc = np.zeros((dh, dw, 3), np.int64)
    for k in range(_TAP_COUNT):
        col = np.clip(cx - 1 + k, 0, SW - 1)
        acc += _W_FIXED[cp, k][None, :, None] * mid[np.arange(dh)[:, None], col[None, :], :]
    acc = np.clip(np.right_shift(acc + (1 << (_FX_SCALE - 1)), _FX_SCALE), 0, 65535)
    return acc.astype(np.float32) * np.float32(1.0 / 65535.0)


def _resample_float(img: np.ndarray, src_bounds, dst_size) -> np.ndarray:
    """float32 双程重采样; img (H,W,3) float32 域 [0,1]。"""
    SH, SW = img.shape[:2]
    t, l, b, r = src_bounds
    src_h, src_w = b - t, r - l
    dw, dh = dst_size

    rc = _subpixel_coords(dh, t, src_h)
    cc = _subpixel_coords(dw, l, src_w)
    ry = np.right_shift(rc, 7).astype(np.int32)
    rp = rc & (_PHASES - 1)
    cx = np.right_shift(cc, 7).astype(np.int32)
    cp = cc & (_PHASES - 1)

    mid = None
    for k in range(_TAP_COUNT):
        row = np.clip(ry - 1 + k, 0, SH - 1)
        term = np.float32(img[row] * _W_FLOAT[rp, k][:, None, None])
        mid = term if mid is None else np.float32(mid + term)
    mid = np.clip(mid, 0.0, 1.0)

    out = None
    for k in range(_TAP_COUNT):
        col = np.clip(cx - 1 + k, 0, SW - 1)
        term = np.float32(mid[np.arange(dh)[:, None], col[None, :], :]
                          * _W_FLOAT[cp, k][None, :, None])
        out = term if out is None else np.float32(out + term)
    return np.clip(out, 0.0, 1.0)


def dng_resample(stage: np.ndarray, src_bounds, dst_size) -> np.ndarray:
    """stage (H,W,3) float32; src_bounds (t,l,b,r); dst_size (w,h)。
    对外接口与渲染管线一致: 传入 Stage3 图(域 [0,1])、裁剪 bounds 与目标尺寸。
    stage 在 x65535 下接近整数值时判定为 16-bit 采样, 走定点路径; 否则走 float32。"""
    scaled = stage * np.float32(65535.0)
    if float(np.abs(scaled - np.rint(scaled.astype(np.float64))).max()) < 0.001:
        u16 = np.clip(np.rint(scaled.astype(np.float64)), 0, 65535).astype(np.uint16)
        return _resample_u16(u16, src_bounds, dst_size)
    return _resample_float(stage, src_bounds, dst_size)

__all__ = ["dng_resample"]
