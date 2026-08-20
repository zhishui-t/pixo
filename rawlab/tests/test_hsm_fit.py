"""test_hsm_fit —— HSM 品红带拟合 (T5) 单元测试。

覆盖对象:
  - rawlab.engine.huesat.make_hue_sat_map: 三平面结构 (hue_shift 全 0 /
    sat_scale 带内写值 / val_scale 恒 1); 带外恒等; 带边缘平滑滚降;
    S/V 阈值保护区; 无点 → 恒等表; 环绕带
  - 合成品红像素: 套表后色度压缩符合预期 (S ≈ s·sat_scale), 恒等区不受影响;
    DCP 往返后表仍生效
  - rawlab.tools.fit_camera_profile.fit_hue_sat_magenta: 合成 pairs 复现
    sat_scale; 无品红 → None; 钳位 [0.08, 1.0]; 样本不足 → None
  - **high#1 应用域一致性 (T10)**: 掩码在线性 ProPhoto (与引擎查表同域) 构造;
    合成 pair 的目标也在应用域构造; 新增『同一对像素在两域掩码差异』回归断言
    (gamma 域掩码 ≠ 应用域掩码, 且应用域掩码 = 引擎实际调制像素集)

验收标准 (03-specification §3 AC / 任务 T5 / T10):
  - 表结构: 90×16×16 三平面, 带内 sat_scale 写入指定值, 其余恒等
  - 套表后品红色度压缩符合预期; 恒等区 (暖/中性/带外) 不受影响
  - 拟合表写入 DcpProfile.hue_sat_map/dims/encoding=1 并随 write_dcp 落盘
  - 拟合掩码与应用域一致 (两域掩码差异断言 + 引擎调制集一致性)

运行: python -m pytest rawlab/tests/test_hsm_fit.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rawlab.dcp import DcpProfile, load_dcp, write_dcp
from rawlab.engine.color import (
    linear_prophoto_to_linear_srgb,
    linear_srgb_to_linear_prophoto,
)
from rawlab.engine.huesat import (
    _hsv_to_rgb,
    _rgb_to_hsv,
    apply_hue_sat_map,
    decode_table,
    make_hue_sat_map,
)
from rawlab.tools.fit_camera_profile import (
    HSM_DIMS,
    HSM_MIN_PIXELS,
    HSM_SAT_SCALE_CLAMP,
    MAGENTA_HUE_RANGE,
    fit_hue_sat_magenta,
    magenta_band_mask,
)

_H, _S, _V = 90, 16, 16  # HSM_DIMS
N_VALS = _H * _S * _V * 3


def _table3d(flat: list) -> np.ndarray:
    """DCP 扁平列表 → (H,S,V,3) 表 (decode_table 语义)。"""
    t = decode_table(flat, (_H, _S, _V))
    assert t is not None
    return t


def _flatten(table: np.ndarray) -> list:
    return table.transpose(2, 0, 1, 3).reshape(-1).tolist()


class MockProf:
    """最小 DcpProfile 替身 (恒等色彩矩阵 + HSM 字段, 与 test_huesat_domain 一致)。"""

    def __init__(self, hue_sat_map=None, hue_sat_dims=None, hue_sat_encoding=None):
        self.hue_sat_map = hue_sat_map
        self.hue_sat_map1 = hue_sat_map
        self.hue_sat_dims = hue_sat_dims
        self.hue_sat_encoding = hue_sat_encoding
        self.look_table = None
        self.look_table_dims = None
        self.color_matrix1 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.color_matrix2 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.forward_matrix1 = None
        self.forward_matrix2 = None
        self.camera_calibration1 = None
        self.camera_calibration2 = None
        self.calibration_illuminant1 = 17
        self.calibration_illuminant2 = 21
        self.baseline_exposure_offset = 0.0
        self.profile_tone_curve = None


# 品红带参数 (03-specification §2.2): hue [235,310], S≥0.05, V≥0.6
BAND = [(272.5, 37.5, 0.3)]   # (center, halfwidth, sat_scale)


def _prophoto_hsv(rgb_linear):
    pp = linear_srgb_to_linear_prophoto(np.asarray(rgb_linear, np.float64))
    return _rgb_to_hsv(pp)


# ---------------------------------------------------------------------------
# 1) make_hue_sat_map: 三平面结构 / 带内写值 / 带外恒等 / 边缘 / 保护区
# ---------------------------------------------------------------------------

def test_make_table_structure():
    """90×16×16 三平面: hue_shift 全 0, sat_scale 带内写值, val_scale 恒 1。"""
    flat = make_hue_sat_map(BAND)
    assert len(flat) == N_VALS
    t = _table3d(flat)
    assert t.shape == (_H, _S, _V, 3)
    assert np.abs(t[..., 0]).max() <= 1e-7              # hue_shift 平面全 0
    assert np.abs(t[..., 2] - 1.0).max() <= 1e-7        # val_scale 平面恒 1
    assert np.abs(t[..., 1] - 1.0).min() >= -1e-7       # sat_scale 存在非恒等
    assert float(t[..., 1].min()) >= 0.08 - 1e-6        # 不越过钳位下限


def test_make_table_identity_no_points():
    """无 band → 恒等表: 每格 (0, 1, 1)。"""
    flat = make_hue_sat_map([])
    t = _table3d(flat)
    assert np.abs(t[..., 0]).max() <= 1e-7
    assert np.abs(t[..., 1] - 1.0).max() <= 1e-7
    assert np.abs(t[..., 2] - 1.0).max() <= 1e-7


def test_make_table_band_writes_value():
    """带内 (中段 hue, 高 S, 高 V) 格点 sat_scale == 指定值 (0.3)。"""
    flat = make_hue_sat_map(BAND)
    t = _table3d(flat)
    for hue_deg in (240.0, 260.0, 280.0, 300.0):        # 带内 4° 网格点
        i = int(round(hue_deg / 360.0 * _H)) % _H
        j = _S - 1                                        # S=1
        k = _V - 1                                        # V=1 (编码后 ≥0.6)
        assert float(t[i, j, k, 1]) == pytest.approx(0.3, abs=1e-5), \
            f"hue {hue_deg}° 格点 sat_scale 应=0.3"


def test_make_table_outside_band_identity():
    """带外 hue (暖/绿/蓝绿) 全 V/S 平面恒等 sat_scale=1。"""
    flat = make_hue_sat_map(BAND)
    t = _table3d(flat)
    for hue_deg in (30.0, 60.0, 120.0, 180.0, 200.0, 330.0):
        i = int(round(hue_deg / 360.0 * _H)) % _H
        assert float(t[i, :, :, 1].max()) <= 1.0 + 1e-7 and \
            float(t[i, :, :, 1].min()) >= 1.0 - 1e-7, f"hue {hue_deg}° 应恒等"


def test_make_table_hue_edge_smooth():
    """带边缘平滑滚降: 边缘格 sat_scale 介于 (0.3, 1) 之间, 不跳变。"""
    flat = make_hue_sat_map(BAND)
    t = _table3d(flat)
    j, k = _S - 1, _V - 1
    edge = 360.0 / _H                                     # 4° 边缘
    # 带边界: 中心 272.5 ± 37.5 → [235, 310]; 边缘 [231,235] 与 [310,314]
    lo_cell = int(np.ceil((235.0 - edge) / 360.0 * _H))   # 231° 前一个格
    hi_cell = int(np.floor((310.0 + edge) / 360.0 * _H))
    vals = [float(t[i, j, k, 1])
            for i in range(lo_cell, hi_cell + 1)
            if i < _H]
    assert vals, "应存在边缘格点"
    assert min(vals) >= 0.3 - 1e-6 and max(vals) <= 1.0 + 1e-6
    # 边缘存在中间值 (非 0.3 也非 1.0): 平滑滚降而非二值跳变
    mid = [v for v in vals if 0.3 + 0.02 < v < 1.0 - 0.02]
    assert mid, "带边缘应存在平滑滚降的中间 sat_scale"


def test_make_table_sat_protection():
    """S 阈值保护区: S=0 行恒等 (近中性不误伤); S<0.05 平滑过渡。"""
    flat = make_hue_sat_map(BAND)
    t = _table3d(flat)
    i = int(round(270.0 / 360.0 * _H)) % _H              # 带内 hue
    assert float(t[i, 0, :, 1].max()) <= 1.0 + 1e-7, "S=0 行必须恒等"
    s_lo = 1 / (_S - 1)                                   # 0.0667 ≥ 0.05 → 全效
    assert float(t[i, 1, _V - 1, 1]) == pytest.approx(0.3, abs=1e-5)


def test_make_table_val_protection():
    """V 阈值保护区: V < 0.6 (编码后坐标) 的平面平滑过渡到恒等。"""
    flat = make_hue_sat_map(BAND)
    t = _table3d(flat)
    i = int(round(270.0 / 360.0 * _H)) % _H
    j = _S - 1
    # k 使 vk=0.4 (< 0.6-1/15≈0.533): 应恒等
    k_lo = int(round(0.4 * (_V - 1)))
    assert float(t[i, j, k_lo, 1]) <= 1.0 + 1e-7
    # vk=1.0 (高光, 编码后仍 1.0 ≥ 0.6): 全效
    assert float(t[i, j, _V - 1, 1]) == pytest.approx(0.3, abs=1e-5)


def test_make_table_wraparound_band():
    """环绕带 (跨 0°) 两侧均写值: center 350°, halfwidth 15° → [335, 360]∪[0, 5]。"""
    flat = make_hue_sat_map([(350.0, 15.0, 0.2)])
    t = _table3d(flat)
    for hue_deg in (356.0, 4.0):
        i = int(round(hue_deg / 360.0 * _H)) % _H
        assert float(t[i, _S - 1, _V - 1, 1]) == pytest.approx(0.2, abs=1e-5)
    assert float(t[int(30.0 / 360 * _H) % _H, _S - 1, _V - 1, 1]) == pytest.approx(1.0, abs=1e-6)


def test_make_table_multi_band_multiplicative():
    """多 band 乘性合成: 两个 0.5 带重叠 → 0.25。"""
    flat = make_hue_sat_map([(270.0, 30.0, 0.5), (280.0, 30.0, 0.5)])
    t = _table3d(flat)
    i = int(round(275.0 / 360.0 * _H)) % _H
    assert float(t[i, _S - 1, _V - 1, 1]) == pytest.approx(0.25, abs=1e-5)


# ---------------------------------------------------------------------------
# 2) 合成品红像素: 套表后色度压缩符合预期, 恒等区不受影响
# ---------------------------------------------------------------------------

def _synthetic_image(size=96):
    """合成图: 品红块 (线性 sRGB, ProPhoto H≈283°∈带) + 暖块 + 中性 + 绿块。"""
    img = np.zeros((size, size, 3), np.float32)
    img[:, :] = 0.25                                      # 中性底
    img[8:44, 8:44] = (1.0, 0.2, 1.0)                     # 品红 (带内)
    img[8:44, 52:88] = (0.9, 0.5, 0.2)                    # 暖橙 (带外, H≈40°)
    img[52:88, 8:44] = (0.2, 0.9, 0.3)                    # 绿 (带外)
    return img


def _blocks(img, size=96):
    """返回各块的布尔掩码。"""
    h, s, v = _prophoto_hsv(img)
    magenta = (h >= 235) & (h <= 310) & (s >= 0.05) & (v >= 0.6)
    warm = (h >= 20) & (h <= 60)
    green = (h >= 90) & (h <= 130)
    neutral = s < 0.05
    return magenta, warm, green, neutral


def test_apply_compresses_magenta_keeps_identity():
    """套表 (sat_scale=0.3): 品红块 S 压缩至 ~0.3×, 暖/绿/中性几乎不变。"""
    img = _synthetic_image()
    prof = MockProf(hue_sat_map=make_hue_sat_map(BAND),
                    hue_sat_dims=HSM_DIMS, hue_sat_encoding=1)
    out = apply_hue_sat_map(img, prof, strength=1.0)

    _, si, vi = _prophoto_hsv(img)
    _, so, vo = _prophoto_hsv(out)
    mag, warm, green, neutral = _blocks(img)

    assert mag.any() and warm.any() and green.any() and neutral.any()
    # 品红: S 压缩 ≈ 0.3 (带内全效)
    ratio = float(np.median(so[mag] / np.maximum(si[mag], 1e-9)))
    assert ratio == pytest.approx(0.3, abs=0.03), f"品红 S 压缩比 {ratio:.3f} ≠ 0.3"
    # 恒等区: 暖/绿/中性 S 几乎不变
    for name, m in (("暖", warm), ("绿", green), ("中性", neutral)):
        d = float(np.abs(so[m] - si[m]).max())
        assert d <= 0.01, f"{name}块 S 变化 {d:.4f} 过大 (应不受影响)"
    # 明度不变 (val_scale 恒 1)
    assert float(np.abs(vo - vi).max()) <= 0.02


def test_apply_with_strength_half():
    """strength=0.5 → S 压缩至 1+0.5*(0.3-1)=0.65×。"""
    img = _synthetic_image()
    prof = MockProf(hue_sat_map=make_hue_sat_map(BAND),
                    hue_sat_dims=HSM_DIMS, hue_sat_encoding=1)
    out = apply_hue_sat_map(img, prof, strength=0.5)
    _, si, _ = _prophoto_hsv(img)
    _, so, _ = _prophoto_hsv(out)
    mag, _, _, _ = _blocks(img)
    ratio = float(np.median(so[mag] / np.maximum(si[mag], 1e-9)))
    assert ratio == pytest.approx(0.65, abs=0.03)


def test_apply_identity_table_noop():
    """恒等表 (无点) 套用 → 输出与输入一致 (≤1e-4, float32 输出精度)。"""
    img = _synthetic_image()
    prof = MockProf(hue_sat_map=make_hue_sat_map([]),
                    hue_sat_dims=HSM_DIMS, hue_sat_encoding=1)
    out = apply_hue_sat_map(img, prof, strength=1.0)
    assert float(np.abs(out - img).max()) <= 1e-4


def test_dcp_roundtrip_table_applies(tmp_path):
    """表随 DCP 落盘: write→load 后套用结果一致 (0xC726/0xC725/0xC7A4 往返)。"""
    p = DcpProfile(path=tmp_path / "hsm.dcp")
    p.name = "T5 HSM test"
    p.color_matrix1 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    p.hue_sat_map = make_hue_sat_map(BAND)
    p.hue_sat_dims = list(HSM_DIMS)
    p.hue_sat_encoding = 1
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.hue_sat_dims == list(HSM_DIMS)
    assert rt.hue_sat_encoding == 1
    assert len(rt.hue_sat_map) == N_VALS
    img = _synthetic_image()
    a = apply_hue_sat_map(img, p, strength=1.0)
    b = apply_hue_sat_map(img, rt, strength=1.0)
    assert float(np.abs(a - b).max()) <= 1e-4          # 往返后表语义一致


# ---------------------------------------------------------------------------
# 3) fit_hue_sat_magenta: 合成 pairs 复现 sat_scale / 无品红 / 钳位 / 样本不足
# ---------------------------------------------------------------------------

def _magenta_pair(seed: int, k: float, block=(0.8, 0.48, 0.8), size=96):
    """合成 pair (high#1: 应用域构造): 底灰 + 品红块; 目标在**线性 ProPhoto**
    HSV 域把品红块 S 缩放 ×k 后转回线性 sRGB —— 与引擎查表/拟合掩码同域。

    block (0.8, 0.48, 0.8) 在线性 ProPhoto 域 hue≈283°∈[235,310]、S=0.32、
    V=0.76 (编码后 0.89≥0.6) → 位于品红带 (应用域掩码全选); 背景随机灰
    [0.1, 0.3] 编码后 V<0.6 被 V 阈值排除 (无泄漏)。
    """
    rng = np.random.default_rng(seed)
    ours = rng.uniform(0.1, 0.3, (size, size, 3)).astype(np.float32)
    blk = np.asarray(block, np.float32)
    ours[20:60, 20:60] = blk                              # 品红块 (ProPhoto H≈283°)
    pp = linear_srgb_to_linear_prophoto(ours.astype(np.float64))
    h, s, v = _rgb_to_hsv(pp)
    m = (h >= MAGENTA_HUE_RANGE[0]) & (h <= MAGENTA_HUE_RANGE[1])
    s2 = np.where(m, s * k, s)
    target = linear_prophoto_to_linear_srgb(_hsv_to_rgb(h, s2, v)).astype(np.float32)
    return {"linear_m8": ours, "target8": target, "wb_b": 2.0}


def _neutral_pair(seed: int, size=96):
    """无品红 pair (中性底 + 暖块); 背景压低到 [0.1,0.3] 使编码后 V<0.6
    (应用域掩码不选背景像素, 确保无品红 → None 语义稳定)。"""
    rng = np.random.default_rng(seed)
    ours = rng.uniform(0.1, 0.3, (size, size, 3)).astype(np.float32)
    ours[20:60, 20:60] = (0.9, 0.6, 0.3)                  # 暖橙 (带外)
    return {"linear_m8": ours, "target8": ours.copy(), "wb_b": 2.2}


# ---------------------------------------------------------------------------
# 3b) high#1 应用域一致性: 同一对像素两域掩码差异 + 引擎调制集一致
# ---------------------------------------------------------------------------
# 实测 (审查 F1): 5236 高光像素 gamma 域与线性 ProPhoto 域 hue 差中位 13.2°,
# S 中位 0.05→0.031 —— 修复前 gamma 域掩码与引擎实际调制像素集错位。
# 构造含"域错位"像素的合成图: ProPhoto 域在带内、gamma 域在带外。

# (0.828, 0.632, 0.758): gamma H≈321° (带外), ProPhoto H≈305° (带内) ——
# 引擎查表 (线性 ProPhoto) 会调制它, 旧 gamma 掩码会漏选。
_DOMAIN_SHIFT_BLOCK = (0.828, 0.632, 0.758)


def _domain_shift_image(size=64):
    """含域错位像素块的合成图 (底灰 + 三块):
      A. _DOMAIN_SHIFT_BLOCK: ProPhoto 带内 / gamma 带外 (high#1 核心错位);
      B. (1.0, 0.2, 1.0): 两域均带内;
      C. (0.9, 0.5, 0.2): 暖橙, 两域均带外。"""
    img = np.zeros((size, size, 3), np.float32)
    img[:, :] = 0.15                                      # 灰底 (V 编码后 <0.6, 排除)
    img[8:32, 8:32] = _DOMAIN_SHIFT_BLOCK
    img[8:32, 36:60] = (1.0, 0.2, 1.0)
    img[36:60, 8:32] = (0.9, 0.5, 0.2)
    return img


def _gamma_mask(rgb):
    """旧 (T5) 拟合掩码语义: gamma/编码域 HSV 取 hue∈[235,310]/S≥0.05/V≥0.6。"""
    h, s, v = _rgb_to_hsv(np.asarray(rgb, np.float64))
    return ((h >= MAGENTA_HUE_RANGE[0]) & (h <= MAGENTA_HUE_RANGE[1])
            & (s >= 0.05) & (v >= 0.6))


def test_mask_domain_mismatch_regression():
    """high#1 回归: 同一对像素, 应用域掩码 ≠ gamma 域掩码。

    域错位块 (0.828,0.632,0.758) 在 gamma 域 hue≈321° (带外, 旧掩码漏选),
    在线性 ProPhoto 域 hue≈305° (带内, 引擎实际调制) → 两域掩码必须不同。
    """
    img = _domain_shift_image()
    mask_app = magenta_band_mask(img, encoding=1)
    mask_gamma = _gamma_mask(img)
    assert mask_app.any() and mask_gamma.any()
    # 两域掩码存在差异 (核心回归: 修复前同一对像素在两域被不同地选择)
    assert not np.array_equal(mask_app, mask_gamma)
    # 应用域多选的像素 = ProPhoto 带内但 gamma 带外 (引擎调制而旧掩码漏选)
    missed = mask_app & ~mask_gamma
    assert missed.any(), "应存在 ProPhoto 带内 / gamma 带外的错位像素"
    # 反向差异 (gamma 带内 / ProPhoto 带外) 在本图可为空, 不强制


def test_mask_matches_engine_modulation_set():
    """high#1 核心: 应用域掩码 = 引擎 apply_hue_sat_map 实际调制像素集。

    套 sat_scale=0.3 品红带表 (encoding=1): 掩码内像素 S 被压缩至 ≈0.3×
    (带内全效); 旧 gamma 掩码漏选的错位像素同样被引擎调制 —— 证明修复后
    拟合掩码与引擎调制域一致 (而非 gamma 域自洽)。
    """
    img = _domain_shift_image()
    prof = MockProf(hue_sat_map=make_hue_sat_map(BAND),
                    hue_sat_dims=HSM_DIMS, hue_sat_encoding=1)
    out = apply_hue_sat_map(img, prof, strength=1.0)
    _, si, _ = _prophoto_hsv(img)
    _, so, _ = _prophoto_hsv(out)
    ratio = so / np.maximum(si, 1e-9)
    mask_app = magenta_band_mask(img, encoding=1)
    mask_gamma = _gamma_mask(img)
    # 掩码内像素全部被调制 (带内全效 ≈0.3; 允许表边缘滚降小幅偏差)
    assert mask_app.any()
    assert float(np.median(ratio[mask_app])) == pytest.approx(0.3, abs=0.05)
    assert bool(np.all(ratio[mask_app] < 0.98))
    # 旧 gamma 掩码漏选的像素 (ProPhoto 带内) 也被引擎调制 → 旧掩码错位
    missed = mask_app & ~mask_gamma
    assert missed.any()
    assert float(np.median(ratio[missed])) == pytest.approx(0.3, abs=0.05)


def test_fit_pair_constructed_in_application_domain():
    """合成 pair 在应用域构造 (high#1): 品红块的 ProPhoto HSV 位于带内,
    背景被 V 阈值排除 → fit 的掩码像素集 = 品红块 (非 gamma 域)。"""
    p = _magenta_pair(11, 0.3)
    mask = magenta_band_mask(p["linear_m8"], encoding=1)
    blk = np.zeros_like(mask)
    blk[20:60, 20:60] = True
    assert mask.any()
    assert float(mask[blk].mean()) > 0.99        # 品红块基本全选
    assert float(mask[~blk].mean()) < 0.01       # 背景基本不选


def test_fit_reproduces_ratio():
    """品红块目标色度 ×0.25 → sat_scale ≈ 0.25 (钳位范围内精确复现)。"""
    pairs = [_magenta_pair(1, 0.25), _magenta_pair(2, 0.25)]
    r = fit_hue_sat_magenta(pairs, apply_curve=lambda x: x)
    assert r is not None
    assert r["sat_scale"] == pytest.approx(0.25, abs=0.04)
    assert r["hue_lo"] == 235.0 and r["hue_hi"] == 310.0
    assert r["n_samples"] >= HSM_MIN_PIXELS
    assert r["n_photos"] == 2


def test_fit_no_magenta_returns_none():
    """无品红样本 → None (调用方写恒等表)。"""
    pairs = [_neutral_pair(3), _neutral_pair(4)]
    assert fit_hue_sat_magenta(pairs, apply_curve=lambda x: x) is None


def test_fit_clamps_ratio():
    """中位比越界钳位: 2.0 → 1.0 (不减饱和); 0.06 → 0.08 (下限)。

    k=0.06 在 u8 Lab 量化下中位比 ≈0.068 (实测, 高于 0.01 的量化退化 0.0),
    落在钳位下限之下 → sat_scale 钳到 0.08。
    """
    r_hi = fit_hue_sat_magenta([_magenta_pair(5, 2.0)], apply_curve=lambda x: x)
    assert r_hi is not None and r_hi["sat_scale"] == pytest.approx(
        HSM_SAT_SCALE_CLAMP[1], abs=1e-6)
    r_lo = fit_hue_sat_magenta([_magenta_pair(6, 0.06)], apply_curve=lambda x: x)
    assert r_lo is not None and r_lo["sat_scale"] == pytest.approx(
        HSM_SAT_SCALE_CLAMP[0], abs=1e-6)


def test_fit_too_few_samples_returns_none():
    """品红样本 < HSM_MIN_PIXELS → None (视为无品红, 写恒等表)。"""
    p = _magenta_pair(7, 0.3, size=96)
    # 只留 20×20=400 px < 500
    p["linear_m8"] = p["linear_m8"][:20, :20].copy()
    p["target8"] = p["target8"][:20, :20].copy()
    assert fit_hue_sat_magenta([p], apply_curve=lambda x: x) is None


def test_fit_pipeline_integration_points_to_table():
    """拟合结果 → make_hue_sat_map 表: 带内 sat_scale == 拟合值。"""
    r = fit_hue_sat_magenta([_magenta_pair(8, 0.3)], apply_curve=lambda x: x)
    assert r is not None
    center = (r["hue_lo"] + r["hue_hi"]) * 0.5
    halfwidth = (r["hue_hi"] - r["hue_lo"]) * 0.5
    flat = make_hue_sat_map([(center, halfwidth, r["sat_scale"])])
    t = _table3d(flat)
    i = int(round(270.0 / 360.0 * _H)) % _H
    assert float(t[i, _S - 1, _V - 1, 1]) == pytest.approx(
        r["sat_scale"], abs=1e-4)
