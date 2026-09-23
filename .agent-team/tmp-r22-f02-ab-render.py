"""R22 F02: 在生产渲染输出 (整链全幅) 上标定降噪算子 —— 真正的 A/B 口径。

链路: pixo.render.web.export._render_full_quality(默认参数, 无 denoise)
      → 全幅 uint8 渲染图 → measure_sharpness (noise_ratio/detail_score 基线)
      → 在渲染图上跑候选亮度降噪 → 复测 → 求下降幅度。
严格串行单进程。用法: python <script> <NEF路径> [tag]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pixo.render.core.calibration import load_dcp  # noqa: E402
from pixo.render.core.skin import guided_filter  # noqa: E402
from pixo.render.web.export import _render_full_quality  # noqa: E402
from pixo.vision.measure import measure_sharpness  # noqa: E402

OUT = ROOT / ".artifacts" / "r22-f02-spike"
OUT.mkdir(parents=True, exist_ok=True)
DCP = ROOT / "resources" / "dcp" / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
_W709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def luma01(img):
    return (img.astype(np.float32) / 255.0) @ _W709


def compose(img_u8, gray_den, preserve):
    g0 = luma01(img_u8)
    g_out = np.clip(gray_den + preserve * (g0 - gray_den), 0.0, 1.0)
    rgb0 = img_u8.astype(np.float32) / 255.0
    chroma = rgb0 - g0[:, :, None]
    return np.clip(g_out[:, :, None] + chroma, 0.0, 1.0)


def meas(img01):
    return measure_sharpness((np.clip(img01, 0.0, 1.0) * 255.0).astype(np.uint8))


CANDS = [
    ("bilateral d=7 sc=0.10 ss=4", lambda g: cv2.bilateralFilter(g, 7, 0.10, 4.0)),
    ("bilateral d=9 sc=0.16 ss=6", lambda g: cv2.bilateralFilter(g, 9, 0.16, 6.0)),
    ("guided r=16 eps=0.04", lambda g: guided_filter(g, g, 16, 0.04)),
    ("gaussian sigma=2 (仅对照)", lambda g: cv2.GaussianBlur(g, (0, 0), 2.0)),
]


def main() -> int:
    nef = Path(sys.argv[1])
    tag = sys.argv[2] if len(sys.argv) > 2 else nef.stem
    prof = load_dcp(DCP)
    t0 = time.perf_counter()
    img = _render_full_quality(nef, prof, {}, output_bps=8)
    t_render = time.perf_counter() - t0
    arr = np.asarray(img)
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0, 65535) / 257.0).astype(np.uint8)
    print(f"[{tag}] render_full {t_render:.1f}s shape={arr.shape}", flush=True)
    base = meas(arr.astype(np.float32) / 255.0)
    print(f"[{tag}] baseline {base}", flush=True)
    np.save(OUT / f"render_full_{tag}.npy", arr)

    res = {"tag": tag, "nef": str(nef), "render_s": round(t_render, 1),
           "shape": list(arr.shape), "baseline": base, "variants": []}
    g = luma01(arr)
    for label, fn in CANDS:
        t1 = time.perf_counter()
        gd = fn(g)
        t_ms = (time.perf_counter() - t1) * 1000.0
        for preserve in (0.0, 0.25, 0.5, 0.75):
            m = meas(compose(arr, gd, preserve))
            nd = round(100.0 * (1 - m["noise_ratio"] / max(base["noise_ratio"], 1e-9)), 2)
            dd = round(100.0 * (1 - m["detail_score"] / max(base["detail_score"], 1e-9)), 2)
            res["variants"].append({"op": label, "preserve": preserve,
                                    "time_ms": round(t_ms, 1), **m,
                                    "noise_drop_pct": nd, "detail_drop_pct": dd})
            print(f"[{tag}] {label:26s} p={preserve:<5} {t_ms:8.0f}ms "
                  f"noise={m['noise_ratio']:.4f} ({nd:6.2f}%) "
                  f"detail={m['detail_score']:8.2f} ({dd:7.2f}%)", flush=True)
        del gd
    (OUT / f"ab_render_{tag}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[done]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
