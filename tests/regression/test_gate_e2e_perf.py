"""Gate: P1-7 真实 NEF + YOLOE/mock 端到端性能门禁。

无 RAW_PATH 时只跑合成图结构基准；有 RAW_PATH 时按预算断言：
  - 单张闭环 ≤30s；
  - 2 worker 批量 ≥2 张/分钟。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pixo.render.tools.bench_e2e_loop import (
    check_budgets,
    load_budget,
    run_batch_benchmark,
    run_single_benchmark,
)

pytestmark = pytest.mark.gate

_RAW_PATH = os.environ.get("RAW_PATH", "")
_DCP = (
    Path(__file__).resolve().parents[2]
    / "resources" / "dcp"
    / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
)


def test_synthetic_perf_structure_and_budgets():
    """合成图基准必须能在无 RAW 环境运行，且预算断言通过。"""
    single = run_single_benchmark(
        None, None, max_iterations=3, preview_long_edge=64
    )
    batch = run_batch_benchmark(
        None, None, workers=2, max_iterations=3, preview_long_edge=64
    )
    verdict = check_budgets(single, batch)

    assert verdict["pass"], verdict
    assert len(single["preview_render_times"]) == 3
    assert single["segment_calls"] == 1
    assert single["segment_total_s"] >= 0.0
    assert single["final_render_times"][0] >= 0.0
    assert batch["per_minute"] >= float(load_budget()["batch_per_minute_min"])


@pytest.mark.gate_e2e
@pytest.mark.skipif(not _RAW_PATH, reason="RAW_PATH not set")
def test_real_raw_e2e_loop_meets_budgets():
    """真实 RAW 单张/批量性能预算断言（需要 RAW_PATH）。"""
    from pixo.render.core.calibration import load_dcp

    if not _DCP.exists():
        pytest.fail(f"DCP 不存在: {_DCP}")

    prof = load_dcp(_DCP)
    single = run_single_benchmark(
        _RAW_PATH, prof, max_iterations=3, preview_long_edge=1024
    )
    batch = run_batch_benchmark(
        _RAW_PATH, prof, workers=2, max_iterations=3, preview_long_edge=1024
    )
    verdict = check_budgets(single, batch)
    budget = load_budget()
    assert verdict["single_ok"], (
        f"单张闭环超预算: {single['total_s']:.2f}s > "
        f"{budget['single_photo_max_seconds']}s"
    )
    assert verdict["batch_ok"], (
        f"批量吞吐不足: {batch['per_minute']:.2f} 张/分钟 < "
        f"{budget['batch_per_minute_min']}"
    )
