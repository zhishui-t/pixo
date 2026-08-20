"""measure_engine —— 渲染引擎色彩/曝光/噪声统一测量工具。

每个 RAW:
  - 定位 LR 导出 JPEG (target dirs 内 <stem>.jpg) 或机内预览;
  - 渲染 half/full, 裁有效画面, 对齐;
  - 输出:
      exposure : L median/p5/p95/p99, dEV, clip/shadow fraction
      color    : full/neutral/skin/highlight Lab, 12 hue sectors, 6x6 grid
      noise    : luma Laplacian std, chroma a/b Laplacian std (ours/target)
  - JSON + Markdown 报告。
"""
from __future__ import annotations
import argparse, glob, json, sys, time
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rawlab.engine.skin import skin_mask
from rawlab.tools.color_probe import (full_stats, grid_stats,
                                      hue_sector_stats, luma_band_stats,
                                      neutral_stats, skin_stats)
from rawlab.tools.fit_camera_profile import srgb_inv
from rawlab.tools.regress_anchors import (align_target, build_runtime,
                                          crop_active_oriented,
                                          load_target_jpeg)

LUM = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _gray(rgb):
    return (rgb.astype(np.float32) @ LUM).astype(np.float32)


def exposure_stats(ours, target):
    go, gt = _gray(ours), _gray(target)
    lo = np.log2(np.maximum(srgb_inv(ours.astype(np.float32) / 255.0), 1e-6))
    lt = np.log2(np.maximum(srgb_inv(target.astype(np.float32) / 255.0), 1e-6))
    def q(a, p):
        return round(float(np.percentile(a, p)), 3)
    return {
        "dL_med": round(float(np.median(go) - np.median(gt)), 3),
        "dEV": round(float(np.median(lo) - np.median(lt)), 4),
        "L_ours": [q(go, 5), q(go, 50), q(go, 95), q(go, 99)],
        "L_target": [q(gt, 5), q(gt, 50), q(gt, 95), q(gt, 99)],
        "clip_ours_pct": round(float((np.max(ours, axis=2) >= 254).mean() * 100), 3),
        "clip_target_pct": round(float((np.max(target, axis=2) >= 254).mean() * 100), 3),
        "shadow_ours_pct": round(float((np.max(ours, axis=2) <= 5).mean() * 100), 3),
        "shadow_target_pct": round(float((np.max(target, axis=2) <= 5).mean() * 100), 3),
    }


def noise_stats(ours, target):
    go, gt = _gray(ours), _gray(target)
    lab_o = cv2.cvtColor(ours, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab_t = cv2.cvtColor(target, cv2.COLOR_RGB2LAB).astype(np.float32)
    return {
        "luma_lap_std": [round(float(cv2.Laplacian(go, cv2.CV_32F).std()), 3),
                         round(float(cv2.Laplacian(gt, cv2.CV_32F).std()), 3)],
        "chroma_a_lap_std": [round(float(cv2.Laplacian(lab_o[..., 1], cv2.CV_32F).std()), 3),
                             round(float(cv2.Laplacian(lab_t[..., 1], cv2.CV_32F).std()), 3)],
        "chroma_b_lap_std": [round(float(cv2.Laplacian(lab_o[..., 2], cv2.CV_32F).std()), 3),
                             round(float(cv2.Laplacian(lab_t[..., 2], cv2.CV_32F).std()), 3)],
    }


def measure_one(ours_u8, target_u8):
    target_u8 = align_target(np.asarray(target_u8), ours_u8.shape[:2])
    return {
        "exposure": exposure_stats(ours_u8, target_u8),
        "noise": noise_stats(ours_u8, target_u8),
        "full": full_stats(ours_u8, target_u8),
        "neutral": neutral_stats(ours_u8, target_u8),
        "skin": skin_stats(ours_u8, target_u8),
        "hue_sectors": hue_sector_stats(ours_u8, target_u8),
        "luma_bands": luma_band_stats(ours_u8, target_u8),
        "grid6": grid_stats(ours_u8, target_u8, n=6),
    }


def find_raws(raw_dirs, n=0):
    files = []
    for d in raw_dirs:
        files.extend(sorted(Path(d).rglob('*.NEF')))
    files = [f for f in files if not f.name.startswith('._')]
    return files[:n] if n else files


def run_measure(raw_paths, target_dirs, preset_path, dcp_path=None, half_size=True):
    prof, pipe, _, _ = build_runtime(dcp_path, preset_path)
    rows = []
    for raw_path in raw_paths:
        raw_path = Path(raw_path)
        stem = raw_path.stem
        target = None
        for d in target_dirs:
            target = load_target_jpeg(d, stem)
            if target is not None:
                break
        if target is None:
            rows.append({"stem": stem, "error": "no_target"})
            continue
        import rawpy
        ours = pipe.run_file(raw_path, prof=prof, half_size=half_size)
        with rawpy.imread(str(raw_path)) as raw:
            ours = crop_active_oriented(ours, raw)
        try:
            meta = json.loads((Path(target_dirs[0]) / f"{stem}.meta.json").read_text(encoding='utf-8'))
            wb_b = float(meta.get("wb_b", meta["wb"][2] / meta["wb"][1]))
        except Exception:
            wb_b = None
        m = measure_one(ours, target)
        m.update({"stem": stem, "wb_b": None if wb_b is None else round(wb_b, 4),
                  "raw": str(raw_path)})
        rows.append(m)
        print(f"[measure] {stem} dEV={m['exposure']['dEV']:+.3f} "
              f"da={m['full']['da']:+.1f} db={m['full']['db']:+.1f}", flush=True)
    return {"preset": preset_path, "targets": [str(d) for d in target_dirs],
            "rows": rows}


def write_report(report, out_json):
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ["# Engine Measure Report", ""]
    for r in report["rows"]:
        if r.get("error"):
            lines.append(f"- {r['stem']}: {r['error']}")
            continue
        e, f = r["exposure"], r["full"]
        sk = r["skin"]
        n = r["noise"]
        lines.append("")
        lines.append(f"## {r['stem']} (wb_B={r['wb_b']})")
        lines.append(f"- exposure: dEV={e['dEV']:+.3f} dLmed={e['dL_med']:+.1f} "
                     f"clip ours/tgt={e['clip_ours_pct']:.2f}/{e['clip_target_pct']:.2f}%")
        lines.append(f"- color: full da={f['da']:+.1f} db={f['db']:+.1f}")
        if sk:
            lines.append(f"- skin: da={sk['da']:+.1f} db={sk['db']:+.1f}")
        lines.append(f"- noise: luma_std ours/tgt={n['luma_lap_std'][0]:.1f}/{n['luma_lap_std'][1]:.1f} "
                     f"chroma_a={n['chroma_a_lap_std'][0]:.1f}/{n['chroma_a_lap_std'][1]:.1f}")
    out_json.with_suffix('.md').write_text(chr(10).join(lines), encoding='utf-8')
    return out_json


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preset', required=True)
    ap.add_argument('--dcp', default=None)
    ap.add_argument('--targets', required=True, help='逗号分隔的 LR 导出目录')
    ap.add_argument('--anchors', nargs='*', default=None)
    ap.add_argument('--raw-dirs', nargs='*', default=None)
    ap.add_argument('--n', type=int, default=0)
    ap.add_argument('--out-json', default=None)
    ap.add_argument('--full', action='store_true')
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    raw_paths = [Path(x) for x in args.anchors] if args.anchors else []
    if args.raw_dirs and (args.n or not raw_paths):
        raw_paths = find_raws(args.raw_dirs, args.n)
    if not raw_paths:
        print('no raw inputs'); return 1
    targets = [Path(x) for x in args.targets.split(',')]
    report = run_measure(raw_paths, targets, args.preset, args.dcp, half_size=not args.full)
    out = Path(args.out_json) if args.out_json else (
        ROOT / 'rawlab' / 'out' / 'profile_fit'
        / f'measure_engine_{time.strftime("%Y%m%d_%H%M%S")}.json')
    write_report(report, out)
    print(f'[measure-engine] -> {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
