"""Screen Xiamen batches: sample NEFs, render camera-matched previews, score."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.pipeline.batch import MockAestheticScorer
from pixo.render.api import Renderer
from pixo.vision import measure_global, measure_sharpness

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
BASE = Path("<corpus_root>/corpus_xiamen")
DIRS = ["1", "101XM_02", "102XM_03", "103XM_04"]
SAMPLE_PER_DIR = 20
OUT = Path("exports/auto/xiamen_screen")


def sample_files(d: Path, n: int):
    files = sorted(list(d.glob("*.NEF")) + list(d.glob("*.nef")))
    files = [f for f in files if not f.name.startswith("._")]
    if not files:
        return []
    if "--all" in sys.argv:
        # Windows 大小写不敏感: *.NEF 与 *.nef 双模式会重复匹配, 按名去重
        return sorted({f.name.lower(): f for f in files}.values())
    if len(files) <= n:
        return files
    idx = sorted(set(
        [0, len(files) - 1] +
        [int(i * (len(files) - 1) / (n - 1)) for i in range(n)]
    ))[:n]
    return [files[i] for i in idx]


def main():
    renderer = Renderer(DCP)
    scorer = MockAestheticScorer()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.time()
    for di in DIRS:
        d = BASE / di
        if not d.exists():
            print("skip missing", d, flush=True)
            continue
        files = sample_files(d, SAMPLE_PER_DIR)
        print(f"{di}: {len(files)} sampled", flush=True)
        for i, raw in enumerate(files, 1):
            stem = raw.stem
            short = f"X{di[:1]}_{stem}" if di != "1" else f"X1_{stem}"
            # avoid duplicate names across dirs (they are unique DSC numbers mostly)
            pid = f"{di}_{stem}"
            try:
                t = time.time()
                img = renderer.render_camera_matched(raw, long_edge=512)
                # Save as RGB -> BGR jpg
                out = OUT / f"{di}_{stem}.jpg"
                cv2.imwrite(str(out), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
                rgb = img
                g = measure_global(rgb)
                sh = measure_sharpness(rgb)
                sc = scorer.score(rgb, {})
                rows.append({
                    "batch": di, "file": raw.name, "raw": str(raw),
                    "preview": str(out),
                    "mean_luminance": round(float(g["mean_luminance"]), 1),
                    "contrast": round(float(g["contrast"]), 3),
                    "highlight_clip": round(float(g["highlight_clip_ratio"]), 4),
                    "shadow_clip": round(float(g["shadow_clip_ratio"]), 4),
                    "detail": round(float(sh["detail_score"]), 2),
                    "overall": round(sc.overall, 3) if sc else None,
                    "render_sec": round(time.time() - t, 2),
                })
                if i % 5 == 0 or i == len(files):
                    print(f"  {i}/{len(files)} {raw.name} {time.time()-t0:.0f}s", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("  error", raw.name, exc, flush=True)
    (OUT / "screen_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DONE {len(rows)} rows, {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
