"""R32-T3: HaldCLUT (RT level 布局) 格式适配测试。

覆盖:
  - hald_level_to_lut: 恒等 CLUT 精确性 (16/8 位)、非法尺寸拒绝;
  - write_cube ↔ parse_cube 往返;
  - 转换工具 convert();
  - 取舍依据量化: 恒等/仿射 CLUT 上四面体 (我方) 逐位精确, RT 三线性
    (clutstore.cc 移植参考, 仅测量用) 存在扇形误差 → 无引擎吸收必要。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.lut3d import (hald_level_to_lut, parse_cube,
                                    tetrahedral_interp, write_cube)


def make_identity_hald(level: int, dtype=np.uint16):
    """恒等 HaldCLUT (RT level 布局) 图: 边 = level³, 网格 = level²。"""
    n = level * level
    side = level ** 3
    img = np.zeros((side, side, 3), dtype=dtype)
    top = np.iinfo(dtype).max if np.issubdtype(dtype, np.integer) else 1.0
    rr, gg, bb = np.meshgrid(np.arange(n), np.arange(n), np.arange(n),
                             indexing="ij")
    idx = (rr + gg * n + bb * n * n).reshape(-1)
    ys, xs = idx // side, idx % side
    vals = np.stack([rr.reshape(-1), gg.reshape(-1), bb.reshape(-1)], axis=1)
    img[ys, xs] = (vals * (top / (n - 1))).astype(dtype)
    return img


def rt_trilinear_ref(data: np.ndarray, x: np.ndarray) -> np.ndarray:
    """RT clutstore.cc getRGB 三线性插值参考 (逐式移植, 仅测量用;
    出处 RawTherapee rtengine/clutstore.cc @ 6c4cb59, GPLv3)。

    data: (N,N,N,3) 展平序同 RT 线性索引 (r + g·N + b·N²); x: (...,3) [0,1]。
    """
    n = data.shape[0]
    flat = data.reshape(-1, 3)
    x = np.asarray(x, dtype=np.float64)
    f = np.minimum(x * (n - 1), n - 2)
    i = np.floor(f).astype(np.int64)
    frac = f - i
    ir, ig, ib = i[..., 0], i[..., 1], i[..., 2]
    fr, fg, fb = frac[..., 0], frac[..., 1], frac[..., 2]
    color = ir + ig * n + ib * n * n
    c = lambda idx: flat[idx]  # noqa: E731

    def intp(t, a, b):
        return a + t * (b - a)

    tmp1 = intp(fr[:, None], c(color), c(color + 1))
    tmp2 = intp(fr[:, None], c(color + n), c(color + n + 1))
    out = intp(fg[:, None], tmp2, tmp1)
    tmp1 = intp(fr[:, None], c(color + n * n), c(color + n * n + 1))
    tmp2 = intp(fr[:, None], c(color + n * n + n), c(color + n * n + n + 1))
    tmp1 = intp(fg[:, None], tmp2, tmp1)
    out = intp(fb[:, None], tmp1, out)
    return out.astype(np.float32)


def test_hald_level_identity_exact():
    """恒等 CLUT: 网格顶点值 == 设计值 (16 位, level 2 → 网格 4)。"""
    level = 2
    img = make_identity_hald(level, np.uint16)
    lut = hald_level_to_lut(img)
    assert lut.n == level * level
    n = lut.n
    grid = np.stack(np.meshgrid(np.arange(n), np.arange(n), np.arange(n),
                                indexing="ij"), axis=-1).reshape(-1, 3)
    expect = (grid / (n - 1)).astype(np.float32)
    got = lut.data.reshape(-1, 3)
    assert np.abs(got - expect).max() <= 1.5e-5  # 16 位量化 (1/65535)


def test_hald_level_bit_depth_consistency():
    """同一 CLUT 的 8 位与 16 位版本 → LUT 差 ≤ 8 位量化半径。"""
    img16 = make_identity_hald(3, np.uint16)
    img8 = (img16 / 257.0).round().astype(np.uint8)
    lut16 = hald_level_to_lut(img16)
    lut8 = hald_level_to_lut(img8)
    assert np.abs(lut8.data - lut16.data).max() <= 2.0 / 255.0 + 1e-5


def test_hald_invalid_sizes_raise():
    bad = np.zeros((500, 500, 3), np.uint16)   # 500 不是 level³
    with pytest.raises(ValueError):
        hald_level_to_lut(bad)
    nonsquare = np.zeros((512, 256, 3), np.uint16)
    with pytest.raises(ValueError):
        hald_level_to_lut(nonsquare)


def test_write_cube_roundtrip(tmp_path):
    rng = np.random.default_rng(32)
    data = rng.random((4, 4, 4, 3)).astype(np.float32)
    path = tmp_path / "r32.cube"
    write_cube(data, path, title="r32 test")
    lut = parse_cube(path)
    assert lut.n == 4
    assert np.abs(lut.data - data).max() <= 2e-6   # %.6g 文本精度
    assert (lut.domain_min, lut.domain_max) == (0.0, 1.0)


def test_tetrahedral_beats_trilinear_on_affine():
    """取舍依据: 仿射 CLUT (线性变换) 上四面体逐位精确, RT 三线性有
    扇形误差 → 引擎吸收无精度收益 (格式适配路线的量化支撑)。"""
    level = 8
    n = level * level
    rng = np.random.default_rng(7)
    m = rng.normal(size=(3, 3)) * 0.3
    c0 = rng.random(3) * 0.2
    rr, gg, bb = np.meshgrid(np.arange(n), np.arange(n), np.arange(n),
                             indexing="ij")
    coords = np.stack([rr, gg, bb], axis=-1).reshape(-1, 3) / (n - 1)
    data = (coords @ m.T + c0).astype(np.float32).reshape(n, n, n, 3)

    probes = rng.random((4096, 3)).astype(np.float32)
    truth = (probes @ m.T + c0).astype(np.float32)

    tet = tetrahedral_interp(data, probes * (n - 1))
    tri = rt_trilinear_ref(data, probes)

    err_tet = np.abs(tet - truth).max()
    err_tri = np.abs(tri - truth).max()
    assert err_tet <= 1e-5, f"四面体在仿射场上应精确, 实得 {err_tet}"
    assert err_tri > err_tet * 10, (
        f"三线性误差应显著大于四面体: tri={err_tri}, tet={err_tet}")


def test_tool_convert_identity(tmp_path):
    """转换工具: 恒等 Hald png (16 位) → .cube → parse ≈ 恒等。"""
    import cv2

    from pixo.render.tools.haldclut_convert import convert
    level = 4
    img = make_identity_hald(level, np.uint16)
    png = tmp_path / "HaldCLUT_identity.png"
    assert cv2.imwrite(str(png), img)          # 16 位 png
    cube = tmp_path / "identity.cube"
    lv, n = convert(png, cube, title="identity")
    assert (lv, n) == (level, level * level)
    lut = parse_cube(cube)
    probe = np.linspace(0.0, 1.0, 9, dtype=np.float32).reshape(-1, 1)
    probe = probe.repeat(3, axis=1)
    out = lut.lookup(probe)
    # R32-T3 reviewer 遗留收紧: 恒等场是仿射场, 四面体插值应达量化级精度
    # (顶点逐位精确, 非网格点仅受 float32 舍入限), 不应出现 1/(N-1) 级误差
    assert np.abs(out - probe).max() <= 1e-4, (
        f"恒等 CLUT 查表误差超量化级: {np.abs(out - probe).max()}")
