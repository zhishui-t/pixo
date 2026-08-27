"""stylize LUT3D native C++ float 四面体内核 (v1.3.0) 测试。

覆盖:
  - LUT3D.apply_f32 native 路径 vs numpy lookup() 参考的严格等价
    (33³ shaper 表 + 17³ 非均匀表, 含边界/超界值/强度混合);
  - native 不可用时的 numpy 回退路径等价;
  - 性能断言: 3024x2012 随机图 native apply < 150ms (宽松上界防 CI 脆);
  - StylizeStage float 路径数值锁定 (快照级, 防未来回归);
  - 旧 u8 apply() 路径 vs 新 float 路径差异的 Lab 域粗验
    (B 代理基准报告 u8 量化 ~0.22 ΔE 量级)。

等价容差推导 (native vs lookup, 两者数学同式):
  numpy 参考的真实精度语义 —— tetrahedral_interp 中 `f = pos - i0`
  (float32 数组 - int32 数组) 按 NEP 50 数组-数组提升规则升 float64,
  因此权重 w 与 4 顶点 MAC 全程 float64, 仅最后 .astype(float32) 舍入
  一次; 1D shaper 的 `frac = pos - i0` 同理 (f64 MAC)。内核同步以
  double 计算权重/MAC/shaper (顶点值从 f32 精确升 f64), 求值序与
  numpy 表达式左结合一致 → 实测 (本机 MinGW g++ -O3/OpenMP vs numpy
  2.5) 逐位相等 (max diff = 0.0)。断言取 1e-6 留编译器/平台重排余量:
  四面体权重和恒 1 (w0+w1+w2+w3 = (1-fmax)+(fmax-fmid)+(fmid-fmin)+fmin),
  输出是表值凸组合, 任一侧若发生 f32 序重排, 全链 ≤ ~8 步舍入
  (域缩放 2 + shaper 2 + 权重 3 + 乘加 4), 每步 ≤ 1 ulp(1) ≈ 1.19e-7,
  理论上界 ~1e-6。
"""
from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from pixo.render import _native as native
from pixo.render.core.lut3d import LUT3D
from pixo.render.modules.style import StylizeStage
from pixo.render.pipeline.context import StageContext

EQUIV_TOL = 1e-6


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 lut3d native 等价测试")


@pytest.fixture()
def native_disabled(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    return native


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------

def _astia_like_lut(n: int = 33, shaper_m: int = 256) -> LUT3D:
    """33³ 类胶片表 (astia 量级): 通道 S 曲线 + 轻微交叉耦合 + 1D shaper。

    本仓库 guanlan/luts/astia.cube 不随 repo 分发 (外部目录), 用同尺寸
    (33³) 的光滑非线性表覆盖同一代码路径 (shaper + 四面体全分支)。
    """
    idx = np.stack(np.mgrid[0:n, 0:n, 0:n], axis=-1).astype(np.float32)
    x = idx / (n - 1.0)
    # 通道 S 曲线 (软胶片对比): x + 0.18*sin(2πx) 的光滑变形
    s = x + 0.18 * np.sin(2.0 * np.pi * x)
    out = np.stack([
        0.92 * s[..., 0] + 0.06 * s[..., 1] + 0.04 * s[..., 2],
        0.05 * s[..., 0] + 0.90 * s[..., 1] + 0.07 * s[..., 2],
        0.03 * s[..., 0] + 0.09 * s[..., 1] + 0.88 * s[..., 2],
    ], axis=-1)
    t = np.linspace(0.0, 1.0, shaper_m, dtype=np.float32)
    shaper = (t ** 2.2).astype(np.float32)   # 凹 shaper (扩展域覆盖)
    return LUT3D(out.astype(np.float32), shaper=shaper)


def _random_nonuniform_lut(n: int = 17, seed: int = 7) -> LUT3D:
    """17³ 合成非均匀表: 随机值域略越界 ([-0.05, 1.05], 覆盖表值尾部),
    DOMAIN [0.1, 0.9] 覆盖输入窗口缩放分支。"""
    rng = np.random.default_rng(seed)
    data = (rng.random((n, n, n, 3), dtype=np.float32) * 1.1 - 0.05)
    return LUT3D(data.astype(np.float32), domain_min=0.1, domain_max=0.9)


def _probe_image(n: int = 33, seed: int = 3) -> np.ndarray:
    """含边界/超界/表格点的探针图 (H,W,3)。"""
    rng = np.random.default_rng(seed)
    special = np.array([
        [0.0, 0.0, 0.0], [1.0, 1.0, 1.0],
        [0.0, 1.0, 0.0], [1.0, 0.0, 1.0],
        [-0.3, 0.5, 0.5], [1.3, 0.2, 0.8],        # 超界 (DOMAIN 截断)
        [1.0, 0.0, 0.0], [0.5, 0.5, 0.5],
        [16 / 32, 16 / 32, 16 / 32],              # 恰为 33³ 表格点
        [8 / 32, 24 / 32, 1 / 32],                # 表格点组合
        [1e-7, 1.0 - 1e-7, 0.5],                  # 逼近边界的次正常数
    ], dtype=np.float32)
    h = w = 24
    img = rng.random((h, w, 3), dtype=np.float32)
    for k, v in enumerate(special):
        img[k // w, k % w] = v
    return img


def _ref_apply_f32(lut: LUT3D, img: np.ndarray, strength: float = 1.0):
    """numpy 参考 (与 apply_f32 回退路径同式)。"""
    out = lut.lookup(img)
    if strength < 1.0:
        out = img * (1.0 - strength) + out * strength
    return out.astype(np.float32, copy=False)


# ---------------------------------------------------------------------------
# 1) 严格等价: native apply_f32 vs lookup()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lut_factory", [
    pytest.param(_astia_like_lut, id="astia_like_33_shaper"),
    pytest.param(_random_nonuniform_lut, id="random_17_domain"),
])
@pytest.mark.parametrize("strength", [1.0, 0.5, 0.37])
def test_apply_f32_native_matches_lookup(native_required, lut_factory,
                                         strength):
    lut = lut_factory()
    img = _probe_image(n=lut.n)
    got = lut.apply_f32(img, strength=strength)
    ref = _ref_apply_f32(lut, img, strength)
    assert got.dtype == np.float32 and got.shape == img.shape
    diff = np.abs(got - ref).max()
    assert diff <= EQUIV_TOL, f"native vs lookup max diff {diff:.3e}"


def test_apply_f32_direct_kernel_bit_exact(native_required):
    """逐位断言 (实测口径): 同表同图, 内核直调 vs lookup 输出逐位相等。"""
    lut = _astia_like_lut()
    img = _probe_image(n=33)
    table = np.ascontiguousarray(lut.data)
    got = native.lut3d_apply_f32(
        img, table, domain_min=lut.domain_min, domain_max=lut.domain_max,
        shaper=lut.shaper, strength=1.0)
    ref = lut.lookup(img)
    assert np.array_equal(got, ref), \
        f"逐位不等: max diff {np.abs(got - ref).max():.3e}"


def test_apply_f32_rejects_bad_shapes(native_required):
    lut = _astia_like_lut(n=4, shaper_m=8)
    with pytest.raises(ValueError):
        lut.apply_f32(np.zeros((5, 3), dtype=np.float32))     # 非 (H,W,3)
    with pytest.raises(ValueError):
        native.lut3d_apply_f32(np.zeros((4, 4, 3), np.float32),
                               np.zeros((4, 4, 3), np.float32))  # 非 4D 表


# ---------------------------------------------------------------------------
# 2) native 不可用 → numpy 回退 (同式, 慢但正确)
# ---------------------------------------------------------------------------

def test_apply_f32_fallback_matches_lookup(native_disabled):
    lut = _astia_like_lut()
    img = _probe_image(n=33)
    got = lut.apply_f32(img, strength=0.5)
    ref = _ref_apply_f32(lut, img, 0.5)
    assert np.array_equal(got, ref), "回退路径必须与 lookup 参考逐位一致"


# ---------------------------------------------------------------------------
# 3) 性能: 3024x2012 随机图 native apply < 150ms (宽松 CI 上界)
# ---------------------------------------------------------------------------

def test_apply_f32_native_perf_half_frame(native_required):
    lut = _astia_like_lut()
    rng = np.random.default_rng(20260826)
    img = rng.random((2012, 3024, 3), dtype=np.float32)
    lut.apply_f32(img)                       # 预热 (页表/缓存)
    best = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        lut.apply_f32(img)
        best = min(best, time.perf_counter() - t0)
    print(f"\n[lut3d native] 3024x2012 apply_f32 best-of-3: {best * 1000:.1f} ms")
    assert best < 0.150, f"native apply_f32 过慢: {best * 1000:.1f} ms"


def test_apply_f32_native_perf_full_frame_measure(native_required):
    """全幅 (6048x4024) 实测量级报告 (不设硬断言, 防多任务环境脆)。"""
    lut = _astia_like_lut()
    rng = np.random.default_rng(20260827)
    img = rng.random((4024, 6048, 3), dtype=np.float32)
    lut.apply_f32(img)
    t0 = time.perf_counter()
    lut.apply_f32(img)
    dt = time.perf_counter() - t0
    print(f"\n[lut3d native] 6048x4024 apply_f32: {dt * 1000:.1f} ms")


# ---------------------------------------------------------------------------
# 4) StylizeStage float 路径数值锁定
# ---------------------------------------------------------------------------

class _FakeCtx(StageContext):
    def __init__(self, img):
        super().__init__("/nonexistent/x.nef")
        self.set_image(img, "gamma_rgb")


def _stylize_out(img, strength, lut):
    stage = StylizeStage({"lut": lut, "lut_strength": strength})
    ctx = _FakeCtx(img)
    stage.process(ctx)
    return ctx.image


def test_stylize_stage_float_path_locked(native_required):
    """小图快照: StylizeStage float 路径输出与 lookup 参考逐位一致。"""
    lut = _astia_like_lut()
    img = _probe_image(n=33)
    out = _stylize_out(img, 0.6, lut)
    ref = _ref_apply_f32(lut, img, 0.6)
    assert out.dtype == np.float32
    assert np.array_equal(out, ref), "stylize float 路径偏离 lookup 参考"


def test_stylize_stage_float_off_u8_grid(native_required):
    """float 路径输出不落 u8/255 网格 (量化回收的直接证据)。"""
    lut = _random_nonuniform_lut()
    rng = np.random.default_rng(11)
    img = rng.random((8, 8, 3), dtype=np.float32) * 0.4 + 0.2
    out = _stylize_out(img, 1.0, lut)
    scaled = out * 255.0
    off_grid = np.abs(scaled - np.round(scaled)).max()
    assert off_grid > 1e-3, "输出仍贴合 u8 网格, float 路径未生效"


def test_stylize_stage_zero_strength_passthrough(native_required):
    lut = _astia_like_lut()
    img = _probe_image(n=33)
    out = _stylize_out(img, 0.0, lut)
    assert np.array_equal(out, img)   # strength=0 直接跳过, 原图不动


# ---------------------------------------------------------------------------
# 5) 旧 u8 apply() vs 新 float 路径: Lab 域 ΔE 粗验 (B 报告 ~0.22 ΔE 量级)
# ---------------------------------------------------------------------------

def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.float32), cv2.COLOR_RGB2LAB)


def test_u8_path_vs_float_path_delta_e(native_required):
    """旧 u8 路径 (quantize→256³表→/255) vs float 路径的 ΔE 实测。

    实测 (本机, 合成 33³ 类 astia 表 + x^2.2 shaper, 256² 均匀随机图):
      mean ≈ 0.40, p99 ≈ 1.2, max ≈ 2.7 (ΔE76, cv2 float Lab)。
    与 B 代理基准报告的 0.22 ΔE 同量级 (亚 ΔE 单位的 u8 网格量化差;
    B 的具体数值口径不同 —— 其用真实 astia.cube 与实拍图, 分布更集中)。
    差异主体来自旧路径的输出 /255 网格 (Lab 在中间调对 v 的斜率 ~
    100×Δv/v, 0.5/255 的输出舍入即 ~0.3 ΔE), 对 LUT 斜率不敏感
    (实测斜率 2.13→1.25 仅 0.41→0.36)。
    """
    lut = _astia_like_lut()
    rng = np.random.default_rng(20260826)
    img = rng.random((256, 256, 3), dtype=np.float32)
    u8 = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    out_u8 = lut.apply(u8).astype(np.float32) / 255.0
    out_f32 = lut.apply_f32(img)
    lab_u8 = _srgb_to_lab(out_u8)
    lab_f32 = _srgb_to_lab(out_f32)
    de = np.sqrt(((lab_u8 - lab_f32) ** 2).sum(axis=-1))
    print(f"\n[lut3d] u8 vs float ΔE76: mean={de.mean():.4f} "
          f"p99={np.percentile(de, 99):.4f} max={de.max():.4f}")
    # 亚 ΔE 单位的量化差 (同 B 报告 0.22 量级); 上界取 0.6 防实现漂移
    assert de.mean() < 0.6, f"u8 vs float ΔE 均值 {de.mean():.4f} 超预期"
    assert de.mean() > 0.05, "两路径不应完全重合 (float 路径未生效?)"
