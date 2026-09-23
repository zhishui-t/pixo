"""R22 F02 spike: bilateral vs guided filter —— 512/1024/全幅 tier 耗时 + 质量。

口径: "导出全幅" = 原始 RAW 经 rawpy 解码全分辨率 (同生产导出尺寸),
      512/1024 tier = 同一全幅图 INTER_AREA 降采样 (与 preview_long_edge 语义一致)。
指标: 复用 pixo.vision.measure.measure_sharpness (noise_ratio / detail_score),
      在**同一 tier** 比较 "无降噪" vs "有降噪"。
亮度降噪形态: gray = Rec709(luma) → 保边滤波 → 按 (1 - detail_preserve) 混合回细节层。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rawpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.render.core.skin import guided_filter  # noqa: E402
from pixo.vision.measure import measure_sharpness  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / ".artifacts" / "r22-f02-spike"
OUT.mkdir(parents=True, exist_ok=True)

RAW = Path(r"K:\data\photo\0711\raw\DSC_5314.NEF")   # ISO 12800
RAW2 = Path(r"K:\data\photo\0711\raw\DSC_5278.NEF")  # ISO 8000
_W709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

BILATERAL_D = 7
BILATERAL_SIGMA_COLOR = 0.06      # 0..1 域 → 等效 u8 的 15
BILATERAL_SIGMA_SPACE = 3.0
GUIDED_R = 8
GUIDED_EPS = 0.0025               # σ=0.05


def load_full(path: Path) -> np.ndarray:
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True,
                              output_bps=8, gamma=(2.222, 4.5))
    return rgb


def resize_long(img: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) <= long_edge:
        return img
    s = long_edge / float(max(h, w))
    return cv2.resize(img, (max(int(round(w * s)), 4), max(int(round(h * s)), 4)),
                      interpolation=cv2.INTER_AREA)


def luma01(img_u8: np.ndarray) -> np.ndarray:
    return (img_u8.astype(np.float32) / 255.0) @ _W709


def compose(img_u8: np.ndarray, gray_den: np.ndarray, preserve: float) -> np.ndarray:
    """亮度降噪重组: out = gray_den + preserve * (gray_orig - gray_den) + 原色度。"""
    g0 = luma01(img_u8)
    detail = g0 - gray_den
    g_out = np.clip(gray_den + preserve * detail, 0.0, 1.0)
    rgb0 = img_u8.astype(np.float32) / 255.0
    chroma = rgb0 - g0[:, :, None]
    return np.clip(g_out[:, :, None] + chroma, 0.0, 1.0)


def op_bilateral(img_u8: np.ndarray) -> np.ndarray:
    g = luma01(img_u8)
    return cv2.bilateralFilter(g, BILATERAL_D, BILATERAL_SIGMA_COLOR,
                               BILATERAL_SIGMA_SPACE)


def op_guided(img_u8: np.ndarray) -> np.ndarray:
    g = luma01(img_u8)
    return guided_filter(g, g, GUIDED_R, GUIDED_EPS)


def gauss_pyramid_only(img_u8: np.ndarray) -> np.ndarray:
    g = luma01(img_u8)
    return cv2.GaussianBlur(g, (0, 0), 2.0)


OPS = {"bilateral": op_bilateral, "guided": op_guided,
       "gaussian_ref": gauss_pyramid_only}


def time_op(fn, img, reps=3):
    fn(img)  # warm
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn(img)
        ts.append((time.perf_counter() - t0) * 1000.0)
    return min(ts)


def measure(img01: np.ndarray) -> dict:
    return measure_sharpness((np.clip(img01, 0.0, 1.0) * 255.0).astype(np.uint8))


def main() -> int:
    report = {"raw": RAW.name, "raw2": RAW2.name,
              "bilateral": {"d": BILATERAL_D, "sigma_color": BILATERAL_SIGMA_COLOR,
                            "sigma_space": BILATERAL_SIGMA_SPACE},
              "guided": {"r": GUIDED_R, "eps": GUIDED_EPS},
              "operators": [], "tiers": {}}
    t0 = time.perf_counter()
    full = load_full(RAW)
    report["decode_full_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    report["full_shape"] = list(full.shape)
    np.save(OUT / "dsc5314_full_u8.npy", full)

    for tier, long_edge in (("512", 512), ("1024", 1024),
                            ("full", max(full.shape[:2]))):
        img = resize_long(full, long_edge) if tier != "full" else full
        entry = {"shape": list(img.shape),
                 "baseline": measure(img.astype(np.float32) / 255.0)}
        entry["timing_ms"] = {name: round(time_op(fn, img), 2)
                              for name, fn in OPS.items()}
        for name, fn in OPS.items():
            gray_den = fn(img)
            for preserve in (0.0, 0.25, 0.5):
                out = compose(img, gray_den, preserve)
                m = measure(out)
                base = entry["baseline"]
                m["noise_ratio_drop_pct"] = round(
                    100.0 * (1.0 - m["noise_ratio"] / max(base["noise_ratio"], 1e-9)), 2)
                m["detail_score_drop_pct"] = round(
                    100.0 * (1.0 - m["detail_score"] / max(base["detail_score"], 1e-9)), 2)
                entry.setdefault("variants", {})[f"{name}|preserve={preserve}"] = m
            del gray_den
        report["tiers"][tier] = entry
        if tier in ("512", "full"):
            base = img
            for name, fn in OPS.items():
                out01 = compose(img, fn(img), 0.25)
                crop = (np.clip(out01, 0, 1) * 255).astype(np.uint8)
                h, w = crop.shape[:2]
                cy, cx = h // 2, w // 2
                s = min(360, h // 2, w // 2)
                cv2.imwrite(str(OUT / f"crop_{tier}_{name}.png"),
                            cv2.cvtColor(crop[cy - s:cy + s, cx - s:cx + s],
                                         cv2.COLOR_RGB2BGR))
            h, w = base.shape[:2]
            cy, cx = h // 2, w // 2
            s = min(360, h // 2, w // 2)
            cv2.imwrite(str(OUT / f"crop_{tier}_baseline.png"),
                        cv2.cvtColor(base[cy - s:cy + s, cx - s:cx + s],
                                     cv2.COLOR_RGB2BGR))
        print(f"[tier {tier}] shape={entry['shape']} "
              f"base noise={entry['baseline']['noise_ratio']} "
              f"detail={entry['baseline']['detail_score']} "
              f"timing={entry['timing_ms']}", flush=True)
        (OUT / "spike_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # 第二张图 (ISO8000) 只测 1024 tier, 交叉验证
    full2 = load_full(RAW2)
    img2 = resize_long(full2, 1024)
    e2 = {"shape": list(img2.shape),
          "baseline": measure(img2.astype(np.float32) / 255.0),
          "timing_ms": {n: round(time_op(f, img2), 2) for n, f in OPS.items()},
          "variants": {}}
    for name, fn in OPS.items():
        gd = fn(img2)
        for preserve in (0.0, 0.25):
            m = measure(compose(img2, gd, preserve))
            b = e2["baseline"]
            m["noise_ratio_drop_pct"] = round(
                100.0 * (1.0 - m["noise_ratio"] / max(b["noise_ratio"], 1e-9)), 2)
            m["detail_score_drop_pct"] = round(
                100.0 * (1.0 - m["detail_score"] / max(b["detail_score"], 1e-9)), 2)
            e2["variants"][f"{name}|preserve={preserve}"] = m
    report["second_image_1024"] = e2
    (OUT / "spike_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[done]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
