"""t6 / M-O1: native Oklab 内核 vs core.oklab numpy 参考的逐位等价 (设计 §2.4 验收硬门)。

覆盖:
  - 随机 100 万像素 (1000x1000) f32: srgb_to_oklab / oklab_to_srgb 双向 bit-exact
  - [0,1]³ 网格 (步长 1/32, 33³) 双向 bit-exact + 往返 ≤1e-7 精度线复核 (设计 §1.3)
  - gamma 阈值/端点/负值/越域边界 (双向 gamma 分支 + 负底 LMS' 立方)
  - dtype 契约 (§1.3): 正向出口 float64 / 逆向出口 float32
  - DLL 缺失时 srgb_to_oklab / oklab_to_srgb 回退 numpy, 结果一致 (FR6)
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.oklab import oklab_to_srgb, srgb_to_oklab
from pixo.render import _native as native

SEED = 20260904
ROUNDTRIP_TOL = 1e-7  # 设计 §1.3 网格往返精度线


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 oklab 数值等价测试")
    if not hasattr(native._lib, "PixoRenderSrgbToOklabF32"):
        pytest.skip("DLL 未导出 oklab 内核 (需 native >= 1.4.0)")


@pytest.fixture()
def native_disabled(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    return native


def _assert_bits_equal(x: np.ndarray, y: np.ndarray, label: str) -> None:
    """逐位比较 (uint 位型视图, 区分 NaN 与位型; ±0 位型不同也判不等)。"""
    assert x.dtype == y.dtype, f"{label} dtype 不一致: {x.dtype} vs {y.dtype}"
    ui = np.uint32 if x.dtype == np.float32 else np.uint64
    xb = np.ascontiguousarray(x).view(ui)
    yb = np.ascontiguousarray(y).view(ui)
    if not np.array_equal(xb, yb):
        bad = int((xb != yb).sum())
        diff = np.abs(x.astype(np.float64) - y.astype(np.float64))
        raise AssertionError(
            f"{label} 非逐位一致: {bad}/{x.size} 点位型不同, max|Δ|={float(diff.max()):.3e}"
        )


def _random_rgb_f32(shape=(1000, 1000, 3), seed=SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random(shape, dtype=np.float32)


def _grid_rgb_f32(steps: int = 32) -> np.ndarray:
    """[0,1]³ 均匀网格 (含端点), 步长 1/32 → 33³ = 35937 像素, 整形为 (33, 1089, 3)。"""
    g = np.arange(steps + 1, dtype=np.float64) / steps
    mesh = np.stack(np.meshgrid(g, g, g, indexing="ij"), axis=-1)
    return mesh.reshape(-1, 3).astype(np.float32).reshape(33, 33 * 33, 3)


# ---------------------------------------------------------------------------
# 验收硬门: 随机 100 万像素 bit-exact
# ---------------------------------------------------------------------------

def test_forward_random_1m_bitwise(native_required):
    x = _random_rgb_f32()
    assert x.size // 3 == 1_000_000
    lab_native = native.srgb_to_oklab_f32(x)
    lab_numpy = srgb_to_oklab(x)
    assert lab_native.dtype == np.float64  # §1.3: 内部工作域出口 f64
    _assert_bits_equal(lab_native, lab_numpy, "srgb_to_oklab 随机 100 万")


def test_inverse_random_1m_bitwise(native_required):
    x = _random_rgb_f32()
    lab = srgb_to_oklab(x)
    srgb_native = native.oklab_to_srgb_f32(lab)
    srgb_numpy = oklab_to_srgb(lab)
    assert srgb_native.dtype == np.float32  # §1.3: 渲染域出口 f32
    _assert_bits_equal(srgb_native, srgb_numpy, "oklab_to_srgb 随机 100 万")
    # 随机域往返复核 (f32 末端舍入下仍须守住 1e-7)
    assert float(np.abs(srgb_native - x).max()) <= ROUNDTRIP_TOL


# ---------------------------------------------------------------------------
# 网格 + 边界 bit-exact
# ---------------------------------------------------------------------------

def test_grid_roundtrip_bitwise(native_required):
    grid = _grid_rgb_f32()
    lab_native = native.srgb_to_oklab_f32(grid)
    lab_numpy = srgb_to_oklab(grid)
    _assert_bits_equal(lab_native, lab_numpy, "srgb_to_oklab 网格")

    srgb_native = native.oklab_to_srgb_f32(lab_native)
    srgb_numpy = oklab_to_srgb(lab_native)
    _assert_bits_equal(srgb_native, srgb_numpy, "oklab_to_srgb 网格")
    # 设计 §1.3 精度验收线: 网格往返 ≤1e-7 (f64 域实测 ~1.8e-10, 叠加 f32 出口舍入)
    assert float(np.abs(srgb_native - grid).max()) <= ROUNDTRIP_TOL


def test_edge_values_bitwise(native_required):
    # 双侧压住 gamma 分段阈值 0.04045 (解码) 与端点; 负值 (clip 0)、>1 (仅解码无上截)
    vals = [0.0, 1.0, 0.5, 0.04045, 0.04046, 0.0031308, 0.0404,
            1e-6, 0.999, 1.5, -0.5, 2.0]
    combos = np.array([[r, g, b] for r in vals for g in vals for b in vals],
                      dtype=np.float32)
    x = combos.reshape(12, 144, 3)
    lab_native = native.srgb_to_oklab_f32(x)
    _assert_bits_equal(lab_native, srgb_to_oklab(x), "srgb_to_oklab 边界值")
    srgb_native = native.oklab_to_srgb_f32(lab_native)
    _assert_bits_equal(srgb_native, oklab_to_srgb(lab_native), "oklab_to_srgb 边界值")


def test_out_of_gamut_inverse_bitwise(native_required):
    # 越域 lab (a/b 放大): 逆向产生负 LMS', 压住 pow(负底, 3.0) 与 clip 编码路径
    grid = _grid_rgb_f32()
    lab = srgb_to_oklab(grid)
    lab[..., 1] *= 2.0
    lab[..., 2] *= 2.0
    srgb_native = native.oklab_to_srgb_f32(lab)
    srgb_numpy = oklab_to_srgb(lab)
    _assert_bits_equal(srgb_native, srgb_numpy, "oklab_to_srgb 越域 lab")
    assert np.isfinite(srgb_native).all()
    assert srgb_native.min() >= 0.0 and srgb_native.max() <= 1.0


def test_single_pixel_and_non_hw_shape(native_required):
    # (1,1,3) 单像素走 native, 与 numpy 逐位一致
    x = np.array([[[0.42, 0.17, 0.93]]], dtype=np.float32)
    lab_native = native.srgb_to_oklab_f32(x)
    _assert_bits_equal(lab_native, srgb_to_oklab(x), "srgb_to_oklab 单像素")


# ---------------------------------------------------------------------------
# 便捷封装 + 回退契约 (对齐 test_native_fallback.py 模式)
# ---------------------------------------------------------------------------

def test_wrapper_uses_native_when_available(native_required):
    x = _random_rgb_f32((64, 48, 3))
    out = native.srgb_to_oklab(x)
    assert out.dtype == np.float64
    _assert_bits_equal(out, native.srgb_to_oklab_f32(x), "封装正向应命中 native")
    lab = srgb_to_oklab(x)
    out2 = native.oklab_to_srgb(lab)
    assert out2.dtype == np.float32
    _assert_bits_equal(out2, native.oklab_to_srgb_f32(lab), "封装逆向应命中 native")


def test_wrapper_fallback_when_native_missing(native_disabled):
    x = np.random.default_rng(SEED).random((32, 32, 3), dtype=np.float32)
    out = native.srgb_to_oklab(x)
    assert out.dtype == np.float64
    assert np.array_equal(out, srgb_to_oklab(x))

    lab = srgb_to_oklab(x)
    out2 = native.oklab_to_srgb(lab)
    assert out2.dtype == np.float32
    assert np.array_equal(out2, oklab_to_srgb(lab))


def test_wrapper_non_3d_routes_to_numpy(native_required):
    # (...,3) 非 (H,W,3) 形状 (core 支持任意 (...,3)): 封装应回退 numpy 而非报错
    x1d = np.array([0.2, 0.5, 0.9], dtype=np.float32)
    assert np.array_equal(native.srgb_to_oklab(x1d), srgb_to_oklab(x1d))
    x2d = np.random.default_rng(SEED).random((5, 3), dtype=np.float32)
    assert np.array_equal(native.srgb_to_oklab(x2d), srgb_to_oklab(x2d))


def test_wrapper_f64_input_routes_to_numpy(native_required):
    # f64 精密输入不可被 native f32 路径静默量化: 封装应走 numpy (§1.3 契约)
    x = np.random.default_rng(SEED).random((16, 16, 3), dtype=np.float64)
    out = native.srgb_to_oklab(x)
    assert np.array_equal(out, srgb_to_oklab(x))
