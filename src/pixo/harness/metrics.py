"""pixo.harness.metrics —— 测量/性能指标兼容入口。

复用 pixo.vision 测量与 render.tools.bench_preview 的 A/B 指标。
"""
from __future__ import annotations

from pixo.render.tools.bench_preview import _ab_metrics, _percentile_abs_diff
from pixo.vision import (
    VisionMeasure,
    measure_global,
    measure_haze,
    measure_motion_blur,
    measure_region,
    measure_sharpness,
    measure_zone_exposure,
)

__all__ = [
    "VisionMeasure",
    "measure_global",
    "measure_region",
    "measure_sharpness",
    "measure_motion_blur",
    "measure_haze",
    "measure_zone_exposure",
    "_percentile_abs_diff",
    "_ab_metrics",
]
