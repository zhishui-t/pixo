"""R22 F02 标定（tester，第一步「快」）——解耦三轴估算器下的 strength 标定。

判据依据 design-r22 §2.2 / §4 / §7 A16（解耦版，用户 2026-09-10 批准方向）：
  轴1 噪声(平坦区) σ ↓≥30% ; 轴2 细节(纹理区) 高频能量 ↓≤10% ; 轴3 保真 ΔE2000 中位数 ≤+0.5 JND

口径（全部写死，落报告）:
  - 解码 = 与 super-dev spike 逐参数相同: rawpy postprocess(use_camera_wb=True,
    no_auto_bright=True, output_bps=8, gamma=(2.222, 4.5)) → "导出全幅"(全分辨率)
  - luma = Rec709 @ (u8/255)  (同 spike)
  - 降噪 = 对 luma 做保边滤波 → out = g_den + preserve*(g0 - g_den)，色度原样（同 spike compose）
  - 区域 = 由**未去噪参考**的梯度幅值分位固定（同一像素集对拍）
  - 梯度 = Sobel(ksize=3) on luma01 → g = hypot(gx, gy)
  - 平坦区 = g <= p30(g)，再 MORPH_OPEN(ones(3,3), iter=1) 去边缘
  - 纹理区 = g >= p70(g)
  - 噪声轴 σ = MAD(L[flat]) / 1.4826   (L = cv2.Laplacian(luma01, CV_32F, ksize=3))
  - 细节轴 E = MAD(L[tex])             (拉普拉斯绝对中位差；与 σ 同原语、不同区域)
  - 保真轴 ΔE00 = median(delta_e_2000(Lab(ref), Lab(out)))；全组合用 stride=4 确定性
    子采样（1.5M 样本，中位数稳健），frontier 组合另算**全像素**（行块累加，内存有界）
  - strength 映射（临时，待与 super-dev F02 stage 对齐）：bilateral σc = 0.24*strength；
    spike 选定 σc=0.06 ⇒ strength=0.25

严格串行、单进程；逐图逐组合释放中间量。输出 .artifacts/r22-noise-ab/calib_report.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rawpy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pixo.pipeline.perceptual import (delta_e_2000, gamma_srgb_to_linear,  # noqa: E402
                                      linear_srgb_to_lab)
from pixo.render.core.skin import guided_filter  # noqa: E402

RAW_DIR = Path(r"K:\data\photo\0711\raw")
SPIKE = ROOT / ".artifacts" / "r22-f02-spike"
OUT_DIR = ROOT / ".artifacts" / "r22-noise-ab"

_W709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_DE_STRIDE = 4
_Q_LOW, _Q_HIGH = 30.0, 70.0
_OPEN_K = np.ones((3, 3), np.uint8)
_JND = 2.3

# (file, iso)；5314 用 spike 已存 npy（与 spike 逐位同输入，便于三角验证）
SAMPLES = [
    ("DSC_5314.NEF", 12800, "saved"),
    ("DSC_5278.NEF", 8000, "decode"),
    ("DSC_5290.NEF", 6400, "decode"),
    ("DSC_5280.NEF", 5000, "decode"),
    ("DSC_5285.NEF", 3200, "decode"),
]

BILATERAL_D, BILATERAL_SS = 7, 3.0
SIGMA_COLORS = (0.02, 0.04, 0.06, 0.10, 0.16, 0.24)   # σc = 0.24*strength
GUIDED_R, GUIDED_EPS_SET = 8, (0.001, 0.0025, 0.01)
PRESERVES = (0.0, 0.25, 0.5)
STRENGTH_SCALE = 0.24

# 冒烟开关（plan-before-execute：先最小验证再全量）
if __import__("os").environ.get("CALIB_SMOKE"):
    SAMPLES = SAMPLES[:1]
    SIGMA_COLORS = SIGMA_COLORS[:2]
    GUIDED_EPS_SET = GUIDED_EPS_SET[:1]
    PRESERVES = PRESERVES[:1]


def load_full(path: Path) -> np.ndarray:
    with rawpy.imread(str(path)) as raw:
        return raw.postprocess(use_camera_wb=True, no_auto_bright=True,
                               output_bps=8, gamma=(2.222, 4.5))


def luma01(img_u8: np.ndarray) -> np.ndarray:
    return (img_u8.astype(np.float32) / 255.0) @ _W709


def compose(gray_den: np.ndarray, g0: np.ndarray, preserve: float) -> np.ndarray:
    """仅 luma 重组（三轴都用 luma，故不建 RGB；ΔE 阶段才按块重建色度）。"""
    return np.clip(gray_den + preserve * (g0 - gray_den), 0.0, 1.0)


def regions(g0: np.ndarray):
    gx = cv2.Sobel(g0, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g0, cv2.CV_32F, 0, 1, ksize=3)
    g = cv2.magnitude(gx, gy)
    del gx, gy
    p_low, p_high = np.percentile(g, [_Q_LOW, _Q_HIGH])
    flat = (g <= p_low).astype(np.uint8)
    tex = (g >= p_high).astype(np.uint8)
    del g
    flat = cv2.morphologyEx(flat, cv2.MORPH_OPEN, _OPEN_K, iterations=1)
    return flat.astype(bool), tex.astype(bool), float(p_low), float(p_high)


def lap_mad(lap: np.ndarray, mask: np.ndarray, k: int = 2_000_000):
    """masked MAD（分块取中位数，内存有界；mask 为 bool 同形）。"""
    vals = lap[mask]
    if vals.size == 0:
        raise RuntimeError("empty region mask")
    med = float(np.median(vals))
    dev = np.abs(vals - med)
    mad = float(np.median(dev))
    del vals, dev
    return mad, med


def de_median_stride(rgb_u8: np.ndarray, g_out: np.ndarray, g0: np.ndarray,
                     stride: int = _DE_STRIDE) -> float:
    sub_rgb = rgb_u8[::stride, ::stride].astype(np.float32) / 255.0
    rgb0 = sub_rgb
    out = np.clip(g_out[::stride, ::stride][:, :, None] + (rgb0 - g0[::stride, ::stride][:, :, None]),
                  0.0, 1.0)
    lab_ref = linear_srgb_to_lab(gamma_srgb_to_linear(rgb0))
    lab_out = linear_srgb_to_lab(gamma_srgb_to_linear(out))
    de = delta_e_2000(lab_ref, lab_out)
    med = float(np.median(de))
    del sub_rgb, rgb0, out, lab_ref, lab_out, de
    return med


def de_median_full(rgb_u8: np.ndarray, g_out: np.ndarray, g0: np.ndarray,
                   block: int = 512) -> float:
    """全像素 ΔE 中位数（行块累加，内存有界）。"""
    h = rgb_u8.shape[0]
    chunks = []
    for y0 in range(0, h, block):
        y1 = min(y0 + block, h)
        rb = rgb_u8[y0:y1].astype(np.float32) / 255.0
        ob = np.clip(g_out[y0:y1][:, :, None] + (rb - g0[y0:y1][:, :, None]), 0.0, 1.0)
        de = delta_e_2000(linear_srgb_to_lab(gamma_srgb_to_linear(rb)),
                          linear_srgb_to_lab(gamma_srgb_to_linear(ob)))
        chunks.append(de.ravel())
        del rb, ob, de
    allv = np.concatenate(chunks)
    med = float(np.median(allv))
    del chunks, allv
    return med


def measure_axes(lap: np.ndarray, flat: np.ndarray, tex: np.ndarray) -> tuple[float, float]:
    sig, _ = lap_mad(lap, flat)
    det, _ = lap_mad(lap, tex)
    return sig / 1.4826, det


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {
        "design": "design-r22 §2.2/§4/§7 A16（解耦三轴）",
        "tier": "导出全幅 rawpy postprocess 全分辨率",
        "decode": "rawpy postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8, gamma=(2.222,4.5))",
        "luma": "Rec709 [0.2126,0.7152,0.0722] @ (u8/255)",
        "grad": "Sobel ksize=3 on luma01 -> hypot(gx,gy)",
        "region_q": {"low_pct": _Q_LOW, "high_pct": _Q_HIGH, "fixed_by": "未去噪参考"},
        "morph": "MORPH_OPEN ones(3,3) iter=1 (仅平坦区)",
        "lap": "cv2.Laplacian(luma01, CV_32F, ksize=3)",
        "noise_axis": "median(|L_flat - median(L_flat)|)/1.4826  ↓>=30%",
        "detail_axis": "median(|L_tex - median(L_tex)|)  ↓<=10%",
        "fidelity_axis": "median CIEDE2000(Lab(ref), Lab(out)) <= +0.5 JND (=1.15 dE00)",
        "de_stride_screening": _DE_STRIDE,
        "de_full_pixel_for_frontier": True,
        "bilateral": {"d": BILATERAL_D, "sigma_space": BILATERAL_SS,
                      "sigma_color_set": list(SIGMA_COLORS),
                      "strength_map": f"sigma_color = {STRENGTH_SCALE}*luminance_strength"
                                      " (临时映射；spike 选定 σc=0.06 ⇒ strength=0.25)"},
        "guided": {"r": GUIDED_R, "eps_set": list(GUIDED_EPS_SET)},
        "detail_preserve_set": list(PRESERVES),
        "jnd_delta_e": _JND,
    }
    report = {"config": cfg, "samples": []}

    for name, iso, how in SAMPLES:
        path = RAW_DIR / name
        t0 = time.perf_counter()
        if how == "saved":
            rgb = np.load(SPIKE / "dsc5314_full_u8.npy")
            decode_ms = None
            # 三角验证：与现场解码逐位/最大差对比
            rgb2 = load_full(path)
            dmax = int(np.abs(rgb.astype(np.int16) - rgb2.astype(np.int16)).max())
            del rgb2
        else:
            rgb = load_full(path)
            dmax = None
        dec_ms = round((time.perf_counter() - t0) * 1000.0, 1) if how != "saved" else None
        g0 = luma01(rgb)
        flat, tex, p_low, p_high = regions(g0)
        lap0 = cv2.Laplacian(g0, cv2.CV_32F, ksize=3)
        sig0, det0 = measure_axes(lap0, flat, tex)
        del lap0
        entry = {
            "file": name, "iso": iso, "how": how, "shape": list(rgb.shape),
            "decode_saved_ms": decode_ms, "decode_vs_saved_maxdiff": dmax,
            "region": {"flat_px": int(flat.sum()), "tex_px": int(tex.sum()),
                       "p30": p_low, "p70": p_high},
            "baseline": {"sigma_noise": sig0, "detail_tex": det0},
            "rows": [],
        }
        print(f"[{name} ISO{iso}] shape={rgb.shape} decode={dec_ms}ms "
              f"maxdiff_vs_saved={dmax} flat={int(flat.sum())} tex={int(tex.sum())} "
              f"sigma0={sig0:.6f} detail0={det0:.6f}", flush=True)

        combos = ([("bilateral", {"sigma_color": sc}) for sc in SIGMA_COLORS]
                  + [("guided", {"eps": e}) for e in GUIDED_EPS_SET])
        for op, kw in combos:
            t_op = time.perf_counter()
            if op == "bilateral":
                gd = cv2.bilateralFilter(g0, BILATERAL_D, kw["sigma_color"], BILATERAL_SS)
                label = f"bilateral sigma_color={kw['sigma_color']}"
                strength = round(kw["sigma_color"] / STRENGTH_SCALE, 3)
            else:
                gd = guided_filter(g0, g0, GUIDED_R, kw["eps"])
                label = f"guided eps={kw['eps']}"
                strength = None
            op_ms = round((time.perf_counter() - t_op) * 1000.0, 1)
            for preserve in PRESERVES:
                g_out = compose(gd, g0, preserve)
                lap = cv2.Laplacian(g_out, cv2.CV_32F, ksize=3)
                sig1, det1 = measure_axes(lap, flat, tex)
                del lap
                nd = round(100.0 * (1.0 - sig1 / max(sig0, 1e-12)), 2)
                dd = round(100.0 * (1.0 - det1 / max(det0, 1e-12)), 2)
                de_s = de_median_stride(rgb, g_out, g0)
                row = {"op": op, "params": kw, "strength": strength,
                       "detail_preserve": preserve, "op_ms": op_ms,
                       "sigma_noise": round(sig1, 6), "detail_tex": round(det1, 6),
                       "noise_drop_pct": nd, "detail_drop_pct": dd,
                       "de_median_stride": round(de_s, 4),
                       "axis1_noise_ok": nd >= 30.0, "axis2_detail_ok": dd <= 10.0,
                       "axis3_de_ok": de_s <= 0.5 * _JND,
                       "all3_ok": (nd >= 30.0 and dd <= 10.0 and de_s <= 0.5 * _JND)}
                entry["rows"].append(row)
                print(f"  {label:32s} p={preserve:<4} op={op_ms:7.0f}ms "
                      f"noise={nd:7.2f}% detail={dd:7.2f}% dE={de_s:6.3f} "
                      f"{'ALL3' if row['all3_ok'] else ''}", flush=True)
                del g_out
            del gd
        # frontier：全像素 ΔE（detail<=10% 的最强档 + 最强噪声档）
        ok = [r for r in entry["rows"] if r["axis2_detail_ok"]]
        cands = []
        if ok:
            cands.append(max(ok, key=lambda r: r["noise_drop_pct"]))
        cands.append(max(entry["rows"], key=lambda r: r["noise_drop_pct"]))
        for r in cands:
            if r.get("de_median_full") is not None:
                continue
            if r["op"] == "bilateral":
                gd = cv2.bilateralFilter(g0, BILATERAL_D, r["params"]["sigma_color"], BILATERAL_SS)
            else:
                gd = guided_filter(g0, g0, GUIDED_R, r["params"]["eps"])
            g_out = compose(gd, g0, r["detail_preserve"])
            r["de_median_full"] = round(de_median_full(rgb, g_out, g0), 4)
            del gd, g_out
        entry["frontier_full_de"] = [
            {"op": r["op"], "params": r["params"], "detail_preserve": r["detail_preserve"],
             "noise_drop_pct": r["noise_drop_pct"], "detail_drop_pct": r["detail_drop_pct"],
             "de_median_full": r.get("de_median_full")} for r in cands]
        report["samples"].append(entry)
        (OUT_DIR / "calib_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  [frontier] {entry['frontier_full_de']}", flush=True)
        del rgb, g0, flat, tex

    # 跨图聚合（同一 (op, params, preserve) 上的 median）
    agg: dict[str, list] = {}
    for e in report["samples"]:
        for r in e["rows"]:
            key = f"{r['op']}|{json.dumps(r['params'], sort_keys=True)}|p={r['detail_preserve']}"
            agg.setdefault(key, []).append(r)
    table = []
    for key, rows in agg.items():
        table.append({
            "combo": key, "n": len(rows),
            "noise_drop_median": round(float(np.median([r["noise_drop_pct"] for r in rows])), 2),
            "detail_drop_median": round(float(np.median([r["detail_drop_pct"] for r in rows])), 2),
            "de_median_stride_median": round(float(np.median([r["de_median_stride"] for r in rows])), 4),
            "n_all3_ok": sum(1 for r in rows if r["all3_ok"]),
            "n_axis2_ok": sum(1 for r in rows if r["axis2_detail_ok"]),
            "max_noise_drop_within_detail10_median": (
                round(float(np.median([r["noise_drop_pct"] for r in rows
                                       if r["axis2_detail_ok"]])), 2)
                if any(r["axis2_detail_ok"] for r in rows) else None),
        })
    table.sort(key=lambda t: t["noise_drop_median"])
    report["aggregate"] = table
    report["any_all3_ok"] = any(r["all3_ok"] for e in report["samples"] for r in e["rows"])
    report["frontier_max_noise_at_detail_le10"] = max(
        [r["noise_drop_pct"] for e in report["samples"] for r in e["rows"]
         if r["axis2_detail_ok"]], default=None)
    (OUT_DIR / "calib_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== aggregate (median across samples) ===", flush=True)
    for t in table:
        print(f"{t['combo']:52s} noise={t['noise_drop_median']:7.2f}% "
              f"detail={t['detail_drop_median']:7.2f}% dE={t['de_median_stride_median']:6.3f} "
              f"all3={t['n_all3_ok']}/{t['n']} axis2ok={t['n_axis2_ok']}/{t['n']} "
              f"max_noise@detail<=10%={t['max_noise_drop_within_detail10_median']}", flush=True)
    print(f"\nANY_ALL3_OK = {report['any_all3_ok']}", flush=True)
    print(f"[wrote] {OUT_DIR / 'calib_report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
