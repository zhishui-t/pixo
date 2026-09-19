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


def curve_lut_from_points(xs: np.ndarray, ys: np.ndarray, n: int = 4096) -> np.ndarray:
    """曲线点 → 均匀采样 LUT (0..1)。"""
    grid = np.linspace(0.0, 1.0, n, dtype=np.float64)
    return np.interp(grid, xs, ys).astype(np.float32)


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

__all__ = [
    "MID_GRAY_GAMMA",
    "srgb_encode", "srgb_decode", "make_srgb_eotf_lut", "make_power_lut",
    "make_base_curve_lut", "base_curve_decode", "make_filmic_lut",
    "apply_lut1d", "apply_lut1d_fast", "apply_gamma_power", "gray_luma",
    "parse_profile_curve", "curve_lut_from_points", "curve_inv_y",
    "curve_anchor_target",
]
