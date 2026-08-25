"""Score calibrated photos and mark which are worth retouching.

Uses Pixo BatchPipeline hard filter + MockAestheticScorer.
Classifies: good / mediocre / skip(hard fail).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.pipeline.batch import BatchPipeline, HardFilterConfig, BatchInput
from pixo.pipeline.batch import MockAestheticScorer
from pixo.vision import measure_global, measure_motion_blur, measure_sharpness

CAL = Path("exports/auto/calibrated")
OUT = Path("exports/auto/scores")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(CAL.glob("*_calibrated.jpg"))
    scorer = MockAestheticScorer()
    rows = []
    for f in files:
        bgr = cv2.imread(str(f))
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        g = measure_global(rgb)
        sh = measure_sharpness(rgb)
        mo = measure_motion_blur(rgb)
        score = scorer.score(rgb, {})
        overall = score.overall if score else 0.0
        detail = float(sh["detail_score"])
        motion = float(mo["strength"])
        hi = float(g["highlight_clip_ratio"])
        shc = float(g["shadow_clip_ratio"])
        luminosity = float(g["mean_luminance"])
        contrast = float(g["contrast"])
        hard_reasons = []
        if motion > 0.35:
            hard_reasons.append("motion_blur")
        if detail < 3.0:
            hard_reasons.append("low_sharpness")
        if hi > 0.08:
            hard_reasons.append("highlight_clip")
        if shc > 0.20:
            hard_reasons.append("shadow_clip")
        # classify
        if hard_reasons:
            label = "skip_bad"
        elif overall >= 3.0:
            label = "good"
        else:
            label = "mediocre"
        rows.append({
            "file": f.name,
            "label": label,
            "overall": round(overall, 3),
            "detail": round(detail, 2),
            "motion": round(motion, 3),
            "highlight_clip": round(hi, 4),
            "shadow_clip": round(shc, 4),
            "mean_luminance": round(luminosity, 1),
            "contrast": round(contrast, 3),
            "hard_reasons": hard_reasons,
        })
    rows.sort(key=lambda r: (-(r["label"] == "good"), -r["overall"]))
    (OUT / "photo_scores.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total {len(rows)}")
    from collections import Counter
    print(Counter(r['label'] for r in rows))
    for r in rows[:60]:
        print(f"{r['label']:8s} {r['overall']:.2f} {r['file']}")


if __name__ == "__main__":
    main()
