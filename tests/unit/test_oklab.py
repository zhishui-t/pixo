"""M-O1 Oklab/OKLCh 转换内核单元测试 (OWN_PIPELINE_STAGE1_DESIGN §2.1)。

验证: sRGB↔Oklab 网格(步长 1/32)/随机往返精度 ≤1e-7、灰轴 C≈0 无 NaN、
黑/白端点精确、批量与单像素逐位一致、OKLCh 往返与 h 环绕 0/360 连续、
Ottosson 2020 文献锚点色值、矩阵对互逆性、dtype/值域契约、色域外裁剪、
非法形状报错。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.oklab import (_M1_INV_LMS_TO_LSRGB, _M1_LSRGB_TO_LMS,
                                    _M2_INV_LAB_TO_LMSP, _M2_LMSP_TO_LAB,
                                    oklab_to_oklch, oklab_to_srgb,
                                    oklch_to_oklab, srgb_to_oklab)

ALL_FNS = (srgb_to_oklab, oklab_to_srgb, oklab_to_oklch, oklch_to_oklab)


def _grid01(step: int = 32) -> np.ndarray:
    """[0,1]³ 均匀网格 (每轴 step+1 点, k/32 均 float64 精确) → (N,3)。"""
    ax = np.arange(step + 1, dtype=np.float64) / step
    return np.stack(np.meshgrid(ax, ax, ax, indexing="ij"), axis=-1).reshape(-1, 3)


# ---------------------------------------------------------------------------
# 往返精度 (核心验收: ≤1e-7)
# ---------------------------------------------------------------------------

def test_roundtrip_grid_step_1over32_max_error():
    """设计 §2.1 硬指标: [0,1]³ 网格 (步长 1/32) sRGB↔Oklab 往返最大误差 ≤1e-7。"""
    grid = _grid01(32)
    back = oklab_to_srgb(srgb_to_oklab(grid))
    err = float(np.abs(back.astype(np.float64) - grid).max())
    assert err <= 1e-7, f"网格往返最大误差 {err:.3e} 超出 1e-7"


def test_roundtrip_random_dense_max_error():
    """随机稠密采样 (含非网格点) 往返同阈值; 顺带覆盖 (N,3) 大批量形状。"""
    rng = np.random.default_rng(42)
    rgb = rng.random((500_000, 3))
    back = oklab_to_srgb(srgb_to_oklab(rgb))
    err = float(np.abs(back.astype(np.float64) - rgb).max())
    assert err <= 1e-7, f"随机往返最大误差 {err:.3e} 超出 1e-7"


def test_oklch_roundtrip_tight():
    """lab → oklch → lab 往返 (f64 工作域) 应接近机器精度。"""
    rng = np.random.default_rng(3)
    lab = srgb_to_oklab(rng.random((10_000, 3)))
    lab2 = oklch_to_oklab(oklab_to_oklch(lab))
    assert float(np.abs(lab2 - lab).max()) <= 1e-9


def test_gray_axis_roundtrip_exact():
    """灰轴 (R=G=B) 往返逐位不动 (线性段) / ≤1e-7 (幂段)。"""
    v = np.linspace(0.0, 1.0, 65)
    gray = np.stack([v, v, v], axis=-1)
    back = oklab_to_srgb(srgb_to_oklab(gray))
    assert float(np.abs(back.astype(np.float64) - gray).max()) <= 1e-7


# ---------------------------------------------------------------------------
# 灰轴 / 端点
# ---------------------------------------------------------------------------

def test_gray_axis_chroma_near_zero_no_nan():
    """灰轴 → C≈0、L/a/b/h 全程有限、h 落在 [0,360)。"""
    v = np.linspace(0.0, 1.0, 65)
    gray = np.stack([v, v, v], axis=-1)
    lab = srgb_to_oklab(gray)
    assert np.isfinite(lab).all()
    lch = oklab_to_oklch(lab)
    assert np.isfinite(lch).all(), "灰轴 OKLCh 不得产生 NaN/Inf"
    assert float(lch[:, 1].max()) < 1e-6, "灰轴色度 C 应 ≈0"
    assert bool((lch[:, 2] >= 0.0).all() and (lch[:, 2] <= 360.0).all())


def test_black_endpoint_exact():
    """黑 (0,0,0): 正向 lab 与逆向 sRGB 均逐位精确 (全零链路无舍入)。"""
    black = np.zeros((1, 3), dtype=np.float64)
    lab = srgb_to_oklab(black)
    assert np.array_equal(lab, np.zeros((1, 3), dtype=np.float64))
    back = oklab_to_srgb(lab)
    assert back.dtype == np.float32
    assert np.array_equal(back, np.zeros((1, 3), dtype=np.float32))
    # OKLCh 端点: C 精确为 0, h 折到 0
    lch = oklab_to_oklch(lab)
    assert float(lch[0, 1]) == 0.0
    assert float(lch[0, 2]) == 0.0


def test_white_endpoint_exact_roundtrip():
    """白 (1,1,1): sRGB 往返逐位精确; lab L 偏差 ≤1e-6 (原文常数行和 1-6.5e-9 所致)。"""
    white = np.ones((1, 3), dtype=np.float64)
    lab = srgb_to_oklab(white)
    assert float(np.abs(lab - np.array([1.0, 0.0, 0.0])).max()) <= 1e-6
    back = oklab_to_srgb(lab)
    assert np.array_equal(back, np.ones((1, 3), dtype=np.float32))
    # C 精确为 0 不强求 (a/b 为 ~1e-8 级的常数行和伪影), 只约束量级
    assert float(oklab_to_oklch(lab)[0, 1]) < 1e-6


# ---------------------------------------------------------------------------
# 批量 vs 单像素
# ---------------------------------------------------------------------------

def test_batch_matches_single_pixel_bitwise():
    """逐分量实现与形状无关: 批量 (H,W,3) 与逐像素调用结果逐位一致 (4 个 API)。"""
    rng = np.random.default_rng(7)
    img = rng.random((5, 6, 3))
    lab = srgb_to_oklab(img)
    lch = oklab_to_oklch(lab)
    for fn, src in ((srgb_to_oklab, img), (oklab_to_srgb, lab),
                    (oklab_to_oklch, lab), (oklch_to_oklab, lch)):
        batched = fn(src)
        for i in range(5):
            for j in range(6):
                assert np.array_equal(np.asarray(batched[i, j]),
                                      np.asarray(fn(src[i, j]))), \
                    f"{fn.__name__} 批量与单像素不一致 @({i},{j})"


def test_accepts_common_shapes():
    """(3,) 单像素、(N,3)、(H,W,3)、(H,W,D,3) 均可用, 输出仅去掉最后一维语义不变。"""
    rng = np.random.default_rng(11)
    img = rng.random((4, 5, 3))
    for fn in ALL_FNS:
        out_img = fn(img)
        assert out_img.shape == (4, 5, 3)
        out_flat = fn(img.reshape(-1, 3))
        assert np.array_equal(out_flat, out_img.reshape(-1, 3))
        out_single = fn(img[2, 3])
        assert np.array_equal(out_single, out_img[2, 3])
    vol = rng.random((2, 3, 4, 3))
    for fn in ALL_FNS:
        assert fn(vol).shape == (2, 3, 4, 3)


# ---------------------------------------------------------------------------
# OKLCh 语义
# ---------------------------------------------------------------------------

def test_oklch_hue_range_and_fold():
    """h 输出严格 [0,360): 极小负 b 的浮点 mod 伪影 (360.0) 折回 0。"""
    rng = np.random.default_rng(5)
    lab = srgb_to_oklab(rng.random((20_000, 3)))
    h = oklab_to_oklch(lab)[:, 2]
    assert bool((h >= 0.0).all() and (h < 360.0).all())
    # b 为极小负数: degrees%360 浮点上恰好等于 360.0, 应折回 0
    h_edge = oklab_to_oklch(np.array([[0.5, 0.1, -1e-14]]))[0, 2]
    assert 0.0 <= h_edge < 360.0


def test_oklch_hue_wrap_continuous():
    """h 环绕连续: 361°≡1°、368°≡8° (348°+20° 跨 0/360 无跳变)。"""
    base1 = oklch_to_oklab(np.array([[0.6, 0.1, 1.0]]))
    wrap1 = oklch_to_oklab(np.array([[0.6, 0.1, 361.0]]))
    assert np.allclose(base1, wrap1, atol=1e-9)
    base8 = oklch_to_oklab(np.array([[0.6, 0.1, 8.0]]))
    wrap8 = oklch_to_oklab(np.array([[0.6, 0.1, 368.0]]))
    assert np.allclose(base8, wrap8, atol=1e-9)


# ---------------------------------------------------------------------------
# 文献锚点与矩阵互逆 (Ottosson 2020)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("srgb,ref", [
    ((1.0, 0.0, 0.0), (0.627955, 0.224863, 0.125846)),    # 红
    ((0.0, 1.0, 0.0), (0.866440, -0.233888, 0.179498)),   # 绿
    ((0.0, 0.0, 1.0), (0.452014, -0.032457, -0.311528)),  # 蓝
])
def test_published_anchor_colors(srgb, ref):
    """sRGB 原色 → Oklab 与 Ottosson 2020 公布示例一致 (容差覆盖文献 6 位舍入)。"""
    got = srgb_to_oklab(np.array([srgb], dtype=np.float64))[0]
    assert np.allclose(got, ref, atol=2e-4), f"{srgb} → {got} 偏离文献值 {ref}"


def test_matrix_pairs_mutually_inverse():
    """正/逆矩阵对互逆 ≤1e-11 —— 往返 ≤1e-7 验收的数值根基 (原生内核对齐前置)。"""
    eye = np.eye(3)
    assert float(np.abs(_M1_INV_LMS_TO_LSRGB @ _M1_LSRGB_TO_LMS - eye).max()) <= 1e-11
    assert float(np.abs(_M2_INV_LAB_TO_LMSP @ _M2_LMSP_TO_LAB - eye).max()) <= 1e-11


# ---------------------------------------------------------------------------
# dtype / 值域契约 / 色域外 / 异常路径
# ---------------------------------------------------------------------------

def test_output_dtype_contract():
    """sRGB 域出口 float32; Oklab/OKLCh 内部工作域出口 float64。"""
    rng = np.random.default_rng(13)
    img = rng.random((3, 3, 3))
    assert srgb_to_oklab(img).dtype == np.float64
    lab = srgb_to_oklab(img)
    assert oklab_to_srgb(lab).dtype == np.float32
    assert oklab_to_oklch(lab).dtype == np.float64
    assert oklch_to_oklab(oklab_to_oklch(lab)).dtype == np.float64
    # float32 输入同样接受
    assert oklab_to_srgb(lab.astype(np.float32)).dtype == np.float32


def test_srgb_output_in_unit_range():
    """oklab_to_srgb 输出严格 [0,1] (域内像素)。"""
    rng = np.random.default_rng(17)
    back = oklab_to_srgb(srgb_to_oklab(rng.random((1000, 3))))
    assert bool((back >= 0.0).all() and (back <= 1.0).all())


def test_out_of_gamut_clipped_no_nan():
    """色域外 Oklab (大 C / L>1): linear clip 后编码, 输出 [0,1] 且无 NaN。"""
    lch = np.array([[0.5, 0.40, 30.0],
                    [0.5, 0.40, 200.0],
                    [1.20, 0.50, 90.0],
                    [0.0, 0.10, 270.0]])
    out = oklab_to_srgb(oklch_to_oklab(lch))
    assert np.isfinite(out).all()
    assert bool((out >= 0.0).all() and (out <= 1.0).all())


def test_negative_srgb_input_no_nan():
    """契约外负输入不产生 NaN (解码侧按 0 处理, 对齐 huesat 纪律)。"""
    lab = srgb_to_oklab(np.array([[-0.5, 0.0, 2.0]]))
    assert np.isfinite(lab).all()


@pytest.mark.parametrize("bad", [
    np.zeros(4),            # 末维 4
    np.zeros((2, 2)),       # 末维 2
    np.zeros(()),           # 标量
    np.zeros((3, 1)),       # 末维 1
])
def test_invalid_shape_raises(bad):
    """最后一维非 3 的输入 → ValueError (4 个 API 一致)。"""
    for fn in ALL_FNS:
        with pytest.raises(ValueError):
            fn(bad)
