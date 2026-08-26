"""T1 单元测试: 色彩常量/矩阵往返精度 + sRGB EOTF 往返。

覆盖对象:
  - pixo.render.core.calibration.XYZ_D65_TO_SRGB   (XYZ(D65) → 线性 sRGB)
  - pixo.render.core.calibration.SRGB_TO_XYZ_D65   (线性 sRGB → XYZ(D65))
  - pixo.render.core.calibration.BRADFORD_D50_TO_D65 (色适应 D50 → D65)
  - pixo.render.core.curves.srgb_encode (sRGB EOTF 编码, 线性 → gamma)

验收标准 (规格 AC-01 / AC-02):
  - 矩阵往返 (M · M⁻¹ ≈ I) 误差 < 1e-5
  - sRGB EOTF 线性↔gamma 往返最大误差 < 1e-4

说明:
  - 代码库当前仅有 srgb_encode (线性→gamma), 无 srgb_decode。
    本测试内置标准解码参考实现 (IEC 61966-2-1), 仅作往返校验基准,
    不引入/修改 render 的既有常量或接口。

运行: python -m pytest tests/test_color_math.py -q
"""
from __future__ import annotations

import numpy as np

from pixo.render.core.calibration import BRADFORD_D50_TO_D65, SRGB_TO_XYZ_D65, XYZ_D65_TO_SRGB
from pixo.render.core.curves import srgb_encode

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


# ---------------------------------------------------------------------------
# S1: _find_matrices 双光源插值顺序 (DNG SDK 口径: 先插值后复合)
# ---------------------------------------------------------------------------

def test_find_matrices_interpolates_before_composing():
    """S1 回归: xyz_to_camera = blend(CC) @ blend(CM), 不是 blend(CC@CM)。

    DNG SDK (dng_color_spec) 先分别插值 CameraCalibration 与 ColorMatrix
    再复合; 矩阵插值与复合不可交换, 旧"先复合后插值"数值不等价。
    """
    from types import SimpleNamespace

    from pixo.render.core.color import (_calibration_temperatures,
                                        _find_matrices,
                                        temperature_from_xy)

    prof = SimpleNamespace(
        calibration_illuminant1=17,   # StdA ~2856K
        calibration_illuminant2=21,   # D65 ~6500K
        color_matrix1=[1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449,
                       -0.0231, 0.0811, 0.7571],
        color_matrix2=[0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286,
                       -0.0648, 0.1513, 0.6375],
        camera_calibration1=[1.02, 0.0, 0.0, 0.0, 0.99, 0.0, 0.0, 0.0, 1.01],
        camera_calibration2=[0.98, 0.01, 0.0, 0.01, 1.02, 0.0, 0.0, -0.01, 0.99],
        forward_matrix1=[0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001,
                         0.0, 0.0, 0.8251],
        forward_matrix2=[0.81, 0.12, 0.03, 0.27, 0.73, 0.001, 0.0, 0.0, 0.82])

    # 取双光源之间的白点 (~4600K 附近), 保证 0<g<1 (插值真正发生)
    xy = (0.355, 0.345)
    temp = temperature_from_xy(*xy)
    t1, t2 = _calibration_temperatures(prof)
    g = (1.0 / temp - 1.0 / t2) / (1.0 / t1 - 1.0 / t2)
    assert t1 < temp < t2 and 0.01 < g < 0.99, (
        f"测试白点未落在插值区: temp={temp}, g={g}")

    xyz_to_camera, fm, cc = _find_matrices(prof, xy)

    def blend(m1, m2):
        return g * np.asarray(m1, dtype=np.float64).reshape(3, 3) \
            + (1.0 - g) * np.asarray(m2, dtype=np.float64).reshape(3, 3)

    cc_expected = blend(prof.camera_calibration1, prof.camera_calibration2)
    cm_expected = blend(prof.color_matrix1, prof.color_matrix2)
    fm_expected = blend(prof.forward_matrix1, prof.forward_matrix2)

    assert np.allclose(cc, cc_expected, atol=1e-12)
    assert np.allclose(fm, fm_expected, atol=1e-12)
    # 先插值后复合 (SDK 口径)
    assert np.allclose(xyz_to_camera, cc_expected @ cm_expected, atol=1e-12)
    # 旧实现 (先复合后插值) 数值上确有差异 → 本断言防回退
    legacy = blend(np.asarray(prof.camera_calibration1).reshape(3, 3)
                   @ np.asarray(prof.color_matrix1).reshape(3, 3),
                   np.asarray(prof.camera_calibration2).reshape(3, 3)
                   @ np.asarray(prof.color_matrix2).reshape(3, 3))
    assert not np.allclose(xyz_to_camera, legacy, atol=1e-6), (
        "xyz_to_camera 退回'先复合后插值'口径")
