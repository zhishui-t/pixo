"""P1-2 单元测试：金样本集 v0 基础设施。

覆盖：
  - manifest 加载/校验
  - 缺失字段检测
  - 哈希校验
  - 合成样本生成
  - 真实 RAW 缺失 skip
  - 回归比对带容差
  - save/load 往返
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pixo.harness.goldens import (
    GoldenManifest,
    GoldenSample,
    compare_measurement,
    compare_sample_with_run,
    generate_synthetic_sample,
    hash_file,
    is_sample_available,
    load_manifest,
    save_manifest,
    validate_manifest,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "pixo"
    / "harness"
    / "goldens"
    / "golden_manifest.json"
)


def test_manifest_load_and_validate():
    """内置 golden_manifest.json 可加载且合法。"""
    manifest = load_manifest(MANIFEST_PATH)
    assert isinstance(manifest, GoldenManifest)
    assert manifest.schema == "pixo-goldens-v0"
    assert len(manifest.samples) == 8
    assert all(s.photo_id for s in manifest.samples)
    assert any(s.synthetic for s in manifest.samples)
    assert any(not s.synthetic and not s.available for s in manifest.samples)


def test_manifest_missing_field_detected():
    """缺失 photo_id 等必需字段时校验返回错误。"""
    invalid = {
        "schema": "pixo-goldens-v0",
        "samples": [
            {
                "type": "exposure",
                "input": {"synthetic": True, "path": None},
                "expected_metrics": {},
                "version": "0.1",
                "available": True,
            }
        ],
    }
    errors = validate_manifest(invalid)
    assert any("photo_id" in e for e in errors)
    assert any("input.synthetic" not in e for e in errors)


def test_hash_file():
    """哈希校验可复现。"""
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(b"pixo-golden-v0")
        path = Path(fh.name)
    try:
        digest = hash_file(path)
        assert len(digest) == 64
        assert hash_file(path) == digest
    finally:
        path.unlink(missing_ok=True)


def test_synthetic_sample_generation_all_types():
    """四类合成样本都能生成 image/masks 且形状正确。"""
    for sample_type in ("exposure", "skin", "scene", "burst"):
        generated = generate_synthetic_sample(sample_type, seed=10, size=(64, 80))
        image = generated["image"]
        masks = generated["masks"]
        assert image.shape == (64, 80, 3)
        assert image.dtype == np.uint8
        assert set(masks) == {"face", "sky", "plant"}
        for mask in masks.values():
            assert mask.shape == (64, 80)
            assert mask.dtype == np.uint8
            assert set(np.unique(mask)).issubset({0, 255})


def test_real_raw_placeholder_skips():
    """真实 RAW 占位路径缺失时应 skip。"""
    manifest = load_manifest(MANIFEST_PATH)
    raw_sample = next(s for s in manifest.samples if not s.synthetic)
    assert raw_sample.available is False
    assert is_sample_available(raw_sample) is False
    result = compare_sample_with_run(raw_sample)
    assert result["skipped"] is True
    assert result["skip_reason"] == "raw_missing"


def test_synthetic_sample_compare_passes_with_tolerance():
    """合成样本运行后与 manifest 期望值比对应通过。"""
    manifest = load_manifest(MANIFEST_PATH)
    sample = next(s for s in manifest.samples if s.photo_id == "syn_exposure_001")
    result = compare_sample_with_run(sample, tolerance=0.05)
    assert result["skipped"] is False
    assert result["result"]["passed"] is True
    assert result["result"]["failed"] == []


def test_compare_measurement_detects_failure():
    """超出容差时 compare_measurement 应报告失败。"""
    actual = {"global": {"mean_luminance": 150.0}}
    expected = {"global.mean_luminance": 100.0}
    result = compare_measurement(actual, expected, tolerance=1.0)
    assert result["passed"] is False
    assert len(result["failed"]) == 1


def test_save_load_roundtrip(tmp_path):
    """save_manifest 与 load_manifest 往返一致。"""
    manifest = GoldenManifest(samples=[
        GoldenSample(
            photo_id="syn_roundtrip_001",
            type="scene",
            synthetic=True,
            seed=7,
            expected_metrics={"global.mean_luminance": 120.0},
            available=True,
        )
    ])
    path = save_manifest(manifest, tmp_path / "manifest.json")
    loaded = load_manifest(path)
    assert len(loaded.samples) == 1
    assert loaded.samples[0].photo_id == "syn_roundtrip_001"
    assert loaded.samples[0].seed == 7
