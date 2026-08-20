"""dng_stage3_replicate —— 从 DNG SDK Stage3 原始采样复刻其线性渲染全链路。

定位用途 (DNG/DCP 基础正确性):
  dng_engine --render --linear 内部把 Stage3 图按 DefaultCropArea 裁剪后
  bicubic 重采样到 DefaultFinalSize, 然后:
    zero-offset(可选) -> CameraWhite*CameraToProPhoto -> HueSatMap
    -> PGTM(可选) -> ExposureRamp -> LookTable -> ProfileToneCurve(RGBTone)
    -> ProPhotoToLinearSRGB。
  本工具复用 dng_engine 的 --dump-stage3-raw / --dump-color-math 与
  DNG_DUMP_TONE_TABLE / DNG_DUMP_RESAMPLE_INFO 探针, 在 Python 侧逐步复刻,
  对比 dng_engine 输出的线性 sRGB TIFF。残差应 < 1e-4 (float32 量化级)。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from rawlux.core.resample import dng_resample  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from rawlab.dcp import load_dcp
from rawlab.engine.huesat import apply_hue_sat_map_prophoto, apply_look_table_prophoto

ENGINE = r"K:\work\project\guanlan\dng_engine\build17\Release\dng_engine.exe"


def run_engine(dng: str, dcp: str, out_dir: Path, stem: str,
               max_px: int = 1024):
    out_dir.mkdir(parents=True, exist_ok=True)
    stage_raw = out_dir / f"{stem}.stage3.raw"
    ref_tif = out_dir / f"{stem}.ref_linear.tif"
    tone_table = out_dir / f"{stem}.tone.table"
    log = out_dir / f"{stem}.engine.log"
    env = dict(os.environ)
    env["DNG_DUMP_RESAMPLE_INFO"] = "1"
    env["DNG_DUMP_TONE_TABLE"] = str(tone_table)
    cmd = [ENGINE, "--render", "--dng", str(dng), "--out", str(ref_tif),
           "--linear", "--max-px", str(max_px), "--profile", str(dcp),
           "--dump-stage3-raw", str(stage_raw), "--dump-color-math"]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env=env)
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    log.write_text(text, encoding="utf-8", errors="replace")
    if not ref_tif.exists() or not stage_raw.exists():
        raise RuntimeError(f"engine failed for {stem}:\n{text[-2000:]}")
    print(f"[{stem}] engine {time.time()-t0:.1f}s -> {ref_tif.name}")
    return stage_raw, ref_tif, tone_table, text


def parse_color_math(text: str):
    def vec3(line: str):
        m = re.search(r"\[([-\d.eE+]+),([-\d.eE+]+),([-\d.eE+]+)\]", line)
        if not m:
            raise ValueError(f"bad vector line: {line!r}")
        return np.array([float(m.group(1)), float(m.group(2)), float(m.group(3))],
                        np.float32)

    def mat3(lines, i):
        return np.array([vec3(lines[i]), vec3(lines[i + 1]), vec3(lines[i + 2])],
                        np.float32)

    lines = text.splitlines()
    info = {}
    for n, line in enumerate(lines):
        if line.startswith("[resample-info]"):
            m = re.search(r"srcBounds=\(([-\d]+),([-\d]+),([-\d]+),([-\d]+)\) "
                          r"stageBounds=\(([-\d]+),([-\d]+),([-\d]+),([-\d]+)\) "
                          r"dstSize=\(([-\d]+),([-\d]+)\)", line)
            if m:
                info["src_bounds"] = tuple(int(x) for x in m.groups()[:4])
                info["stage_bounds"] = tuple(int(x) for x in m.groups()[4:8])
                info["dst_size"] = (int(m.group(9)), int(m.group(10)))
        if "[color-math] CameraWhite=" in line:
            info["camera_white"] = vec3(line.split("CameraWhite=", 1)[1])
        if "[color-math] CameraToProPhoto=" in line:
            info["cam_to_pp"] = mat3(lines, n + 1)
        if "[color-math] ProPhotoToLinearSRGB=" in line:
            info["pp_to_srgb"] = mat3(lines, n + 1)
        if "[color-math] Stage3Gain=" in line:
            m = re.search(r"Stage3Gain=([-\d.eE+]+) Stage3BlackLevel=([-\d]+)", line)
            if m:
                info["stage3_gain"] = float(m.group(1))
                info["stage3_black"] = int(m.group(2))
        if "[color-math] TotalBaselineExposure=" in line:
            m = re.search(r"TotalBaselineExposure=([-\d.eE+]+)", line)
            if m:
                info["total_baseline"] = float(m.group(1))
    required = ["src_bounds", "stage_bounds", "dst_size", "camera_white",
                "cam_to_pp", "pp_to_srgb", "stage3_gain", "stage3_black",
                "total_baseline"]
    missing = [k for k in required if k not in info]
    if missing:
        raise ValueError(f"missing color math fields {missing}")
    return info


def abc_to_prophoto(img: np.ndarray, white: np.ndarray, m: np.ndarray):
    a = np.minimum(img, white[np.newaxis, np.newaxis, :])
    out = np.empty_like(a)
    for c in range(3):
        out[..., c] = np.float32(a[..., 0] * m[c, 0]
                                 + a[..., 1] * m[c, 1]
                                 + a[..., 2] * m[c, 2])
    return np.clip(out, 0.0, 1.0)


def exposure_ramp(img: np.ndarray, baseline_ev: float) -> np.ndarray:
    # dng_render: white = 1 / 2^max(0, exposure), black=0 -> 斜率 = 1/white。
    # exposure<0 时 ramp 为恒等, 负补偿由 totalTone 的 exposureTone 承担
    # (dumped tone table 已含该段)。
    gain = np.float32(2.0 ** max(0.0, float(baseline_ev)))
    return np.clip(img * gain, 0.0, 1.0)


def tone_table_interp(table: np.ndarray, x: np.ndarray) -> np.ndarray:
    n = np.float32(len(table) - 2)  # fTableCount
    y = np.float32(x * n)
    idx = np.floor(y).astype(np.int32)
    z = idx.astype(np.float32)
    fract = np.float32(y - z)
    idx = np.clip(idx, 0, len(table) - 2)
    return np.float32(table[idx] * np.float32(1.0 - fract)
                      + table[idx + 1] * fract)



def rgb_tone(img: np.ndarray, table: np.ndarray) -> np.ndarray:
    """RefBaselineRGBTone 的 7 分支逐像素复刻 (float32)。"""
    img = np.clip(img, 0.0, 1.0).astype(np.float32)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    rr = np.empty_like(r)
    gg = np.empty_like(g)
    bb = np.empty_like(b)

    def interp(x):
        return tone_table_interp(table, x)

    m1 = (r >= g) & (g > b)
    if np.any(m1):
        tr, tb = interp(r[m1]), interp(b[m1])
        rr[m1] = tr
        bb[m1] = tb
        gg[m1] = np.float32(tb + np.float32(np.float32(tr - tb)
                                            * np.float32(g[m1] - b[m1]))
                            / np.float32(r[m1] - b[m1]))
    m2 = (r >= g) & ~(g > b) & (b > r)
    if np.any(m2):
        tb, tg = interp(b[m2]), interp(g[m2])
        bb[m2] = tb
        gg[m2] = tg
        rr[m2] = np.float32(tg + np.float32(np.float32(tb - tg)
                                            * np.float32(r[m2] - g[m2]))
                            / np.float32(b[m2] - g[m2]))
    m3 = (r >= g) & ~(g > b) & ~(b > r) & (b > g)
    if np.any(m3):
        tr, tg = interp(r[m3]), interp(g[m3])
        rr[m3] = tr
        gg[m3] = tg
        bb[m3] = np.float32(tg + np.float32(np.float32(tr - tg)
                                            * np.float32(b[m3] - g[m3]))
                            / np.float32(r[m3] - g[m3]))
    m4 = (r >= g) & ~(g > b) & ~(b > r) & ~(b > g)
    if np.any(m4):
        rr[m4] = interp(r[m4])
        gg[m4] = interp(g[m4])
        bb[m4] = gg[m4]
    m5 = (r < g) & (r >= b)
    if np.any(m5):
        tg, tb = interp(g[m5]), interp(b[m5])
        gg[m5] = tg
        bb[m5] = tb
        rr[m5] = np.float32(tb + np.float32(np.float32(tg - tb)
                                            * np.float32(r[m5] - b[m5]))
                            / np.float32(g[m5] - b[m5]))
    m6 = (r < g) & ~(r >= b) & (b > g)
    if np.any(m6):
        tb, tr = interp(b[m6]), interp(r[m6])
        bb[m6] = tb
        rr[m6] = tr
        gg[m6] = np.float32(tr + np.float32(np.float32(tb - tr)
                                            * np.float32(g[m6] - r[m6]))
                            / np.float32(b[m6] - r[m6]))
    m7 = (r < g) & ~(r >= b) & ~(b > g)
    if np.any(m7):
        tg, tr = interp(g[m7]), interp(r[m7])
        gg[m7] = tg
        rr[m7] = tr
        bb[m7] = np.float32(tr + np.float32(np.float32(tg - tr)
                                            * np.float32(b[m7] - r[m7]))
                            / np.float32(g[m7] - r[m7]))
    return np.stack([rr, gg, bb], axis=-1)


def load_tone_table(path) -> np.ndarray:
    b = Path(path).read_bytes()
    if len(b) < 8:
        raise ValueError(f"tone table too short: {path}")
    n = int(np.frombuffer(b[:4], dtype="<u4")[0])
    table = np.frombuffer(b[4:], dtype="<f4")
    if len(table) < n + 1:
        raise ValueError(f"tone table short {len(table)} < {n + 1}")
    table = table[:n + 1].astype(np.float32)
    return np.append(table, table[-1]).astype(np.float32)


def replicate(stage_raw: Path, tone_path: Path, dcp_path: str, info: dict):
    hdr = np.fromfile(stage_raw, dtype="<u4", count=2)
    sw, sh = int(hdr[0]), int(hdr[1])
    stage = np.fromfile(stage_raw, dtype="<f4", offset=8, count=sw * sh * 3)
    stage = stage.reshape(sh, sw, 3)
    sb = info["stage_bounds"]
    expected_w = sb[3] - sb[1]
    expected_h = sb[2] - sb[0]
    if (sw, sh) != (expected_w, expected_h):
        print(f"  note: stage raw {sw}x{sh} vs stage bounds {expected_w}x{expected_h}")
    if info["stage3_black"]:
        # 本批 DNG 均为 0; 若出现非 0, dng_function_zero_offset 尚待复刻。
        raise NotImplementedError("Stage3BlackLevel != 0 未复刻")
    if info["src_bounds"] == info["stage_bounds"] and info["dst_size"] == (
            expected_w, expected_h):
        src = stage
    else:
        src = dng_resample(stage, info["src_bounds"], info["dst_size"])
    pp = abc_to_prophoto(src, info["camera_white"], info["cam_to_pp"])
    prof = load_dcp(dcp_path)
    # HueSatMap (0xC6FA) 在 ExposureRamp 之前; LookTable (0xC726) 在之后。
    pp = apply_hue_sat_map_prophoto(pp, prof, 1.0)
    baseline_ev = info["total_baseline"] - np.log2(info["stage3_gain"])
    pp = exposure_ramp(pp, float(baseline_ev))
    pp = apply_look_table_prophoto(pp, prof, 1.0)
    table = load_tone_table(tone_path)
    pp = rgb_tone(pp, table)
    m = info["pp_to_srgb"]
    out = np.empty_like(pp)
    for c in range(3):
        out[..., c] = np.float32(pp[..., 0] * m[c, 0]
                                 + pp[..., 1] * m[c, 1]
                                 + pp[..., 2] * m[c, 2])
    return np.clip(out, 0.0, 1.0)


def metrics(ours: np.ndarray, ref: np.ndarray, scaled: bool = False):
    ref = np.asarray(ref, np.float32)
    if scaled:
        luma = np.array([0.2126, 0.7152, 0.0722], np.float32)
        scale = float(np.median(ref @ luma) / max(np.median(ours @ luma), 1e-9))
        ours = np.clip(ours * scale, 0.0, None)
    diff = ours - ref
    out = {"mae": float(np.abs(diff).mean())}
    for i, ch in enumerate("RGB"):
        d = diff[..., i]
        out[f"{ch}_mae"] = float(np.abs(d).mean())
        out[f"{ch}_p95"] = float(np.percentile(np.abs(d), 95))
        out[f"{ch}_mean"] = float(d.mean())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dng", required=True)
    ap.add_argument("--dcp", required=True)
    ap.add_argument("--out-dir", default=r"K:\dsh-share\dng_verify\replicate")
    ap.add_argument("--stem", default=None)
    ap.add_argument("--max-px", type=int, default=1024)
    ap.add_argument("--write-ours", action="store_true")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    stem = args.stem or Path(args.dng).stem
    stage_raw, ref_tif, tone_path, text = run_engine(
        args.dng, args.dcp, out_dir, stem, args.max_px)
    info = parse_color_math(text)
    print(f"[{stem}] crop={info['src_bounds']} stage={info['stage_bounds']} "
          f"dst={info['dst_size']} baseline={info['total_baseline']} "
          f"Stage3Gain={info['stage3_gain']}")
    t0 = time.time()
    ours = replicate(stage_raw, tone_path, args.dcp, info)
    print(f"[{stem}] python replicate {time.time()-t0:.1f}s")
    ref = cv2.imread(str(ref_tif), cv2.IMREAD_UNCHANGED)
    if ref is None:
        raise RuntimeError(f"cannot read ref {ref_tif}")
    ref = cv2.cvtColor(ref.astype(np.float32), cv2.COLOR_BGR2RGB)
    if ours.shape != ref.shape:
        ours = cv2.resize(ours, (ref.shape[1], ref.shape[0]),
                          interpolation=cv2.INTER_AREA)
    print("raw:", metrics(ours, ref))
    print("scaled:", metrics(ours, ref, scaled=True))
    if args.write_ours:
        p = out_dir / f"{stem}.py_linear.tif"
        cv2.imwrite(str(p), cv2.cvtColor(ours, cv2.COLOR_RGB2BGR))
        print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
