"""R22 F02 参数标定: 在全幅解码图上找「noise_ratio↓>=30% 且 detail_score↓<=10%」的算子参数。

用已存盘的 .artifacts/r22-f02-spike/dsc5314_full_u8.npy (4040x6064) 做全幅扫描 +
1:1 裁剪目视存证。严格串行, 无并发。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.render.core.skin import guided_filter  # noqa: E402
from pixo.vision.measure import measure_sharpness  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / ".artifacts" / "r22-f02-spike"
FULL = np.load(OUT / "dsc5314_full_u8.npy")
_W709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
print("full", FULL.shape, flush=True)


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


def bil(g, d, sc, ss):
    return cv2.bilateralFilter(g, d, sc, ss)


def gdf(g, r, eps):
    return guided_filter(g, g, r, eps)


def main() -> int:
    full = FULL
    base = meas(full.astype(np.float32) / 255.0)
    print("FULL baseline", base, flush=True)
    rows = []
    g_full = luma01(full)

    cands = []
    for d, sc, ss in ((5, 0.08, 3.0), (7, 0.10, 4.0), (9, 0.12, 5.0),
                      (9, 0.16, 6.0), (11, 0.20, 6.0), (13, 0.25, 8.0),
                      (15, 0.30, 10.0)):
        cands.append((f"bilateral d={d} sc={sc} ss={ss}", "bil", (d, sc, ss)))
    for r, eps in ((8, 0.0025), (8, 0.01), (12, 0.01), (16, 0.04), (24, 0.09)):
        cands.append((f"guided r={r} eps={eps}", "gdf", (r, eps)))

    for label, kind, args in cands:
        t0 = time.perf_counter()
        gd = bil(g_full, *args) if kind == "bil" else gdf(g_full, *args)
        t_ms = (time.perf_counter() - t0) * 1000.0
        for preserve in (0.0, 0.25, 0.5):
            m = meas(compose(full, gd, preserve))
            nd = round(100.0 * (1 - m["noise_ratio"] / max(base["noise_ratio"], 1e-9)), 2)
            dd = round(100.0 * (1 - m["detail_score"] / max(base["detail_score"], 1e-9)), 2)
            rows.append({"op": label, "preserve": preserve, "time_ms": round(t_ms, 1),
                         "noise_ratio": m["noise_ratio"], "noise_drop_pct": nd,
                         "detail_score": m["detail_score"], "detail_drop_pct": dd,
                         "fft_high_ratio": m["fft_high_ratio"]})
            print(f"{label:28s} p={preserve:<5} {t_ms:8.0f}ms noise={m['noise_ratio']:.4f} "
                  f"({nd:6.2f}%) detail={m['detail_score']:8.2f} ({dd:7.2f}%) "
                  f"fft={m['fft_high_ratio']}", flush=True)
        del gd
    (OUT / "param_sweep_full.json").write_text(
        json.dumps({"baseline": base, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    # 1:1 目视裁剪: 基线 vs 最佳候选 (bilateral d=9 sc=0.16 ss=6 preserve=0.25)
    h, w = full.shape[:2]
    cy, cx = h // 2, w // 2
    s = 400
    crop = full[cy - s:cy + s, cx - s:cx + s]
    cv2.imwrite(str(OUT / "full1to1_baseline.png"),
                cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    sub = crop
    g_sub = luma01(sub)
    for tag, gd in (("bil_d9_sc016_ss6", bil(g_sub, 9, 0.16, 6.0)),
                    ("gdf_r16_eps004", gdf(g_sub, 16, 0.04))):
        for pr in (0.25,):
            o = (np.clip(compose(sub, gd, pr), 0, 1) * 255).astype(np.uint8)
            cv2.imwrite(str(OUT / f"full1to1_{tag}_p{pr}.png"),
                        cv2.cvtColor(o, cv2.COLOR_RGB2BGR))
    print("[done]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
