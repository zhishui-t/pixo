"""Conservative retouch on camera-calibrated Pixo base for 10 samples.

Uses Pixo vision metrics to make small, safe adjustments:
- reduce highlight clipping via tone.highlights
- lift deep shadows via tone.shadows
- add a touch of contrast when image is flat
- preserve the camera-calibrated color base (no global WB changes)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.meta import extract
from pixo.render.api import Renderer
from pixo.vision.measure import VisionMeasure
from pixo.vision.segmenters.yoloe import YoloeSegmenter

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
CAL_REPORT = Path("exports/auto/calibrated/calibration_report.json")
OUT = Path("exports/auto/retouched10")

SELECTED = [
    "DSC_5236_raw", "DSC_5245_raw", "DSC_5269_raw", "DSC_5270_raw",
    "DSC_5276_raw", "DSC_5288_raw", "DSC_0352_corpus_festival",
    "DSC_0358_corpus_festival", "DSC_0363_corpus_festival", "DSC_0368_corpus_festival",
]

PROMPTS = ["person", "face", "sky", "tree", "plant", "mountain",
           "building", "water", "road", "flower", "crowd", "light"]


def rotate_orientation(img, raw):
    try:
        o = int((extract(raw)["capture"].get("orientation") or 1))
        if o == 3:
            return cv2.rotate(img, cv2.ROTATE_180)
        if o == 6:
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        if o == 8:
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    except Exception:
        pass
    return img


def measure(measurer, bgr, masks=None):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    m = measurer.measure(rgb, masks or {})
    return m


def main():
    report = json.loads(CAL_REPORT.read_text(encoding="utf-8"))
    cal = {r["photo_id"]: r["params"] for r in report["photos"]}

    renderer = Renderer(DCP)
    measurer = VisionMeasure()
    segmenter = YoloeSegmenter(model_path=r"K:\work\project\guanlan\models\yoloe-26l-seg.pt",
                               conf_threshold=0.05, device="cpu")
    OUT.mkdir(parents=True, exist_ok=True)

    results = []
    for pid in SELECTED:
        raw = next(r["raw"] for r in report["photos"] if r["photo_id"] == pid)
        calp = cal[pid]
        ev = calp["ev"]
        trim = calp["trim"]
        print(f"[retouch] {pid} ev={ev}", flush=True)

        # Base calibrated preview for masks/metrics (no extra tone)
        base = renderer.render_preview_full(
            raw, long_edge=1024,
            params={"exposure": {"mode": ev}, "whitebalance": {"trim": trim}})
        base = rotate_orientation(base, raw)
        base_bgr = cv2.cvtColor(base, cv2.COLOR_RGB2BGR)
        try:
            masks = segmenter.segment(base, PROMPTS)
        except Exception as exc:  # noqa: BLE001
            print("  segment unavailable", exc, flush=True)
            masks = {}
        bm = measure(measurer, base_bgr, masks)
        g = bm.get("global", {})
        hi = g.get("highlight_clip_ratio") or 0
        sh = g.get("shadow_clip_ratio") or 0
        ct = g.get("contrast") or 0
        face = (bm.get("regions") or {}).get("face") or {}
        face_l = face.get("mean_luminance") if face.get("reliable") else None
        print(f"  base L={g.get('mean_luminance'):.0f} hi={hi:.3f} sh={sh:.3f} ct={ct:.2f} face={face_l}", flush=True)

        # Conservative tone adjustments
        tone = {}
        if hi > 0.04:
            tone["highlights"] = round(-min(0.35, (hi - 0.04) * 4.0), 2)
        if sh > 0.08:
            tone["shadows"] = round(min(0.35, (sh - 0.08) * 3.0), 2)
        if ct < 0.28:
            tone["contrast"] = 0.08
        if face_l is not None and face_l < 72:
            tone["shadows"] = round((tone.get("shadows") or 0) + 0.15, 2)
        print(f"  tone={tone}", flush=True)

        params = {
            "exposure": {"mode": ev},
            "whitebalance": {"trim": trim},
            **({"tone": tone} if tone else {}),
        }
        img = renderer.render_preview_full(raw, long_edge=1024, params=params)
        img = rotate_orientation(img, raw)
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        out = OUT / f"{pid.replace('corpus_festival', 'Spring')}_retouched.jpg"
        cv2.imwrite(str(out), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])

        am = measure(measurer, bgr, masks)
        ag = am.get("global", {})
        face2 = (am.get("regions") or {}).get("face") or {}
        face2l = face2.get("mean_luminance") if face2.get("reliable") else None
        print(f"  after L={ag.get('mean_luminance'):.0f} hi={ag.get('highlight_clip_ratio'):.3f} "
              f"sh={ag.get('shadow_clip_ratio'):.3f} ct={ag.get('contrast'):.2f} face={face2l}", flush=True)

        results.append({
            "photo_id": pid,
            "raw": raw,
            "params": params,
            "after_path": str(out),
            "base_metrics": {k: g.get(k) for k in ("mean_luminance", "highlight_clip_ratio", "shadow_clip_ratio", "contrast")},
            "after_metrics": {k: ag.get(k) for k in ("mean_luminance", "highlight_clip_ratio", "shadow_clip_ratio", "contrast")},
        })
        (OUT / "retouch_report.json").write_text(
            json.dumps({"photos": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("DONE", OUT / "retouch_report.json", flush=True)


if __name__ == "__main__":
    main()
