"""Gate: L3 端到端 A-B（预览 vs 全质量，长边 1024）。

RAW_PATH 缺失时按 FUNCTION_GATE_SPEC §10 显式豁免（skip）；
设置 RAW_PATH 后本用例阻塞合并。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.gate, pytest.mark.gate_e2e]

_RAW_PATH = os.environ.get("RAW_PATH", "")
_DCP = Path(__file__).resolve().parents[2] / "profiles" / \
    "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"


@pytest.mark.skipif(not _RAW_PATH, reason="RAW_PATH not set")
def test_preview_full_ab_1024_meets_limits():
    from render.api import Renderer
    from render.tools.bench_preview import _ab_metrics

    renderer = Renderer(_DCP)
    result = _ab_metrics(renderer, Path(_RAW_PATH), long_edge=1024)
    assert result["pass"], (
        f"预览 A/B 门禁未达标: {result['per_channel']} (limits={result['limits']})")
