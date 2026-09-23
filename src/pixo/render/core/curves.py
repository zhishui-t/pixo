"""engine.curves —— 影调曲线原语 (全部查表实现, 单调、可微、无逐像素幂)。

旧管线教训: 对比度 S 曲线、gamma、高光回拉各自为政 + 校准表打架。
这里统一为:
  - **基座影调 = 曲线基**: 精确 sRGB EOTF (默认) 或纯 1/2.2 幂 (eotf 参数)。
  - DCP ProfileToneCurve 为可选 Adobe look (tone_map._get_profile_lut):
    **linear→linear** 场景曲线, 与曲线基**复合**使用 (base∘curve, R24)。
  - filmic 作为 Phase 1.5 影调重塑层保留 (make_filmic_lut, 默认不用)。
"""
from __future__ import annotations

import numpy as np

# 中灰显示值 (gamma 域): 0.18^(1/2.2) ≈ 0.4587 → ×255 ≈ 117。
# 曝光锚点即"令影调曲线输出中灰 (≈117)"对应的线性输入 (curve_anchor_target)。
MID_GRAY_GAMMA = float(0.18 ** (1.0 / 2.2))


# sRGB EOTF 编码 (线性 → gamma)
def srgb_encode(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def srgb_decode(y):
    """sRGB EOTF 逆 (gamma → 线性); 标量或 ndarray 均可。

    R30 起 huesat oklch 形变消费 (原 core/tone.py 向量化版随 DNG 复刻线
    退役迁入); 标量输入返回 float, 数组输入返回数组, 语义与旧版逐位一致
    (y≤0→0, 末段按 min(y,1) 截断)。
    """
    arr = np.asarray(y, dtype=np.float64)
    out = np.where(
        arr <= 0.0, 0.0,
        np.where(arr <= 0.04045, arr / 12.92,
                 ((np.minimum(arr, 1.0) + 0.055) / 1.055) ** 2.4))
    if np.ndim(y) == 0:
        return float(out)
    return out


def make_srgb_eotf_lut(n: int = 4096) -> np.ndarray:
    """精确 sRGB EOTF 曲线 LUT: 线性 x∈[0,1] → gamma 编码 y∈[0,1]。"""
    x = np.linspace(0.0, 1.0, n, dtype=np.float64)
    y = srgb_encode(x)
    y[0] = 0.0
    y[-1] = 1.0
    return y.astype(np.float32)


def make_power_lut(gamma: float = 2.2, n: int = 4096) -> np.ndarray:
    """纯幂 gamma 曲线 LUT: x^(1/gamma) (端点强约束 0/1)。"""
    x = np.linspace(0.0, 1.0, n, dtype=np.float64)
    y = np.power(x, 1.0 / gamma)
    y[0] = 0.0
    y[-1] = 1.0
    return y.astype(np.float32)


def make_base_curve_lut(eotf: str = "srgb", gamma: float = 2.2, n: int = 4096) -> np.ndarray:
    """曲线基 (无 ProfileToneCurve 时的回退编码曲线)。

    eotf='srgb'     精确 sRGB EOTF (默认)
    eotf='power22'  纯 1/gamma 幂 (gamma 默认 2.2)
    """
    if eotf == "power22":
        return make_power_lut(gamma=gamma, n=n)
    return make_srgb_eotf_lut(n=n)


def make_filmic_lut(n: int = 4096, contrast: float = 0.0,
                    toe: float = 0.55, shoulder: float = 0.0) -> np.ndarray:
    """构造 filmic 曲线 LUT: 线性值 x∈[0,1] → gamma 编码值 y∈[0,1]。

    Phase 1.5 影调重塑层 (基座默认不用, 可选):
      - 纯幂映射 x^(1/2.2) 为基础。
      - 高光肩部: 超过 shoulder 的线性值软压缩 (避免生硬裁剪)。
      - contrast: 绕 0.5 的 S 形对比。
      - toe: 阴影提升。
    单调性由构造保证。
    """
    x = np.linspace(0.0, 1.0, n, dtype=np.float64)
    y = np.power(x, 1.0 / 2.2)
    if shoulder > 0.0:
        # 肩部软压缩: x>shoulder 的增益渐降
        w = np.clip((x - shoulder) / 0.25, 0.0, 1.0)
        w = w * w * (3.0 - 2.0 * w)  # smoothstep
        y = y * (1.0 - w * 0.15)
    if contrast > 0.0:
        k = 1.0 + 6.0 * contrast
        s = 1.0 / (1.0 + np.exp(-k * (x - 0.5) * 2.0))
        s = (s - s[0]) / (s[-1] - s[0])
        y = y * (1.0 - contrast * 0.5) + s * contrast * 0.5
        y = y / np.max(y) * np.max(np.power(x, 1.0 / 2.2))
    if toe > 0.0:
        # 黑位提升 (lift): y = (y + b) / (1 + b), 恒单调, 阴影上浮
        b = toe * 0.08
        y = (y + b) / (1.0 + b)
    y = np.clip(y, 0.0, 1.0)
    # 端点强约束
    y[0] = 0.0
    y[-1] = 1.0
    return y.astype(np.float32)


def apply_lut1d(x: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """对 0..1 浮点图应用 1D LUT, **线性插值** (替代旧最近邻 floor, 精度 ≈ 1/n)。

    输入 >1 按端点值截断 (高光交给调用方软滚降/肩部处理)。
    """
    n = len(lut) - 1
    xc = np.clip(x, 0.0, 1.0)
    pos = xc * n
    i0 = np.floor(pos).astype(np.int32)
    i1 = np.minimum(i0 + 1, n)
    frac = (pos - i0).astype(np.float32)
    y = lut[i0] * (1.0 - frac) + lut[i1] * frac
    return y.astype(np.float32)


def apply_lut1d_fast(x: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """1D LUT 最近邻单 gather 快路径 (tone stage 热路径)。

    单次 gather + floor, 耗时约为线性插值的一半。配合 16384 级 LUT,
    量化误差 < 1/32768 (gamma 域 ~0.008/255), 不可感知; 语义与
    apply_lut1d 一致 (越界截断)。
    """
    n = len(lut) - 1
    idx = (np.clip(x, 0.0, 1.0) * n + 0.5).astype(np.int32)
    np.minimum(idx, n, out=idx)
    return lut[idx].astype(np.float32)


def apply_gamma_power(x: np.ndarray, gamma: float = 2.2) -> np.ndarray:
    """纯幂 gamma 编码 (兼容旧 render 行为)。"""
    return np.power(np.clip(x, 0.0, None), 1.0 / gamma).astype(np.float32)


def gray_luma(rgb: np.ndarray) -> np.ndarray:
    """Rec.709 亮度 (输入任意域 RGB, 仅作分析用)。"""
    return (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1]
            + 0.0722 * rgb[:, :, 2]).astype(np.float32)


# ---- DCP 影调曲线 (ProfileToneCurve, 125 点 (x,y) 交错) ----

def parse_profile_curve(vals) -> tuple[np.ndarray, np.ndarray] | None:
    """解析 DCP 影调曲线数据 → (xs, ys)。数据为 (x,y) 交错 0..1 单调序列。"""
    if vals is None or len(vals) < 16:
        return None
    arr = np.array(vals, dtype=np.float64)
    if arr.size % 2 != 0:
        return None
    xs, ys = arr[0::2], arr[1::2]
    if xs[0] < -1e-6 or xs[-1] > 1.0 + 1e-6 or ys.min() < -1e-6 or ys.max() > 1.0 + 1e-6:
        return None  # 不是 0..1 曲线 (防误判)
    if np.any(np.diff(xs) <= 0) or np.any(np.diff(ys) < -1e-6):
        return None  # 非单调
    return xs.astype(np.float32), np.clip(ys, 0, 1).astype(np.float32)


def curve_inv_y(xs: np.ndarray, ys: np.ndarray, y: float) -> float:
    """反查: 求 x 使 curve(x)=y (单调递增曲线)。"""
    x = float(np.interp(y, ys, xs))
    return x


def base_curve_decode(y: float, eotf: str = "srgb", gamma: float = 2.2) -> float:
    """曲线基逆映射 (gamma → 线性), 标量; 语义与 make_base_curve_lut 对偶。

    eotf='power22'  y^gamma (gamma=2.2 时 MID_GRAY_GAMMA^2.2 = 0.18 精确回位)
    其它 (含 'srgb')  精确 sRGB EOTF 逆 (0.4587 → ≈0.178)
    """
    if eotf == "power22":
        return float(np.clip(y, 0.0, 1.0)) ** float(gamma)
    return srgb_decode(y)


def curve_anchor_target(prof, eotf: str = "srgb", gamma: float = 2.2) -> float:
    """曝光锚点: 令**复合影调**输出中灰 (MID_GRAY_GAMMA≈0.459→gamma 117)
    的线性输入值 → log2。

    R24 复合语义 (与 tone_map._get_profile_lut 同源): ProfileToneCurve 是
    linear→linear 场景曲线、之后走基座编码, 即总变换 = base∘curve —— 锚点
    反查分两步: 先解码基座得目标线性值 t (power22=0.18; srgb≈0.178),
    再反查曲线 x = curve⁻¹(t)。旧语义把曲线当完整编码直接反查
    curve⁻¹(0.459), 随 profile_curve 槽位一并废弃。
    无 DCP 曲线 (或 prof=None) ⇔ 恒等曲线 ⇒ 锚点 = log2(t)。
    """
    t = base_curve_decode(MID_GRAY_GAMMA, eotf=eotf, gamma=gamma)
    parsed = parse_profile_curve(getattr(prof, "profile_tone_curve", None)) \
        if prof is not None else None
    if parsed is None:
        return float(np.log2(t))
    xs, ys = parsed
    x = curve_inv_y(xs, ys, t)
    x = float(np.clip(x, 0.02, 0.9))
    return float(np.log2(x))

# ---- 控制点曲线插值模式 (R32-T4 对照吸收) ----
#
# 出处对照 (RawTherapee rtengine/diagonalcurves.cc @ 6c4cb59, GPLv3; 本节为
# 公开数学的独立 numpy 实现, 非代码移植 —— 算法出处逐式标注):
#   - "spline"      = natural cubic spline (RT DCT_Spline: spline_cubic_set
#                     自然边界 ypp0=yppN=0 + 标准 cubic spline 求值式);
#   - "catmull_rom" = centripetal Catmull-Rom, alpha=0.375 (RT
#                     DCT_CatumullRom: catmull_rom_tj 的 alpha 常量与端点
#                     斜率受限反射 catmull_rom_reflect 为 RT 参数化选择),
#                     y∈{0,1} 的平段精确保持 (RT 平段语义, 黑白点渐近线);
#   - "akima"       = Akima (1970) 子样条 (公开文献; RT 无此模式, 任务书
#                     点名纳入作为低过冲选项);
#   - "monotone"    = Fritsch–Carlson (1980) 单调三次 Hermite (公开文献;
#                     过冲自由选项 —— spline/CR 在陡峭控制点间可能过冲,
#                     monotone 数学上保证不过冲);
#   - "linear"      = 既有 np.interp (缺省, 逐位不变)。
# 共同语义: 控制点 x 须严格递增 (平滑模式); 定义域 [xs0, xsN] 外平坦延伸
# (与 np.interp 端点钳位一致, 无斜率外推)。

_CURVE_MODES = ("linear", "spline", "akima", "catmull_rom", "monotone")


def _natural_cubic_coeffs(xs: np.ndarray, ys: np.ndarray):
    """自然边界三次样条系数 (公开教科书算法; 同 RT DCT_Spline 的数学)。

    返回 per-interval (a, b, c, d) 系数 (n-1 组)。
    """
    n = len(xs)
    h = np.diff(xs)
    A = np.zeros((n, n))
    rhs = np.zeros(n)
    A[0, 0] = A[-1, -1] = 1.0
    rhs[0] = rhs[-1] = 0.0                       # 自然边界: ypp0 = yppN = 0
    for i in range(1, n - 1):
        A[i, i - 1] = h[i - 1]
        A[i, i] = 2.0 * (h[i - 1] + h[i])
        A[i, i + 1] = h[i]
        rhs[i] = 6.0 * ((ys[i + 1] - ys[i]) / h[i]
                        - (ys[i] - ys[i - 1]) / h[i - 1])
    ypp = np.linalg.solve(A, rhs)
    c = ypp[:-1] / 2.0
    d = (ypp[1:] - ypp[:-1]) / (6.0 * h)
    b = (ys[1:] - ys[:-1]) / h - h * (ypp[1:] + 2.0 * ypp[:-1]) / 6.0
    return ys[:-1], b, c, d


def _cubic_hermite_coeffs(xs, ys, m):
    """标准三次 Hermite per-interval 系数 (给定节点切线 m)。

      y(t) = a + b·t + c·t² + d·t³, t = x - x_i;
      b = m_i,  c = (3Δ/h - 2m_i - m_{i+1})/h,  d = (m_i + m_{i+1} - 2Δ/h)/h²。
    """
    h = np.diff(xs)
    delta = (ys[1:] - ys[:-1]) / h
    a = ys[:-1]
    b = m[:-1]
    c = (3.0 * delta - 2.0 * m[:-1] - m[1:]) / h
    d = (m[:-1] + m[1:] - 2.0 * delta) / (h * h)
    return a, b, c, d


def _eval_cubic_on_grid(xs, coeffs, xs_out):
    """在 xs_out (已钳到 [xs0, xsN]) 上求值分段三次 (searchsorted 定区间)。"""
    a, b, c, d = coeffs
    idx = np.clip(np.searchsorted(xs, xs_out, side="right") - 1, 0, len(xs) - 2)
    t = xs_out - xs[idx]
    return a[idx] + b[idx] * t + c[idx] * t * t + d[idx] * t * t * t


def _smooth_lut_by_mode(xs: np.ndarray, ys: np.ndarray, xs_out: np.ndarray,
                        mode: str) -> np.ndarray:
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    xs_out = np.clip(np.asarray(xs_out, dtype=np.float64), xs[0], xs[-1])
    if mode == "spline":
        coeffs = _natural_cubic_coeffs(xs, ys)
    elif mode == "monotone":
        coeffs = _cubic_hermite_coeffs(xs, ys, _fritsch_carlson_tangents(xs, ys))
    elif mode == "akima":
        coeffs = _cubic_hermite_coeffs(xs, ys, _akima_tangents(xs, ys))
    elif mode == "catmull_rom":
        return _catmull_rom_lut(xs, ys, xs_out)
    else:
        raise ValueError(f"未知曲线模式: {mode}")
    return _eval_cubic_on_grid(xs, coeffs, xs_out)


def _fritsch_carlson_tangents(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Fritsch–Carlson (1980) 单调保持节点切线 (公开文献)。"""
    n = len(xs)
    h = np.diff(xs)
    delta = np.diff(ys) / h
    m = np.zeros(n)
    if n == 2:
        m[:] = delta[0]
        return m
    m[0] = delta[0]
    m[-1] = delta[-1]
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0:
            m[i] = 0.0
        else:
            m[i] = 2.0 * delta[i - 1] * delta[i] / (delta[i - 1] + delta[i])
    for i in range(n - 1):
        if delta[i] == 0.0:
            m[i] = m[i + 1] = 0.0
            continue
        a = m[i] / delta[i]
        b = m[i + 1] / delta[i]
        s = a * a + b * b
        if s > 9.0:
            tau = 3.0 / np.sqrt(s)
            m[i] = tau * a * delta[i]
            m[i + 1] = tau * b * delta[i]
    return m


def _akima_tangents(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Akima (1970) 节点切线 (公开文献; 差分线性延拓至两端)。

    语义对齐 scipy Akima1DInterpolator (源码核实, 2026-09): 权重
      w1 = |δ_{i+1} - δ_i|,  w2 = |δ_{i-1} - δ_{i-2}|,
      t_i = (w1·δ_{i-1} + w2·δ_i)/(w1+w2);
    f12 = w1+w2 相对近零 (≤1e-9·max) 处切线取相邻割线平均
    (scipy break_mult 语义, 消除 f12=0 的定性不连续)。
    """
    n = len(xs)
    d = np.diff(ys) / np.diff(xs)            # δ_0..δ_{n-2}
    # 延拓 (scipy 同序): d[0]=δ_{-2}=2δ_{-1}-δ_0, d[1]=δ_{-1}=2δ_0-δ_1
    # (右端 d[-2]=δ_n, d[-1]=δ_{n+1} 同构)
    d = np.concatenate([
        [2 * (2 * d[0] - d[1]) - d[0], 2 * d[0] - d[1]],
        d,
        [2 * d[-1] - d[-2], 2 * (2 * d[-1] - d[-2]) - d[-1]]])
    m = np.zeros(n)
    # 向量化: 节点 i 用 δ_{i-2..i+1} = d[i..i+3]
    i = np.arange(n)
    w1 = np.abs(d[i + 3] - d[i + 2])         # |δ_{i+1} - δ_i|
    w2 = np.abs(d[i + 1] - d[i])             # |δ_{i-1} - δ_{i-2}|
    f12 = w1 + w2
    fmax = float(f12.max()) if n else 0.0
    # scipy break_mult 语义: f12 相对近零处取割线平均
    avg = 0.5 * (d[i + 1] + d[i + 2])
    ok = f12 > (1e-9 * fmax if fmax > 0.0 else 0.0)
    m[ok] = (w1[ok] * d[i[ok] + 1] + w2[ok] * d[i[ok] + 2]) / f12[ok]
    m[~ok] = avg[~ok]
    return m


def _catmull_rom_reflect(px: float, py: float, cx: float, cy: float):
    """端点反射 (RT catmull_rom_reflect 同式: 斜率受限, dx·0.01)。"""
    dx = px - cx
    dy = py - cy
    rx = cx - dx * 0.01
    ry = (dy / dx) * (rx - cx) + cy if dx > 1e-5 else cy
    return rx, ry


def _catmull_rom_lut(xs: np.ndarray, ys: np.ndarray,
                     xs_out: np.ndarray) -> np.ndarray:
    """Centripetal Catmull-Rom (alpha=0.375, RT 参数化) 密采样 → np.interp。

    y∈{0,1} 的平段精确保持 (RT 平段语义); 端点斜率受限反射。
    """
    n_cp = len(xs)
    fx, fy = _catmull_rom_reflect(xs[1], ys[1], xs[0], ys[0])
    lx, ly = _catmull_rom_reflect(xs[n_cp - 2], ys[n_cp - 2],
                                  xs[n_cp - 1], ys[n_cp - 1])

    def tj(ti, xi, yi, xj, yj):
        return float(np.sqrt((xj - xi) ** 2 + (yj - yi) ** 2) ** 0.375) + ti

    res_x: list[float] = []
    res_y: list[float] = []
    segments = n_cp - 1
    for i in range(segments):
        p0x = fx if i == 0 else xs[i - 1]
        p0y = fy if i == 0 else ys[i - 1]
        p3x = lx if i == segments - 1 else xs[i + 2]
        p3y = ly if i == segments - 1 else ys[i + 2]
        p1x, p1y, p2x, p2y = xs[i], ys[i], xs[i + 1], ys[i + 1]
        t0 = 0.0
        t1 = tj(t0, p0x, p0y, p1x, p1y)
        t2 = tj(t1, p1x, p1y, p2x, p2y)
        t3 = tj(t2, p2x, p2y, p3x, p3y)
        n_points = max(int(round(512 * (p2x - p1x))), 2)
        res_x.append(p1x)
        res_y.append(p1y)
        if p1y == p2y and p1y in (0.0, 1.0):
            # RT 平段语义: 黑/白渐近线段精确保持
            step = (p2x - p1x) / max(n_points - 1, 1)
            t = p1x + step
            while t < p2x:
                res_x.append(t)
                res_y.append(p1y)
                t += step
        else:
            space = (t2 - t1) / max(n_points - 1, 1)
            for k in range(1, n_points - 1):
                t = t1 + space * k
                c = (t1 - t) / (t1 - t0)
                d = (t - t0) / (t1 - t0)
                a1x = c * p0x + d * p1x
                a1y = c * p0y + d * p1y
                a2x = (t2 - t) / (t2 - t1) * p1x + (t - t1) / (t2 - t1) * p2x
                a2y = (t2 - t) / (t2 - t1) * p1y + (t - t1) / (t2 - t1) * p2y
                a3x = (t3 - t) / (t3 - t2) * p2x + (t - t2) / (t3 - t2) * p3x
                a3y = (t3 - t) / (t3 - t2) * p2y + (t - t2) / (t3 - t2) * p3y
                b1x = (t2 - t) / (t2 - t0) * a1x + (t - t0) / (t2 - t0) * a2x
                b1y = (t2 - t) / (t2 - t0) * a1y + (t - t0) / (t2 - t0) * a2y
                b2x = (t3 - t) / (t3 - t1) * a2x + (t - t1) / (t3 - t1) * a3x
                b2y = (t3 - t) / (t3 - t1) * a2y + (t - t1) / (t3 - t1) * a3y
                cx_ = (t2 - t) / (t2 - t1) * b1x + (t - t1) / (t2 - t1) * b2x
                cy_ = (t2 - t) / (t2 - t1) * b1y + (t - t1) / (t2 - t1) * b2y
                res_x.append(cx_)
                res_y.append(cy_)
    res_x.append(p2x)
    res_y.append(p2y)
    order = np.argsort(res_x)
    res_x = np.asarray(res_x)[order]
    res_y = np.asarray(res_y)[order]
    return np.interp(xs_out, res_x, res_y)


def curve_lut_from_points(xs: np.ndarray, ys: np.ndarray, n: int = 4096,
                          mode: str = "linear") -> np.ndarray:
    """曲线点 → 均匀采样 LUT (0..1)。

    mode: "linear" (缺省, np.interp, 既有语义逐位不变) | "spline" (自然
    三次样条, RT DCT_Spline 同数学) | "akima" (Akima 1970) |
    "catmull_rom" (向心 CR α=0.375, RT DCT_CatumullRom 同参) |
    "monotone" (Fritsch–Carlson 单调 Hermite, 过冲自由)。
    控制点 <3 时平滑模式自动回退 linear (同 RT: N>2 才启用样条)。
    """
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    grid = np.linspace(0.0, 1.0, n, dtype=np.float64)
    if mode == "linear" or len(xs) < 3:
        return np.interp(grid, xs, ys).astype(np.float32)
    if mode not in _CURVE_MODES:
        raise ValueError(f"未知曲线模式: {mode} (合法: {_CURVE_MODES})")
    if np.any(np.diff(xs) <= 0):
        raise ValueError(
            f"mode={mode} 要求控制点 x 严格递增 (发现相等/回退)")
    return _smooth_lut_by_mode(xs, ys, grid, mode).astype(np.float32)


__all__ = [
    "MID_GRAY_GAMMA",
    "srgb_encode", "srgb_decode", "make_srgb_eotf_lut", "make_power_lut",
    "make_base_curve_lut", "base_curve_decode", "make_filmic_lut",
    "apply_lut1d", "apply_lut1d_fast", "apply_gamma_power", "gray_luma",
    "parse_profile_curve", "curve_lut_from_points", "curve_inv_y",
    "curve_anchor_target",
]
