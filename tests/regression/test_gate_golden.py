"""Gate: L2 golden 回归（FUNCTION_GATE_SPEC §6）。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gate

_GOLDEN_DIR = Path(__file__).resolve().parent / "goldens" / "gate"
_MANIFEST = _GOLDEN_DIR / "manifest.json"


def _load_cases():
    import sys
    if str(_GOLDEN_DIR.parent) not in sys.path:
        sys.path.insert(0, str(_GOLDEN_DIR.parent))
    import gate_cases
    return gate_cases


def test_manifest_schema_and_files():
    assert _MANIFEST.exists(), "gate golden manifest 不存在"
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest.get("schema") == "render-gate-golden-v1"
    features = manifest.get("features", {})
    assert len(features) == 12, f"golden feature 数量 {len(features)} != 12"
    for feature, meta in features.items():
        assert meta.get("shape") and meta.get("dtype") and meta.get("sha256")
        assert (_GOLDEN_DIR / meta["file"]).exists(), f"golden 文件缺失: {feature}"


def test_current_output_matches_goldens():
    gate_cases = _load_cases()
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for feature, meta in manifest["features"].items():
        expected = np.load(_GOLDEN_DIR / meta["file"])
        current = np.asarray(gate_cases.compute(feature))
        assert current.shape == expected.shape, f"{feature} shape 变化"
        err = float(np.abs(current.astype(np.float64)
                           - expected.astype(np.float64)).max())
        assert err <= 1e-6, f"{feature} golden diff={err:.3e} > 1e-6"
