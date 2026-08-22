"""pixo.harness.regression —— 金样本/回归兼容入口。

复用 pixo.harness.goldens 与 render.tools.gate_golden 能力。
"""
from __future__ import annotations

from pixo.harness.goldens import (
    GOLDEN_MANIFEST_VERSION,
    GOLDEN_SCHEMA,
    GoldenManifest,
    GoldenSample,
    compare_measurement,
    compare_sample_with_run,
    generate_synthetic_sample,
    hash_file,
    is_sample_available,
    is_valid_manifest,
    load_manifest,
    save_manifest,
    validate_manifest,
)
from pixo.render.tools.gate_golden import (
    FEATURES,
    THRESHOLD_U8,
    THRESHOLD_U16,
)

__all__ = [
    "GOLDEN_SCHEMA",
    "GOLDEN_MANIFEST_VERSION",
    "GoldenManifest",
    "GoldenSample",
    "load_manifest",
    "save_manifest",
    "validate_manifest",
    "is_valid_manifest",
    "hash_file",
    "is_sample_available",
    "compare_measurement",
    "compare_sample_with_run",
    "generate_synthetic_sample",
    "FEATURES",
    "THRESHOLD_U8",
    "THRESHOLD_U16",
]
