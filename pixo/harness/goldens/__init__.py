"""pixo.harness.goldens —— 金样本集 v0 基础设施。

包含 manifest schema/加载/校验、合成样本生成、回归比对接口。
不依赖真实 RAW；真实路径缺失自动 skip。
"""
from __future__ import annotations

from .compare import (
    DEFAULT_TOLERANCE,
    compare_measurement,
    compare_sample,
    compare_sample_with_run,
    run_synthetic_sample,
)
from .manifest import (
    GOLDEN_MANIFEST_VERSION,
    GOLDEN_SCHEMA,
    SAMPLE_TYPES,
    GoldenManifest,
    GoldenSample,
    hash_file,
    is_sample_available,
    is_valid_manifest,
    load_manifest,
    save_manifest,
    validate_manifest,
    verify_input_hash,
)
from .samples import (
    build_builtin_samples,
    build_manifest_dict,
    compute_expected_metrics,
    generate_synthetic_sample,
)

__all__ = [
    "GOLDEN_SCHEMA",
    "GOLDEN_MANIFEST_VERSION",
    "SAMPLE_TYPES",
    "GoldenManifest",
    "GoldenSample",
    "validate_manifest",
    "is_valid_manifest",
    "load_manifest",
    "save_manifest",
    "hash_file",
    "is_sample_available",
    "verify_input_hash",
    "generate_synthetic_sample",
    "compute_expected_metrics",
    "build_builtin_samples",
    "build_manifest_dict",
    "compare_measurement",
    "compare_sample",
    "run_synthetic_sample",
    "compare_sample_with_run",
    "DEFAULT_TOLERANCE",
]
