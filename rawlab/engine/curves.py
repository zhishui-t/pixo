"""engine.curves —— 影调曲线原语 (全部查表实现, 单调、可微、无逐像素幂)。

旧管线教训: 对比度 S 曲线、gamma、高光回拉各自为政 + 校准表打架。
这里统一为: 一条可参数化 filmic 曲线 (线性域 → gamma 域), 参数收敛在少数几个语义量。
"""
from __future__ import annotations

import numpy as np

# sRGB EOTF 编码 (线性 → gamma)
def srgb_encode(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def make_filmic_lut(n: int = 4096, contrast: float = 0.0,
                    toe: float = 0.55, shoulder: float = 0.0) -> np.ndarray:
    """构造 filmic 曲线 LUT: 线性值 x∈[0,1] → gamma 编码值 y∈[0,1]。

    设计:
      - 纯幂映射 x^(1/2.2) 为基础 (与旧管线一致, 保证中性灰定位可预测)。
      - 高光肩部: 超过 shoulder 的线性值软压缩 (避免生硬裁剪), 肩宽 0.25。
      - contrast: 绕 0.5 的 S 形对比 (sigmoid 变体, 端点不动)。
      - toe: 阴影提升 (黑位锚定 0, 阴影区亮度补偿)。
    单调性由构造保证。
    """
    x = np.linspace(0.0, 1.0, n, dtype=np.float64)
    y = np.power(x, 1.0 / 2.2)
    if shoulder > 0.0:
        # 肩部软压缩: x>shoulder 的增益渐降, shoulder+0.25 处压到 98%
        w = np.clip((x - shoulder) / 0.25, 0.0, 1.0)
        w = w * w * (3.0 - 2.0 * w)  # smoothstep
        y_shoulder = 1.0 - 0.02 * (x - shoulder) / 0.25 * (1.0 - w) \
                     - (1.0 - y) * 0.0
        # 简化: 对 y 施加软上限 0.98, 在肩部区域平滑过渡
        y = y * (1.0 - w * 0.15)
    if contrast > 0.0:
        k = 1.0 + 6.0 * contrast
        s = 1.0 / (1.0 + np.exp(-k * (x - 0.5) * 2.0))
        s = (s - s[0]) / (s[-1] - s[0])
        y = y ** 1.0 * (1.0 - contrast * 0.5) + s * contrast * 0.5
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
    """对 0..1 浮点图应用 LUT (4096 级量化直接索引, 误差 < 1/4096)。

    输入 >1 按端点值截断 (高光交给调用方软滚降/肩部处理)。
    """
    n = len(lut) - 1
    idx = np.clip(x, 0.0, 1.0) * n
    i = np.floor(idx).astype(np.int32)
    return lut[i].astype(np.float32)


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


def curve_anchor_target(prof) -> float:
    """曝光锚点: 令影调曲线输出 0.45 (≈gamma 117) 的线性输入值 → log2。

    无 DCP 曲线时回退 log2(0.18) (纯 1/2.2: 0.18^(1/2.2)≈0.459)。
    """
    parsed = parse_profile_curve(getattr(prof, "profile_tone_curve", None)) \
        if prof is not None else None
    if parsed is None:
        return float(np.log2(0.18))
    xs, ys = parsed
    x = curve_inv_y(xs, ys, 0.45)
    x = float(np.clip(x, 0.02, 0.9))
    return float(np.log2(x))
