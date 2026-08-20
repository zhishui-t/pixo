"""T5 单元测试: 四面体 3D LUT + .cube 1D shaper + DOMAIN。

覆盖对象:
  - rawlab.engine.lut3d.tetrahedral_interp  (四面体插值, Kasson 1993)
  - rawlab.engine.lut3d.LUT3D / parse_cube / hald_to_lut
  - rawlab.lut (对 engine.lut3d 的兼容再导出)

验收标准 (规格 AC-08 / 任务 T5):
  - identity 33³ LUT 误差 0 (8bit 输出 == 输入, 位精确)
  - 四面体在已知线性(仿射)梯度场上插值精确 (顶点/面/边/体心)
  - 1D shaper 先于 3D LUT 生效
  - DOMAIN_MIN/MAX 缩放正确
  - 256³ 建表分块 (chunk) 且结果与直接 lookup 一致

运行: python -m pytest rawlab/tests/test_lut.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from rawlab.engine.lut3d import LUT3D, hald_to_lut, parse_cube, tetrahedral_interp


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------

def _identity_lut(n: int) -> np.ndarray:
    """恒等 3D LUT: data[r,g,b] = (r,g,b)/(n-1)。"""
    idx = np.stack(np.mgrid[0:n, 0:n, 0:n], axis=-1)  # (n,n,n,3)
    return (idx / (n - 1)).astype(np.float32)


def _affine_lut(n: int, a: np.ndarray, offset: np.ndarray) -> np.ndarray:
    """仿射场 3D LUT: data[r,g,b] = a @ coord + offset, coord=(r,g,b)/(n-1)。

    a      : (3,3) 斜率矩阵
    offset : (3,)  偏移
    """
    idx = np.stack(np.mgrid[0:n, 0:n, 0:n], axis=-1).astype(np.float32)  # (n,n,n,3)
    coord = idx / (n - 1.0)
    out = np.einsum("...j,ij->...i", coord, a) + np.asarray(offset, np.float32)
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# 1) identity 33³ LUT 误差 0 (AC-08)
# ---------------------------------------------------------------------------

def test_identity_33_lut_apply_error_zero():
    n = 33
    lut = LUT3D(_identity_lut(n))
    # 随机 8bit 图: 输出必须位精确等于输入 (AC-08)
    rng = np.random.default_rng(0)
    rgb = rng.integers(0, 256, (64, 64, 3)).astype(np.uint8)
    out = lut.apply(rgb)
    assert out.dtype == np.uint8
    assert np.array_equal(out, rgb), "identity 33³ LUT 8bit 输出必须位精确等于输入"
    # 全部 256 级灰阶: 逐级精确 (捕获任一 off-by-one)
    gray = np.arange(256, dtype=np.uint8)
    gray_rgb = np.stack([gray, gray, gray], axis=-1)  # (256,3)
    assert np.array_equal(lut.apply(gray_rgb), gray_rgb), \
        "identity LUT 全部 256 级灰阶必须逐级精确"


# ---------------------------------------------------------------------------
# 2) 四面体在已知线性梯度场上的插值精确 (顶点/面/边/体心)
# ---------------------------------------------------------------------------

def test_tetrahedral_exact_on_affine_field():
    n = 17
    a = np.array([[2.0, 0.5, -1.0],
                  [-0.25, 3.0, 0.5],
                  [1.0, -0.5, 2.5]], dtype=np.float32)
    offset = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    data = _affine_lut(n, a, offset)

    # 顶点 / 面心 / 边心 / 体心 / 内部一般点 (归一化 0..1)
    points = np.array([
        [0.0, 0.0, 0.0],   # 顶点
        [1.0, 1.0, 1.0],   # 顶点
        [0.0, 1.0, 0.0],   # 顶点
        [0.0, 0.5, 0.5],   # 面心 (r=0)
        [0.5, 1.0, 0.5],   # 面心 (g=1)
        [0.5, 0.5, 1.0],   # 面心 (b=1)
        [0.5, 0.0, 0.0],   # 边心
        [0.0, 0.0, 0.5],   # 边心
        [1.0, 0.5, 1.0],   # 边心 (g 中点)
        [0.5, 0.5, 0.5],   # 体心
        [0.25, 0.5, 0.75],  # 内部一般点
    ], dtype=np.float32)

    got = tetrahedral_interp(data, points * (n - 1.0))
    exact = points @ a.T + offset
    assert np.allclose(got, exact, atol=1e-4, rtol=1e-4), \
        f"四面体插值在仿射场上不精确, 最大误差 {np.abs(got - exact).max():.3e}"


def test_tetrahedral_vertex_bit_exact():
    """整数格点处四面体插值必须位精确等于 data 值 (f=0 → c000)。"""
    n = 8
    a = np.array([[1.5, -0.3, 0.7], [0.2, 2.0, -0.4], [-0.6, 0.9, 1.3]], np.float32)
    data = _affine_lut(n, a, np.array([0.05, 0.1, -0.15], np.float32))
    for r in (0, 3, 7):
        for g in (0, 3, 7):
            for b in (0, 3, 7):
                pos = np.array([[r, g, b]], dtype=np.float32)
                got = tetrahedral_interp(data, pos)
                assert np.array_equal(got[0], data[r, g, b]), \
                    f"顶点 ({r},{g},{b}) 插值应位精确"


# ---------------------------------------------------------------------------
# 3) 1D shaper 生效 (先于 3D LUT)
# ---------------------------------------------------------------------------

def test_shaper_applied_before_3d_lut():
    n = 5
    m = 1024
    t = np.linspace(0.0, 1.0, m, dtype=np.float32)
    shaper = (t * t).astype(np.float32)   # 凹曲线 x → x²
    lut = LUT3D(_identity_lut(n), shaper=shaper)

    # 0.5 → shaper 0.25 → identity 3D → 0.25
    out = lut.lookup(np.array([[0.5, 0.5, 0.5]], dtype=np.float32))
    assert np.allclose(out, 0.25, atol=1e-3), f"shaper 未生效: {out}"
    # 端点精确
    assert np.allclose(lut.lookup(np.array([[1.0, 1.0, 1.0]], np.float32)), 1.0, atol=1e-4)
    assert np.allclose(lut.lookup(np.array([[0.0, 0.0, 0.0]], np.float32)), 0.0, atol=1e-4)


def test_no_shaper_behaves_as_identity():
    n = 5
    lut = LUT3D(_identity_lut(n))
    out = lut.lookup(np.array([[0.3, 0.6, 0.9]], dtype=np.float32))
    assert np.allclose(out, [0.3, 0.6, 0.9], atol=1e-4)


# ---------------------------------------------------------------------------
# 4) DOMAIN 缩放正确
# ---------------------------------------------------------------------------

def test_domain_scaling_gain():
    n = 5
    lut = LUT3D(_identity_lut(n), domain_min=0.0, domain_max=0.5)
    vals = np.array([0.0, 0.125, 0.25, 0.5, 0.6], dtype=np.float32)
    x = np.repeat(vals[:, None], 3, axis=1)
    got = lut.lookup(x)[:, 0]
    expected = np.clip(vals * 2.0, 0.0, 1.0)   # t = (v-0)/0.5 = 2v
    assert np.allclose(got, expected, atol=1e-4), f"DOMAIN 增益缩放错误: {got} vs {expected}"


def test_domain_scaling_shifted():
    n = 5
    lut = LUT3D(_identity_lut(n), domain_min=0.2, domain_max=0.6)
    vals = np.array([0.0, 0.2, 0.3, 0.4, 0.6, 1.0], dtype=np.float32)
    x = np.repeat(vals[:, None], 3, axis=1)
    got = lut.lookup(x)[:, 0]
    expected = np.clip((vals - 0.2) / 0.4, 0.0, 1.0)
    assert np.allclose(got, expected, atol=1e-4), f"DOMAIN 平移缩放错误: {got} vs {expected}"


def test_invalid_domain_raises():
    with pytest.raises(ValueError):
        LUT3D(_identity_lut(4), domain_min=0.5, domain_max=0.5)


# ---------------------------------------------------------------------------
# 5) .cube 解析 (LUT_1D_SIZE shaper + DOMAIN + LUT_3D_SIZE)
# ---------------------------------------------------------------------------

def _write_cube(tmp_path, body_lines):
    p = tmp_path / "t.cube"
    p.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return p


def test_from_cube_parses_shaper_domain_and_3d(tmp_path):
    n = 3
    lines = [
        'TITLE "synthetic"',
        "DOMAIN_MIN 0.0",
        "DOMAIN_MAX 0.5",
        "LUT_1D_SIZE 3",
        "0.0",
        "0.25",
        "1.0",
        "LUT_3D_SIZE 3",
    ]
    for r in range(n):
        for g in range(n):
            for b in range(n):
                lines.append(f"{r / 2:.6f} {g / 2:.6f} {b / 2:.6f}")

    lut = LUT3D.from_cube(_write_cube(tmp_path, lines))
    assert lut.n == 3
    assert lut.domain_min == 0.0
    assert lut.domain_max == 0.5
    assert lut.shaper is not None and lut.shaper.shape == (3,)

    # domain [0,0.5] + 非线性 shaper (3 点: 0,0.25,1):
    #   输入 0.5 → 域缩放 t=1.0 → shaper(1.0)=1.0 → identity 3D → 1.0
    #   输入 0.25 → 域缩放 t=0.5 → shaper(0.5)=0.25 → identity 3D → 0.25
    #   输入 0.125 → 域缩放 t=0.25 → shaper(0.25)=0.125 → identity 3D → 0.125
    assert np.allclose(lut.lookup(np.array([[0.5, 0.5, 0.5]], np.float32)), 1.0, atol=1e-3)
    assert np.allclose(lut.lookup(np.array([[0.25, 0.25, 0.25]], np.float32)), 0.25, atol=1e-3)
    assert np.allclose(lut.lookup(np.array([[0.125, 0.125, 0.125]], np.float32)), 0.125, atol=1e-3)


def test_from_cube_defaults_no_shaper_no_domain(tmp_path):
    n = 4
    lines = ["LUT_3D_SIZE 4"]
    for r in range(n):
        for g in range(n):
            for b in range(n):
                lines.append(f"{r / 3:.6f} {g / 3:.6f} {b / 3:.6f}")
    lut = LUT3D.from_cube(_write_cube(tmp_path, lines))
    assert lut.n == 4
    assert lut.shaper is None
    assert lut.domain_min == 0.0 and lut.domain_max == 1.0
    # identity: 0.5 → 0.5
    assert np.allclose(lut.lookup(np.array([[0.5, 0.5, 0.5]], np.float32)), 0.5, atol=1e-4)


def test_from_cube_invalid_row_count_raises(tmp_path):
    p = _write_cube(tmp_path, ["LUT_3D_SIZE 2", "0 0 0", "1 1 1"])
    with pytest.raises(ValueError):
        parse_cube(p)


def test_from_cube_invalid_domain_raises(tmp_path):
    p = _write_cube(tmp_path, ["DOMAIN_MIN 1.0", "DOMAIN_MAX 1.0",
                               "LUT_3D_SIZE 2"] + ["0 0 0"] * 8)
    with pytest.raises(ValueError):
        parse_cube(p)


# ---------------------------------------------------------------------------
# 6) 分块建表 (chunk) 正确性
# ---------------------------------------------------------------------------

def test_build_table_chunked_matches_lookup():
    n = 8
    a = np.array([[1.2, -0.4, 0.6], [0.3, 1.8, -0.2], [-0.5, 0.7, 1.4]], np.float32)
    data = _affine_lut(n, a, np.array([0.02, -0.1, 0.15], np.float32))
    lut = LUT3D(data)
    lut._build_table(chunk=3)   # 小 chunk 强制多次分块
    assert lut._table is not None
    assert lut._table.shape == (256, 256, 256, 3)
    assert lut._table.dtype == np.uint8

    rng = np.random.default_rng(1)
    rgb = rng.integers(0, 256, (800, 3)).astype(np.uint8)
    got = lut.apply(rgb)
    ref = (np.clip(lut.lookup(rgb.astype(np.float32) / 255.0), 0.0, 1.0) * 255.0 + 0.5) \
        .astype(np.uint8)
    assert np.abs(got.astype(np.int16) - ref.astype(np.int16)).max() <= 1


def test_build_table_idempotent():
    lut = LUT3D(_identity_lut(4))
    sentinel = np.zeros((256, 256, 256, 3), dtype=np.uint8)
    lut._table = sentinel
    lut._build_table(chunk=16)
    assert lut._table is sentinel   # 已建表则不重复构建


# ---------------------------------------------------------------------------
# 7) Hald CLUT 布局
# ---------------------------------------------------------------------------

def test_hald_to_lut_layout():
    n = 4
    # 按官方布局构造 Hald 图: 像素 (y,x) 颜色 = 其编码坐标 (r,g,b)/(n-1)
    img = np.zeros((n * n, n * n, 3), dtype=np.float32)
    for b in range(n):
        ty, tx = divmod(b, n)
        for g in range(n):
            for r in range(n):
                img[ty * n + g, tx * n + r] = (r / (n - 1), g / (n - 1), b / (n - 1))

    lut = hald_to_lut(img * 255.0)   # 输入 0..255
    assert lut.n == n
    for r in range(n):
        for g in range(n):
            for b in range(n):
                expect = (r / (n - 1), g / (n - 1), b / (n - 1))
                assert np.allclose(lut.data[r, g, b], expect, atol=1e-6), \
                    f"Hald 布局错误 @({r},{g},{b})"


def test_hald_to_lut_invalid():
    with pytest.raises(ValueError):
        hald_to_lut(np.zeros((10, 10, 3), dtype=np.uint8))   # 10 不是 n²
    with pytest.raises(ValueError):
        hald_to_lut(np.zeros((10, 8, 3), dtype=np.uint8))    # 非正方形


# ---------------------------------------------------------------------------
# 8) rawlab.lut 兼容再导出
# ---------------------------------------------------------------------------

def test_rawlab_lut_reexports_engine_lut3d():
    from rawlab.lut import LUT3D as CompatLUT3D, hald_to_lut as compat_hald
    assert CompatLUT3D is LUT3D
    assert compat_hald is hald_to_lut
