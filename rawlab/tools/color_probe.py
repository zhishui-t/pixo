"""color_probe —— 渲染引擎色彩精准测量工具 (只测量, 不改渲染管线)。

目的 (用户反馈轮 2026-08-18):
  曝光已经和 LR 对齐, 色彩仍有"整体/局部偏红、金黄"问题。全局 da/db 中位
  会掩盖不同色相/亮度/肤色的反向漂移。本工具把一张 ours-vs-target 照片切成:
    - 12 色相桶 (HSV hue, 每 15°)
    - 4 亮度段 (Lab L)
    - 6x6 / 9x9 空间网格
    - 肤色椭圆区 / 中性区 / 高光区
  逐口径报 RGB/Lab/HSV 中位差, 并按场景 wb_B 汇总, 输出 JSON + Markdown。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from rawlab.tools.regress_anchors import (
    align_target,
    build_runtime,
    crop_active_oriented,
    load_target_jpeg,
)
from rawlab.engine.skin import skin_mask

HUE_BINS = 12
LUM_BANDS = [(0.0, 50.0), (50.0, 100.0), (100.0, 160.0), (160.0, 256.0)]


# ---------------------------------------------------------------------------
# 纯函数 (可单测)
# ---------------------------------------------------------------------------

def _lab(rgb_u8: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.asarray(rgb_u8, dtype=np.uint8),
                        cv2.COLOR_RGB2LAB).astype(np.float32)


def _hsv(rgb_u8: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.asarray(rgb_u8, dtype=np.uint8),
                        cv2.COLOR_RGB2HSV).astype(np.float32)


def _mask_stats(ours_u8, target_u8, mask, min_n: int = 100):
    """掩码内 RGB/Lab/HSV 中位差; 样本不足返回 None。"""
    if mask is None or int(mask.sum()) < min_n:
        return None
    ro = np.median(ours_u8[mask].reshape(-1, 3), axis=0)
    rt = np.median(target_u8[mask].reshape(-1, 3), axis=0)
    lo = _lab(ours_u8)
    lt = _lab(target_u8)
    ho = _hsv(ours_u8)
    ht = _hsv(target_u8)
    return {
        "n": int(mask.sum()),
        "dR": round(float(ro[0] - rt[0]), 2),
        "dG": round(float(ro[1] - rt[1]), 2),
        "dB": round(float(ro[2] - rt[2]), 2),
        "dL": round(float(np.median(lo[..., 0][mask]) - np.median(lt[..., 0][mask])), 2),
        "da": round(float(np.median(lo[..., 1][mask]) - np.median(lt[..., 1][mask])), 2),
        "db": round(float(np.median(lo[..., 2][mask]) - np.median(lt[..., 2][mask])), 2),
        "dS": round(float(np.median(ho[..., 1][mask]) - np.median(ht[..., 1][mask])), 2),
        "dV": round(float(np.median(ho[..., 2][mask]) - np.median(ht[..., 2][mask])), 2),
    }


def full_stats(ours_u8, target_u8) -> dict:
    return _mask_stats(ours_u8, target_u8,
                       np.ones(target_u8.shape[:2], dtype=bool), min_n=1)


def neutral_stats(ours_u8, target_u8, c_max: float = 12.0) -> dict:
    lt = _lab(target_u8)
    C = np.sqrt((lt[..., 1] - 128.0) ** 2 + (lt[..., 2] - 128.0) ** 2)
    return _mask_stats(ours_u8, target_u8, C < c_max)


def skin_stats(ours_u8, target_u8) -> dict:
    m = skin_mask(target_u8) > 0.5
    return _mask_stats(ours_u8, target_u8, m)


def highlight_stats(ours_u8, target_u8, l_min: float = 160.0) -> dict:
    lt = _lab(target_u8)
    return _mask_stats(ours_u8, target_u8, lt[..., 0] > l_min)


def hue_sector_stats(ours_u8, target_u8, n_bins: int = HUE_BINS,
                     s_min: float = 20.0, v_min: float = 40.0) -> list[dict]:
    """12 色相桶: 目标侧有色的像素逐桶报中位差; 空桶 None。"""
    ho = _hsv(ours_u8)
    ht = _hsv(target_u8)
    colorful = (ht[..., 1] >= s_min) & (ht[..., 2] >= v_min)
    lo = _lab(ours_u8)
    lt = _lab(target_u8)
    rows = []
    width = 180.0 / n_bins
    for k in range(n_bins):
        lo_h, hi_h = k * width, (k + 1) * width
        m = colorful & (ht[..., 0] >= lo_h) & (ht[..., 0] < hi_h)
        if int(m.sum()) < 100:
            rows.append(None)
            continue
        rows.append({
            "hue_range": [round(lo_h, 1), round(hi_h, 1)],
            "n": int(m.sum()),
            "da": round(float(np.median(lo[..., 1][m]) - np.median(lt[..., 1][m])), 2),
            "db": round(float(np.median(lo[..., 2][m]) - np.median(lt[..., 2][m])), 2),
            "dS": round(float(np.median(ho[..., 1][m]) - np.median(ht[..., 1][m])), 2),
            "dV": round(float(np.median(ho[..., 2][m]) - np.median(ht[..., 2][m])), 2),
            "dhue": round(float(np.median(ho[..., 0][m]) - np.median(ht[..., 0][m])), 2),
        })
    return rows


def luma_band_stats(ours_u8, target_u8) -> list[dict]:
    lt = _lab(target_u8)
    rows = []
    for lo_, hi_ in LUM_BANDS:
        m = (lt[..., 0] >= lo_) & (lt[..., 0] < hi_)
        s = _mask_stats(ours_u8, target_u8, m)
        rows.append(None if s is None else {"range": [lo_, hi_], **s})
    return rows


def grid_stats(ours_u8, target_u8, n: int = 6,
               da_min: float = 3.0, db_min: float = 3.0,
               rgb_min: float = 10.0) -> list[dict]:
    """n×n 网格, 返回超过阈值的格 (按 |da|+|db| 排序)。"""
    h, w = target_u8.shape[:2]
    lo = _lab(ours_u8)
    lt = _lab(target_u8)
    ro = ours_u8.astype(np.float32)
    rt = target_u8.astype(np.float32)
    rows = []
    for i in range(n):
        y0, y1 = i * h // n, (i + 1) * h // n
        for j in range(n):
            x0, x1 = j * w // n, (j + 1) * w // n
            da = float(np.median(lo[y0:y1, x0:x1, 1]) - np.median(lt[y0:y1, x0:x1, 1]))
            db = float(np.median(lo[y0:y1, x0:x1, 2]) - np.median(lt[y0:y1, x0:x1, 2]))
            d_rgb = (np.median(ro[y0:y1, x0:x1], axis=(0, 1))
                     - np.median(rt[y0:y1, x0:x1], axis=(0, 1)))
            if abs(da) >= da_min or abs(db) >= db_min or abs(d_rgb).max() >= rgb_min:
                rows.append({"cell": [i, j], "da": round(da, 2), "db": round(db, 2),
                             "dR": round(float(d_rgb[0]), 2),
                             "dG": round(float(d_rgb[1]), 2),
                             "dB": round(float(d_rgb[2]), 2)})
    rows.sort(key=lambda r: abs(r["da"]) + abs(r["db"]), reverse=True)
    return rows


def measure_photo(ours_u8, target_u8, stem: str = "", wb_b: float | None = None,
                  grids=(6, 9)) -> dict:
    target_u8 = align_target(np.asarray(target_u8), ours_u8.shape[:2])
    return {
        "stem": stem,
        "wb_b": None if wb_b is None else round(float(wb_b), 4),
        "full": full_stats(ours_u8, target_u8),
        "neutral": neutral_stats(ours_u8, target_u8),
        "skin": skin_stats(ours_u8, target_u8),
        "highlight": highlight_stats(ours_u8, target_u8),
        "hue_sectors": hue_sector_stats(ours_u8, target_u8),
        "luma_bands": luma_band_stats(ours_u8, target_u8),
        "grids": {str(n): grid_stats(ours_u8, target_u8, n=n) for n in grids},
    }


def summarize_suggestions(measurements: list[dict]) -> dict:
    """按 wb_B 场景分桶汇总肤色/全帧通道残差, 给出修正方向建议。"""
    buckets = [
        ("day_warm", 1.00, 1.45),
        ("warm_mid", 1.45, 1.80),
        ("warm_tail", 1.80, 2.30),
        ("warm_extreme", 2.30, 3.00),
    ]
    out = {}
    for name, lo, hi in buckets:
        rows = [m for m in measurements
                if m.get("wb_b") is not None and lo <= m["wb_b"] < hi]
        if not rows:
            continue
        skins = [m["skin"] for m in rows if m["skin"]]
        fulls = [m["full"] for m in rows if m["full"]]
        out[name] = {
            "n": len(rows),
            "stems": [m["stem"] for m in rows],
            "skin": {k: round(float(np.median([s[k] for s in skins])), 2)
                     for k in ("dR", "dG", "dB", "da", "db")} if skins else None,
            "full": {k: round(float(np.median([f[k] for f in fulls])), 2)
                     for k in ("dR", "dG", "dB", "da", "db")} if fulls else None,
        }
    return out


# ---------------------------------------------------------------------------
# 真实渲染入口 (测试可注入 render_fn / load_target_fn)
# ---------------------------------------------------------------------------

def run_probe(raw_paths: list[str], targets_dir: str | Path,
              dcp_path: str | None = None, preset_path: str | None = None,
              render_fn=None, load_target_fn=None,
              half_size: bool = True, grids=(6, 9)) -> dict:
    if render_fn is None:
        prof, pipe, _, _ = build_runtime(dcp_path, preset_path)
    else:
        prof = pipe = None
    load_target = load_target_fn
    load_target = load_target_fn or load_target_jpeg

    measurements = []
    for raw_path in raw_paths:
        stem = Path(raw_path).stem
        target = load_target(targets_dir, stem)
        if target is None:
            measurements.append({"stem": stem, "error": "no_target"})
            continue
        if render_fn is None:
            import rawpy
            ours = pipe.run_file(raw_path, prof=prof, half_size=half_size)
            with rawpy.imread(raw_path) as raw:
                ours = crop_active_oriented(ours, raw)
            try:
                meta = json.loads((Path(targets_dir) / f"{stem}.meta.json").read_text(encoding="utf-8"))
                wb_b = float(meta.get("wb_b", meta["wb"][2] / meta["wb"][1]))
            except Exception:
                wb_b = None
        else:
            ours = render_fn(raw_path, prof, pipe)
            wb_b = None
        ours = np.asarray(ours)
        if ours.dtype != np.uint8:
            ours = (np.clip(ours, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        t0 = time.perf_counter()
        m = measure_photo(ours, target, stem=stem, wb_b=wb_b, grids=grids)
        m["seconds"] = round(time.perf_counter() - t0, 3)
        measurements.append(m)
    return {
        "name": "color_probe",
        "targets": str(targets_dir),
        "measurements": measurements,
        "suggestions": summarize_suggestions(measurements),
    }


def write_report(report: dict, out_json: Path) -> Path:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out_json.with_suffix(".md")
    lines = ["# Color Probe", ""]
    for m in report["measurements"]:
        if m.get("error"):
            lines.append(f"- {m['stem']}: {m['error']}")
            continue
        f, sk, ne = m["full"], m["skin"], m["neutral"]
        lines.append("")
        lines.append(f"## {m['stem']} (wb_B={m['wb_b']})")
        lines.append(f"- full: dR={f['dR']:+} dG={f['dG']:+} dB={f['dB']:+} da={f['da']:+} db={f['db']:+}")
        if sk:
            lines.append(f"- skin: dR={sk['dR']:+} dG={sk['dG']:+} dB={sk['dB']:+} da={sk['da']:+} db={sk['db']:+}")
        if ne:
            lines.append(f"- neutral: da={ne['da']:+} db={ne['db']:+}")
        worst = []
        for sec in m["hue_sectors"]:
            if sec and (abs(sec["da"]) >= 2 or abs(sec["db"]) >= 2):
                worst.append(f"hue[{sec['hue_range'][0]:.0f}-{sec['hue_range'][1]:.0f}] "
                             f"da={sec['da']:+} db={sec['db']:+} dhue={sec['dhue']:+}")
        if worst:
            lines.append("- hue sectors: " + "; ".join(worst[:6]))
    md.write_text(chr(10).join(lines), encoding="utf-8")
    return out_json


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="render color probe")
    ap.add_argument("--preset", required=True)
    ap.add_argument("--targets", required=True)
    ap.add_argument("--anchors", nargs="+", required=True)
    ap.add_argument("--dcp", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--full", action="store_true")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_json = Path(args.out_json) if args.out_json else (
        ROOT / "rawlab" / "out" / "profile_fit"
        / f"color_probe_{time.strftime('%Y%m%d_%H%M%S')}.json")
    t0 = time.perf_counter()
    report = run_probe(args.anchors, args.targets, dcp_path=args.dcp,
                       preset_path=args.preset, half_size=not args.full)
    write_report(report, out_json)
    print(f"[color-probe] {len(report['measurements'])} photos, {time.perf_counter()-t0:.1f}s -> {out_json}")
    for m in report["measurements"]:
        if m.get("error"):
            print(f"  {m['stem']}: {m['error']}")
            continue
        f, sk = m["full"], m["skin"]
        skin_txt = f" skin da/db={sk['da']:+.1f}/{sk['db']:+.1f}" if sk else ""
        print(f"  {m['stem']}: full da/db={f['da']:+.1f}/{f['db']:+.1f}{skin_txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
