"""M5/P1: native CFA 2×2 分箱解码测试。

覆盖:
  - native vs Python 参考 max|Δ| ≤ 1e-6
  - pixo.render.core.io.decode_cfa_half(raw) 对 MockRaw 的集成
  - native 不可用时模块可导入、decode 调用抛 RuntimeError (回退契约)
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render import _native as native
from pixo.render.core import io

TOL = 1e-6


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 decode 数值等价测试")


def _ref_decode(cfa, pattern_r, pattern_g0, pattern_g1, pattern_b,
                black, white_level, output_scale=1.0):
    cfa = np.asarray(cfa, dtype=np.uint16)
    h, w = cfa.shape
    out_h, out_w = h // 2, w // 2
    out = np.zeros((out_h, out_w, 3), dtype=np.float32)
    channel = {
        pattern_r: 0,
        pattern_g0: 1,
        pattern_g1: 1,
        pattern_b: 2,
    }
    for oy in range(out_h):
        for ox in range(out_w):
            for pos in range(4):
                rr = oy * 2 + pos // 2
                cc = ox * 2 + pos % 2
                v = (float(cfa[rr, cc]) - float(black[pos])) / max(
                    float(white_level) - float(black[pos]), 1.0)
                v = max(v, 0.0) * output_scale
                ch = channel[pos]
                if ch == 1:
                    out[oy, ox, 1] += v
                else:
                    out[oy, ox, ch] = v
            out[oy, ox, 1] /= 2.0
    return out


def _random_cfa(seed=20260820, h=64, w=64, max_val=16384):
    rng = np.random.default_rng(seed)
    return rng.integers(0, max_val, size=(h, w), dtype=np.uint16)


def test_decode_cfa_half_matches_reference(native_required):
    cfa = _random_cfa()
    black = [64.0, 64.0, 64.0, 64.0]
    white = 16384.0
    out = native.decode_cfa_half(
        cfa, pattern_r=0, pattern_g0=1, pattern_g1=3, pattern_b=2,
        black=black, white_level=white)
    ref = _ref_decode(cfa, 0, 1, 3, 2, black, white)
    assert out.shape == (32, 32, 3)
    assert out.dtype == np.float32
    err = float(np.abs(out - ref).max())
    assert err <= TOL, f"decode max|Δ|={err:.3e} > {TOL}"


def test_decode_cfa_half_bgra_pattern(native_required):
    # 非 RGGB 排列: BGGR 的线性位置 0=B,1=G1,2=G0,3=R
    cfa = _random_cfa(seed=7, h=16, w=16)
    black = [100.0, 80.0, 80.0, 90.0]
    white = 15000.0
    out = native.decode_cfa_half(
        cfa, pattern_r=3, pattern_g0=2, pattern_g1=1, pattern_b=0,
        black=black, white_level=white)
    ref = _ref_decode(cfa, 3, 2, 1, 0, black, white)
    err = float(np.abs(out - ref).max())
    assert err <= TOL, f"BGGR decode max|Δ|={err:.3e} > {TOL}"


def test_decode_cfa_half_invalid_shape(native_required):
    with pytest.raises(ValueError, match="至少 2x2"):
        native.decode_cfa_half(np.zeros((1, 8), dtype=np.uint16),
                               pattern_r=0, pattern_g0=1,
                               pattern_g1=3, pattern_b=2,
                               black=[0, 0, 0, 0], white_level=1)


def test_io_decode_cfa_half_with_mock_raw(native_required):
    class MockRaw:
        raw_image_visible = _random_cfa(seed=11, h=8, w=8)
        raw_pattern = np.array([[0, 1], [1, 2]], dtype=np.int32)
        color_desc = b"RGBG"
        black_level_per_channel = [64, 64, 64, 64]
        white_level = 16384

    out = io.decode_cfa_half(MockRaw())
    # pattern [[0,1],[1,2]] -> 线性位置 0=R, 1=G0, 2=G1, 3=B
    ref = _ref_decode(MockRaw.raw_image_visible, 0, 1, 2, 3,
                      [64, 64, 64, 64], 16384)
    assert out.shape == (4, 4, 3)
    assert float(np.abs(out - ref).max()) <= TOL


def test_decode_unavailable_raises(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.decode_cfa_half(np.zeros((4, 4), dtype=np.uint16),
                               pattern_r=0, pattern_g0=1,
                               pattern_g1=3, pattern_b=2,
                               black=[0, 0, 0, 0], white_level=1)


# ---------------------------------------------------------------------------
# E3 回归: decode_stage3_like 的 white_level 机型守卫
# ---------------------------------------------------------------------------

import struct
from pathlib import Path


def _write_tiff_with_make(path: Path, make: str) -> None:
    """最小合法 TIFF (IFD0 仅 Make 标签 0x010F), 小端。"""
    make_b = make.encode("ascii") + b"\x00"
    # 布局: 头 8B + IFD(2B count + 12B entry + 4B next) + Make 字符串@26
    entry = struct.pack("<HHII", 0x010F, 2, len(make_b), 26)
    data = (struct.pack("<2sHI", b"II", 42, 8)
            + struct.pack("<H", 1) + entry + struct.pack("<I", 0) + make_b)
    path.write_bytes(data)


class _Stage3MockRaw:
    """decode_stage3_like 所需的最小 RawPy 替身 (均匀 mosaic=15892)。"""

    raw_image_visible = np.full((4, 4), 15892, dtype=np.uint16)
    raw_colors = np.tile(np.array([[0, 1], [2, 3]], dtype=np.int32), (2, 2))
    color_desc = b"RGBG"
    black_level_per_channel = [0, 0, 0, 0]
    white_level = 16383


def _stage3_out(tmp_path: Path, name: str, make: str):
    raw_file = tmp_path / name
    _write_tiff_with_make(raw_file, make)
    img, _ = io.decode_stage3_like(raw_file)
    return img


def test_raw_make_reads_tiff_make_tag(tmp_path):
    nikon = tmp_path / "nikon.tif"
    _write_tiff_with_make(nikon, "NIKON CORPORATION")
    assert io._raw_make(nikon) == "NIKON CORPORATION"
    canon = tmp_path / "canon.tif"
    _write_tiff_with_make(canon, "Canon Inc.")
    assert io._raw_make(canon) == "Canon Inc."
    garbage = tmp_path / "garbage.bin"
    garbage.write_bytes(b"\x00\x01not-a-tiff")
    assert io._raw_make(garbage) == ""


def test_stage3_white_level_nikon_uses_measured_15892(tmp_path, monkeypatch):
    """NEF 且 Make=Nikon → WhiteLevel=15892 (Z5 NEF→Adobe DNG 实测)。"""
    monkeypatch.setattr(io.rawpy, "imread",
                        staticmethod(lambda p: _Stage3MockRaw()))
    img = _stage3_out(tmp_path, "x.nef", "NIKON CORPORATION")
    # mosaic=15892, black=0: white=15892 → 线性化到 65535 (即 1.0)
    # (ds=1 时 Stage3 只做同色平均, 每像素仅一个非零通道 → 用 max 比较)
    assert abs(float(img.max()) - 1.0) < 1e-6


def test_stage3_white_level_non_nikon_falls_back_to_rawpy(tmp_path, monkeypatch):
    """E3 回归: 非 Nikon 的非 DNG 输入不得套 15892, 回退 rawpy white_level。"""
    monkeypatch.setattr(io.rawpy, "imread",
                        staticmethod(lambda p: _Stage3MockRaw()))
    img = _stage3_out(tmp_path, "y.arw", "SONY")
    # white=16383: 15892*65535/16383 ≈ 63527.6 → round → 63528
    expected = round(15892 * 65535 / 16383) / 65535.0
    assert abs(float(img.max()) - expected) < 1e-6


def test_stage3_white_level_dng_uses_rawpy(tmp_path, monkeypatch):
    """DNG 输入 (即使 Make=Nikon): 用 rawpy white_level (与 DNG 文件实测一致)。"""
    monkeypatch.setattr(io.rawpy, "imread",
                        staticmethod(lambda p: _Stage3MockRaw()))
    img = _stage3_out(tmp_path, "z.dng", "NIKON CORPORATION")
    expected = round(15892 * 65535 / 16383) / 65535.0
    assert abs(float(img.max()) - expected) < 1e-6
