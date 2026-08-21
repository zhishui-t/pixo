"""pixo.render.tools.bench_e2e_loop —— P1-7 单张/批量端到端性能基准。

用途：
  - 真实 RAW（通过 --raw / 环境变量 RAW_PATH）时，测单张闭环 compose →
    segment → 3 轮 preview → FINAL_QC 的总耗时与分段耗时；
  - 批量用 2 个 worker 跑相同闭环，验证 ≥2 张/分钟预算；
  - 无 RAW 时可用合成图跑“结构完整性”基准（不阻塞门禁）。

预算读自 pixo/render/bench/gate_e2e_loop_budget.json，
默认：单张 ≤30s，批量 ≥2 张/分钟。
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from pixo.pipeline.loop import (
    RawRenderBackend,
    SinglePhotoLoop,
    SyntheticRenderBackend,
)
from pixo.vision import MockSegmenter, Segmenter

_BUDGET_PATH = (
    Path(__file__).resolve().parents[1] / "bench" / "gate_e2e_loop_budget.json"
)
_DCP_PATH = (
    Path(__file__).resolve().parents[1]
    / "profiles"
    / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
)


def load_budget(path: str | Path | None = None) -> dict[str, Any]:
    """读取性能预算 JSON；缺失时返回内置默认值。"""
    budget_file = Path(path) if path is not None else _BUDGET_PATH
    if budget_file.exists():
        return json.loads(budget_file.read_text(encoding="utf-8"))
    return {
        "schema": "pixo-e2e-loop-budget-v1",
        "single_photo_max_seconds": 30.0,
        "batch_per_minute_min": 2.0,
        "batch_workers": 2,
    }


def _synthetic_image(h: int = 64, w: int = 96) -> np.ndarray:
    """生成带亮块的合成图，避免全黑/全白影响 Decide。"""
    img = np.full((h, w, 3), 0.08, dtype=np.float32)
    img[12:44, 20:72] = 0.35
    return img


class TimedRenderBackend:
    """包装渲染后端，记录 preview / full 渲染耗时。"""

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.preview_times: list[float] = []
        self.full_times: list[float] = []

    def render_preview(self, params: dict[str, Any], long_edge: int = 512) -> np.ndarray:
        start = time.perf_counter()
        try:
            return self.backend.render_preview(params, long_edge=long_edge)
        finally:
            self.preview_times.append(time.perf_counter() - start)

    def render_full(self, params: dict[str, Any]) -> np.ndarray:
        start = time.perf_counter()
        try:
            return self.backend.render_full(params)
        finally:
            self.full_times.append(time.perf_counter() - start)


class TimedSegmenter:
    """包装分割器，记录每次 segment 耗时。"""

    def __init__(self, segmenter: Segmenter) -> None:
        self.segmenter = segmenter
        self.times: list[float] = []
        self.calls = 0

    def segment(self, image_rgb: np.ndarray, prompts: list[str]):
        start = time.perf_counter()
        try:
            return self.segmenter.segment(image_rgb, prompts)
        finally:
            self.times.append(time.perf_counter() - start)
            self.calls += 1


def _default_compose_params() -> dict[str, Any]:
    """默认构图参数：居中 4:3 裁剪，不旋转/翻转。"""
    return {
        "mode": "ratio",
        "ratio": "4:3",
        "center": [0.5, 0.5],
        "rotation": 0.0,
        "horizontal_flip": False,
        "vertical_flip": False,
    }


def run_single_benchmark(
    raw_path: str | Path | None = None,
    prof: Any | None = None,
    *,
    max_iterations: int = 3,
    preview_long_edge: int = 512,
    compose_params: dict[str, Any] | None = None,
    segmenter: Segmenter | None = None,
) -> dict[str, Any]:
    """跑一次单张闭环并返回各阶段耗时与结果摘要。

    有 raw_path + prof 时走真实 RAW；否则走合成图。
    """
    compose = _default_compose_params() if compose_params is None else compose_params
    seg = TimedSegmenter(segmenter or MockSegmenter())

    if raw_path is not None and prof is not None:
        backend = TimedRenderBackend(RawRenderBackend(raw_path, prof))
        image_rgb = None
        raw_arg = Path(raw_path)
    else:
        image = _synthetic_image()
        backend = TimedRenderBackend(SyntheticRenderBackend(image, stages=("compose", "tone")))
        image_rgb = image
        raw_arg = None

    loop = SinglePhotoLoop(
        render_backend=backend,
        segmenter=seg,
        max_iterations=max_iterations,
        preview_long_edge=preview_long_edge,
        prompts=["face", "sky", "plant"],
    )
    start = time.perf_counter()
    result = loop.run(
        "bench_single",
        raw_path=raw_arg,
        image_rgb=image_rgb,
        compose_params=compose,
    )
    total_s = time.perf_counter() - start

    preview_s = float(sum(backend.preview_times))
    segment_s = float(sum(seg.times))
    final_s = float(sum(backend.full_times))
    return {
        "total_s": total_s,
        "state": result.state,
        "iteration": result.iteration,
        "compose_s": float(backend.preview_times[0]) if backend.preview_times else 0.0,
        "preview_render_times": list(backend.preview_times),
        "preview_render_total_s": preview_s,
        "preview_iterations_s": preview_s + segment_s,
        "segment_times": list(seg.times),
        "segment_total_s": segment_s,
        "segment_calls": seg.calls,
        "final_qc_s": final_s,
        "final_render_times": list(backend.full_times),
        "final_render_total_s": final_s,
        "compose_params": compose,
        "segmenter": "mock",
        "raw_path": str(raw_arg) if raw_arg is not None else None,
        "preview_long_edge": preview_long_edge,
        "max_iterations": max_iterations,
    }


def run_batch_benchmark(
    raw_path: str | Path | None = None,
    prof: Any | None = None,
    *,
    workers: int = 2,
    max_iterations: int = 3,
    preview_long_edge: int = 512,
) -> dict[str, Any]:
    """用 ThreadPool 模拟 2 worker 批量，返回吞吐指标。

    单张预算达标时，2 个 worker 同时处理同一 RAW 文件可作为批量吞吐
    的可复现近似；无 RAW 时使用合成图，只验证结构/预算不阻塞。
    """
    if raw_path is not None and prof is not None:
        def _job(i: int) -> dict[str, Any]:
            return run_single_benchmark(
                raw_path, prof,
                max_iterations=max_iterations,
                preview_long_edge=preview_long_edge,
            )
    else:
        def _job(i: int) -> dict[str, Any]:
            return run_single_benchmark(
                None, None,
                max_iterations=max_iterations,
                preview_long_edge=preview_long_edge,
            )

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_job, range(workers)))
    elapsed_s = time.perf_counter() - start
    per_minute = workers * 60.0 / max(elapsed_s, 1e-9)
    return {
        "workers": workers,
        "elapsed_s": elapsed_s,
        "jobs": len(results),
        "per_minute": per_minute,
        "results": results,
    }


def check_budgets(bench: dict[str, Any], batch: dict[str, Any],
                  budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """按预算 JSON 判定单张与批量是否达标。"""
    b = budget or load_budget()
    single_max = float(b["single_photo_max_seconds"])
    batch_min = float(b["batch_per_minute_min"])
    single_ok = float(bench["total_s"]) <= single_max
    batch_ok = float(batch["per_minute"]) >= batch_min
    return {
        "pass": bool(single_ok and batch_ok),
        "single_ok": bool(single_ok),
        "batch_ok": bool(batch_ok),
        "budget": b,
        "single_seconds": float(bench["total_s"]),
        "batch_per_minute": float(batch["per_minute"]),
    }


def main() -> int:
    """命令行入口：--raw 可选，无 RAW 时跑合成图结构基准。"""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=None, help="真实 RAW/NEF 路径")
    parser.add_argument("--dcp", default=None, help="DCP profile 路径")
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--preview-long-edge", type=int, default=512)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    prof = None
    if args.raw:
        from pixo.render.core.calibration import load_dcp
        dcp = Path(args.dcp or _DCP_PATH)
        if not dcp.exists():
            print(f"[bench_e2e_loop] DCP 不存在: {dcp}")
            return 2
        prof = load_dcp(dcp)

    single = run_single_benchmark(
        args.raw, prof,
        max_iterations=args.max_iterations,
        preview_long_edge=args.preview_long_edge,
    )
    batch = run_batch_benchmark(
        args.raw, prof,
        workers=args.workers,
        max_iterations=args.max_iterations,
        preview_long_edge=args.preview_long_edge,
    )
    verdict = check_budgets(single, batch)
    print(json.dumps({
        "single": single,
        "batch": batch,
        "verdict": verdict,
    }, ensure_ascii=False, indent=2))
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
