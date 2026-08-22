"""Phase E 补齐文件：scripts/configs/docs/harness/decide.rules 可导入与存在性。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def test_harness_wrappers_importable():
    from pixo.harness import batch_render, failure_injection, metrics, regression

    assert hasattr(batch_render, "BatchPipeline")
    assert hasattr(metrics, "VisionMeasure")
    assert hasattr(regression, "GoldenManifest")
    assert callable(failure_injection.inject_segmenter_failure)


def test_decide_rules_mirror_and_configs_exist():
    config_rules = ROOT / "configs" / "rules"
    package_rules = SRC / "pixo" / "decide" / "rules"

    for name in ("exposure_rule_001.yaml", "highlight_protect_rule_002.yaml"):
        assert (config_rules / name).exists()
        assert (package_rules / name).exists()


def test_phase_e_docs_exist():
    for name in ("architecture.md", "tech_debt.md", "changelog.md"):
        assert (ROOT / "docs" / name).exists()


def test_phase_e_scripts_exist():
    for name in ("render_debug.py", "vision_debug.py", "batch_process.py"):
        assert (ROOT / "scripts" / name).exists()
