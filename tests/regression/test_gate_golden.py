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
    import generate_gate_goldens
    return gate_cases, generate_gate_goldens


def test_manifest_schema_and_files():
    gate_cases, generate_gate_goldens = _load_cases()
    assert _MANIFEST.exists(), "gate golden manifest 不存在"
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    # 只认合成 golden 的 schema id；读到 render/tools 的 raw 版直接判失败。
    assert manifest.get("schema") == generate_gate_goldens.SCHEMA, (
        f"schema 应为 {generate_gate_goldens.SCHEMA}（合成 golden），"
        f"实际为 {manifest.get('schema')!r}；若为 {generate_gate_goldens.RAW_SCHEMA} "
        f"则说明混入了 render/tools 的真实 RAW manifest，两套条目结构互不兼容")
    features = manifest.get("features", {})
    assert len(features) == 15, f"golden feature 数量 {len(features)} != 15"
    # reviewer 必须非空：golden 变更不得脱离复核静默合入。
    reviewer = str(manifest.get("reviewer") or "").strip()
    assert reviewer, "manifest.reviewer 为空：golden 基线必须由 reviewer 复核后合入"
    assert reviewer != "pending", "manifest.reviewer 仍为 pending，尚未完成复核"
    for feature, meta in features.items():
        assert meta.get("shape") and meta.get("dtype") and meta.get("sha256")
        assert (_GOLDEN_DIR / meta["file"]).exists(), f"golden 文件缺失: {feature}"


def test_baseline_files_match_manifest_sha256():
    """基线 .npy 文件自身 sha256 必须与 manifest 一致（防误替换/损坏）。"""
    gate_cases = _load_cases()[0]
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for feature, meta in manifest["features"].items():
        actual = gate_cases.sha256_file(_GOLDEN_DIR / meta["file"])
        assert actual == meta["sha256"], (
            f"{feature} 基线文件 sha256 与 manifest 不一致（manifest="
            f"{meta['sha256']} 实际={actual}），基线可能被误替换/损坏，"
            f"请重跑 generate_gate_goldens.py 并由 reviewer 复核")


def test_generator_check_mode_reports_no_drift():
    """--check 模式：当前实现与现有 manifest 应无漂移（退出码 0）。"""
    generate_gate_goldens = _load_cases()[1]
    rc = generate_gate_goldens.run_check(_GOLDEN_DIR)
    assert rc == 0, "当前实现与 gate golden manifest 存在漂移，--check 应返回 0"


def test_current_output_matches_goldens():
    gate_cases = _load_cases()[0]
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for feature, meta in manifest["features"].items():
        expected = np.load(_GOLDEN_DIR / meta["file"])
        current = np.asarray(gate_cases.compute(feature))
        assert current.shape == expected.shape, f"{feature} shape 变化"
        err = float(np.abs(current.astype(np.float64)
                           - expected.astype(np.float64)).max())
        assert err <= 1e-6, f"{feature} golden diff={err:.3e} > 1e-6"
