"""观感增强纯函数测试 (clarity / dehaze)。

覆盖 (增强层验收):
  - clarity: strength=0 恒等; 中频对比提升; 增益钳位无晕边 (输出 0..1)
  - dehaze: strength=0 恒等; 合成雾图 (I = J*t + A*(1-t)) 恢复接近 J;
    输出值域 0..1

运行: python -m pytest tests/test_enhance.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.enhance import clarity, dehaze


def test_clarity_zero_strength_identity():
    x = np.random.default_rng(0).random((32, 32, 3)).astype(np.float32)
    assert np.array_equal(clarity(x, strength=0.0), x)


def test_clarity_increases_mid_frequency_contrast():
    # 低频背景 + 中频纹理: clarity 后局部对比应增大
    rng = np.random.default_rng(1)
    y, x_ = np.mgrid[0:64, 0:64]
    base = 0.5 + 0.2 * np.sin(x_ / 32.0)[:, :, None]  # 大尺度 (64,64,1)
    tex = 0.05 * np.sin(x_ / 2.0)[:, :, None]          # 中频纹理 (64,64,1)
    img = np.clip(np.repeat(base + tex, 3, axis=2), 0, 1).astype(np.float32)
    out = clarity(img, strength=0.5)
    from pixo.render.core.enhance import _gray
    before = float(np.abs(np.diff(_gray(img), axis=1)).mean())
    after = float(np.abs(np.diff(_gray(out), axis=1)).mean())
    assert after > before, f"clarity 未提升局部对比: {before:.4f} -> {after:.4f}"


def test_clarity_output_in_range_no_halo_blowup():
    rng = np.random.default_rng(2)
    img = np.clip(rng.random((64, 64, 3)), 0, 1).astype(np.float32)
    out = clarity(img, strength=0.9)
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0


def test_dehaze_zero_strength_identity():
    x = np.random.default_rng(3).random((32, 32, 3)).astype(np.float32)
    assert np.array_equal(dehaze(x, strength=0.0), x)


def test_dehaze_recovers_synthetic_haze():
    # 合成雾图: I = J*t + A*(1-t), t=0.5, A=0.85。
    # J 需含暗像素 (暗通道先验假设无雾图暗通道≈0):
    # 25% 像素压暗到 <0.15, 保证 7x7 窗口内存在暗像素。
    rng = np.random.default_rng(4)
    J = np.clip(rng.random((64, 64, 3)), 0.02, 1.0).astype(np.float32)
    dark_pix = rng.random((64, 64)) < 0.25
    J[dark_pix] *= 0.1
    t = 0.5
    A = 0.85
    I = J * t + A * (1.0 - t)
    out = dehaze(I, strength=1.0, radius=3)
    err_in = float(np.abs(I - J).mean())
    err_out = float(np.abs(out - J).mean())
    assert err_out < err_in, f"dehaze 未降低雾霾误差: {err_in:.4f} -> {err_out:.4f}"


def test_dehaze_output_in_range():
    rng = np.random.default_rng(5)
    img = np.clip(rng.random((64, 64, 3)), 0, 1).astype(np.float32)
    out = dehaze(img, strength=0.8, radius=5)
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0
