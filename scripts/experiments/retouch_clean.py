"""Clean + saturated retouch for 10 samples.

Keeps the camera-calibrated base color, then applies Pixo's clarity,
contrast, vibrance/saturation, sharpen/denoise and subtle highlight control.
Photos judged out-of-focus or badly shot are skipped.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.meta import extract
from pixo.render.api import Renderer
from pixo.vision.measure import VisionMeasure

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
CAL_REPORT = Path("exports/auto/calibrated/calibration_report.json")
OUT = Path("exports/auto/retouched_clean")

SELECTED = [
    ("DSC_5236_raw", "DSC_5236_raw", False),
    ("DSC_5245_raw", "DSC_5245_raw", False),
    ("DSC_5269_raw", "DSC_5269_raw", False),
    ("DSC_5270_raw", "DSC_5270_raw", False),
    ("DSC_5276_raw", "DSC_5276_raw", False),
    ("DSC_5288_raw", "DSC_5288_raw", True),   # out of focus / soft - skip
    ("DSC_0352_2026春节", "DSC_0352_Spring", False),
    ("DSC_0358_2026春节", "DSC_0358_Spring", False),
    ("DSC_0363_2026春节", "DSC_0363_Spring", False),
    ("DSC_0368_2026春节", "DSC_0368_Spring", False),
]

# Typical clean/colorful enhancement params (kept conservative)
ENHANCE = {
    "tone": {"contrast": 0.10, "brightness": 0.03,
             "highlights": -0.10, "shadows": 0.08},
    "clarity": {"enabled": True, "strength": 0.45},
    "colorcal": {"vibrance": 0.28, "saturation": 0.08},
    "refine": {"sharpen": 0.30, "chroma_denoise": 0.6, "highlight_desat": 0.3},
}


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


def main():
    report = json.loads(CAL_REPORT.read_text(encoding="utf-8"))
    cal = {r["photo_id"]: r["params"] for r in report["photos"]}
    raw_of = {r["photo_id"]: r["raw"] for r in report["photos"]}

    renderer = Renderer(DCP)
    measurer = VisionMeasure()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []

    for pid, out_id, skip in SELECTED:
        raw = raw_of[pid]
        calp = cal[pid]
        rec = {"photo_id": pid, "skip": skip, "reason": None}
        if skip:
            print(f"[skip] {pid} 脱焦/拍糊，不修", flush=True)
            rec["reason"] = "out_of_focus_or_bad_shot"
            results.append(rec)
            continue

        params = {
            "exposure": {"mode": calp["ev"]},
            "whitebalance": {"trim": calp["trim"]},
            **{k: dict(v) for k, v in ENHANCE.items()},
        }
        img = renderer.render_preview_full(raw, long_edge=1024, params=params)
        img = rotate_orientation(img, raw)
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        out = OUT / f"{out_id}_enhanced.jpg"
        cv2.imwrite(str(out), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])

        g = measurer.measure_global(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        rec.update({"params": params, "after_path": str(out),
                    "metrics": {k: g.get(k) for k in
                                ("mean_luminance", "highlight_clip_ratio",
                                 "shadow_clip_ratio", "contrast")}})
        results.append(rec)
        print(f"[ok] {pid} -> {out}", flush=True)

    (OUT / "retouch_clean_report.json").write_text(
        json.dumps({"photos": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE", OUT / "retouch_clean_report.json", flush=True)


if __name__ == "__main__":
    main()
