"""pixo.render pipeline 性能基准 (M5 / T5)。

用法:
  python render/tools/bench_pipeline.py [--nef <NEF>] [--dcp <dcp>] \
      [--runs 5] [--warmup 1] [--size 2020x3032] [--hot] \
      [--baseline render/bench/native_baseline_v1.json] \
      [--compare old.json]

说明:
  - 默认合成图模式: 使用最小 MockProf + exposure/whitebalance 关闭,
    在 2020x3032x3 float32 线性相机图上跑默认管线。
  - --nef 模式: 使用真实 RAW (half_size=True), 计时包含 rawpy 解码;
    需要可用的 DCP (--dcp 或本机默认 Adobe DCP)。
  - 每个 stage 预热 1 次后取 5 次中位数 (可配 --warmup/--runs)。
  - 输出每 stage 中位耗时、总耗时、native_available, 并保存 JSON。
  - --compare 与旧基线比较, 任一 stage 慢 >20% 时返回退出码 1。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pixo.render.pipeline.context import DOMAIN_LINEAR_CAM, StageContext
from pixo.render.pipeline.presets import build_default_pipeline

DEFAULT_SIZE = (2020, 3032)  # (H, W), half_size 真实 NEF 常用尺寸
DEFAULT_RUNS = 5
DEFAULT_WARMUP = 1
DEFAULT_DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
               r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard v2.dcp")
HOT_PARAMS = {
    "huesat": {"warm_highlight_sat": 2.0, "warm_sat_spot_scale": 2.0},
    "colorcal": {"saturation": 0.2, "vibrance": 0.2,
                 "neutral_mode": "adaptive", "skin_protect": 0.7},
    "refine": {"sharpen": 0.35, "chroma_denoise": 0.8,
               "highlight_desat": 0.6},
}


class MockProf:
    """合成图模式的最小 DcpProfile 替身 (恒等 ColorMatrix)。

    字段与 render/tests/test_pipeline.py 的 MockProf 保持一致, 使默认管线
    在 exposure/whitebalance 关闭时仍可完整运行。
    """

    def __init__(self):
        self.color_matrix1 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.color_matrix2 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.forward_matrix1 = None
        self.forward_matrix2 = None
        self.camera_calibration1 = None
        self.camera_calibration2 = None
        self.calibration_illuminant1 = 17
        self.calibration_illuminant2 = 21
        self.baseline_exposure_offset = 0.0
        self.profile_tone_curve = None


def parse_size(text: str) -> Tuple[int, int]:
    text = text.replace(",", "x").replace("X", "x")
    parts = text.split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"尺寸须为 HxW, 实际 {text!r}")
    h, w = int(parts[0]), int(parts[1])
    if h <= 0 or w <= 0:
        raise argparse.ArgumentTypeError("尺寸必须为正数")
    return h, w


def _synthetic_params(hot: bool) -> Dict[str, Dict[str, Any]]:
    params: Dict[str, Dict[str, Any]] = {
        "exposure": {"mode": "off"},
        "whitebalance": {"mode": "off"},
        "skin": {"enabled": False},
    }
    if hot:
        for stage, overrides in HOT_PARAMS.items():
            params.setdefault(stage, {}).update(overrides)
    return params


def _build_synthetic_pipeline(hot: bool):
    prof = MockProf()
    params = _synthetic_params(hot)
    pipe = build_default_pipeline(prof=prof, params=params)
    return pipe, prof, params


def _run_synthetic_once(pipe, prof, params, size: Tuple[int, int]):
    h, w = size
    rng = np.random.default_rng(20260820)
    img = rng.random((h, w, 3), dtype=np.float32)
    ctx = StageContext("synthetic", prof=prof, config={
        "half_size": False,
        "stages": params,
    })
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    t0 = time.perf_counter()
    pipe.run(ctx)
    total_ms = (time.perf_counter() - t0) * 1000.0
    stages = {r.name: r.time_s * 1000.0 for r in ctx.results}
    return stages, total_ms


def _run_nef_once(pipe, prof, raw_path: Path, params: Dict[str, Dict[str, Any]]):
    from pixo.render.core.io import decode_raw

    t_decode0 = time.perf_counter()
    img, raw = decode_raw(raw_path, half_size=True)
    decode_ms = (time.perf_counter() - t_decode0) * 1000.0
    try:
        ctx = StageContext(raw_path, raw=raw, prof=prof, config={
            "half_size": True,
            "stages": params,
        })
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["half_size"] = True
        t0 = time.perf_counter()
        pipe.run(ctx)
        total_ms = (time.perf_counter() - t0) * 1000.0
        stages = {r.name: r.time_s * 1000.0 for r in ctx.results}
        stages["decode"] = decode_ms
        total_ms = total_ms + decode_ms
        return stages, total_ms
    finally:
        try:
            raw.close()
        except Exception:
            pass


def _load_dcp(dcp_path: str | None):
    from pixo.render.core.calibration import load_dcp

    path = Path(dcp_path) if dcp_path else Path(DEFAULT_DCP)
    if not path.exists():
        raise FileNotFoundError(
            f"DCP 不存在: {path}; 请用 --dcp 指定或改用合成图模式")
    return load_dcp(path)


def _median_ms(samples: List[float]) -> float:
    return float(statistics.median(samples))


def _collect(pipe, prof, params, raw_path, size, runs, warmup):
    """预热 + 采样, 返回 (stage_samples, total_samples)。"""
    stage_samples: Dict[str, List[float]] = {}
    total_samples: List[float] = []
    for i in range(warmup + runs):
        if raw_path is not None:
            stages, total_ms = _run_nef_once(pipe, prof, raw_path, params)
        else:
            stages, total_ms = _run_synthetic_once(pipe, prof, params, size)
        if i >= warmup:
            for name, ms in stages.items():
                stage_samples.setdefault(name, []).append(ms)
            total_samples.append(total_ms)
    return stage_samples, total_samples


def _make_report(stage_samples, total_samples, raw_path, dcp_path, size,
                 hot: bool) -> Dict[str, Any]:
    stages = {name: _median_ms(v) for name, v in sorted(stage_samples.items())}
    try:
        from pixo.render import _native as native
        native_available = bool(native.available())
    except Exception:
        native_available = False
    return {
        "schema": "render-bench-pipeline-v1",
        "mode": "nef" if raw_path is not None else "synthetic",
        "raw": str(raw_path) if raw_path is not None else None,
        "dcp": str(dcp_path) if dcp_path else None,
        "size": list(size) if size is not None else None,
        "hot": hot,
        "runs": len(total_samples),
        "native_available": native_available,
        "stages": stages,
        "total_ms": _median_ms(total_samples),
        "stage_samples_ms": {k: [round(x, 4) for x in v]
                             for k, v in stage_samples.items()},
        "total_samples_ms": [round(x, 4) for x in total_samples],
    }


def _print_report(report: Dict[str, Any]) -> None:
    print(f"mode={report['mode']} size={report['size']} "
          f"runs={report['runs']} native_available={report['native_available']}")
    print(f"{'stage':<14s} {'median_ms':>10s}")
    for name, ms in report["stages"].items():
        print(f"{name:<14s} {ms:>10.2f}")
    print(f"{'total':<14s} {report['total_ms']:>10.2f}")


def _compare(report: Dict[str, Any], old_path: Path) -> int:
    old = json.loads(Path(old_path).read_text(encoding="utf-8"))
    old_stages = old.get("stages", {})
    new_stages = report.get("stages", {})
    failed = False
    print(f"{'stage':<14s} {'old_ms':>10s} {'new_ms':>10s} {'change%':>8s}  verdict")
    for name in sorted(set(old_stages) | set(new_stages)):
        old_ms = old_stages.get(name)
        new_ms = new_stages.get(name)
        if old_ms is None or new_ms is None:
            print(f"{name:<14s} {old_ms if old_ms is not None else '-':>10} "
                  f"{new_ms if new_ms is not None else '-':>10} "
                  f"{'-':>8s}  skip")
            continue
        change = (new_ms - old_ms) / old_ms * 100.0 if old_ms else 0.0
        ok = new_ms <= old_ms * 1.20
        failed = failed or (not ok)
        print(f"{name:<14s} {old_ms:>10.2f} {new_ms:>10.2f} "
              f"{change:>+7.1f}%  {'PASS' if ok else 'FAIL'}")
    if failed:
        print("RESULT: FAIL (存在 stage 慢 >20%)")
        return 1
    print("RESULT: PASS (无 stage 慢 >20%)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nef", default=None, help="真实 NEF/DNG 路径 (half_size)")
    ap.add_argument("--dcp", default=None, help="DCP 路径 (--nef 模式必需或默认)")
    ap.add_argument("--size", type=parse_size, default=DEFAULT_SIZE,
                    help="合成图尺寸 HxW (默认 2020x3032)")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help="采样次数 (默认 5)")
    ap.add_argument("--warmup", type=int, default=DEFAULT_WARMUP,
                    help="预热次数 (默认 1)")
    ap.add_argument("--hot", action="store_true",
                    help="启用 huesat/colorcal/refine 热点参数 (默认关)")
    ap.add_argument("--baseline", default=None,
                    help="保存基线 JSON 路径")
    ap.add_argument("--compare", default=None,
                    help="与旧基线 JSON 比较, 慢 >20% 返回非零")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.nef is not None:
        raw_path = Path(args.nef)
        if not raw_path.exists():
            print(f"[bench] RAW 不存在: {raw_path}", file=sys.stderr)
            return 2
        prof = _load_dcp(args.dcp)
        params = {"skin": {"enabled": False}}
        if args.hot:
            for stage, overrides in HOT_PARAMS.items():
                params.setdefault(stage, {}).update(overrides)
        pipe = build_default_pipeline(prof=prof, params=params)
        size = None
        dcp_path = args.dcp or DEFAULT_DCP
    else:
        raw_path = None
        prof = None
        pipe, prof, params = _build_synthetic_pipeline(args.hot)
        size = args.size
        dcp_path = None

    stage_samples, total_samples = _collect(
        pipe, prof, params, raw_path, size, args.runs, args.warmup)
    report = _make_report(stage_samples, total_samples, raw_path, dcp_path,
                          size, args.hot)
    _print_report(report)

    if args.baseline:
        out = Path(args.baseline)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[bench] baseline -> {out}")

    if args.compare:
        return _compare(report, Path(args.compare))
    return 0


if __name__ == "__main__":
    sys.exit(main())
