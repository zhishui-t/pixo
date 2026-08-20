"""engine.color —— DCP 色彩链路纯函数模块 (数学层, 无 I/O)。

权威依据:
  - DNG 1.4 规范 (相机色彩标定附录)
  - Adobe DNG SDK: dng_color_spec.cpp / dng_camera_profile.cpp / dng_tag_codes.h

核心结论 (相对旧管线的修正):
  1. ColorMatrix (CM) 与 ForwardMatrix (FM) 方向不同:
     - ColorMatrix:  XYZ → 相机原生空间 (未 WB)。camera→XYZ 需取逆。
     - ForwardMatrix: WB 后的相机值 → XYZ(D50)。这是"look/观感"矩阵,
       不是 colorimetric 的 camera→XYZ。旧管线误把它当 camera→XYZ 用。
  2. 基座 (colorimetric) 路径:
        camRGB × WB → inv(CM_interp × CC_interp) → XYZ(场景参考)
        → Bradford 色适应 (场景白 → D50) → XYZ(D50) → Bradford(D50→D65) → sRGB
     CM1/CM2 按 1/T 在 CalibrationIlluminant1/2 之间插值 (Adobe FindXYZtoCamera)。
  3. 缺 CM 时回退 FM 路径并告警 (换机/非标 DCP 不崩)。
  4. CCT 反演: WB 中性点 → inv(CM) → xy → McCamy CCT (替代 Tanner Helland 误用)。

约定: 所有 3×3 矩阵用"列向量"语义 (out = M @ in), 与现有调用处
`rgb_row @ M.T` 一致 (见 whitebalance.py)。
"""
from __future__ import annotations

import warnings

import numpy as np

from rawlux.core.calibration import (BRADFORD_D50_TO_D65, SRGB_TO_XYZ_D65,
                                    XYZ_D65_TO_SRGB)

# ---- CIE 标准白点 ----
D50_XY = (0.34567, 0.35850)   # CIE D50 (ICC PCS 白点)
# 注: 相关色温 (CCT) 的黑体轨迹反查 (temperature_from_xy) 使用公开
# CIE 1960 UCS (u,v) + Planckian locus (Kim et al. 2002 近似, 见 temp_to_xy)
# 独立实现, 不依赖任何第三方常量表; 详见本文件 "色温插值 (M3)" 节。
D65_XY = (0.31271, 0.32902)   # CIE D65 (sRGB 白点)

# ---- 预计算常量矩阵 (float64, 列向量语义: out = M @ in) ----
_XYZ65_TO_SRGB = np.asarray(XYZ_D65_TO_SRGB, dtype=np.float64)
_SRGB_TO_XYZ_D65 = np.asarray(SRGB_TO_XYZ_D65, dtype=np.float64)
_BRADFORD_D50_TO_D65 = np.asarray(BRADFORD_D50_TO_D65, dtype=np.float64)

# ---- ProPhoto RGB (ROMM RGB, ISO 22028-2) —— HueSatMap 应用域 (线性, D50) ----
# Adobe DNG SDK 在线性 ProPhoto(D50)、影调曲线之前应用 HueSatMap/LookTable
# (见 dsh-plan-task-p4/research/hsmap-domain.md)。ROMM RGB 原色:
#   R(0.7347, 0.2653)  G(0.1596, 0.8404)  B(0.0366, 0.0001), 白点 D50。
# 线性 RGB → XYZ(D50) 标准矩阵 (ICC / Bruce Lindbloom, 7 位有效数字)。
PROPHOTO_RGB_TO_XYZ_D50 = [
    [0.7976749, 0.1351917, 0.0313534],
    [0.2880402, 0.7118741, 0.0000857],
    [0.0000000, 0.0000000, 0.8252100],
]

_PROPHOTO_RGB_TO_XYZ_D50 = np.asarray(PROPHOTO_RGB_TO_XYZ_D50, dtype=np.float64)

# 复合矩阵 (列向量语义, 与调用处 rgb @ M.T 一致):
#   ProPhoto(D50) → sRGB(D65) = XYZ→sRGB @ Bradford(D50→D65) @ ROMM RGB→XYZ (字面复合)
#   sRGB(D65) → ProPhoto(D50) = 上述复合矩阵的**数值逆** (与字面复合差异 ≤2e-7,
#     即 sRGB/ROMM 常量 7 位舍入量级; 取逆保证 sRGB↔ProPhoto 往返 ≈ 恒等,
#     这是"恒等表往返 ≤1e-6"验收的数值根基)。
_PROPHOTO_TO_SRGB = _XYZ65_TO_SRGB @ _BRADFORD_D50_TO_D65 @ _PROPHOTO_RGB_TO_XYZ_D50
_SRGB_TO_PROPHOTO = np.linalg.inv(_PROPHOTO_TO_SRGB)

# ---- 缺 CM 回退 FM 的告警类型 ----
class ColorMatrixFallbackWarning(UserWarning):
    """DCP 缺 ColorMatrix, 已回退 ForwardMatrix 路径 (colorimetric 降级为 look)。"""


# ---------------------------------------------------------------------------
# 基础原语
# ---------------------------------------------------------------------------

def _mat3(values) -> np.ndarray | None:
    """9 元素列表 → 3×3 float64 矩阵 (行主序); 非法返回 None。"""
    if values is None:
        return None
    a = np.asarray(values, dtype=np.float64).reshape(-1)
    if a.size < 9:
        return None
    return a[:9].reshape(3, 3)


def illuminant_cct(light) -> float:
    """DNG/EXIF 光源枚举 → 色温 K (对齐 dng_camera_profile::IlluminantToTemperature)。

    未知光源返回 0.0 (调用方自行回退默认照明体)。
    """
    return {
        1: 5500.0,    # Daylight
        2: 4150.0,    # Fluorescent
        3: 2850.0,    # Tungsten
        4: 5500.0,    # Flash
        9: 5500.0,    # Fine weather
        10: 6500.0,   # Cloudy weather
        11: 7500.0,   # Shade
        12: 6400.0,   # Daylight fluorescent
        13: 5050.0,   # Day white fluorescent
        14: 4150.0,   # Cool white fluorescent
        15: 3525.0,   # White fluorescent
        16: 2925.0,   # Warm white fluorescent
        17: 2850.0,   # Standard light A (2856K 近似)
        18: 5500.0,   # Standard light B
        19: 6500.0,   # Standard light C
        20: 5500.0,   # D55
        21: 6500.0,   # D65
        22: 7500.0,   # D75
        23: 5000.0,   # D50
        24: 3200.0,   # ISO studio tungsten
    }.get(int(light), 0.0)


def xy_to_cct(x: float, y: float) -> float:
    """CIE xy → 相关色温 K (McCamy 1992 三次近似)。

    在 2856K~6500K 区间误差 <10K (对照黑体轨迹验证); 超出区间仍给出单调估计。
    """
    n = (x - 0.3320) / (y - 0.1858)
    return -449.0 * n ** 3 + 3525.0 * n ** 2 - 6823.3 * n + 5520.33


def xyz_to_xy(xyz) -> tuple[float, float]:
    """XYZ → CIE xy (色度, 归一化后与 Y 无关)。"""
    v = np.asarray(xyz, dtype=np.float64).reshape(3)
    s = float(v.sum())
    if s <= 0:
        return (0.3333, 0.3333)
    return (float(v[0] / s), float(v[1] / s))


def xy_to_xyz(x: float, y: float) -> np.ndarray:
    """CIE xy → XYZ (Y=1 归一化)。"""
    return np.array([x / y, 1.0, (1.0 - x - y) / y], dtype=np.float64)


def bradford_adapt(src_xy, dst_xy) -> np.ndarray:
    """线性化 Bradford 色适应矩阵 (映射 src 白点 → dst 白点)。

    对齐 dng_color_spec.cpp 的 MapWhiteMatrix (Mb / A / Mb^-1 结构)。
    """
    mb = np.array([[0.8951, 0.2664, -0.1614],
                   [-0.7502, 1.7135, 0.0367],
                   [0.0389, -0.0685, 1.0296]], dtype=np.float64)
    w1 = mb @ xy_to_xyz(*src_xy)
    w2 = mb @ xy_to_xyz(*dst_xy)
    w1 = np.maximum(w1, 0.0)
    w2 = np.maximum(w2, 0.0)
    a = np.diag([w2[0] / w1[0] if w1[0] > 0 else 1.0,
                 w2[1] / w1[1] if w1[1] > 0 else 1.0,
                 w2[2] / w1[2] if w1[2] > 0 else 1.0])
    return np.linalg.inv(mb) @ a @ mb


def _interp_1_over_t(m1: np.ndarray, m2: np.ndarray | None,
                     cct: float, t1: float, t2: float) -> np.ndarray:
    """按 1/T 在 m1(照明体1, 温度 t1)与 m2(照明体2, 温度 t2)间插值。

    blend = (1/T - 1/t1) / (1/t2 - 1/t1), 端点 blend=0→m1, blend=1→m2。
    m2 缺失或与 m1 相同则直接返回 m1; 温度非法也退回 m1。
    """
    if m2 is None or np.allclose(m1, m2):
        return m1
    if t1 <= 0 or t2 <= 0 or t1 == t2 or cct <= 0:
        return m1
    blend = (1.0 / cct - 1.0 / t1) / (1.0 / t2 - 1.0 / t1)
    blend = float(np.clip(blend, 0.0, 1.0))
    return (1.0 - blend) * m1 + blend * m2


# ---------------------------------------------------------------------------
# DCP 矩阵提取与插值
# ---------------------------------------------------------------------------

def _calibration_temperatures(prof) -> tuple[float, float]:
    """(t1, t2) = 两个校准照明体的色温; 缺省回退 StdA/D65。"""
    ill1 = getattr(prof, "calibration_illuminant1", None) or 17
    ill2 = getattr(prof, "calibration_illuminant2", None) or 21
    t1 = illuminant_cct(ill1) or 2850.0
    t2 = illuminant_cct(ill2) or 6500.0
    if t1 == t2:
        t2 = t1 + 1.0  # 防除零; 此时插值退化为 m1
    return t1, t2


def interpolate_color_matrices(prof, cct: float) -> tuple[np.ndarray, np.ndarray]:
    """按色温插值 (ColorMatrix, CameraCalibration) —— 均为 XYZ→相机方向。

    返回 (cm, cc): cm 映射 XYZ→参考相机, cc 映射参考相机→个体相机 (缺省单位阵)。
    camera→XYZ = inv(cm) @ inv(cc)。
    """
    cm1 = _mat3(getattr(prof, "color_matrix1", None))
    if cm1 is None:
        raise ValueError("DCP 缺少 ColorMatrix1")
    cm2 = _mat3(getattr(prof, "color_matrix2", None))
    cc1 = _mat3(getattr(prof, "camera_calibration1", None))
    cc2 = _mat3(getattr(prof, "camera_calibration2", None))
    if cc1 is None:
        cc1 = np.eye(3, dtype=np.float64)
    if cc2 is None:
        cc2 = cc1
    t1, t2 = _calibration_temperatures(prof)
    return _interp_1_over_t(cm1, cm2, cct, t1, t2), \
           _interp_1_over_t(cc1, cc2, cct, t1, t2)


def interpolate_forward_matrix(prof, wb) -> np.ndarray | None:
    """按 WB 色温插值 ForwardMatrix1/2 (look 参考 / 缺 CM 回退)。"""
    fm1 = _mat3(getattr(prof, "forward_matrix1", None))
    if fm1 is None:
        return None
    fm2 = _mat3(getattr(prof, "forward_matrix2", None))
    if fm2 is None or np.allclose(fm1, fm2):
        return fm1
    cct = cct_from_wb(wb, prof)
    t1, t2 = _calibration_temperatures(prof)
    return _interp_1_over_t(fm1, fm2, cct, t1, t2)


# ---------------------------------------------------------------------------
# 色温插值 (M3) —— 基于公开 CIE 色度学的 1/T 黑体轨迹反查
# ---------------------------------------------------------------------------
# 说明: DNG colorimetric 双光源 (CalibrationIlluminant1/2) 间用 1/T 插值。
# 相关色温 (CCT) 由 CIE 1960 UCS (u,v) 平面上到 Planckian(黑体) 轨迹的最近
# 距离求得 (Robertson 思路), 轨迹由公开 Kim et al. (2002) 近似生成 (见
# temp_to_xy), 再经 CIE xy→uv 变换。与任何第三方专有常量表无关, 独立实现。

def _xy_to_uv(x: float, y: float) -> tuple[float, float]:
    """CIE xy → CIE 1960 UCS (u, v) (公开定义式)。"""
    d = -2.0 * x + 12.0 * y + 3.0
    return (4.0 * x / d, 6.0 * y / d)


# 黑体轨迹缓存: 首次调用时由公开近似构建。
_PLANCKIAN_T_K = None
_PLANCKIAN_U = None
_PLANCKIAN_V = None


def _ensure_planckian_curve() -> None:
    """惰性构建 Planckian locus 在 CIE 1960 uv 平面的细采样曲线。

    源: Kim et al. (2002) 的 CCT→xy 近似 (见 temp_to_xy), 转换为 uv。
    采样步长 5K, 覆盖 1600K..25000K, 可支撑 ≤~0.5K 的插值精度。
    """
    global _PLANCKIAN_T_K, _PLANCKIAN_U, _PLANCKIAN_V
    if _PLANCKIAN_T_K is not None:
        return
    t_k = np.arange(1600.0, 25000.0, 5.0)
    u = np.empty_like(t_k)
    v = np.empty_like(t_k)
    for i, t in enumerate(t_k):
        x, y = temp_to_xy(float(t))
        uu, vv = _xy_to_uv(x, y)
        u[i], v[i] = uu, vv
    _PLANCKIAN_T_K, _PLANCKIAN_U, _PLANCKIAN_V = t_k, u, v


def temperature_from_xy(x: float, y: float) -> float:
    """CIE xy → 相关色温 K (公开 CIE 1960 uv 黑体轨迹最近邻)。

    在 uv 平面找到离查询点最近的 Planckian 轨迹点, 用三点二次插值细化得到
    相邻黑体温度 (K)。这是 DNG 1/T 双光源插值所需的相关色温。
    """
    _ensure_planckian_curve()
    u, v = _xy_to_uv(x, y)
    du = _PLANCKIAN_U - u
    dv = _PLANCKIAN_V - v
    d2 = du * du + dv * dv
    i = int(np.argmin(d2))
    lo = min(max(i - 1, 0), len(_PLANCKIAN_T_K) - 3)
    hi = lo + 2
    t0, t1, t2 = _PLANCKIAN_T_K[lo:hi + 1]
    y0, y1, y2 = d2[lo:hi + 1]
    denom = (t0 - t1) * (t0 - t2) * (t1 - t2)
    a = (t0 * (y2 - y1) + t1 * (y0 - y2) + t2 * (y1 - y0)) / denom
    b = (t0 * t0 * (y1 - y2) + t1 * t1 * (y2 - y0) + t2 * t2 * (y0 - y1)) / denom
    temp = -b / (2.0 * a) if a != 0.0 else t1
    return float(min(max(temp, 1600.0), 25000.0))


def _find_matrices(prof, white_xy):
    """按白点相关色温在双校准照明体间做 1/T 加权插值。

    返回 (xyz_to_camera, forward_matrix, camera_calibration):
      xyz_to_camera = 插值后的 (CameraCalibration @ ColorMatrix), XYZ→相机原生空间
      forward_matrix 同权重插值 (可能缺失)
      camera_calibration 同权重插值 (个体/参考逆矩阵用)
    权重 g: g=1 → 照明体 1, g=0 → 照明体 2, 按 1/T 线性 (DNG 色彩标定附录)。
    """
    temp = temperature_from_xy(*white_xy)
    t1, t2 = _calibration_temperatures(prof)
    if temp <= t1:
        g = 1.0
    elif temp >= t2:
        g = 0.0
    else:
        inv_t = 1.0 / temp
        g = (inv_t - 1.0 / t2) / (1.0 / t1 - 1.0 / t2)
    cm1 = _mat3(getattr(prof, "color_matrix1", None))
    if cm1 is None:
        raise ValueError("DCP 缺少 ColorMatrix1")
    cm2 = _mat3(getattr(prof, "color_matrix2", None))
    cc1 = _mat3(getattr(prof, "camera_calibration1", None))
    cc2 = _mat3(getattr(prof, "camera_calibration2", None))
    if cc1 is None:
        cc1 = np.eye(3, dtype=np.float64)
    if cc2 is None:
        cc2 = cc1
    fm1 = _mat3(getattr(prof, "forward_matrix1", None))
    fm2 = _mat3(getattr(prof, "forward_matrix2", None))

    def blend(m1, m2):
        if m2 is None:
            return m1
        return g * m1 + (1.0 - g) * m2

    xyz_to_camera = blend(cc1 @ cm1, cc2 @ cm2)
    fm = blend(fm1, fm2) if fm1 is not None else None
    cc = blend(cc1, cc2)
    return xyz_to_camera, fm, cc


def _neutral_to_xy(neutral, prof):
    """相机中性 RGB → 白点 CIE xy (不动点迭代, DNG 色彩标定方法)。

    反复以当前 xy 估计双光源插值矩阵, 逆矩阵作用于中性向量得新 xy, 收敛到
    白点在色度图上的位置。最多 30 轮; 若振荡取两值平均。
    """
    neutral = np.asarray(neutral, dtype=np.float64).reshape(3)
    last = D50_XY
    nxt = D50_XY
    for _ in range(30):
        xyz_to_camera, _, _ = _find_matrices(prof, last)
        nxt = xyz_to_xy(np.linalg.inv(xyz_to_camera) @ neutral)
        if abs(nxt[0] - last[0]) + abs(nxt[1] - last[1]) < 1e-7:
            return nxt
        last = nxt
    return ((last[0] + nxt[0]) * 0.5, (last[1] + nxt[1]) * 0.5)


# ---------------------------------------------------------------------------
# WB 中性点 → xy / CCT
# ---------------------------------------------------------------------------

def wb_to_neutral(wb) -> np.ndarray:
    """WB 乘数 (G=1) → 相机中性 RGB (WB 后为 [1,1,1] 的原始比例)。"""
    wb = np.asarray(wb, dtype=np.float64).reshape(3)
    if wb[1] <= 0:
        wb = np.array([1.0, 1.0, 1.0], dtype=np.float64)
    else:
        wb = wb / wb[1]
    neutral = 1.0 / np.maximum(wb, 1e-9)
    return neutral / neutral[1]


def neutral_to_xy(neutral, prof) -> tuple[float, float]:
    """相机中性 RGB → 场景白点 CIE xy。

    有 ColorMatrix 时用不动点迭代 (对齐 dng_color_spec::NeutralToXY):
      next = XYZtoXY(inv(CM_interp(last)) @ neutral), 收敛到场景白点。
    无 CM 时退化为 FM1 @ neutral (或 sRGB 近似)。
    """
    neutral = np.asarray(neutral, dtype=np.float64).reshape(3)
    cm1 = _mat3(getattr(prof, "color_matrix1", None)) if prof is not None else None
    if cm1 is None:
        fm1 = _mat3(getattr(prof, "forward_matrix1", None)) if prof is not None else None
        if fm1 is not None:
            return xyz_to_xy(fm1 @ neutral)
        # 无任何相机矩阵: 假设相机原生 ≈ sRGB 原色 (粗略近似, 仅作回退)
        return xyz_to_xy(_SRGB_TO_XYZ_D65 @ neutral)
    cm2 = _mat3(getattr(prof, "color_matrix2", None))
    t1, t2 = _calibration_temperatures(prof)
    last = D50_XY
    nxt = D50_XY
    for _ in range(30):
        cct = xy_to_cct(*last)
        cm = _interp_1_over_t(cm1, cm2, cct, t1, t2)
        nxt = xyz_to_xy(np.linalg.inv(cm) @ neutral)
        if abs(nxt[0] - last[0]) + abs(nxt[1] - last[1]) < 1e-7:
            return nxt
        last = nxt
    # 两值振荡: 取均值 (对齐 SDK)
    return ((last[0] + nxt[0]) * 0.5, (last[1] + nxt[1]) * 0.5)


def cct_from_wb(wb, prof=None) -> float:
    """WB 乘数 → 相关色温 K (CIE xy → McCamy)。

    越界钳位到 [1000, 50000] K (规格: 越界钳位)。
    """
    neutral = wb_to_neutral(wb)
    xy = neutral_to_xy(neutral, prof)
    return float(np.clip(xy_to_cct(*xy), 1000.0, 50000.0))


# ---------------------------------------------------------------------------
# 色温/色调 (temp/tint) 正反解 —— LR 观感暖度校正的键
# ---------------------------------------------------------------------------
# LR 面板的 Temperature(K)/Tint(-150..+150) 与相机 WB 系数互为映射:
#   - 正解 temp_tint_to_wb: 读数 → WB 系数 (Kim 黑体轨迹 + uv 空间等温线偏移);
#   - 反解 wb_to_temp_tint: WB 系数 → 读数 (Newton, 纯 numpy)。
# 实测 (Nikon Z 5 2): 0376 wb[1.291,1,2.287] → (3500K, +30); 5236 wb[1.244,1,1.791]
# → (3543K, -30)。与 LR 面板读数 (3300/+27, 3450/0) 方向一致、幅值接近
# (Adobe 的映射是每机私有标定, 此处用 DCP ColorMatrix 反推, 仅作校正键)。

def temp_to_xy(temp_k: float) -> tuple[float, float]:
    """色温 K → CIE 黑体轨迹 xy (Kim et al. 2002 近似)。"""
    t = float(temp_k)
    if t < 1667:
        t = 1667.0
    if t <= 4000:
        x = (-0.2661239e9 / t ** 3 - 0.2343589e6 / t ** 2
             + 0.8776956e3 / t + 0.179910)
    else:
        x = (-3.0258469e9 / t ** 3 + 2.1070379e6 / t ** 2
             + 0.2226347e3 / t + 0.240390)
    if t <= 2222:
        y = (-1.1063814 * x ** 3 - 1.34811020 * x ** 2
             + 2.18555832 * x - 0.20219683)
    elif t <= 4000:
        y = (-0.9549476 * x ** 3 - 1.37418593 * x ** 2
             + 2.09137015 * x - 0.16748867)
    else:
        y = (3.0817580 * x ** 3 - 5.87338670 * x ** 2
             + 3.75112997 * x - 0.37001483)
    return x, y


def temp_tint_to_xy(temp_k: float, tint: float) -> tuple[float, float]:
    """色温+色调 → xy: tint 沿等温线在 uv 空间偏移 (±150 ≈ ±0.010 uv)。"""
    x, y = temp_to_xy(temp_k)
    u = 4 * x / (-2 * x + 12 * y + 3)
    v = 6 * y / (-2 * x + 12 * y + 3)
    v += (float(tint) / 150.0) * 0.010
    x2 = 3 * u / (2 * u - 8 * v + 4)
    y2 = 2 * v / (2 * u - 8 * v + 4)
    return max(0.05, min(x2, 0.75)), max(0.05, min(y2, 0.75))


def temp_tint_to_wb(prof, temp_k: float, tint: float) -> np.ndarray:
    """色温/色调读数 → 相机 WB 系数 [r, 1, b] (G=1)。

    路径: xy → XYZ → inv(ColorMatrix) → 相机中性响应 → wb=1/响应。
    """
    cm1 = _mat3(getattr(prof, "color_matrix1", None))
    cm2 = _mat3(getattr(prof, "color_matrix2", None))
    if cm1 is None:
        raise ValueError("DCP 缺 ColorMatrix1")
    t1, t2 = _calibration_temperatures(prof)
    x, y = temp_tint_to_xy(temp_k, tint)
    cct = xy_to_cct(x, y)
    cm = _interp_1_over_t(cm1, cm2, cct, t1, t2)
    xyz = xy_to_xyz(x, y)
    # CM 方向 = XYZ→camera (engine.color 约定: out = M @ in), 相机对光源的
    # 中性响应 = CM @ xyz (校准光源处 ≈ [1,1,1] 恒等)。旧实现误用 inv(cm),
    # 导致钨丝灯下响应 B 通道反向失真 (2026-08 修复)。
    resp = cm @ xyz
    resp = np.maximum(resp, 1e-6)
    wb = 1.0 / resp
    wb = wb / wb[1]
    return np.array([wb[0], 1.0, wb[2]], dtype=np.float32)


def wb_to_temp_tint(prof, wb, max_iter: int = 12) -> tuple[float, float]:
    """相机 WB 系数 [r, g, b] → (temp K, tint), temp_tint_to_wb 的反函数。

    求解要点 (2026-08 教训): tint 对 WB 系数的影响极小 (±150 tint ≈ ±0.010 uv,
    WB 系数相对变化 ~1e-4/tint 单位), 数值有限差分的步长必须按量纲放大,
    否则步长 h=1e-4 的差分被浮点噪声淹没 → 错误收敛 (曾把两张图都解成
    tint=-20, 导致 warm 强度只剩 0.15)。实现: scipy least_squares (多起点),
    scipy 缺失时回退粗网格扫描 (纯 numpy)。
    """
    wb = np.asarray(wb, dtype=np.float64)
    target = np.array([wb[0] / wb[1], wb[2] / wb[1]], dtype=np.float64)

    def residual(p):
        t, ti = float(p[0]), float(p[1])
        out = temp_tint_to_wb(prof, t, ti).astype(np.float64)
        return np.array([out[0] / out[1] - target[0],
                         out[2] / out[1] - target[1]], dtype=np.float64)

    cct0 = float(np.clip(cct_from_wb(wb, prof), 1500.0, 40000.0))
    starts = [(cct0, 0.0), (3000.0, 0.0), (5000.0, 0.0),
              (cct0, 25.0), (cct0, -25.0)]
    try:
        from scipy.optimize import least_squares
        best, best_cost = None, float("inf")
        for t0, ti0 in starts:
            r = least_squares(residual, [t0, ti0],
                              bounds=([1500.0, -150.0], [50000.0, 150.0]),
                              x_scale=[100.0, 10.0], max_nfev=60)
            cost = float(np.sum(residual(r.x) ** 2))
            if cost < best_cost:
                best, best_cost = (float(r.x[0]), float(r.x[1])), cost
        return float(best[0]), float(best[1])
    except ImportError:
        pass
    # 纯 numpy 回退: 粗网格 + 局部二次插值
    best, best_cost = None, float("inf")
    for t in np.linspace(2000.0, 8000.0, 13):
        for ti in np.linspace(-60.0, 60.0, 13):
            cost = float(np.sum(residual([t, ti]) ** 2))
            if cost < best_cost:
                best, best_cost = (float(t), float(ti)), cost
    return float(best[0]), float(best[1])


# ---------------------------------------------------------------------------
# 相机 → XYZ(D50) / 线性 sRGB 主链路
# ---------------------------------------------------------------------------

def cam_to_xyz_matrix(prof, wb) -> np.ndarray:
    """WB 后相机 RGB (`cam * wb`, 中性→[1,1,1]) → XYZ(D50) 3×3 矩阵。

    基座 colorimetric 路径 (有 CM):
      xyz = Bradford(场景白→D50) @ inv(CM_interp) @ inv(CC_interp) @ diag(1/wb) @ (cam*wb)
    即: 先把 WB 后的相机值还原为原生相机值 (diag(1/wb)), 经 inv(CM×CC) 得
    XYZ(场景参考), 再 Bradford 色适应到 D50。
    缺 CM: 回退 FM 路径 (FM 本身即 WB 相机 → XYZ(D50)) 并告警。
    """
    cm1 = _mat3(getattr(prof, "color_matrix1", None))
    if cm1 is not None:
        neutral = wb_to_neutral(wb)
        scene_xy = neutral_to_xy(neutral, prof)
        cct = xy_to_cct(*scene_xy)
        cm, cc = interpolate_color_matrices(prof, cct)
        cam_to_xyz_scene = np.linalg.inv(cm) @ np.linalg.inv(cc)
        # diag(1/wb) 把 WB 后相机值还原为原生 (未 WB) 相机值
        return bradford_adapt(scene_xy, D50_XY) @ cam_to_xyz_scene @ _diag_inv_wb(wb)

    fm = interpolate_forward_matrix(prof, wb)
    if fm is None:
        raise ValueError("DCP 既缺 ColorMatrix 又缺 ForwardMatrix, 无法建立 camera→XYZ 映射")
    warnings.warn(
        "DCP 缺 ColorMatrix, 已回退 ForwardMatrix (look) 路径: "
        "colorimetric 精度下降, 仅保证中性与方向一致。",
        ColorMatrixFallbackWarning,
        stacklevel=2,
    )
    return fm


def _diag_inv_wb(wb) -> np.ndarray:
    """diag(1/wb) —— 把 WB 后相机值还原为原生 (未 WB) 相机值。"""
    wb = np.asarray(wb, dtype=np.float64).reshape(3)
    return np.diag(1.0 / np.maximum(wb, 1e-9))


def cam_to_linear_srgb_matrix(prof, wb) -> np.ndarray:
    """WB 后相机 RGB → 线性 sRGB(D65) 3×3 矩阵 (完整基座链路)。"""
    m_xyz = cam_to_xyz_matrix(prof, wb)
    return _XYZ65_TO_SRGB @ _BRADFORD_D50_TO_D65 @ m_xyz


def camera_white(prof, wb) -> np.ndarray:
    """DNG SDK 的 CameraWhite 向量 (WB 后相机值在 ProPhoto 转换前的裁剪上限)。

    对齐 dng_color_spec::CameraWhite: fColorMatrix(AB*CC*CM) × XYZ(scene white),
    按最大通道归一化后 pin 到 [0.001, 1]。插值用 dng_temperature 而非 McCamy。
    """
    neutral = wb_to_neutral(wb)
    scene_xy = _neutral_to_xy(neutral, prof)
    color_matrix, _, _ = _find_matrices(prof, scene_xy)
    cam_white = color_matrix @ xy_to_xyz(*scene_xy)
    mx = float(np.max(cam_white))
    if mx <= 0:
        return np.ones(3, dtype=np.float64)
    cam_white = cam_white / mx
    return np.clip(cam_white, 0.001, 1.0)


def cam_to_prophoto_matrix(prof, wb) -> np.ndarray:
    """WB 后相机 RGB → 线性 ProPhoto(D50) 3×3 矩阵 (DNG SDK ForwardMatrix 路径)。

    对齐 dng_render.cpp:
      CameraToPCS = FM × inv(diag(inv(CC)×CameraWhite)) × inv(CC)
      CameraToRGB = ProPhoto.MatrixFromPCS × CameraToPCS
    矩阵插值使用 DNG dng_temperature 反查 (与 dng_color_spec 一致)。
    """
    neutral = wb_to_neutral(wb)
    scene_xy = _neutral_to_xy(neutral, prof)
    _, fm, cc = _find_matrices(prof, scene_xy)
    if fm is None:
        raise ValueError("DCP 缺 ForwardMatrix, 无法复刻 DNG SDK HSM 应用域")
    # NormalizeForwardMatrix: FM * ones 归一化到 PCS 白点 (D50)。
    # 注意 DNG 源码用 D50_xy_coord()=(0.3457,0.3585) 四位小数,
    # 不是更精确的 (0.34567,0.35850); 差值会把 CameraToPCS 带偏 ~7e-5。
    _DNG_D50_XY = (0.3457, 0.3585)
    xyz_one = fm @ np.ones(3, dtype=np.float64)
    fm = np.diag(xy_to_xyz(*_DNG_D50_XY)) @ np.diag(1.0 / np.maximum(xyz_one, 1e-9)) @ fm
    # DNG SDK: individualToReference = inv(AnalogBalance * CameraCalibration)
    individual_to_ref = np.linalg.inv(cc)
    cam_white = camera_white(prof, wb)
    ref_cam_white = individual_to_ref @ cam_white
    inv_diag = np.diag(1.0 / np.maximum(ref_cam_white, 1e-9))
    camera_to_pcs = fm @ inv_diag @ individual_to_ref
    # dng_space_ProPhoto::SetMatrixToPCS: 先用 4 位小数常量 M, 再按
    # S = diag(PCStoXYZ() / (M*ones)) 缩放使 device white 精确落到 PCS,
    # 最后 MatrixFromPCS = Invert(S*M)。不能直接 invert 原始 M。
    dng_pp_m = np.array([[0.7977, 0.1352, 0.0313],
                         [0.2880, 0.7119, 0.0001],
                         [0.0000, 0.0000, 0.8249]], dtype=np.float64)
    dng_pcs_xyz = xy_to_xyz(0.3457, 0.3585)
    w1 = dng_pp_m @ np.ones(3, dtype=np.float64)
    s = np.diag(dng_pcs_xyz / w1)
    prophoto_from_pcs = np.linalg.inv(s @ dng_pp_m)
    return prophoto_from_pcs @ camera_to_pcs


def prophoto_to_linear_srgb_matrix() -> np.ndarray:
    """dng_render fRGBtoFinal = sRGB_Linear.MatrixFromPCS * ProPhoto.MatrixToPCS。

    两个 space 都经过 SetMatrixToPCS 的白点缩放 (4 位小数原色矩阵 + PCS D50
    (0.3457,0.3585)), 不能直接用标准 sRGB/ROMM 7 位矩阵。
    """
    pcs_xyz = xy_to_xyz(0.3457, 0.3585)
    pp_m = np.array([[0.7977, 0.1352, 0.0313],
                     [0.2880, 0.7119, 0.0001],
                     [0.0000, 0.0000, 0.8249]], dtype=np.float64)
    srgb_m = np.array([[0.4361, 0.3851, 0.1431],
                       [0.2225, 0.7169, 0.0606],
                       [0.0139, 0.0971, 0.7141]], dtype=np.float64)
    pp_to_pcs = np.diag(pcs_xyz / (pp_m @ np.ones(3))) @ pp_m
    srgb_to_pcs = np.diag(pcs_xyz / (srgb_m @ np.ones(3))) @ srgb_m
    return np.linalg.inv(srgb_to_pcs) @ pp_to_pcs


def linear_prophoto_to_srgb(pp: np.ndarray) -> np.ndarray:
    """DNG SDK 的线性 ProPhoto → 线性 sRGB (final space 矩阵 + Pin[0,1])。"""
    m = prophoto_to_linear_srgb_matrix()
    x = np.asarray(pp, dtype=np.float32)
    out = np.clip(x, 0.0, 1.0) @ m.T
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def cam_wb_to_prophoto(cam_wb, prof, wb) -> np.ndarray:
    """WB 后相机 RGB → DNG SDK 线性 ProPhoto (含 CameraWhite 裁剪 + [0,1] 钳位)。"""
    m = cam_to_prophoto_matrix(prof, wb)
    white = camera_white(prof, wb)
    x = np.asarray(cam_wb, dtype=np.float64)
    x = np.minimum(x, white[np.newaxis, np.newaxis, :])
    out = x @ m.T
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def cam_to_xyz(cam_rgb, wb, prof) -> np.ndarray:
    """完整色彩链路: 相机原生 RGB (未 WB) → 线性 sRGB(D65) (规格接口)。

    入参 cam_rgb 为 WB 前的相机 RGB; 内部先乘 wb 中性化, 再经
    cam_to_linear_srgb_matrix (WB 相机 → 线性 sRGB)。输出是线性 sRGB 而非 XYZ
    (命名沿用规格; 真正的 XYZ(D50) 矩阵见 cam_to_xyz_matrix)。向量化, 支持 (...,3)。
    """
    m = cam_to_linear_srgb_matrix(prof, wb)
    wb = np.asarray(wb, dtype=np.float64).reshape(3)
    cam = np.asarray(cam_rgb, dtype=np.float64)
    shaped = cam * wb
    out = shaped @ m.T
    return np.clip(out, 0.0, None).astype(np.float32)


def xyz_to_linear_srgb(xyz_d50) -> np.ndarray:
    """XYZ(D50) → 线性 sRGB(D65) (Bradford D50→D65 + sRGB 矩阵)。"""
    xyz = np.asarray(xyz_d50, dtype=np.float64)
    return np.clip(xyz @ (_XYZ65_TO_SRGB @ _BRADFORD_D50_TO_D65).T,
                   0.0, None).astype(np.float32)


# ---------------------------------------------------------------------------
# 线性 sRGB(D65) ↔ 线性 ProPhoto/ROMM RGB(D50) —— HueSatMap 应用域转换
# ---------------------------------------------------------------------------
# Adobe DNG SDK 在线性 ProPhoto(D50)、影调曲线之前应用 HueSatMap/LookTable
# (见 dsh-plan-task-p4/research/hsmap-domain.md)。转换经 XYZ(D65)+Bradford 往返:
#   sRGB → XYZ(D65) → Bradford(D65→D50) → XYZ(D50) → ProPhoto (ROMM 标准矩阵)
# 复合矩阵在模块加载时以 float64 求值; 两函数互为精确逆 (往返误差 ≤ 1e-6)。

def linear_srgb_to_linear_prophoto(rgb: np.ndarray) -> np.ndarray:
    """线性 sRGB(D65) → 线性 ProPhoto/ROMM RGB(D50) ((...,3))。

    路径: XYZ(D65) → Bradford(D65→D50) → ProPhoto RGB (ROMM 标准矩阵)。
    向量化, 支持 (...,3)。输出精度跟随输入: float32 输入 → float32 输出
    (规格接口); float64 输入 → float64 输出 (HSM 高精度路径, 恒等表 ≤1e-6)。
    """
    src = np.asarray(rgb)
    x = src.astype(np.float64)
    out = x @ _SRGB_TO_PROPHOTO.T
    return out.astype(np.float32) if src.dtype == np.float32 else out


def linear_prophoto_to_linear_srgb(rgb: np.ndarray) -> np.ndarray:
    """线性 ProPhoto/ROMM RGB(D50) → 线性 sRGB(D65) ((...,3))。

    路径: ProPhoto RGB → XYZ(D50) → Bradford(D50→D65) → XYZ(D65) → sRGB。
    与 linear_srgb_to_linear_prophoto 互为逆; 恒等往返误差 ≤ 1e-6
    (float64 输入下往返误差 ≈ 末次浮点舍入)。
    """
    src = np.asarray(rgb)
    x = src.astype(np.float64)
    out = x @ _PROPHOTO_TO_SRGB.T
    return out.astype(np.float32) if src.dtype == np.float32 else out

__all__ = [
    "D50_XY", "D65_XY", "PROPHOTO_RGB_TO_XYZ_D50", "ColorMatrixFallbackWarning",
    "illuminant_cct", "xy_to_cct", "xyz_to_xy", "xy_to_xyz", "bradford_adapt",
    "interpolate_color_matrices", "interpolate_forward_matrix",
    "temperature_from_xy", "wb_to_neutral", "neutral_to_xy", "cct_from_wb",
    "temp_to_xy", "temp_tint_to_xy", "temp_tint_to_wb", "wb_to_temp_tint",
    "cam_to_xyz_matrix", "cam_to_linear_srgb_matrix", "camera_white",
    "cam_to_prophoto_matrix", "prophoto_to_linear_srgb_matrix",
    "linear_prophoto_to_srgb", "cam_wb_to_prophoto", "cam_to_xyz",
    "xyz_to_linear_srgb", "linear_srgb_to_linear_prophoto",
    "linear_prophoto_to_linear_srgb",
]
