"""Autonomous real-photo Pixo loop: render -> segment -> measure -> decide -> iterate.

Selects representative NEFs from the real photo folders, runs the real
RawRenderBackend + YOLOE segmenter + VisionMeasure + Decide loop, and saves
before/after previews, full result, and a JSON report for later review.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.decide import load_rules
from pixo.decide.rules import DEFAULT_RULES
from pixo.pipeline.loop import RawRenderBackend, SinglePhotoLoop
from pixo.render.api import Renderer
from pixo.vision.measure import VisionMeasure
from pixo.vision.segmenters.yoloe import YoloeSegmenter

DCP = r"resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
YOLOE_MODEL = r"K:\work\project\guanlan\models\yoloe-26l-seg.pt"
OUT_ROOT = Path("exports/auto")
PROMPTS = [
    "person", "face", "sky", "tree", "plant", "mountain",
    "building", "water", "road", "flower", "crowd", "light",
]

PHOTOS_0711 = [
    "DSC_5236.NEF", "DSC_5245.NEF", "DSC_5250.NEF", "DSC_5257.NEF",
    "DSC_5260.NEF", "DSC_5268.NEF",
]
PHOTOS_SPRING = [
    "DSC_0352.NEF", "DSC_0356.NEF", "DSC_0360.NEF", "DSC_0368.NEF",
]


def save_rgb(path: Path, rgb: np.ndarray, quality: int = 95) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])


def global_metrics(measurer: VisionMeasure, rgb: np.ndarray) -> dict:
    m = measurer.measure_global(rgb)
    return {k: m.get(k) for k in (
        "mean_luminance", "contrast", "highlight_clip_ratio",
        "shadow_clip_ratio", "preview_highlight_clip_estimate",
        "haze_density", "sharpness", "motion_blur",
    ) if k in m}


def run_one(renderer, measurer, segmenter, raw_path: Path, photo_id: str,
            max_iterations: int, out_dir: Path) -> dict:
    raw_path = Path(raw_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Base/preview before any edits (same RawPreviewSession used by loop).
    before_rgb = RawRenderBackend(raw_path, renderer.profile).render_preview({}, long_edge=1024)
    before_path = out_dir / f"{photo_id}_before.jpg"
    save_rgb(before_path, before_rgb)
    before_metrics = global_metrics(measurer, before_rgb)

    rules = [r for path in DEFAULT_RULES for r in load_rules(path)]

    loop = SinglePhotoLoop(
        prof=renderer.profile,
        segmenter=segmenter,
        measurer=measurer,
        preview_long_edge=1024,
        max_iterations=max_iterations,
        prompts=PROMPTS,
        rules=rules,
        manual_on_unreliable=False,
        export_path=str(out_dir / f"{photo_id}_loop_export.jpg"),
    )

    t0 = time.time()
    try:
        result = loop.run(
            photo_id,
            raw_path=str(raw_path),
            max_iterations=max_iterations,
        )
        run_time = time.time() - t0
        final_image = result.final_image
        state = result.state
        reason = result.reason
        trace = result.trace_events
    except Exception as exc:  # noqa: BLE001
        return {
            "photo_id": photo_id,
            "raw": str(raw_path),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "before_metrics": before_metrics,
            "before_path": str(before_path),
            "run_time_sec": round(time.time() - t0, 2),
        }

    after_metrics = None
    if final_image is not None:
        after_path = out_dir / f"{photo_id}_after.jpg"
        save_rgb(after_path, final_image)
        after_metrics = global_metrics(measurer, final_image)
        # Also save a small preview for quick review.
        h, w = final_image.shape[:2]
        scale = 1024 / max(h, w)
        if scale < 1.0:
            small = cv2.resize(final_image, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
            save_rgb(out_dir / f"{photo_id}_after_preview.jpg", small)

    data = result.to_dict()
    data.update({
        "ok": True,
        "raw": str(raw_path),
        "state": state,
        "reason": reason,
        "run_time_sec": round(run_time, 2),
        "before_path": str(before_path),
        "after_path": str(out_dir / f"{photo_id}_after.jpg") if final_image is not None else None,
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "accepted": state in ("ACCEPTED",),
    })
    # Keep trace as-is; measurements already in data.
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--photo", action="append", default=None,
                        help="explicit NEF path (can repeat)")
    parser.add_argument("--max-iterations", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--scan", action="store_true",
                        help="scan all NEFs from the real photo folders")
    parser.add_argument("--offset", type=int, default=0,
                        help="scan offset")
    parser.add_argument("--count", type=int, default=20,
                        help="number of photos to process in scan mode")
    args = parser.parse_args()

    photo_paths: list[Path] = []
    if args.photo:
        photo_paths = [Path(p) for p in args.photo]
    elif args.scan:
        roots = [Path(r"K:\data\photo\0711\raw"),
                 Path(r"K:\data\photo\2026春节")]
        all_paths: list[Path] = []
        for root in roots:
            if root.exists():
                all_paths.extend(sorted(root.glob("*.NEF")))
        photo_paths = all_paths[args.offset:args.offset + args.count]
    else:
        for base, names in (
            (Path(r"K:\data\photo\0711\raw"), PHOTOS_0711),
            (Path(r"K:\data\photo\2026春节"), PHOTOS_SPRING),
        ):
            for name in names:
                p = base / name
                if p.exists():
                    photo_paths.append(p)
        if args.limit:
            photo_paths = photo_paths[:args.limit]

    if not photo_paths:
        print("No photos found.", file=sys.stderr)
        sys.exit(2)

    renderer = Renderer(DCP)
    measurer = VisionMeasure()
    segmenter = YoloeSegmenter(model_path=YOLOE_MODEL, conf_threshold=0.05, device="cpu")
    print(f"YOLOE ready={segmenter.ready}", flush=True)

    report_path = OUT_ROOT / "report" / f"auto_report_{int(time.time())}.json"
    report: dict = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dcp": DCP,
        "yoloe": YOLOE_MODEL,
        "prompts": PROMPTS,
        "max_iterations": args.max_iterations,
        "photos": [],
    }

    for i, p in enumerate(photo_paths, 1):
        photo_id = f"{p.stem}_{p.parent.name}"
        print(f"[{i}/{len(photo_paths)}] {photo_id} -> {p}", flush=True)
        rec = run_one(renderer, measurer, segmenter, p, photo_id,
                      args.max_iterations, OUT_ROOT)
        rec["source_dir"] = str(p.parent)
        report["photos"].append(rec)
        print(f"  state={rec.get('state')} ok={rec.get('ok')} "
              f"time={rec.get('run_time_sec')} reason={rec.get('reason')}", flush=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [report updated] {report_path}", flush=True)

    print(f"\nDONE. Report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
