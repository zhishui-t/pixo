"""render_dcp —— NEF/DNG + DCP 极简渲染, 保证两者输出一致。

用法:
  python rawlab/tools/render_dcp.py --raw <NEF|DNG> --dcp <dcp> \
      [--dng-pair <同名DNG>] --out <jpg|tif>

NEF 场景:
  1) 从配对 DNG 读取 opcode/白点/影调探针;
  2) 用 rawpy 把 NEF mosaic 线性化到与 DNG Stage2 完全一致;
  3) 走与 DNG 文件相同的 DCP 底座渲染。
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from rawlab.tools.dng_linear_probe import render_from_stage3
from rawlab.tools.dng_stage3_replicate import dng_resample, run_engine
from rawlab.engine.decode import decode_dng_stage3_like
from rawlab.engine.color import cam_wb_to_prophoto, dng_linear_prophoto_to_srgb
from rawlab.engine.huesat import apply_hue_sat_map_prophoto, apply_look_table_prophoto
from rawlab.engine.dng_render import dng_exposure_ramp, apply_dng_rgb_tone, load_dng_tone_table
from rawlab.engine.decode import camera_neutral_wb
from rawlab.engine.render_base import render_dcp_linear


def save_stage3(img, path):
    H, W = img.shape[:2]
    with open(path, "wb") as f:
        np.array([W, H], dtype="<u4").tofile(f)
        img.astype("<f4").tofile(f)


def to_gamma8(x):
    x = np.clip(x, 0, 1)
    y = np.where(x <= 0.0031308, 12.92 * x,
                 1.055 * np.power(x, 1.0 / 2.4) - 0.055)
    return (np.clip(y, 0, 1) * 255.0 + 0.5).astype(np.uint8)


def nef_key(path):
    import exifread
    with open(path, 'rb') as f:
        tags = exifread.process_file(f, details=False)
    return (str(tags.get('Image Model', '')).strip(),
            str(tags.get('EXIF LensModel', '')).strip(),
            str(tags.get('EXIF FocalLength', '')).strip())


def render_base_from_image(img, dcp_path, raw_path, entry):
    import json, rawpy
    from rawlab.dcp import load_dcp
    prof = load_dcp(dcp_path)
    rp = rawpy.imread(str(raw_path))
    wb = camera_neutral_wb(rp)
    rp.close()
    src = dng_resample(img, tuple(entry['src_bounds']), tuple(entry['dst_size']))
    pp = cam_wb_to_prophoto(src, prof, wb)
    pp = apply_hue_sat_map_prophoto(pp, prof, 1.0)
    baseline_ev = entry['total_baseline'] - np.log2(entry['stage3_gain'])
    pp = dng_exposure_ramp(pp, baseline_ev)
    pp = apply_look_table_prophoto(pp, prof, 1.0)
    table = load_dng_tone_table(entry['tone_table'])
    pp = apply_dng_rgb_tone(pp, table)
    return dng_linear_prophoto_to_srgb(pp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--dcp", required=True)
    ap.add_argument("--dng-pair", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    raw = Path(args.raw)
    cache = raw.parent / "rawflow_render_cache"
    cache.mkdir(exist_ok=True)
    pair = Path(args.dng_pair) if args.dng_pair else (
        raw if raw.suffix.lower() == ".dng" else None)
    if pair is None:
        t0 = time.time()
        lin = render_dcp_linear(raw, args.dcp)
        print(f"[render_dcp] base render {time.time()-t0:.2f}s")
        ref_tif = None
    else:
        stem = raw.stem
        stage_raw = cache / f"{stem}_nef.stage3.raw"
        print(f"[render_dcp] decode {raw} (dng_pair={pair}) ...")
        t0 = time.time()
        img, rawpy_obj = decode_dng_stage3_like(str(raw), dng_pair=str(pair))
        rawpy_obj.close()
        print(f"[render_dcp] stage3 {img.shape} decode={time.time()-t0:.2f}s")
        save_stage3(img, stage_raw)
        print("[render_dcp] dng_engine probes ...")
        _, ref_tif, tone_path, _ = run_engine(str(pair), args.dcp, cache, stem)
        log = cache / f"{stem}.engine.log"
        lin, state = render_from_stage3(
            stage_raw, str(pair), args.dcp, log, hsm=True, tone_table=tone_path)
    out = Path(args.out)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        cv2.imwrite(str(out), cv2.cvtColor(to_gamma8(lin), cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
    else:
        cv2.imwrite(str(out), cv2.cvtColor(lin, cv2.COLOR_RGB2BGR))
    if ref_tif is not None:
        ref = cv2.cvtColor(cv2.imread(str(ref_tif), cv2.IMREAD_UNCHANGED)
                           .astype(np.float32), cv2.COLOR_BGR2RGB)
        d = lin - ref
        print(f"[render_dcp] wrote {out}  mae_vs_dng={float(np.abs(d).mean()):.6e}")
    else:
        print(f"[render_dcp] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
