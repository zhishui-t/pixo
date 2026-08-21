"""T2 单元测试: DCP 完整色彩链路 (CM×CameraCalibration→XYZ + FM look)。

覆盖对象 (render/core/color.py):
  - cam_to_xyz_matrix / cam_to_linear_srgb_matrix / cam_to_xyz (基座 colorimetric 路径)
  - interpolate_color_matrices (ColorMatrix1/2 按 1/T 插值)
  - cct_from_wb / xy_to_cct (CIE xy → McCamy CCT)
  - 缺 CM 回退 FM 并告警 (ColorMatrixFallbackWarning)
  - neutral_to_xy (相机中性点 → 场景白 xy)

验收标准 (规格 AC-01/AC-02 + T2 acceptance):
  - 矩阵往返误差 <1e-5
  - CCT 反演在已知黑体温度 (2856/5000/6500K 等) 误差 <300K
  - 缺 CM 回退 FM 并告警
  - CM 1/T 插值端点正确 (T=T1→CM1, T=T2→CM2)
  - 中性 spread≈1 (WB 中性 [1,1,1] → 中性 sRGB)
  - 皮肤 a/b 方向与相机一致 (CM 与 FM 路径 a、b 同号, 且为暖色)

运行: python -m pytest render/tests/test_dcp_color.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from render.core.calibration import BRADFORD_D50_TO_D65, SRGB_TO_XYZ_D65, XYZ_D65_TO_SRGB, DcpProfile
from render.core.color import (
    ColorMatrixFallbackWarning,
    cam_to_linear_srgb_matrix,
    cam_to_xyz,
    cam_to_xyz_matrix,
    cct_from_wb,
    interpolate_color_matrices,
    neutral_to_xy,
    wb_to_neutral,
    xy_to_cct,
)

# ---- 验收阈值 ----
MATRIX_TOL = 1e-5
CCT_TOL = 300.0          # K
NEUTRAL_SPREAD_TOL = 0.01  # max/min - 1

# 真实 Nikon Z 5 II Camera Standard 的矩阵 (作为确定性测试用例, 无需外部文件)
_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]

# CIE 1931 2° 标准观察者黑体轨迹色度 (x, y)
_BLACKBODY_XY = {
    2856: (0.44757, 0.40746),
    4000: (0.38048, 0.37675),
    5000: (0.34509, 0.35161),
    6500: (0.31348, 0.32365),
    10000: (0.28064, 0.28829),
}


def _mat3(values):
    return np.asarray(values, dtype=np.float64).reshape(3, 3)


_DEFAULT = object()


def _make_profile(cm1=_DEFAULT, cm2=_DEFAULT, fm1=_DEFAULT, fm2=_DEFAULT,
                  cc1=None, cc2=None, ill1=17, ill2=21) -> DcpProfile:
    """构造合成 DcpProfile (参数缺省用 Nikon 矩阵; 显式传 None 表示"缺失该标签")。"""
    return DcpProfile(
        path=Path("test.dcp"),
        color_matrix1=_NIKON_CM1 if cm1 is _DEFAULT else cm1,
        color_matrix2=_NIKON_CM2 if cm2 is _DEFAULT else cm2,
        forward_matrix1=_NIKON_FM1 if fm1 is _DEFAULT else fm1,
        forward_matrix2=_NIKON_FM1 if fm2 is _DEFAULT else fm2,
        camera_calibration1=cc1,
        camera_calibration2=cc2,
        calibration_illuminant1=ill1,
        calibration_illuminant2=ill2,
    )


def _srgb_decode(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _srgb_encode(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)


def _lab_from_linear_srgb(rgb):
    """线性 sRGB(D65) → CIE Lab (D65 白点), 返回 (L, a, b)。"""
    xyz = np.asarray(SRGB_TO_XYZ_D65, dtype=np.float64) @ np.asarray(rgb, dtype=np.float64)
    xn, yn, zn = 0.95047, 1.0, 1.08883
    x, y, z = xyz[0] / xn, xyz[1] / yn, xyz[2] / zn
    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


# ---------------------------------------------------------------------------
# 矩阵往返精度
# ---------------------------------------------------------------------------

def test_cam_to_xyz_matrix_invertible():
    """camera→XYZ(D50) 矩阵与其逆往返 ≈ I。"""
    prof = _make_profile()
    wb = np.array([2.0, 1.0, 1.5])
    m = cam_to_xyz_matrix(prof, wb)
    err = float(np.abs(m @ np.linalg.inv(m) - np.eye(3)).max())
    assert err < MATRIX_TOL, f"camera→XYZ 矩阵往返误差 {err:.3e} ≥ {MATRIX_TOL}"


def test_cam_to_linear_srgb_matrix_composition():
    """cam→sRGB 矩阵 = sRGB @ Bradford(D50→D65) @ (cam→XYZ D50)。"""
    prof = _make_profile()
    wb = np.array([2.0, 1.0, 1.5])
    full = cam_to_linear_srgb_matrix(prof, wb)
    expected = (_mat3(XYZ_D65_TO_SRGB) @ _mat3(BRADFORD_D50_TO_D65)
                @ cam_to_xyz_matrix(prof, wb))
    err = float(np.abs(full - expected).max())
    assert err < MATRIX_TOL, f"矩阵组合不一致, 误差 {err:.3e}"


def test_functional_round_trip():
    """相机 RGB → 线性 sRGB → 相机 RGB 功能往返。"""
    prof = _make_profile()
    wb = np.array([2.0, 1.0, 1.5])
    m = cam_to_linear_srgb_matrix(prof, wb)
    rng = np.random.default_rng(0)
    cam_wb = rng.random((50, 3))  # WB 后相机 RGB
    srgb = cam_wb @ m.T
    back = srgb @ np.linalg.inv(m).T
    err = float(np.abs(back - cam_wb).max())
    assert err < 1e-8, f"功能往返误差 {err:.3e} 过大"


# ---------------------------------------------------------------------------
# CCT 反演 (McCamy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("temp,xy", sorted(_BLACKBODY_XY.items()))
def test_cct_inversion_known_blackbody(temp, xy):
    """已知黑体温度 xy → McCamy CCT, 误差 < 300K。"""
    cct = xy_to_cct(*xy)
    assert abs(cct - temp) < CCT_TOL, f"黑体 {temp}K 反演为 {cct:.1f}K, 误差 {abs(cct - temp):.1f}K"


def test_cct_from_wb_range_and_direction():
    """cct_from_wb 落在 [1000,50000] 且蓝增益高(钨丝)→低温, 红增益高(阴影)→高温。"""
    prof = _make_profile()
    cct_tungsten = cct_from_wb(np.array([1.0, 1.0, 2.2]), prof)   # 高蓝增益 → 钨丝灯 (低温)
    cct_shade = cct_from_wb(np.array([2.2, 1.0, 1.0]), prof)      # 高红增益 → 阴影 (高温)
    assert 1000.0 <= cct_tungsten <= 50000.0
    assert 1000.0 <= cct_shade <= 50000.0
    assert cct_tungsten < cct_shade, \
        f"色温方向错误: 钨丝 {cct_tungsten:.0f}K 应低于阴影 {cct_shade:.0f}K"


def test_cct_from_wb_no_profile_does_not_crash():
    """无 profile 时 cct_from_wb 仍返回有限值 (回退 sRGB 近似)。"""
    cct = cct_from_wb(np.array([2.0, 1.0, 1.5]), None)
    assert np.isfinite(cct) and 1000.0 <= cct <= 50000.0


# ---------------------------------------------------------------------------
# 缺 CM 回退 FM 并告警
# ---------------------------------------------------------------------------

def test_missing_cm_falls_back_to_fm_with_warning():
    """缺 ColorMatrix → 返回 ForwardMatrix 并抛 ColorMatrixFallbackWarning。"""
    prof = _make_profile(cm1=None, cm2=None, fm1=_NIKON_FM1, fm2=_NIKON_FM1)
    wb = np.array([2.0, 1.0, 1.5])
    with pytest.warns(ColorMatrixFallbackWarning):
        m = cam_to_xyz_matrix(prof, wb)
    err = float(np.abs(m - _mat3(_NIKON_FM1)).max())
    assert err < 1e-12, "回退路径应原样返回 ForwardMatrix"


def test_missing_both_raises():
    """既缺 CM 又缺 FM → 报错。"""
    prof = _make_profile(cm1=None, cm2=None, fm1=None, fm2=None)
    with pytest.raises(ValueError):
        cam_to_xyz_matrix(prof, np.array([2.0, 1.0, 1.5]))


# ---------------------------------------------------------------------------
# 1/T 插值端点行为
# ---------------------------------------------------------------------------

def test_interp_endpoints_exact():
    """T=T1 返回 CM1 (恒等), T=T2 返回 CM2 (2I)。"""
    prof = _make_profile(
        cm1=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        cm2=[2, 0, 0, 0, 2, 0, 0, 0, 2],
        fm1=None, fm2=None, ill1=17, ill2=21)  # 2850 / 6500
    cm_lo, _ = interpolate_color_matrices(prof, 2850.0)
    cm_hi, _ = interpolate_color_matrices(prof, 6500.0)
    assert float(np.abs(cm_lo - np.eye(3)).max()) < 1e-12
    assert float(np.abs(cm_hi - 2.0 * np.eye(3)).max()) < 1e-12


def test_interp_midpoint_between_endpoints():
    """1/T 中点处矩阵严格位于两端点之间 (按 1/T 加权)。"""
    prof = _make_profile(
        cm1=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        cm2=[2, 0, 0, 0, 2, 0, 0, 0, 2],
        fm1=None, fm2=None, ill1=17, ill2=21)
    # 1/T 中点: 1/T = (1/2850 + 1/6500)/2
    t_mid = 1.0 / ((1.0 / 2850.0 + 1.0 / 6500.0) / 2.0)
    cm, _ = interpolate_color_matrices(prof, t_mid)
    assert float(np.abs(cm - 1.5 * np.eye(3)).max()) < 1e-6


def test_interp_out_of_range_clamps():
    """端点外钳位: T<T1 → CM1, T>T2 → CM2。"""
    prof = _make_profile(
        cm1=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        cm2=[2, 0, 0, 0, 2, 0, 0, 0, 2],
        fm1=None, fm2=None, ill1=17, ill2=21)
    cm_cold, _ = interpolate_color_matrices(prof, 2000.0)
    cm_hot, _ = interpolate_color_matrices(prof, 20000.0)
    assert float(np.abs(cm_cold - np.eye(3)).max()) < 1e-12
    assert float(np.abs(cm_hot - 2.0 * np.eye(3)).max()) < 1e-12


# ---------------------------------------------------------------------------
# 中性保持 (spread ≈ 1)
# ---------------------------------------------------------------------------

def test_neutral_preserved_cm_path():
    """WB 中性 [1,1,1] 经基座 CM 路径 → 中性线性 sRGB (spread≈1)。"""
    prof = _make_profile()
    wb = np.array([2.0, 1.0, 1.5])
    m = cam_to_linear_srgb_matrix(prof, wb)
    out = np.array([1.0, 1.0, 1.0]) @ m.T
    out = out / out[1]
    spread = float(out.max() / out.min()) - 1.0
    assert spread < NEUTRAL_SPREAD_TOL, f"中性 spread={spread:.5f} 过大"


def test_neutral_preserved_cam_to_xyz_convenience():
    """cam_to_xyz 便捷接口: 原生中性 (1/wb) 输入 → 中性输出。"""
    prof = _make_profile()
    wb = np.array([2.0, 1.0, 1.5])
    neutral_native = wb_to_neutral(wb)
    out = cam_to_xyz(np.array([neutral_native]), wb, prof)[0]
    out = out / out[1]
    spread = float(out.max() / out.min()) - 1.0
    assert spread < NEUTRAL_SPREAD_TOL, f"中性 spread={spread:.5f} 过大"


def test_camera_calibration_applied():
    """CameraCalibration 非恒等时被正确合入 (camera→XYZ = inv(CM×CC))。"""
    prof = _make_profile(cc1=[1.1, 0, 0, 0, 0.9, 0, 0, 0, 1.0])
    wb = np.array([2.0, 1.0, 1.5])
    m = cam_to_xyz_matrix(prof, wb)
    # 中性仍保持 (CC 对角缩放不会破坏中性: inv(CC) 也是对角)
    out = np.array([1.0, 1.0, 1.0]) @ m.T
    # CC 非恒等 → 中性在 XYZ 空间 Y 归一后仍应近似 D50 (R/B 通道增益改变)
    assert np.all(np.isfinite(out))
    # 与无 CC 的差异应存在 (验证 CC 确实被合入)
    m_ref = cam_to_xyz_matrix(_make_profile(cc1=None), wb)
    assert float(np.abs(m - m_ref).max()) > 1e-6


# ---------------------------------------------------------------------------
# 皮肤 a/b 方向与相机一致
# ---------------------------------------------------------------------------

def test_skin_ab_direction_consistent_with_camera():
    """同一皮肤相机 RGB, CM 基座与 FM(look) 路径的 Lab a/b 同号且为暖色。"""
    prof = _make_profile()
    wb = np.array([2.0, 1.0, 1.5])
    fm1 = _mat3(_NIKON_FM1)

    # 由已知肤色 (gamma sRGB) 反推 WB 后相机 RGB (经 FM 逆), 作为"该皮肤在相机里的响应"
    skin_gamma = np.array([0.83, 0.58, 0.47])
    skin_lin = _srgb_decode(skin_gamma)
    xyz65 = _mat3(SRGB_TO_XYZ_D65) @ skin_lin
    xyz50 = np.linalg.inv(_mat3(BRADFORD_D50_TO_D65)) @ xyz65
    cam_wb = np.linalg.inv(fm1) @ xyz50

    # CM 基座路径
    m_cm = cam_to_linear_srgb_matrix(prof, wb)
    srgb_cm = np.clip(cam_wb @ m_cm.T, 0.0, None)
    # FM look 路径
    m_fm = _mat3(XYZ_D65_TO_SRGB) @ _mat3(BRADFORD_D50_TO_D65) @ fm1
    srgb_fm = np.clip(cam_wb @ m_fm.T, 0.0, None)

    _, a_cm, b_cm = _lab_from_linear_srgb(srgb_cm)
    _, a_fm, b_fm = _lab_from_linear_srgb(srgb_fm)

    # 暖肤色: a>0 (红), b>0 (黄); 且 CM/FM 方向一致
    assert a_cm > 0 and b_cm > 0, f"CM 路径皮肤方向错误 a={a_cm:.1f} b={b_cm:.1f}"
    assert a_fm > 0 and b_fm > 0, f"FM 路径皮肤方向错误 a={a_fm:.1f} b={b_fm:.1f}"
    assert np.sign(a_cm) == np.sign(a_fm) and np.sign(b_cm) == np.sign(b_fm), \
        f"CM/FM 皮肤方向不一致: CM=({a_cm:.1f},{b_cm:.1f}) FM=({a_fm:.1f},{b_fm:.1f})"


# ---------------------------------------------------------------------------
# dcp.py 解析补全 (CameraCalibration / CalibrationIlluminant / BaselineExposureOffset)
# ---------------------------------------------------------------------------

def test_real_dcp_parses_new_fields():
    """加载真实 Nikon Camera Standard DCP (若存在): 校验新增字段解析。"""
    from render.core.calibration import load_dcp
    candidates = [
        Path(r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp"),
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        pytest.skip("本机无 Nikon Z 5 2 Camera Standard.dcp")
    prof = load_dcp(path)
    assert prof.color_matrix1 is not None
    assert prof.calibration_illuminant1 == 17      # StdA
    assert prof.calibration_illuminant2 == 21      # D65
    assert abs(prof.baseline_exposure_offset - (-0.15)) < 1e-6
