"""pixo.render P1 全链路预览基准与回归 (v1.5 / t12)。

用法:
  python render/tools/bench_preview.py [--raw <NEF|DNG>] [--dcp <dcp>] \
      [--edges 1024,2048] [--runs 5] [--warmup 1] [--ab] \
      [--baseline render/bench/preview_full_baseline_v1.json] \
      [--compare old.json]

功能:
  - 对 long1024 / long2048 测量端到端、decode/stage 分段耗时（5 次中位数）。
  - 验证 8-bit / 16-bit 输出 dtype 与形状。
  - --ab: 计算 P1 预览 vs 全质量等比缩图的 A/B 差异
    （每通道 p50 ≤ 2/255、p99 ≤ 10/255）。
  - 输出 JSON 基线；--compare 与旧基线比较，任一档 total 慢 >20% 判失败。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pixo.render.api import Renderer
from pixo.render.pipeline.presets import build_default_pipeline

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DCP = (REPO_ROOT / "resources" / "dcp"
               / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")
DEFAULT_RAW = Path(r"K:\dsh-share\dng_verify\DSC_5607.dng")
DEFAULT_EDGES = [1024, 2048]
DEFAULT_RUNS = 5
DEFAULT_WARMUP = 1

# A/B 门禁 (8-bit 单位)
AB_P50_LIMIT = 2.0
AB_P99_LIMIT = 10.0

# v1.6 cold/hot 门禁 (ms)
HOT_LIMITS = {
    "1024": {"decode_ms": 300.0, "total_ms": 1000.0},
    "2048": {"decode_ms": 300.0, "total_ms": 2000.0},
}
COLD_LIMITS = {
    "1024": {"decode_ms": 1500.0, "total_ms": 2000.0},
    "2048": {"decode_ms": 1500.0, "total_ms": 3000.0},
}


def _clear_decode_caches() -> None:
    """清空解码/WB 缓存并切换到一个全新空磁盘缓存目录，用于 cold 口径测量。"""
    import tempfile
    import pixo.render.core.io as io

    io._DECODE_CACHE.clear()
    try:
        io._WB_CACHE.clear()
    except Exception:
        pass
    # 每个 cold 采样使用全新的空目录，避免命中上次落盘的磁盘缓存
    io._DECODE_CACHE_DIR = Path(tempfile.mkdtemp(prefix="render_cold_"))


def _parse_edges(text: str) -> List[int]:
    return [int(x) for x in text.replace(" ", "").split(",") if x]


def _percentile_abs_diff(a: np.ndarray, b: np.ndarray) -> Dict[str, Dict[str, float]]:
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.float64)
    out: Dict[str, Dict[str, float]] = {}
    names = ["r", "g", "b", "all"]
    channels = [d[..., 0], d[..., 1], d[..., 2], d.reshape(-1)]
    for name, ch in zip(names, channels):
        out[name] = {
            "p50": float(np.percentile(ch, 50)),
            "p99": float(np.percentile(ch, 99)),
            "max": float(np.max(ch)),
        }
    return out


def _ab_metrics(renderer: Renderer, raw_path: Path, long_edge: int) -> Dict[str, Any]:
    import cv2
    import rawpy

    # A/B 口径统一：A 和 B 都走同一 CFA half 解码 + 完整 12 stage。
    # A 先在原始 half 分辨率跑完整管线，再等比缩到 long_edge；
    # B 直接以 long_edge 跑完整管线。差异只来自“先缩后渲 vs 先渲后缩”。
    raw = rawpy.imread(str(raw_path))
    half_long = max(raw.sizes.height // 2, raw.sizes.width // 2)
    raw.close()
    a = renderer.render_preview_full(raw_path, long_edge=half_long, output_bps=8)
    h, w = a.shape[:2]
    scale = float(long_edge) / max(h, w)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    if (new_w, new_h) != (w, h):
        a = cv2.resize(a, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # B = P1 全链路预览 (CFA half decode + 完整 12 stage, 直接 long_edge)
    b = renderer.render_preview_full(raw_path, long_edge=long_edge, output_bps=8)

    if a.shape != b.shape:
        raise RuntimeError(f"A/B shape 不一致: A={a.shape}, B={b.shape}")
    metrics = _percentile_abs_diff(a, b)
    ok = all(
        metrics[ch]["p50"] <= AB_P50_LIMIT and metrics[ch]["p99"] <= AB_P99_LIMIT
        for ch in ("r", "g", "b")
    )
    return {
        "long_edge": int(long_edge),
        "shape": list(b.shape),
        "per_channel": metrics,
        "pass": bool(ok),
        "limits": {"p50": AB_P50_LIMIT, "p99": AB_P99_LIMIT},
    }


def _run_preview_once(renderer: Renderer, raw_path: Path, long_edge: int,
                      output_bps: int, params: Optional[dict] = None
                      ) -> Tuple[np.ndarray, Dict[str, float], Dict[str, float]]:
    """复刻 render_preview_full 逻辑并返回 (out, timings, stage_ms)。"""
    import cv2
    import rawpy

    from pixo.render.core.io import decode_cfa_half
    from pixo.render.pipeline.context import (DOMAIN_GAMMA_RGB, DOMAIN_LINEAR_CAM,
                                         StageContext)

    timings: Dict[str, float] = {}
    t0 = time.perf_counter()
    raw = rawpy.imread(str(raw_path))
    timings["imread_ms"] = (time.perf_counter() - t0) * 1000.0

    try:
        img = None
        t_decode0 = time.perf_counter()
        try:
            img = decode_cfa_half(raw, raw_path=raw_path)
        except Exception:
            img = None
        if img is None:
            rgb16 = raw.postprocess(
                use_camera_wb=False,
                output_bps=16,
                output_color=rawpy.ColorSpace.raw,
                no_auto_bright=True,
                half_size=True,
                user_wb=[1.0, 1.0, 1.0, 1.0],
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            )
            img = rgb16.astype(np.float32) / 65535.0
        timings["decode_ms"] = (time.perf_counter() - t_decode0) * 1000.0

        h, w = img.shape[:2]
        scale = float(long_edge) / max(h, w)
        t_resize0 = time.perf_counter()
        if abs(scale - 1.0) > 1e-6:
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        timings["resize_ms"] = (time.perf_counter() - t_resize0) * 1000.0

        pipe = build_default_pipeline(prof=renderer.profile, params=params or {})
        config = {
            "stages": dict(params or {}),
            "half_size": True,
            "decode_mode": "cfa_half_native",
            "long_edge": int(long_edge),
            "preview": True,
        }
        ctx = StageContext(raw_path, raw=raw, prof=renderer.profile,
                           config=config)
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["half_size"] = True
        try:
            from pixo.render.core.io import camera_neutral_wb_cached
            ctx.state["camera_wb"] = camera_neutral_wb_cached(raw, raw_path)
        except Exception:
            pass

        t_pipe0 = time.perf_counter()
        pipe.run(ctx)
        timings["pipeline_ms"] = (time.perf_counter() - t_pipe0) * 1000.0
        stage_ms = {r.name: r.time_s * 1000.0 for r in ctx.results}
        timings["stage_total_ms"] = sum(stage_ms.values())

        if ctx.domain != DOMAIN_GAMMA_RGB:
            raise RuntimeError(
                f"预览管线最终域不是 {DOMAIN_GAMMA_RGB} 而是 {ctx.domain}")
        out = ctx.image

        t_enc0 = time.perf_counter()
        if output_bps == 16:
            out = (np.clip(out, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
        else:
            out = (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        timings["encode_ms"] = (time.perf_counter() - t_enc0) * 1000.0
        timings["total_ms"] = (time.perf_counter() - t0) * 1000.0
        return out, timings, stage_ms
    finally:
        try:
            raw.close()
        except Exception:
            pass


def _collect_edge(renderer: Renderer, raw_path: Path, long_edge: int,
                  runs: int, warmup: int, mode: str = "hot") -> Dict[str, Any]:
    sample_totals: List[float] = []
    sample_stages: Dict[str, List[float]] = {}
    sample_decode: List[float] = []
    sample_imread: List[float] = []
    sample_stage_total: List[float] = []
    last_out8 = None
    last_out16 = None
    last_stage_ms = None

    for i in range(warmup + runs):
        if mode == "cold":
            # cold 口径：每次测量前清空解码/WB 缓存，模拟无缓存首帧
            _clear_decode_caches()
        out8, timings, stage_ms = _run_preview_once(
            renderer, raw_path, long_edge, output_bps=8)
        if mode == "cold":
            _clear_decode_caches()
        out16, _, _ = _run_preview_once(
            renderer, raw_path, long_edge, output_bps=16)
        if i >= warmup:
            sample_totals.append(timings["total_ms"])
            sample_decode.append(timings["decode_ms"])
            sample_imread.append(timings["imread_ms"])
            sample_stage_total.append(timings["stage_total_ms"])
            for name, ms in stage_ms.items():
                sample_stages.setdefault(name, []).append(ms)
        last_out8 = out8
        last_out16 = out16
        last_stage_ms = stage_ms

    def med(v: List[float]) -> float:
        return float(statistics.median(v))

    return {
        "long_edge": int(long_edge),
        "mode": mode,
        "shape8": list(last_out8.shape),
        "dtype8": str(last_out8.dtype),
        "shape16": list(last_out16.shape),
        "dtype16": str(last_out16.dtype),
        "runs": len(sample_totals),
        "imread_ms": med(sample_imread),
        "decode_ms": med(sample_decode),
        "stage_total_ms": med(sample_stage_total),
        "stage_ms": {name: med(v) for name, v in sorted(sample_stages.items())},
        "total_ms": med(sample_totals),
        "samples_total_ms": [round(x, 4) for x in sample_totals],
        "samples_decode_ms": [round(x, 4) for x in sample_decode],
        "last_stage_ms": last_stage_ms,
    }


def _make_report(renderer, raw_path, dcp_path, edges, runs, warmup,
                 ab: bool, mode: str = "hot") -> Dict[str, Any]:
    from pixo.render import _native as native

    edges_report = {}
    all_ok = True
    for edge in edges:
        rep = _collect_edge(renderer, raw_path, edge, runs, warmup, mode=mode)
        if ab:
            rep["ab"] = _ab_metrics(renderer, raw_path, edge)
            all_ok = all_ok and bool(rep["ab"]["pass"])
        # v1.6 门禁：hot/cold 分别按 total/decode 验收
        limits_map = HOT_LIMITS if mode == "hot" else COLD_LIMITS
        rep["limits"] = limits_map.get(str(edge), None)
        edges_report[str(edge)] = rep
        if rep["limits"]:
            ok_decode = rep["decode_ms"] <= rep["limits"]["decode_ms"]
            ok_total = rep["total_ms"] <= rep["limits"]["total_ms"]
            rep["pass_perf"] = bool(ok_decode and ok_total)
            all_ok = all_ok and bool(rep["pass_perf"])
        else:
            rep["pass_perf"] = None
    return {
        "schema": "render-bench-preview-v1.6",
        "raw": str(raw_path),
        "dcp": str(dcp_path),
        "native_available": bool(native.available()),
        "runs": runs,
        "warmup": warmup,
        "mode": mode,
        "edges": edges_report,
        "pass": all_ok,
    }


def _print_report(report: Dict[str, Any]) -> None:
    print(f"raw={report['raw']}")
    print(f"native_available={report['native_available']}  pass={report['pass']}")
    for edge, rep in report["edges"].items():
        print(f"\n=== long{edge} ===")
        print(f"  size8={rep['shape8']} dtype8={rep['dtype8']} "
              f"size16={rep['shape16']} dtype16={rep['dtype16']}")
        print(f"  decode={rep['decode_ms']:.1f}ms  stage_total={rep['stage_total_ms']:.1f}ms  "
              f"total={rep['total_ms']:.1f}ms  pass_perf={rep['pass_perf']}")
        for name, ms in rep["stage_ms"].items():
            print(f"    {name:<14s} {ms:8.2f}ms")
        if "ab" in rep:
            ab = rep["ab"]
            print(f"  A/B pass={ab['pass']}  limits p50<={ab['limits']['p50']} "
                  f"p99<={ab['limits']['p99']}")
            for ch, m in ab["per_channel"].items():
                print(f"    {ch}: p50={m['p50']:.3f} p99={m['p99']:.3f} max={m['max']:.3f}")


def _compare(report: Dict[str, Any], old_path: Path) -> int:
    old = json.loads(Path(old_path).read_text(encoding="utf-8"))
    old_edges = old.get("edges", {})
    failed = False
    print(f"{'edge':<8s} {'old_total':>10s} {'new_total':>10s} {'change%':>8s} verdict")
    for edge, rep in report["edges"].items():
        old_rep = old_edges.get(str(edge))
        if old_rep is None:
            print(f"{edge:<8d} {'-':>10s} {rep['total_ms']:>10.2f} {'-':>8s} skip")
            continue
        old_ms = float(old_rep["total_ms"])
        new_ms = float(rep["total_ms"])
        change = (new_ms - old_ms) / old_ms * 100.0 if old_ms else 0.0
        ok = new_ms <= old_ms * 1.20
        failed = failed or (not ok)
        print(f"{edge:<8d} {old_ms:>10.2f} {new_ms:>10.2f} "
              f"{change:>+7.1f}%  {'PASS' if ok else 'FAIL'}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(DEFAULT_RAW), help="RAW 文件路径")
    ap.add_argument("--dcp", default=str(DEFAULT_DCP), help="DCP 路径")
    ap.add_argument("--edges", default=",".join(str(x) for x in DEFAULT_EDGES),
                    help="逗号分隔长边列表 (默认 1024,2048)")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    ap.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    ap.add_argument("--mode", default="both", choices=["cold", "hot", "both"],
                    help="cold=清缓存冷启动, hot=缓存热启动, both=双口径 (默认 both)")
    ap.add_argument("--ab", action="store_true", help="执行 A/B 差异验收")
    ap.add_argument("--baseline", default=None, help="保存基线 JSON")
    ap.add_argument("--compare", default=None, help="与旧基线比较 total 慢 >20% 返回非零")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    raw_path = Path(args.raw)
    if not raw_path.exists():
        print(f"[bench_preview] RAW 不存在: {raw_path}", file=sys.stderr)
        return 2
    dcp_path = Path(args.dcp)
    if not dcp_path.exists():
        print(f"[bench_preview] DCP 不存在: {dcp_path}", file=sys.stderr)
        return 2

    renderer = Renderer(dcp_path)
    edges = _parse_edges(args.edges)
    overall_pass = True

    def run_one(mode: str, baseline: Path | None):
        nonlocal overall_pass
        warmup = args.warmup if mode == "hot" else 0
        report = _make_report(renderer, raw_path, dcp_path, edges,
                              args.runs, warmup, args.ab, mode=mode)
        print(f"\n########## mode={mode} ##########")
        _print_report(report)
        if baseline is not None:
            baseline.parent.mkdir(parents=True, exist_ok=True)
            baseline.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            print(f"[bench_preview] {mode} baseline -> {baseline}")
        overall_pass = overall_pass and bool(report["pass"])

    if args.mode in ("hot", "both"):
        base = Path(args.baseline) if args.baseline else None
        hot_base = None
        if base is not None:
            hot_base = (base.with_name(base.stem + "_hot" + base.suffix)
                        if args.mode == "both" else base)
        run_one("hot", hot_base)

    if args.mode in ("cold", "both"):
        base = Path(args.baseline) if args.baseline else None
        cold_base = None
        if base is not None:
            cold_base = (base.with_name(base.stem + "_cold" + base.suffix)
                         if args.mode == "both" else base)
        run_one("cold", cold_base)

    if args.compare:
        # 与旧基线比较：仅对 hot 口径做 total 慢 >20% 检查
        if args.mode in ("hot", "both"):
            report = json.loads(
                (Path(args.baseline).with_name(
                    Path(args.baseline).stem + "_hot" + Path(args.baseline).suffix)
                 if args.mode == "both" and args.baseline
                 else Path(args.baseline)).read_text(encoding="utf-8"))
            return _compare(report, Path(args.compare))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
