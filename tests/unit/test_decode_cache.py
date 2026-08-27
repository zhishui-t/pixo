"""T20: decode_cfa_half 磁盘缓存（冷启动预热）测试 + 解码缓存字节预算测试。"""
from __future__ import annotations

from collections import OrderedDict

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


# ---------------------------------------------------------------------------
# 字节预算 (PIXO_DECODE_CACHE_MB): 条目按数组 nbytes 计, 超预算淘汰最旧。
# 条目单位: (4,4,3) float32 = 192 B; 预算 1 KiB → 5 条 (960B) 达标。
# ---------------------------------------------------------------------------

_KIB_MB = str(1024 / 2**20)  # float 精确: 2**-10


def _entry():
    return np.zeros((4, 4, 3), dtype=np.float32)  # nbytes = 192


def test_budget_default_and_env(monkeypatch):
    monkeypatch.delenv("PIXO_DECODE_CACHE_MB", raising=False)
    assert io._decode_cache_budget_bytes() == 2048 * 2**20
    monkeypatch.setenv("PIXO_DECODE_CACHE_MB", "1")
    assert io._decode_cache_budget_bytes() == 2**20
    monkeypatch.setenv("PIXO_DECODE_CACHE_MB", "not-a-number")  # 非法回退缺省
    assert io._decode_cache_budget_bytes() == 2048 * 2**20
    monkeypatch.setenv("PIXO_DECODE_CACHE_MB", "0")            # 0 = 关闭
    assert io._decode_cache_budget_bytes() == 0


def test_small_budget_large_entry_triggers_eviction(monkeypatch):
    monkeypatch.setenv("PIXO_DECODE_CACHE_MB", _KIB_MB)
    cache = OrderedDict()
    for i in range(6):
        io._decode_cache_put(cache, (f"k{i}",), _entry())
    # 6 条 × 192B = 1152B > 1024B → 淘汰最旧 1 条后 960B 达标
    assert list(cache) == [(f"k{i}",) for i in range(1, 6)]


def test_budget_zero_disables_cache(monkeypatch):
    monkeypatch.setenv("PIXO_DECODE_CACHE_MB", "0")
    cache = OrderedDict()
    io._decode_cache_put(cache, ("k",), _entry())
    assert len(cache) == 0


def test_hit_does_not_get_evicted(monkeypatch):
    monkeypatch.setenv("PIXO_DECODE_CACHE_MB", _KIB_MB)
    cache = OrderedDict()
    for i in range(5):
        io._decode_cache_put(cache, (f"k{i}",), _entry())   # 960B ≤ 1024B
    assert len(cache) == 5
    # 命中 k0 刷新 recency → 再插入新条目时淘汰的是次旧 k1 而非热点 k0
    io._lru_get(cache, ("k0",))
    io._decode_cache_put(cache, ("new",), _entry())          # 1152B → 淘汰 1 条
    assert ("k0",) in cache
    assert ("k1",) not in cache
    assert len(cache) == 5


def test_single_oversized_entry_kept(monkeypatch):
    # 单条即超预算: 保留最新一条 (刚解码即丢会使缓存彻底失效)
    monkeypatch.setenv("PIXO_DECODE_CACHE_MB", str(1024 / 2**20))
    cache = OrderedDict()
    big = np.zeros((512, 512, 3), dtype=np.float32)  # 3 MiB ≫ 1 KiB
    io._decode_cache_put(cache, ("big",), big)
    assert len(cache) == 1 and ("big",) in cache

