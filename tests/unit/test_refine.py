"""RefineStage 饱和保护回归 (烟花橙黄反馈轮).

覆盖:
  - _sat_protection: 低饱和全处理 / 高饱和全保护, 单调平滑
  - _highlight_desat: 高亮近中性去色, 高亮高饱和色基本保留
  - _chroma_denoise_small: 小面积高饱和亮斑不被降采样模糊吞掉
"""
from __future__ import annotations

import cv2
import numpy as np

from pixo.render.modules.refine import (
    RefineStage,
    _check_warm_hue_curve,
    _check_warm_sat_curve,
    _check_warm_sat_spot,
    apply_warm_sat_gamma,
)


def _gray(img):
    return RefineStage._gray(img)


def test_sat_protection_endpoints():
    neutral = np.full((4, 4, 3), 0.8, np.float32)
    sat = np.zeros((4, 4, 3), np.float32)
    sat[..., 0], sat[..., 1], sat[..., 2] = 1.0, 0.3, 0.0
    p_neu = RefineStage._sat_protection(neutral)
    p_sat = RefineStage._sat_protection(sat)
    assert float(p_neu.max()) < 1e-3
    assert float(p_sat.min()) > 1.0 - 1e-3


def test_highlight_desat_preserves_saturated_warm_highlight():
    img = np.zeros((4, 4, 3), np.float32)
    img[0, 0] = (0.84, 0.78, 0.80)   # 高亮近中性: S≈0.07
    img[1, 1] = (1.00, 0.45, 0.05)   # 高亮橙: S 高
    gray = _gray(img)
    out = RefineStage._highlight_desat(img, 1.0, gray)

    # 近中性高光被拉向灰 (三个通道差变小)
    n0 = float(np.max(img[0, 0]) - np.min(img[0, 0]))
    n1 = float(np.max(out[0, 0]) - np.min(out[0, 0]))
    assert n1 < n0 * 0.55
    # 高饱和橙基本保留 (去色前后通道差损失 <20%)
    s0 = float(np.max(img[1, 1]) - np.min(img[1, 1]))
    s1 = float(np.max(out[1, 1]) - np.min(out[1, 1]))
    assert s1 > s0 * 0.8


def test_chroma_denoise_preserves_small_bright_spots():
    img = np.full((32, 32, 3), 0.05, np.float32)
    img[14:18, 14:18] = (1.0, 0.45, 0.05)   # 2% 面积高亮橙斑
    gray = _gray(img)
    out = RefineStage._chroma_denoise_small(img, 1.5, gray)

    def hsv_s(patch):
        u8 = (np.clip(patch, 0, 1) * 255 + 0.5).astype(np.uint8)
        return float(cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)[..., 1].mean())

    s_in = hsv_s(img[15:17, 15:17])
    s_out = hsv_s(out[15:17, 15:17])
    # 小亮斑色度保留 ≥70% (旧无条件替换会与暗背景平均, 只剩 ~10-20%)
    assert s_out >= s_in * 0.7
    # 背景仍基本中性 (无偏色)
    assert float(np.max(np.abs(out[:5, :5] - gray[:5, :5, np.newaxis]))) < 0.05


# ---------------------------------------------------------------------------
# A1 显示域暖色饱和补强 (gamma HSV, wb_B + 覆盖率门控)
# ---------------------------------------------------------------------------

def _warm_img(size=256, patch=None, rgb=(0.95, 0.42, 0.05)):
    """深灰底 + 暖色块 (可指定 [y0,y1,x0,x1]); 返回 float RGB 0..1。"""
    img = np.full((size, size, 3), 0.05, np.float32)
    if patch is not None:
        y0, y1, x0, x1 = patch
        img[y0:y1, x0:x1] = rgb
    return img


def test_warm_sat_gamma_identity_without_params():
    img = _warm_img()
    wb = np.array([1.4, 1.0, 1.41], np.float32)
    assert np.array_equal(apply_warm_sat_gamma(img, wb), img)


def test_warm_sat_gamma_broad_curve():
    img = _warm_img(patch=(0, 256, 0, 256))          # 全覆盖暖色
    wb = np.array([1.4, 1.0, 1.41], np.float32)       # wb_B=1.41 → gain .5
    curve = [[1.0, 0.0], [1.34, 0.2], [1.40, 0.5], [1.50, 0.0]]
    out = apply_warm_sat_gamma(img, wb, curve=curve)
    s0 = float(cv2.cvtColor((img * 255 + .5).astype(np.uint8),
                            cv2.COLOR_RGB2HSV)[..., 1].mean())
    s1 = float(cv2.cvtColor((np.clip(out, 0, 1) * 255 + .5).astype(np.uint8),
                            cv2.COLOR_RGB2HSV)[..., 1].mean())
    assert s1 > s0 + 5.0 and s1 <= 255.0


def test_warm_sat_gamma_spot_window_and_anchor_safe():
    # 128x128 里 20x20 暖斑: 覆盖率 0.024 偏大; 换 16x16 → 0.0156 命中 spot
    img = _warm_img(size=128, patch=(56, 72, 56, 72))
    wb_hit = np.array([1.0, 1.0, 1.78], np.float32)
    spot = [[1.75, 1.80, 0.7]]
    out_hit = apply_warm_sat_gamma(img, wb_hit, spot_windows=spot)
    assert float(np.abs(out_hit - img).max()) > 1e-3
    # wb_B 窗口外 → 不变
    wb_miss = np.array([1.0, 1.0, 1.60], np.float32)
    assert np.array_equal(apply_warm_sat_gamma(img, wb_miss, spot_windows=spot), img)
    # 覆盖率过低 (5236 锚点) → 不变
    tiny = _warm_img(size=256, patch=(120, 124, 120, 124))   # 16px/65536 < 0.001
    assert np.array_equal(apply_warm_sat_gamma(tiny, wb_hit, spot_windows=spot), tiny)


def test_warm_sat_gamma_validation():
    assert _check_warm_sat_curve([[1.0, 0.0], [1.5, 0.5]]).shape == (2, 2)
    assert _check_warm_sat_spot([[1.7, 1.8, 0.7]]).shape == (1, 3)
    import pytest as _pytest
    with _pytest.raises(ValueError):
        _check_warm_sat_curve([[1.5, 0.5], [1.0, 0.0]])
    with _pytest.raises(ValueError):
        _check_warm_sat_curve([[1.0, 1.5], [1.5, 0.5]])
    with _pytest.raises(ValueError):
        _check_warm_sat_spot([[1.8, 1.7, 0.5]])


def test_warm_hue_curve_shift_and_validation():
    img = _warm_img(patch=(0, 256, 0, 256))
    wb = np.array([1.0, 1.0, 1.41], np.float32)
    hue_curve = [[1.0, 0.0], [1.4, 3.0], [2.0, 0.0]]
    out = apply_warm_sat_gamma(img, wb, hue_curve=hue_curve)
    def hue_med(x):
        u8 = (np.clip(x, 0, 1) * 255 + .5).astype(np.uint8)
        return float(np.median(cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)[..., 0]))
    h0, h1 = hue_med(img), hue_med(out)
    assert abs(h1 - h0) > 1.5 and abs(h1 - h0) < 5.0     # 约 +3°, 平滑滚降
    assert _check_warm_hue_curve(hue_curve).shape == (3, 2)
    import pytest as _pytest
    with _pytest.raises(ValueError):
        _check_warm_hue_curve([[1.0, 0.0], [0.5, 3.0]])
    with _pytest.raises(ValueError):
        _check_warm_hue_curve([[1.0, 0.0], [2.0, 20.0]])
