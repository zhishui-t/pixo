"""DNG Stage3 之后的影调/色彩可复用数值函数 (M1 clean-room 版).

本模块实现 DNG 渲染链路 Stage3 之后的四个无状态数值环节:
  - 曝光斜坡  (exposure_ramp)
  - sRGB 编码/解码查表  (srgb_encode / srgb_decode, 4096 项)
  - 影调表一维插值 + RGB 影调  (tone_table_interp / apply_rgb_tone)
  - HSV 查找表应用  (apply_hue_sat_map)

依据 (只使用公开材料, 不参考任何 SDK 实现源码):
  - DNG 1.4 规范: ProfileToneCurve / ProfileLookTable 章节 (控制点 -> 平滑曲线
    -> 均匀采样成查表; ProfileLookTableEncoding=1 时 V 轴按 sRGB EOTF 编码)。
  - IETF/公开 sRGB 定义: 分段幂律 EOTF (0.0031308 / 12.92 阈值)。
  - 黑盒 oracle (仅用作数值对照, 不读取其源码):
      K:/dsh-share/dng_verify/replicate/*.tone.table   (SDK 影调表 dump)
      K:/dsh-share/dng_verify/replicate/*.engine.log    (含 [lut-debug] 采样)

对外函数名与签名与本仓库其他模块 (render_base / huesat / stages.huesat /
tools.render_dcp / tools.dng_linear_probe) 一致, 保持不变。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def exposure_ramp(pp, baseline_ev):
    """曝光补偿斜坡 (黑点=0)。

    正曝光按 2^ev 放大并钳到 [0,1]; 负曝光不做放大 (斜坡恒等),
    欠曝补偿交给影调曲线处理。
    """
    gain = np.float32(2.0 ** max(0.0, float(baseline_ev)))
    return np.clip(np.asarray(pp, np.float32) * gain, 0.0, 1.0)


# ---------------------------------------------------------------------------
# 2) sRGB 编码/解码 4096 查表
#
# ProfileLookTableEncoding=1 时, DNG 的 LookTable 的 V 轴不是直接套 sRGB
# 解析式, 而是先建一张 4096 项的一维查表 (按 sRGB EOTF 均匀采样), 再对
# V 做一维查表插值。这样在阈值附近与逐点解析式会有 ~1e-5 的差异, 因此
# 这里也按"建表 + 插值"处理, 保证与 SDK dump 数值一致。
# ---------------------------------------------------------------------------
_SRGB_TABLE_N = 4096


def _srgb_encode_eval(x: float) -> float:
    """sRGB EOTF 编码 (公开定义): 低值段线性, 高值段 1.055 x^(1/2.4) - 0.055。"""
    if x <= 0.0031308:
        return x * 12.92
    return 1.055 * (x ** (1.0 / 2.4)) - 0.055


def _srgb_decode_eval(y: float) -> float:
    """sRGB EOTF 解码 (公开定义)。"""
    if y <= 0.0031308 * 12.92:
        return y * (1.0 / 12.92)
    return ((y + 0.055) * (1.0 / 1.055)) ** 2.4


def _build_srgb_tables():
    """建 4096 项 sRGB 编码/解码查表 (含末位重复元素便于线性插值)。"""
    n = _SRGB_TABLE_N
    enc = np.empty(n + 1, np.float32)
    dec = np.empty(n + 1, np.float32)
    for i in range(n + 1):
        x = i * (1.0 / n)
        enc[i] = np.float32(_srgb_encode_eval(x))
        dec[i] = np.float32(_srgb_decode_eval(x))
    # 尾部补一项查表末值, 使 x=1.0 的插值段闭合
    enc = np.append(enc, enc[-1]).astype(np.float32)
    dec = np.append(dec, dec[-1]).astype(np.float32)
    return enc, dec


_SRGB_ENC_TABLE, _SRGB_DEC_TABLE = _build_srgb_tables()


def table_interp(table, x):
    """一维查表线性插值 (x 已按 [0,1] 处理)。

    表约定: 表长比采样点数多 2 (尾端重复项), 采样口径 count = len-2。
    对越界的 idx 钳到 [0, count-1]。
    """
    table = np.asarray(table, np.float32)
    x = np.asarray(x, np.float32)
    n = np.float32(len(table) - 2)
    scaled = np.float32(x * n)
    idx = np.floor(scaled).astype(np.int32)
    lo = idx.astype(np.float32)
    fract = np.float32(scaled - lo)
    idx = np.clip(idx, 0, len(table) - 2)
    return np.float32(table[idx] * np.float32(1.0 - fract)
                      + table[idx + 1] * fract)


def srgb_encode(v):
    """线性值 [0,1] 用 4096 表插值编码; >1 的高光用解析式扩展。"""
    x = np.asarray(v, np.float32)
    out = np.empty_like(x)
    lo = x <= 1.0
    out[lo] = table_interp(_SRGB_ENC_TABLE, x[lo])
    hi = ~lo
    if np.any(hi):
        xh = np.maximum(x[hi], 1.0)
        out[hi] = np.float32(1.055 * np.power(xh.astype(np.float64), 1.0 / 2.4)
                             - 0.055)
    return out


def srgb_decode(v_enc):
    """编码值 [0,1] 用 4096 表插值解码; >1 的高光用解析式扩展。"""
    y = np.asarray(v_enc, np.float32)
    out = np.empty_like(y)
    lo = y <= 1.0
    out[lo] = table_interp(_SRGB_DEC_TABLE, y[lo])
    hi = ~lo
    if np.any(hi):
        yh = np.maximum(y[hi], 1.0)
        out[hi] = np.float32(np.power((yh.astype(np.float64) + 0.055)
                                      * (1.0 / 1.055), 2.4))
    return out


# ---------------------------------------------------------------------------
# 3) 影调表插值 + RGB 影调
#
# tone_table_interp 与 table_interp 都是同一套"一维表线性插值"语义;
# 前者用于影调 (ProfileToneCurve 采样表), 后者用于 sRGB LookTable V 轴。
# 两者数值约定一致 (表尾重复项 + 采样点数 = 表长-2)。
# ---------------------------------------------------------------------------


def tone_table_interp(table, x):
    """影调表线性插值 (语义与 table_interp 一致, 供影调环节调用)。"""
    return table_interp(table, x)


def apply_rgb_tone(pp, table):
    """RGB 影调: 对线性 ProPhoto 域图按表做逐通道影调映射。

    做法 (影调曲线在"色彩饱和的中间通道"上做主轴插值, 避免灰阶偏色):
      - 把像素按 R/G/B 值排序为 最大/中间/最小 三通道;
      - 最大、最小通道直接查影调表;
      - 中间通道按其原始值在 [min,max] 中的相对位置, 在"已影调的
        min->max 区间"上线性取值恢复。
    纯灰 (max==min) 三通道同值, 直接查一次表。
    """
    img = np.clip(np.asarray(pp, np.float32), 0.0, 1.0)
    r0, g0, b0 = img[..., 0], img[..., 1], img[..., 2]
    vmax = np.maximum(np.maximum(r0, g0), b0)
    vmin = np.minimum(np.minimum(r0, g0), b0)
    vmid = np.float32(r0 + g0 + b0) - np.float32(vmax + vmin)

    tmax = tone_table_interp(table, vmax)
    tmin = tone_table_interp(table, vmin)

    denom = np.float32(vmax - vmin)
    eq = denom == np.float32(0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.float32((vmid - vmin) / denom)
    tmid = np.where(eq, tmax, np.float32(tmin + np.float32(tmax - tmin) * frac))

    def _pick(v0):
        is_max = v0 == vmax
        is_min = v0 == vmin
        return np.where(is_max, tmax, np.where(is_min, tmin, tmid))

    out = np.empty_like(img)
    out[..., 0] = _pick(r0)
    out[..., 1] = _pick(g0)
    out[..., 2] = _pick(b0)
    return out


# ---------------------------------------------------------------------------
# 影调表加载 + 从 ProfileToneCurve 控制点自建影调表
# ---------------------------------------------------------------------------


def load_tone_table(path):
    """读取 SDK 探针 dump 的影调表 (uint32 采样点数 + float32 表体)。

    表体含采样点数+1 个值; 这里再补一个表末重复项, 使插值口径与
    tone_table_interp (表长-2) 一致。
    """
    b = Path(path).read_bytes()
    if len(b) < 8:
        raise ValueError(f"tone table too short: {path}")
    n = int(np.frombuffer(b[:4], dtype="<u4")[0])
    table = np.frombuffer(b[4:], dtype="<f4")
    if len(table) < n + 1:
        raise ValueError(f"tone table short {len(table)} < {n + 1}")
    table = table[:n + 1].astype(np.float32)
    return np.append(table, table[-1]).astype(np.float32)


def build_tonetable(x_pts, y_pts, count: int = 4096):
    """从影调控制点对 x/y (首端 0, 末端 1, 白->白契约) 自建 count 项影调表。

    做法: 自然三次样条插值穿过控制点, 再在 [0,1] 均匀取 count 个样本。
    这是与 SDK `.tone.table` dump 对齐的 self-implement 影调表。
    """
    xs = np.asarray(x_pts, np.float64)
    ys = np.asarray(y_pts, np.float64)
    n = len(xs)
    if n < 2 or not (xs[0] == 0.0 and xs[-1] == 1.0):
        raise ValueError("tonetable 控制点需从 0 到 1 且点数 >= 2")

    h = np.diff(xs)
    if np.any(h <= 0.0):
        raise ValueError("tonetable 控制点 x 必须严格递增")

    # 自然三次样条 (二阶导端点=0): 解三对角线性系统求各点二阶导 M
    A = np.zeros((n, n)); rhs = np.zeros(n)
    A[0, 0] = 1.0; A[-1, -1] = 1.0
    for i in range(1, n - 1):
        A[i, i - 1] = h[i - 1]
        A[i, i] = 2.0 * (h[i - 1] + h[i])
        A[i, i + 1] = h[i]
        rhs[i] = 6.0 * ((ys[i + 1] - ys[i]) / h[i]
                        - (ys[i] - ys[i - 1]) / h[i - 1])
    M = np.linalg.solve(A, rhs)

    xq = np.arange(count, dtype=np.float64) / float(count)
    seg = np.clip(np.searchsorted(xs, xq) - 1, 0, n - 2)
    dx = xq - xs[seg]
    hh = h[seg]
    A = (xs[seg + 1] - xq) / hh
    Bv = dx / hh
    A3 = A ** 3 - A
    B3 = Bv ** 3 - Bv
    vals = (A * ys[seg] + Bv * ys[seg + 1]
            + (A3 * M[seg] + B3 * M[seg + 1]) * (hh ** 2) / 6.0)
    grid = np.float32(vals)
    return np.append(grid, grid[-1]).astype(np.float32)


# ---------------------------------------------------------------------------
# 4) HSV LookTable / HueSatMap 应用
#
# 输入: 线性 ProPhoto (float32, [0,1]), 查表维度 (H,S,V), 表体 (H,S,V,3)
# (每格 3 值 = (色相偏移度, 饱和缩放, 明度缩放))。encoding=1 时明度轴先走
# 4096 sRGB 编码表再缩放, 输出前再解码回线性域。
# 过程: RGB->HSV(色相归一 [0,6)) -> 查表轴坐标 -> 三线性/环绕插值 ->
#       偏移/缩放 -> HSV->RGB。
# ---------------------------------------------------------------------------


def apply_hue_sat_map(pp, table, dims, encoding, strength=1.0):
    """LookTable/HueSatMap 的 HSV 域应用 (float32, 非 HDR)。"""
    if strength <= 0.0:
        return np.asarray(pp, np.float32).copy()
    H, S, V = int(dims[0]), int(dims[1]), int(dims[2])
    table = np.ascontiguousarray(table, dtype=np.float32)
    img = np.clip(np.asarray(pp, np.float32), 0.0, 1.0)
    r = img[..., 0]
    g = img[..., 1]
    b = img[..., 2]

    # RGB -> HSV (色相 [0,6))
    v = np.maximum(r, np.maximum(g, b))
    gap = np.float32(v - np.minimum(r, np.minimum(g, b)))
    h = np.zeros_like(v, np.float32)
    s = np.zeros_like(v, np.float32)
    nonzero = gap > np.float32(0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_is_max = nonzero & (r == v)
        h = np.where(r_is_max, np.float32((g - b) / gap), h)
        h = np.where(h < np.float32(0.0), np.float32(h + np.float32(6.0)), h)
        g_is_max = nonzero & ~r_is_max & (g == v)
        h = np.where(g_is_max, np.float32(2.0 + np.float32((b - r) / gap)), h)
        b_is_max = nonzero & ~r_is_max & ~g_is_max
        h = np.where(b_is_max, np.float32(4.0 + np.float32((r - g) / gap)), h)
        s = np.where(nonzero, np.float32(gap / v), s)

    v_enc = srgb_encode(v) if encoding == 1 else v

    hmm = np.float32(H * (1.0 / 6.0))
    smm = np.float32(S - 1)
    vmm = np.float32(V - 1)
    max_h = H - 1
    max_s = S - 2
    max_v = V - 2
    hs = np.float32(h * hmm)
    ss = np.float32(s * smm)
    vs = np.float32(v_enc * vmm)
    h0 = hs.astype(np.int32)
    s0 = np.minimum(ss.astype(np.int32), max_s)
    v0 = np.minimum(vs.astype(np.int32), max_v)
    v1 = v0 + 1
    h1 = h0 + 1
    wrap = h0 >= max_h
    h0 = np.where(wrap, max_h, h0)
    h1 = np.where(wrap, 0, h1)
    hf1 = np.float32(hs - np.float32(h0))
    sf1 = np.float32(ss - np.float32(s0))
    vf1 = np.float32(vs - np.float32(v0))
    hf0 = np.float32(1.0 - hf1)
    sf0 = np.float32(1.0 - sf1)
    vf0 = np.float32(1.0 - vf1)

    def _cell(sidx):
        e00 = table[h0, sidx, v0]
        e01 = table[h1, sidx, v0]
        e10 = table[h0, sidx, v1]
        e11 = table[h1, sidx, v1]
        hue_c = np.float32(vf0 * np.float32(hf0 * e00[..., 0] + hf1 * e01[..., 0])
                           + vf1 * np.float32(hf0 * e10[..., 0] + hf1 * e11[..., 0]))
        sat_c = np.float32(vf0 * np.float32(hf0 * e00[..., 1] + hf1 * e01[..., 1])
                           + vf1 * np.float32(hf0 * e10[..., 1] + hf1 * e11[..., 1]))
        val_c = np.float32(vf0 * np.float32(hf0 * e00[..., 2] + hf1 * e01[..., 2])
                           + vf1 * np.float32(hf0 * e10[..., 2] + hf1 * e11[..., 2]))
        return hue_c, sat_c, val_c

    hue0, sat0, val0 = _cell(s0)
    hue1, sat1, val1 = _cell(s0 + 1)
    hue = np.float32(sf0 * hue0 + sf1 * hue1)
    sat = np.float32(sf0 * sat0 + sf1 * sat1)
    val = np.float32(sf0 * val0 + sf1 * val1)

    if strength != 1.0:
        hue = np.float32(hue * np.float32(strength))
        sat = np.float32(1.0 + np.float32(strength) * np.float32(sat - 1.0))
        val = np.float32(1.0 + np.float32(strength) * np.float32(val - 1.0))

    h = np.float32(h + np.float32(hue * np.float32(6.0 / 360.0)))
    s = np.minimum(np.float32(s * sat), np.float32(1.0))
    v_enc = np.clip(np.float32(v_enc * val), 0.0, 1.0)
    v = srgb_decode(v_enc) if encoding == 1 else v_enc

    # HSV -> RGB (色相 [0,6))
    out = np.empty_like(img)
    colored = s > np.float32(0.0)
    rr = np.where(colored, r, v)
    gg = np.where(colored, g, v)
    bb = np.where(colored, b, v)
    hp = h[colored]
    hp = np.fmod(hp, np.float32(6.0))
    hp = np.where(hp < np.float32(0.0), hp + np.float32(6.0), hp)
    sector = hp.astype(np.int32)
    ff = np.float32(hp - np.float32(sector))
    vv = v[colored]
    ss = s[colored]
    p1 = np.float32(vv * np.float32(1.0 - ss))
    q1 = np.float32(vv * np.float32(1.0 - np.float32(ss * ff)))
    t1 = np.float32(vv * np.float32(1.0 - np.float32(ss * np.float32(1.0 - ff))))
    cirr = np.empty_like(vv)
    cigg = np.empty_like(vv)
    cibb = np.empty_like(vv)
    for case in range(7):
        m = sector == case
        if case in (0, 6):
            cirr[m] = vv[m]; cigg[m] = t1[m]; cibb[m] = p1[m]
        elif case == 1:
            cirr[m] = q1[m]; cigg[m] = vv[m]; cibb[m] = p1[m]
        elif case == 2:
            cirr[m] = p1[m]; cigg[m] = vv[m]; cibb[m] = t1[m]
        elif case == 3:
            cirr[m] = p1[m]; cigg[m] = q1[m]; cibb[m] = vv[m]
        elif case == 4:
            cirr[m] = t1[m]; cigg[m] = p1[m]; cibb[m] = vv[m]
        elif case == 5:
            cirr[m] = vv[m]; cigg[m] = p1[m]; cibb[m] = q1[m]
    rr[colored] = cirr
    gg[colored] = cigg
    bb[colored] = cibb
    out[..., 0] = rr
    out[..., 1] = gg
    out[..., 2] = bb
    return np.clip(out, 0.0, 1.0).astype(np.float32)

__all__ = ["exposure_ramp", "table_interp", "srgb_encode", "srgb_decode", "tone_table_interp", "apply_rgb_tone", "load_tone_table", "build_tonetable", "apply_hue_sat_map"]
