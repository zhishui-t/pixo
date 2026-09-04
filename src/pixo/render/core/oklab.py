"""engine.oklab —— Oklab / OKLCh 转换内核 (纯 numpy, M-O1 先行任务)。

权威依据:
  - Björn Ottosson, "A perceptual color space for image processing", 2020,
    https://bottosson.github.io/posts/oklab/ —— 正向矩阵常数逐位抄原文 (10 位小数),
    红/绿/蓝/灰锚点值与原文公布示例在公布精度内一致 (公布值仅 6 位小数)。
  - sRGB gamma: IEC 61966-2-1 分段幂律 (0.04045/0.0031308 阈值),
    写法与 huesat._srgb_encode_v/_srgb_decode_v 一致。

链路:
  正向  gamma sRGB --EOTF 解码--> linear sRGB --M1--> LMS --cbrt--> LMS' --M2--> Oklab
  逆向  Oklab --M2⁻¹--> LMS' --三次方--> LMS --M1⁻¹--> linear sRGB --EOTF 编码--> gamma sRGB

逆矩阵常数说明 (对原文的有意偏离):
  原文也公布了配套逆矩阵常数, 但与正向常数**不严格互逆** (实测 M2⁻¹·M2 偏差
  ~5.5e-8, 集中在 L 列系数 0.9999999985 ≠ 1), sRGB 往返误差 ~2e-6, 超出本阶段
  ≤1e-7 的精度验收线 (设计 §1.3)。故逆矩阵取**正向常数的数值逆**并冻结为字面
  常数 (12 位有效数字, 互逆残差 ~3e-12 —— 12 位冻结的舍入极限; 实时
  np.linalg.inv 为 ~3e-16) —— 与 core/color.py 的 _SRGB_TO_PROPHOTO 取逆
  纪律同源。锚点/正向行为不受影响。

cbrt 用 np.cbrt (实数立方根, 负值有定义), 与原文一致; oklab_to_srgb 对超出
sRGB 色域的 linear 值 clip 后编码 (输出保证 [0,1])。

域约定 (对齐 core.hsl / core.split_tone, 见 OWN_PIPELINE_STAGE1_DESIGN.md §1.3):
  - sRGB 域: 输入/输出 gamma sRGB float [0,1], oklab_to_srgb 出口 float32 (渲染纪律);
  - Oklab/OKLCh 是**内部工作域**: 出口 float64 ("内部 float64 计算"的延伸,
    这是 sRGB↔Oklab 往返 ≤1e-7 验收的根基——lab 若以 float32 交接, 量化噪声
    经近黑区 gamma 斜率 12.92 放大, 实测往返下限 ~7e-7, 物理上不可达 1e-7);
  - oklab_to_oklch 的 h 为度、值域 [0,360); oklch_to_oklab 的 h 环绕连续 (任意实数可入);
  - 纯函数、无 I/O、无全局可变状态。
形状: 最后一维为通道 3 的任意形状 (..., 3) → (..., 3) (含 (3,) 单像素)。
矩阵应用写成逐分量加权和 (与原文参考代码逐行对应), 不走 BLAS matmul——
计算与形状无关, 批量与单像素逐位一致, 也为后续 native 逐位等价 (设计 §2.4) 打底。
"""
from __future__ import annotations

import numpy as np

__all__ = ["srgb_to_oklab", "oklab_to_srgb", "oklab_to_oklch", "oklch_to_oklab"]

# ---------------------------------------------------------------------------
# 矩阵常数 (行向量语义: out_i = sum_j M[i,j] * in_j, 即 out = in @ M.T)
# ---------------------------------------------------------------------------

# M1: linear sRGB → LMS (Ottosson 2020, 抄原文)
_M1_LSRGB_TO_LMS = np.asarray([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
], dtype=np.float64)

# M1⁻¹: LMS → linear sRGB = inv(M1) 冻结 12 位有效数字 (出处见模块 docstring)
_M1_INV_LMS_TO_LSRGB = np.asarray([
    [4.07674166135, -3.30771159041, 0.230969928729],
    [-1.26843800409, 2.60975740066, -0.34131939631],
    [-0.00419608654184, -0.703418614459, 1.70761470093],
], dtype=np.float64)

# M2: LMS' → Oklab (Ottosson 2020, 抄原文)
_M2_LMSP_TO_LAB = np.asarray([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
], dtype=np.float64)

# M2⁻¹: Oklab → LMS' = inv(M2) 冻结 12 位有效数字 (出处见模块 docstring)
_M2_INV_LAB_TO_LMSP = np.asarray([
    [0.999999998451, 0.396337792174, 0.215803758061],
    [1.00000000888, -0.105561342324, -0.0638541747717],
    [1.00000005467, -0.089484182095, -1.29148553786],
], dtype=np.float64)


# ---------------------------------------------------------------------------
# sRGB gamma (IEC 61966-2-1)
# ---------------------------------------------------------------------------

def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    """gamma sRGB → linear。负输入按 0 处理 (对齐 huesat 解码, 避免负底幂 NaN)。"""
    c = np.clip(c, 0.0, None)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    """linear → gamma sRGB (入参须已裁剪为非负, 裁剪责任在调用方)。"""
    return np.where(lin <= 0.0031308, 12.92 * lin,
                    1.055 * np.power(lin, 1.0 / 2.4) - 0.055)


def _as_3ch(x, name: str) -> np.ndarray:
    """入参转 ndarray 并校验最后一维为 3 (只做结构校验, 不改数值)。"""
    arr = np.asarray(x)
    if arr.ndim == 0 or arr.shape[-1] != 3:
        raise ValueError(f"{name} 最后一维需为 3 (实际 shape={arr.shape})")
    return arr


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------

def srgb_to_oklab(rgb01):
    """gamma sRGB [0,1] → Oklab (L∈[0,1], a/b 有符号)。出口 float64 (内部工作域)。

    rgb01: (..., 3) 任意形状; 负输入按 0 解码 (防 NaN)。
    """
    rgb = _as_3ch(rgb01, "rgb01").astype(np.float64)
    lin = _srgb_to_linear(rgb)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    m = _M1_LSRGB_TO_LMS
    l = m[0, 0] * r + m[0, 1] * g + m[0, 2] * b
    mm = m[1, 0] * r + m[1, 1] * g + m[1, 2] * b
    s = m[2, 0] * r + m[2, 1] * g + m[2, 2] * b
    # cbrt: np.cbrt 实数立方根 (负值有定义), 与原文一致
    l_, m_, s_ = np.cbrt(l), np.cbrt(mm), np.cbrt(s)
    m = _M2_LMSP_TO_LAB
    L = m[0, 0] * l_ + m[0, 1] * m_ + m[0, 2] * s_
    a = m[1, 0] * l_ + m[1, 1] * m_ + m[1, 2] * s_
    b2 = m[2, 0] * l_ + m[2, 1] * m_ + m[2, 2] * s_
    return np.stack([L, a, b2], axis=-1)


def oklab_to_srgb(lab):
    """Oklab → gamma sRGB [0,1]。出口 float32。

    色域外处理 (设计 §2.1): linear 域 clip 到 [0,1] 后再编码, 输出保证 [0,1] 无 NaN。
    """
    lab = _as_3ch(lab, "lab").astype(np.float64)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    m = _M2_INV_LAB_TO_LMSP
    l_ = m[0, 0] * L + m[0, 1] * a + m[0, 2] * b
    m_ = m[1, 0] * L + m[1, 1] * a + m[1, 2] * b
    s_ = m[2, 0] * L + m[2, 1] * a + m[2, 2] * b
    lms_l, lms_m, lms_s = l_ ** 3, m_ ** 3, s_ ** 3   # cbrt 逆: 立方 (负值有定义)
    m = _M1_INV_LMS_TO_LSRGB
    r = m[0, 0] * lms_l + m[0, 1] * lms_m + m[0, 2] * lms_s
    g = m[1, 0] * lms_l + m[1, 1] * lms_m + m[1, 2] * lms_s
    b2 = m[2, 0] * lms_l + m[2, 1] * lms_m + m[2, 2] * lms_s
    lin = np.clip(np.stack([r, g, b2], axis=-1), 0.0, 1.0)
    return _linear_to_srgb(lin).astype(np.float32)


def oklab_to_oklch(lab):
    """Oklab (L,a,b) → OKLCh (L, C, h)。h 为度、值域 [0,360)。出口 float64 (内部工作域)。

    C = hypot(a,b); h = atan2(b,a) 折到 [0,360)。a=b=0 (中性灰) 时 h=0, 无 NaN。
    """
    lab = _as_3ch(lab, "lab").astype(np.float64)
    a, b = lab[..., 1], lab[..., 2]
    c = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a)) % 360.0
    # b 为极小负数时浮点 mod 可能给出 360.0, 折回 0 严格满足 [0,360)
    h = np.where(h >= 360.0, 0.0, h)
    return np.stack([lab[..., 0], c, h], axis=-1)


def oklch_to_oklab(lch):
    """OKLCh (L,C,h) → Oklab。h 环绕连续: 任意实数角度可入 (cos/sin 周期性)。出口 float64 (内部工作域)。"""
    lch = _as_3ch(lch, "lch").astype(np.float64)
    hr = np.deg2rad(lch[..., 2])
    return np.stack([lch[..., 0],
                     lch[..., 1] * np.cos(hr),
                     lch[..., 1] * np.sin(hr)], axis=-1)
