"""t57 —— colorcal 四向方向语义合成小图单测。

固化 t56 复审的四向方向探针：vibrance/saturation 正负增益下，
colorfulness 与 mean_S 的变化方向必须与规则语义一致，
防止 colorcal 未来实现回归时方向翻转（无需 RAW，纯合成图）。
"""
from __future__ import annotations

import numpy as np

from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext


def _synthetic_image() -> np.ndarray:
    """确定性合成图：色相扫掠渐变 + 中等饱和度斑块（float32 [0,1]）。"""
    h, w = 48, 64
    yy, xx = np.mgrid[0:h, 0:w]
    u = xx / max(w - 1, 1)
    v = yy / max(h - 1, 1)
    r = np.clip(0.35 + 0.45 * u, 0.0, 1.0)
    g = np.clip(0.30 + 0.30 * v, 0.0, 1.0)
    b = np.clip(0.55 - 0.35 * u * v, 0.0, 1.0)
    img = np.stack([r, g, b], axis=-1).astype(np.float32)
    noise = np.random.default_rng(20260825).uniform(-0.02, 0.02, img.shape)
    return np.clip(img + noise.astype(np.float32), 0.0, 1.0)


def _apply(params: dict) -> np.ndarray:
    stage = ColorCalStage()
    ctx = StageContext("synthetic.NEF", config={"stages": {"colorcal": dict(params)}})
    ctx.set_image(_synthetic_image(), DOMAIN_GAMMA_RGB)
    stage.run(ctx)
    return ctx.image


def _colorfulness(rgb: np.ndarray) -> float:
    """Hasler-Süsstrunk 彩度指标（域无关的方向性足够）。"""
    rg = rgb[..., 0] - rgb[..., 1]
    yb = 0.5 * (rgb[..., 0] + rgb[..., 1]) - rgb[..., 2]
    return float(
        np.sqrt(rg.std() ** 2 + yb.std() ** 2)
        + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )


def _mean_s(rgb: np.ndarray) -> float:
    """HSV 语义平均饱和度 S=(max-min)/max。"""
    mx = rgb.max(axis=-1)
    mn = rgb.min(axis=-1)
    s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return float(s.mean())


BASELINE_IMG = None
BASELINE_CF = None
BASELINE_MS = None


def _baseline():
    global BASELINE_IMG, BASELINE_CF, BASELINE_MS
    if BASELINE_IMG is None:
        BASELINE_IMG = _apply({})
        BASELINE_CF = _colorfulness(BASELINE_IMG)
        BASELINE_MS = _mean_s(BASELINE_IMG)
    return BASELINE_CF, BASELINE_MS


MARGIN = 1e-4


def test_zero_gain_matches_baseline_identity():
    cf, ms = _baseline()
    out = _apply({"saturation": 0.0, "vibrance": 0.0})
    assert abs(_colorfulness(out) - cf) < MARGIN
    assert abs(_mean_s(out) - ms) < MARGIN


def test_positive_vibrance_raises_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"vibrance": 0.4})
    assert _colorfulness(out) > cf + MARGIN
    assert _mean_s(out) > ms + MARGIN


def test_negative_vibrance_lowers_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"vibrance": -0.4})
    assert _colorfulness(out) < cf - MARGIN
    assert _mean_s(out) < ms - MARGIN


def test_positive_saturation_raises_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"saturation": 0.4})
    assert _colorfulness(out) > cf + MARGIN
    assert _mean_s(out) > ms + MARGIN


def test_negative_saturation_lowers_chroma_direction():
    cf, ms = _baseline()
    out = _apply({"saturation": -0.4})
    assert _colorfulness(out) < cf - MARGIN
    assert _mean_s(out) < ms - MARGIN
