"""T1 单元测试: 色彩常量/矩阵往返精度 + sRGB EOTF 往返。

覆盖对象:
  - render.core.calibration.XYZ_D65_TO_SRGB   (XYZ(D65) → 线性 sRGB)
  - render.core.calibration.SRGB_TO_XYZ_D65   (线性 sRGB → XYZ(D65))
  - render.core.calibration.BRADFORD_D50_TO_D65 (色适应 D50 → D65)
  - render.core.curves.srgb_encode (sRGB EOTF 编码, 线性 → gamma)

验收标准 (规格 AC-01 / AC-02):
  - 矩阵往返 (M · M⁻¹ ≈ I) 误差 < 1e-5
  - sRGB EOTF 线性↔gamma 往返最大误差 < 1e-4

说明:
  - 代码库当前仅有 srgb_encode (线性→gamma), 无 srgb_decode。
    本测试内置标准解码参考实现 (IEC 61966-2-1), 仅作往返校验基准,
    不引入/修改 render 的既有常量或接口。

运行: python -m pytest src/render/tests/test_color_math.py -q
"""
from __future__ import annotations

import numpy as np

from render.core.calibration import BRADFORD_D50_TO_D65, SRGB_TO_XYZ_D65, XYZ_D65_TO_SRGB
from render.core.curves import srgb_encode

# ---- 验收阈值 ----
MATRIX_TOL = 1e-5   # 矩阵往返误差上限
EOTF_TOL = 1e-4     # sRGB EOTF 往返误差上限


def _mat(m) -> np.ndarray:
    """3x3 常量 (list[list[float]]) → float64 ndarray。"""
    return np.asarray(m, dtype=np.float64)


def srgb_decode(c) -> np.ndarray:
    """标准 sRGB EOTF 解码 (gamma → 线性), IEC 61966-2-1 参考实现。

    srgb_encode 的逆: 与 srgb_encode 互逆, 用于往返测试。
    """
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))


# ---------------------------------------------------------------------------
# 矩阵往返精度 (AC-01)
# ---------------------------------------------------------------------------

def test_xyz_to_srgb_and_srgb_to_xyz_are_inverses_forward():
    """XYZ→sRGB · sRGB→XYZ ≈ I (前向组合)。"""
    a = _mat(XYZ_D65_TO_SRGB)
    b = _mat(SRGB_TO_XYZ_D65)
    err = float(np.abs(a @ b - np.eye(3)).max())
    assert err < MATRIX_TOL, f"XYZ→sRGB·sRGB→XYZ 往返误差 {err:.3e} ≥ {MATRIX_TOL}"


def test_xyz_to_srgb_and_srgb_to_xyz_are_inverses_backward():
    """sRGB→XYZ · XYZ→sRGB ≈ I (反向组合)。"""
    a = _mat(XYZ_D65_TO_SRGB)
    b = _mat(SRGB_TO_XYZ_D65)
    err = float(np.abs(b @ a - np.eye(3)).max())
    assert err < MATRIX_TOL, f"sRGB→XYZ·XYZ→sRGB 往返误差 {err:.3e} ≥ {MATRIX_TOL}"


def test_bradford_d50_to_d65_round_trip():
    """Bradford 色适应矩阵与其逆矩阵往返 ≈ I。"""
    m = _mat(BRADFORD_D50_TO_D65)
    minv = np.linalg.inv(m)
    err_fwd = float(np.abs(m @ minv - np.eye(3)).max())
    err_bwd = float(np.abs(minv @ m - np.eye(3)).max())
    assert err_fwd < MATRIX_TOL, f"Bradford 往返误差 {err_fwd:.3e} ≥ {MATRIX_TOL}"
    assert err_bwd < MATRIX_TOL, f"Bradford 反向往返误差 {err_bwd:.3e} ≥ {MATRIX_TOL}"


def test_bradford_maps_d50_white_to_d65_white():
    """方向校验: D50 白点经 Bradford(D50→D65) 映射到 D65 白点。"""
    m = _mat(BRADFORD_D50_TO_D65)
    d50_white = np.array([0.96422, 1.0, 0.82521])   # CIE D50 白点 (Y=1)
    d65_white = np.array([0.95047, 1.0, 1.08883])   # CIE D65 白点 (Y=1)
    err = float(np.abs(m @ d50_white - d65_white).max())
    assert err < 1e-4, f"D50→D65 白点映射误差 {err:.3e} 过大"


# ---------------------------------------------------------------------------
# sRGB EOTF 往返 (AC-02)
# ---------------------------------------------------------------------------

def test_srgb_eotf_linear_gamma_linear_round_trip():
    """线性 → gamma → 线性 往返 (稠密网格)。"""
    x = np.linspace(0.0, 1.0, 100_001)
    err = float(np.abs(srgb_decode(srgb_encode(x)) - x).max())
    assert err < EOTF_TOL, f"sRGB EOTF 线性→gamma→线性 误差 {err:.3e} ≥ {EOTF_TOL}"


def test_srgb_eotf_gamma_linear_gamma_round_trip():
    """gamma → 线性 → gamma 往返 (稠密网格)。"""
    c = np.linspace(0.0, 1.0, 100_001)
    err = float(np.abs(srgb_encode(srgb_decode(c)) - c).max())
    assert err < EOTF_TOL, f"sRGB EOTF gamma→线性→gamma 误差 {err:.3e} ≥ {EOTF_TOL}"


def test_srgb_eotf_round_trip_random():
    """随机采样往返 (覆盖分段阈值两侧, 固定种子可复现)。"""
    rng = np.random.default_rng(0)
    x = rng.random(200_000)
    c = rng.random(200_000)
    err_lin = float(np.abs(srgb_decode(srgb_encode(x)) - x).max())
    err_gam = float(np.abs(srgb_encode(srgb_decode(c)) - c).max())
    assert err_lin < EOTF_TOL, f"随机线性往返误差 {err_lin:.3e} ≥ {EOTF_TOL}"
    assert err_gam < EOTF_TOL, f"随机 gamma 往返误差 {err_gam:.3e} ≥ {EOTF_TOL}"


def test_srgb_encode_anchor_points():
    """编码锚点: 端点 0/1 与线性分段阈值 0.0031308 → 0.04045。"""
    assert float(srgb_encode(np.array([0.0]))[0]) == 0.0
    assert abs(float(srgb_encode(np.array([1.0]))[0]) - 1.0) < 1e-9
    assert abs(float(srgb_encode(np.array([0.0031308]))[0]) - 0.04045) < 1e-6


def test_srgb_decode_anchor_points():
    """解码锚点: 端点 0/1 与 gamma 分段阈值 0.04045 → 0.0031308。"""
    assert float(srgb_decode(np.array([0.0]))[0]) == 0.0
    assert abs(float(srgb_decode(np.array([1.0]))[0]) - 1.0) < 1e-9
    assert abs(float(srgb_decode(np.array([0.04045]))[0]) - 0.0031308) < 1e-6
