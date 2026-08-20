"""color_probe 色彩测量纯函数测试 (合成数据, 无 RAW/DCP 依赖)。"""
from __future__ import annotations
import numpy as np

from rawlab.tools.color_probe import (
    full_stats,
    grid_stats,
    hue_sector_stats,
    luma_band_stats,
    measure_photo,
    summarize_suggestions,
)


def _img(seed=0, size=64):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (size, size, 3), dtype=np.uint8)


def test_identity_measure_photo():
    img = _img(1)
    m = measure_photo(img, img, stem="DSC_X", wb_b=1.41)
    assert m["full"]["da"] == 0.0 and m["full"]["db"] == 0.0
    assert m["skin"] is not None and m["skin"]["da"] == 0.0
    assert len(m["hue_sectors"]) == 12
    assert len(m["luma_bands"]) == 4


def test_hue_sector_stats_has_diff():
    ours = _img(2)
    tgt = np.clip(ours.astype(np.int16) + [20, -10, 0], 0, 255).astype(np.uint8)
    sectors = [s for s in hue_sector_stats(ours, tgt) if s is not None]
    assert sectors and any(abs(s["da"]) > 1.0 or abs(s["db"]) > 1.0 for s in sectors)


def test_grid_stats_top_sorted():
    ours = _img(3)
    tgt = np.clip(ours.astype(np.int16) + [30, 0, 0], 0, 255).astype(np.uint8)
    rows = grid_stats(ours, tgt, n=4)
    assert rows and abs(rows[0]["dR"]) >= abs(rows[-1]["dR"])


def test_summarize_suggestions_buckets():
    m = [{"stem": "A", "wb_b": 1.41, "full": full_stats(_img(4), _img(4)),
          "skin": full_stats(_img(4), _img(4))},
         {"stem": "B", "wb_b": 2.38, "full": full_stats(_img(5), _img(5)),
          "skin": None}]
    s = summarize_suggestions(m)
    assert "day_warm" in s and s["day_warm"]["stems"] == ["A"]
    assert "warm_extreme" in s and s["warm_extreme"]["stems"] == ["B"]
