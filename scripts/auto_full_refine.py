"""Full-resolution driven refinement for photos the preview-loop left unqualified.

Uses the full-quality renderer directly for each iteration, so decisions are
made on the same image that will be exported. Saves refinements separately.
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
OUT = Path("exports/auto/refined")
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
    if sh > 0.05:
        issues.append("shadow")
    if face_ok:
        fl = face["mean_luminance"]
        if fl < 85:
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


def ev_delta(issues, m, current_ev):
    g = m.get("global") or {}
    regs = m.get("regions") or {}
    face = regs.get("face") or {}
    face_ok = bool(face.get("reliable") and face.get("mean_luminance") is not None)
    hi = g.get("highlight_clip_ratio") or 0
    mean = g.get("mean_luminance")
    if "highlight" in issues:
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
        # Empirical full-res sensitivity is roughly 22 luminance levels per EV.
        mean = mean or 0
        delta = (78 - mean) / 22.0
        return max(0.15, min(0.45, delta))
    if "shadow" in issues:
        return 0.15
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path,
                        default=Path("exports/auto/report/auto_report_1787417198.json"))
    parser.add_argument("--ids", nargs="*", default=None,
                        help="photo ids to refine; default: all non-qualified from assessment")
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    d = json.loads(args.report.read_text(encoding="utf-8"))
    photos = {p["photo_id"]: p for p in d["photos"]}
    if args.ids:
        selected = [photos[i] for i in args.ids if i in photos]
    elif not args.all:
        ap = Path("exports/auto/assessment.json")
        if ap.exists():
            rows = json.loads(ap.read_text(encoding="utf-8"))
            sel = {r["photo_id"] for r in rows if not r["qualified"]}
            selected = [photos[i] for i in sel if i in photos]
        else:
            selected = [p for p in d["photos"] if p.get("state") == "MANUAL_REVIEW"]
    else:
        selected = list(d["photos"])

    if not selected:
        print("No photos selected.")
        return

    renderer = Renderer(DCP)
    measurer = VisionMeasure()
    segmenter = YoloeSegmenter(model_path=YOLOE_MODEL, conf_threshold=0.05, device="cpu")
    OUT.mkdir(parents=True, exist_ok=True)

    refined: list[dict] = []
    for p in selected:
        pid = p["photo_id"]
        raw = p["raw"]
        print(f"[refine] {pid}", flush=True)
        backend = RawRenderBackend(raw, renderer.profile)
        prev = backend.render_preview({}, long_edge=1024)
        try:
            masks = segmenter.segment(prev, PROMPTS)
        except Exception as exc:  # noqa: BLE001
            print("  segmentation unavailable, global-only", exc, flush=True)
            masks = {}

        start_ev = 0.0
        try:
            ex = (p.get("params") or {}).get("exposure") or {}
            start_ev = float(ex.get("mode", 0.0))
        except (TypeError, ValueError):
            start_ev = 0.0

        ev = start_ev
        history = []
        best = None
        final_img = None
        final_m = None
        t0 = time.time()
        for it in range(1, args.max_iterations + 1):
            params = {"exposure": {"mode": "auto", "target_offset": ev}}
            img = backend.render_full(params)
            full_masks = resize_masks(masks, img.shape[:2])
            m = measurer.measure(img, full_masks, image_id=pid,
                                 render_version="pixo_render_0.1",
                                 detection_version="yoloe26l_seg_v1")
            issues = issues_from_measurement(m)
            history.append({"iteration": it, "ev": ev, "issues": issues,
                            "global": {k: (m.get("global") or {}).get(k)
                                       for k in ("mean_luminance", "contrast",
                                                 "highlight_clip_ratio", "shadow_clip_ratio")},
                            "face": (m.get("regions") or {}).get("face")})
            print(f"  it{it} ev={ev:+.2f} L={m['global']['mean_luminance']:.0f} "
                  f"hi={m['global']['highlight_clip_ratio']:.3f} issues={issues}", flush=True)
            if not issues:
                best = {"ev": ev, "measurement": m}
                final_img, final_m = img, m
                break
            delta = ev_delta(issues, m, ev)
            if delta == 0:
                best = {"ev": ev, "measurement": m}
                final_img, final_m = img, m
                break
            new_ev = max(-1.5, min(1.5, ev + delta))
            if abs(new_ev - ev) < 1e-9:
                best = {"ev": ev, "measurement": m}
                final_img, final_m = img, m
                break
            ev = new_ev
        else:
            # Loop ended by max iterations; re-render the last tried ev for a clean final.
            params = {"exposure": {"mode": "auto", "target_offset": ev}}
            img = backend.render_full(params)
            full_masks = resize_masks(masks, img.shape[:2])
            m = measurer.measure(img, full_masks, image_id=pid,
                                 render_version="pixo_render_0.1",
                                 detection_version="yoloe26l_seg_v1")
            best = {"ev": ev, "measurement": m}
            final_img, final_m = img, m

        if final_img is None:
            params = {"exposure": {"mode": "auto", "target_offset": ev}}
            final_img = backend.render_full(params)
            full_masks = resize_masks(masks, final_img.shape[:2])
            final_m = measurer.measure(final_img, full_masks, image_id=pid)
            best = {"ev": ev, "measurement": final_m}

        after_path = OUT / f"{pid}_refined.jpg"
        save = cv2.cvtColor(final_img, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(after_path), save, [cv2.IMWRITE_JPEG_QUALITY, 95])
        h, w = final_img.shape[:2]
        if max(h, w) > 1024:
            scale = 1024 / max(h, w)
            small = cv2.resize(final_img, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(OUT / f"{pid}_refined_preview.jpg"),
                        cv2.cvtColor(small, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])

        rec = {
            "photo_id": pid,
            "raw": raw,
            "params": {"exposure": {"mode": "auto", "target_offset": round(best["ev"], 3)}},
            "final_measurement": final_m,
            "history": history,
            "after_path": str(after_path),
            "qualified": not issues_from_measurement(final_m),
            "issues": issues_from_measurement(final_m),
            "run_time_sec": round(time.time() - t0, 2),
        }
        refined.append(rec)
        out_report = OUT / f"refined_{int(time.time())}.json"
        out_report.write_text(json.dumps({"photos": refined}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        print(f"  done ev={best['ev']:+.2f} qualified={rec['qualified']} -> {after_path}", flush=True)

    print(f"\nRefined {len(refined)} photos.", flush=True)


if __name__ == "__main__":
    main()
