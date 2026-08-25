"""t63 —— 评分器适配器仿射标定单测。

锚点精确性（t58 表 overall 行）、保序性、合成域高位+domain_hint、
实拍域中段无提示、Mock 路径无追溯字段。
"""
from __future__ import annotations

import pytest

from pixo.pipeline.batch import (
    AestheticScore,
    _PIXO_CAL_ANCHORS_RAW,
    _PixoScorerAdapter,
)


def _adapter_with_raw(raw: float):
    class _Fixed:
        def score(self, image_rgb):
            return {"overall": raw, "quality": raw * 0.5}

    return _PixoScorerAdapter(_Fixed())


def test_anchor_p25_maps_exactly_to_target_lo():
    lo_raw = _PIXO_CAL_ANCHORS_RAW["overall"][0]
    result = _adapter_with_raw(lo_raw).score(None)
    assert result.source == "pixo"
    assert result.overall == pytest.approx(2.0, abs=1e-6)
    assert result.raw_overall == pytest.approx(lo_raw, abs=1e-9)


def test_anchor_p75_maps_exactly_to_target_hi():
    hi_raw = _PIXO_CAL_ANCHORS_RAW["overall"][1]
    result = _adapter_with_raw(hi_raw).score(None)
    assert result.overall == pytest.approx(4.0, abs=1e-6)


def test_monotonic_preserved_under_affine():
    """保序：raw 更高者映射后仍不低于（严格更高直至硬界）。"""
    raws = [-0.90, -0.64, -0.47, -0.27, 0.0]
    outs = [_adapter_with_raw(r).score(None).overall for r in raws]
    assert outs[0] < outs[1] < outs[2] < outs[3]
    assert outs[4] == 5.0                      # 外延越界 → 硬界兜底
    assert outs == sorted(outs)


def test_synthetic_noise_lands_high_with_domain_hint():
    """合成噪声 raw=+0.32 → 映射落高位(硬界5)，并标记 domain_hint。"""
    result = _adapter_with_raw(0.32).score(None)
    assert result.overall == 5.0
    assert result.domain_hint == "synthetic_like"
    assert result.raw_overall == pytest.approx(0.32, abs=1e-9)


def test_real_photo_midband_without_hint():
    """实拍典型值(raw=-0.47≈p50) → 落契约中段，无域外提示。"""
    result = _adapter_with_raw(-0.47).score(None)
    assert result.overall == pytest.approx(2.915, abs=1e-3)
    assert result.domain_hint is None


def test_below_real_band_no_synthetic_hint():
    """低于下尾仍是实拍域内差片：不标 synthetic_like，映射触底 0。"""
    result = _adapter_with_raw(-2.0).score(None)
    assert result.overall == 0.0
    assert result.domain_hint is None


def test_mock_path_has_no_traceability_fields():
    from pixo.pipeline.batch import MockAestheticScorer

    img = __import__("numpy").zeros((8, 8, 3), dtype="uint8")
    result = MockAestheticScorer().score(img)
    assert isinstance(result, AestheticScore)
    assert result.raw_overall is None
    assert result.domain_hint is None
