"""Manual-exposure fallback for photos the auto-offset full-scan cannot fix.

The pipeline's automatic exposure has a highlight-protection cap that can make
target_offset ineffective on high-key/clipped scenes.  This script switches to
explicit manual EV (which always changes the output) and re-runs the full
Pixo measure/iterate loop for those selected photos.
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

from pixo.pipeline.loop import RawRenderBackend
from pixo.render.api import Renderer
from pixo.vision.measure import VisionMeasure
from pixo.vision.segmenters.yoloe import YoloeSegmenter

DCP = r"resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
YOLOE_MODEL = r"K:\work\project\guanlan\models\yoloe-26l-seg.pt"
OUT = Path("exports/auto/full_scan/manual")
PROMPTS = ["person", "face", "sky", "tree", "plant", "mountain",
           "building", "water", "road", "flower", "crowd", "light"]


def resize_masks(masks, shape):
    h, w = shape
    out = {}
    for k, v in masks.items():
        arr = np.asarray(v)
        if arr.shape == (h, w):
            out[k] = arr
        else:
            r = cv2.resize(arr.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
            out[k] = (r > 127).astype(np.uint8) * 255
    return out


def issues_from_measurement(m):
    g = m.get("global") or {}
    regs = m.get("regions") or {}
    face = regs.get("face") or {}
    face_ok = bool(face.get("reliable") and face.get("mean_luminance") is not None)
    mean = g.get("mean_luminance")
    hi = g.get("highlight_clip_ratio") or 0
    sh = g.get("shadow_clip_ratio") or 0
    contrast = g.get("contrast") or 0
    issues = []
    if hi > 0.03:
        issues.append("highlight")
    if sh > 0.08:
        issues.append("shadow")
    if face_ok:
        fl = face["mean_luminance"]
        if fl < 75:
            issues.append("face_dark")
        elif fl > 160:
            issues.append("face_bright")
    else:
        if mean is not None and mean < 75:
            issues.append("image_dark")
        elif mean is not None and mean > 170:
            issues.append("image_bright")
    if contrast < 0.2:
        issues.append("low_contrast")
    return issues


def ev_delta(issues, m):
    g = m.get("global") or {}
    regs = m.get("regions") or {}
    face = regs.get("face") or {}
    face_ok = bool(face.get("reliable") and face.get("mean_luminance") is not None)
    hi = g.get("highlight_clip_ratio") or 0
    mean = g.get("mean_luminance")
    if "highlight" in issues:
        if hi > 0.20:
            return -0.40
        if hi > 0.08:
            return -0.35
        if hi > 0.05:
            return -0.30
        return -0.20
    if "face_bright" in issues or (face_ok and face["mean_luminance"] > 160):
        return -0.25
    if "face_dark" in issues or (face_ok and face["mean_luminance"] < 85):
        return 0.25
    if "image_bright" in issues:
        return -0.25
    if "image_dark" in issues:
        # manual EV full-res sensitivity ~22 L per EV
        delta = (80 - (mean or 0)) / 22.0
        return max(0.15, min(0.45, delta))
    if "shadow" in issues:
        return 0.15
    return 0.0


def process_one(renderer, measurer, segmenter, raw, max_iterations, out_dir):
    pid = f"{Path(raw).stem}_{Path(raw).parent.name}"
    backend = RawRenderBackend(raw, renderer.profile)
    prev = backend.render_preview({}, long_edge=1024)
    try:
        masks = segmenter.segment(prev, PROMPTS)
    except Exception as exc:  # noqa: BLE001
        print("  segmentation unavailable, global-only", exc, flush=True)
        masks = {}

    ev = 0.0
    history = []
    final_img = None
    final_m = None
    t0 = time.time()
    for it in range(1, max_iterations + 1):
        params = {"exposure": {"mode": ev}}
        img = backend.render_full(params)
        full_masks = resize_masks(masks, img.shape[:2])
        m = measurer.measure(img, full_masks, image_id=pid,
                             render_version="pixo_render_0.1",
                             detection_version="yoloe26l_seg_v1")
        issues = issues_from_measurement(m)
        history.append({"iteration": it, "ev": ev, "issues": issues,
                        "global": {k: (m.get("global") or {}).get(k)
                                   for k in ("mean_luminance", "contrast",
                                             "highlight_clip_ratio", "shadow_clip_ratio")}})
        print(f"  it{it} ev={ev:+.2f} L={m['global']['mean_luminance']:.0f} "
              f"hi={m['global']['highlight_clip_ratio']:.3f} issues={issues}", flush=True)
        if not issues:
            final_img, final_m = img, m
            break
        delta = ev_delta(issues, m)
        if delta == 0:
            final_img, final_m = img, m
            break
        ev = max(-1.5, min(1.5, ev + delta))
    else:
        params = {"exposure": {"mode": ev}}
        final_img = backend.render_full(params)
        full_masks = resize_masks(masks, final_img.shape[:2])
        final_m = measurer.measure(final_img, full_masks, image_id=pid,
                                   render_version="pixo_render_0.1",
                                   detection_version="yoloe26l_seg_v1")

    out_dir.mkdir(parents=True, exist_ok=True)
    after_path = out_dir / f"{pid}_manual.jpg"
    cv2.imwrite(str(after_path), cv2.cvtColor(final_img, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 95])
    g = final_m.get("global") or {}
    return {
        "photo_id": pid,
        "raw": str(raw),
        "params": {"exposure": {"mode": round(ev, 3)}},
        "final_measurement": final_m,
        "history": history,
        "after_path": str(after_path),
        "qualified": not issues_from_measurement(final_m),
        "issues": issues_from_measurement(final_m),
        "mean_luminance": g.get("mean_luminance"),
        "highlight_clip_ratio": g.get("highlight_clip_ratio"),
        "shadow_clip_ratio": g.get("shadow_clip_ratio"),
        "contrast": g.get("contrast"),
        "run_time_sec": round(time.time() - t0, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path,
                        default=Path("exports/auto/full_scan/full_scan_1787419786.json"))
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument("--ids", nargs="*", default=None)
    args = parser.parse_args()

    # Use the newest full_scan report if no explicit report given.
    report_path = args.report
    if not report_path.exists():
        import glob
        reports = sorted(glob.glob("exports/auto/full_scan/full_scan_*.json"))
        if reports:
            report_path = Path(reports[-1])
    d = json.loads(report_path.read_text(encoding="utf-8"))
    photos = d.get("photos", [])
    if args.ids:
        photos = [p for p in photos if p["photo_id"] in args.ids]
    else:
        photos = [p for p in photos if not p.get("qualified", True)]

    if not photos:
        print("No fallback photos selected.")
        return

    renderer = Renderer(DCP)
    measurer = VisionMeasure()
    segmenter = YoloeSegmenter(model_path=YOLOE_MODEL, conf_threshold=0.05, device="cpu")
    results = []
    out_report = OUT.parent / f"manual_fallback_{int(time.time())}.json"
    for p in photos:
        pid = p["photo_id"]
        print(f"[manual] {pid}", flush=True)
        rec = process_one(renderer, measurer, segmenter, p["raw"],
                          args.max_iterations, OUT)
        results.append(rec)
        out_report.write_text(json.dumps({"photos": results}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        print(f"  -> {rec['qualified']} {rec['params']} L={rec['mean_luminance']} "
              f"hi={rec['highlight_clip_ratio']}", flush=True)
    print(f"\nDONE {out_report}", flush=True)


if __name__ == "__main__":
    main()
