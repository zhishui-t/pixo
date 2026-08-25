"""Calibrate Pixo output to the RAW embedded camera preview.

Uses the camera thumbnail as reference, iteratively solves a manual EV and
whitebalance.trim so the rendered output matches the camera's original color
and brightness on average.
"""
from __future__ import annotations

import argparse
import json
import glob
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rawpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.render.api import Renderer

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
OUT = Path("exports/auto/calibrated")


def camera_thumb_bgr(raw: str | Path) -> np.ndarray:
    with rawpy.imread(str(raw)) as rr:
        th = rr.extract_thumb()
        if th.format == rawpy.ThumbFormat.JPEG:
            return cv2.imdecode(np.frombuffer(th.data, np.uint8), cv2.IMREAD_COLOR)
        return th.data


def mean_rgb(img: np.ndarray) -> np.ndarray:
    return img.astype(np.float32).mean(axis=(0, 1))


def calibrate(renderer, raw, iters: int = 3, preview_edge: int = 512):
    base = renderer.render_preview_full(raw, long_edge=preview_edge,
                                        params={"exposure": {"mode": 0.0},
                                                "whitebalance": {"trim": [1, 1, 1]}})
    cam = camera_thumb_bgr(raw)
    cam_r = cv2.resize(cam, (base.shape[1], base.shape[0]),
                       interpolation=cv2.INTER_AREA)
    target = cv2.cvtColor(cam_r, cv2.COLOR_BGR2RGB).astype(np.float32).mean(axis=(0, 1))
    base_mean = mean_rgb(base)
    ev = float(np.log2(target.mean() / max(base_mean.mean(), 1e-6)))
    trim = np.array([1.0, 1.0, 1.0], dtype=np.float64)
    for _ in range(iters):
        img = renderer.render_preview_full(
            raw, long_edge=preview_edge,
            params={"exposure": {"mode": ev},
                    "whitebalance": {"trim": trim.tolist()}})
        cur = mean_rgb(img)
        ev += float(np.log2(target.mean() / max(cur.mean(), 1e-6)))
        trim = trim * (target / np.maximum(cur, 1e-6))
        trim = np.clip(trim, 0.3, 3.0)
        ev = float(np.clip(ev, -1.5, 1.5))
    final = renderer.render_preview_full(
        raw, long_edge=preview_edge,
        params={"exposure": {"mode": ev}, "whitebalance": {"trim": trim.tolist()}})
    fin_mean = mean_rgb(final)
    return {
        "ev": round(ev, 3),
        "trim": [round(float(x), 4) for x in trim],
        "target_mean": [round(float(x), 1) for x in target],
        "output_mean": [round(float(x), 1) for x in fin_mean],
        "mean_abs_err": round(float(np.abs(fin_mean - target).mean()), 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--raw", action="append", default=None)
    args = parser.parse_args()

    raws = {}
    if args.raw:
        for p in args.raw:
            pid = Path(p).stem
            raws[pid] = p
    else:
        for f in glob.glob("exports/auto/full_scan/full_scan_*.json"):
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            for p in d.get("photos", []):
                raws[p["photo_id"]] = p["raw"]
    # dedupe by actual filename stem too
    items = list(raws.items())
    if args.limit:
        items = items[:args.limit]

    renderer = Renderer(DCP)
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"photos": []}
    report_path = OUT / "calibration_report.json"

    for i, (pid, raw) in enumerate(items, 1):
        t0 = time.time()
        print(f"[{i}/{len(items)}] {pid}", flush=True)
        try:
            cal = calibrate(renderer, raw, iters=3)
            img = renderer.render_preview_full(
                raw, long_edge=1024,
                params={"exposure": {"mode": cal["ev"]},
                        "whitebalance": {"trim": cal["trim"]}})
            out = OUT / f"{pid}_calibrated.jpg"
            cv2.imwrite(str(out), cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            rec = {"photo_id": pid, "raw": raw, "params": cal,
                   "after_path": str(out), "run_time_sec": round(time.time() - t0, 2)}
        except Exception as exc:  # noqa: BLE001
            rec = {"photo_id": pid, "raw": raw, "error": str(exc)[:200],
                   "run_time_sec": round(time.time() - t0, 2)}
        report["photos"].append(rec)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"  -> {rec.get('params', {}).get('ev') if rec.get('params') else 'ERR'} "
              f"err={rec.get('params', {}).get('mean_abs_err') if rec.get('params') else '-'}",
              flush=True)
    print(f"DONE {report_path}", flush=True)


if __name__ == "__main__":
    main()
