"""T20: decode_cfa_half 磁盘缓存（冷启动预热）测试。"""
from __future__ import annotations

import numpy as np
import pytest

import pixo.render._native as native
import pixo.render.core.io as io


class _FakeRaw:
    def __init__(self, h=8, w=8):
        self.raw_image_visible = np.arange(h * w, dtype=np.uint16).reshape(h, w)
        self.raw_pattern = np.array([[0, 1], [1, 2]], dtype=np.int32)
        self.color_desc = b"RGBG"
        self.black_level_per_channel = [64, 64, 64, 64]
        self.white_level = 16384


def _install_fake_native(monkeypatch, out):
    calls = []
    def fake_decode(cfa, pattern_r, pattern_g0, pattern_g1, pattern_b,
                    black, white_level, output_scale=1.0):
        calls.append(1)
        return out
    monkeypatch.setattr(native, "decode_cfa_half", fake_decode)
    return calls


def test_disk_cache_avoids_rawpy_unpack(monkeypatch, tmp_path):
    out = np.full((4, 4, 3), 0.5, dtype=np.float32)
    calls = _install_fake_native(monkeypatch, out)

    # 指向临时缓存目录，并清空内存缓存
    monkeypatch.setattr(io, "_DECODE_CACHE_DIR", tmp_path / "decode_cache")
    monkeypatch.setattr(io, "_DECODE_CACHE", {})

    raw_path = tmp_path / "fake.dng"
    raw_path.write_bytes(b"fake")

    raw = _FakeRaw()
    # 首次：走 native 并写盘
    r1 = io.decode_cfa_half(raw, raw_path=raw_path)
    assert np.array_equal(r1, out)
    assert len(calls) == 1

    # 模拟新进程：清空内存缓存，第二次应直接读盘，不触发 native
    monkeypatch.setattr(io, "_DECODE_CACHE", {})
    r2 = io.decode_cfa_half(raw, raw_path=raw_path)
    assert np.array_equal(r2, out)
    assert len(calls) == 1  # native 未再调用
