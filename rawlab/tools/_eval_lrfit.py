"""eval_lrfit —— 给定 k, 写 JSON, 全管线渲染两张图, 打印 vs LR 目标。

用法: python rawlab/tools/_eval_lrfit.py r g b
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(r"K:\work\project\RawFlow")
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
from rawlab.dcp import load_dcp
from rawlab.engine.pipeline import pipeline_from_config

DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
       r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")
PHOTOS = [(r"K:\data\photo\2026春节\DSC_0376.NEF",
           r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_0376.jpg", "0376"),
          (r"K:\data\photo\0711\raw\DSC_5236.NEF",
           r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_5236.jpg", "5236")]
LR_PARAMS = {"exposure": {"mode": "baseline"},
             "tone": {"eotf": "lrfit"},
             "colorcal": {"neutral_mode": "off"},
             "refine": {"highlight_desat": 0.25}}
JSON = ROOT / "rawlab" / "engine" / "lr_tone_curve.json"


def stat(img, tag):
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    per = np.percentile(img, [1, 5, 50, 95, 99], axis=(0, 1))
    print(f"{tag:10s} p1={[round(float(v),1) for v in per[0]]} "
          f"p50={[round(float(v),1) for v in per[2]]} "
          f"p95={[round(float(v),1) for v in per[3]]} "
          f"a={np.median(lab[...,1])-128:+.1f} b={np.median(lab[...,2])-128:+.1f} "
          f"S={hsv[...,1].mean():.1f}")


def main():
    k = [float(a) for a in sys.argv[1:4]]
    warmth = float(sys.argv[4]) if len(sys.argv) > 4 else None
    sat = float(sys.argv[5]) if len(sys.argv) > 5 else None
    data = json.loads(JSON.read_text(encoding="utf-8"))
    data["gains"] = k
    JSON.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    params = dict(LR_PARAMS)
    if warmth is not None:
        params["whitebalance"] = {"warmth": warmth}
    if sat is not None:
        params["colorcal"] = {"neutral_mode": "off", "saturation": sat}
    print(f"k = {k} warmth = {warmth} colorcal_sat = {sat}")
    prof = load_dcp(DCP)
    for raw_path, lr_path, tag in PHOTOS:
        p = pipeline_from_config({"params": params}, prof=prof)
        out = p.run_file(raw_path, prof=prof)
        stat(out, f"ours {tag}")
        lr = cv2.cvtColor(cv2.imread(lr_path), cv2.COLOR_BGR2RGB)
        stat(lr, f"LR   {tag}")
        print()


if __name__ == "__main__":
    main()
