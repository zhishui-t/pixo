"""生成 HTML 对照页: 引擎渲染 vs 相机预览 并排 + 每张指标, 供人工目视验收。

用法: python rawlab/tools/make_contact_sheet.py --n 12 --mode engine
输出: rawlab/out/contact_sheet/index.html (浏览器直接打开)
"""
import argparse
import glob
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rawlab.dcp import load_dcp
from rawlab.tools.batch_iter import camera_preview

DEFAULT_DCP = r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp"
DEFAULT_RAW_DIRS = [r"K:\data\photo\0711\raw", r"K:\data\photo\2026春节"]
OUT = Path(__file__).resolve().parent.parent / "out" / "contact_sheet"


def metrics(mine, cam):
    cam_s = cv2.resize(cam, (mine.shape[1], mine.shape[0]),
                       interpolation=cv2.INTER_AREA)
    gm = cv2.cvtColor(mine, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gc = cv2.cvtColor(cam_s, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lm = cv2.cvtColor(mine, cv2.COLOR_RGB2LAB).astype(np.float32)
    lc = cv2.cvtColor(cam_s, cv2.COLOR_RGB2LAB).astype(np.float32)
    chroma_c = np.sqrt((lc[:, :, 1] - 128) ** 2 + (lc[:, :, 2] - 128) ** 2)
    neu = (chroma_c < 12) & (lc[:, :, 0] > 40) & (lc[:, :, 0] < 240)
    return {
        "d_med": float(np.median(gm) - np.median(gc)),
        "d_a": float(np.median(lm[:, :, 1]) - np.median(lc[:, :, 1])),
        "d_b": float(np.median(lm[:, :, 2]) - np.median(lc[:, :, 2])),
        "neu_a": float(np.median(lm[:, :, 1][neu] - 128)) if neu.sum() > 500 else float("nan"),
        "neu_b": float(np.median(lm[:, :, 2][neu] - 128)) if neu.sum() > 500 else float("nan"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="engine", choices=["baseline", "engine"])
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--dcp", default=os.environ.get("RAWLAB_DCP", DEFAULT_DCP))
    ap.add_argument("--raw-dir", action="append", default=None, help="RAW 目录, 可多次指定")
    args = ap.parse_args()

    prof = load_dcp(args.dcp)
    if args.mode == "engine":
        from rawlab.engine import build_default_pipeline
        pipe = build_default_pipeline(prof=prof)

    raw_dirs = args.raw_dir
    if not raw_dirs:
        env = os.environ.get("RAWLAB_RAW_DIRS")
        raw_dirs = [d for d in env.split(";") if d] if env else DEFAULT_RAW_DIRS
    files = []
    for d in raw_dirs:
        files.extend(sorted(glob.glob(os.path.join(d, "*.NEF"))))
    files = files[args.start: args.start + args.n]

    img_dir = OUT / args.mode
    img_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in files:
        name = os.path.basename(f)
        try:
            if args.mode == "baseline":
                from rawlab.render import render
                mine = render(f, prof, half_size=True)
            else:
                mine = pipe.run_file(f, half_size=True)
            cam = camera_preview(f)
            if cam is None:
                continue
            cam_s = cv2.resize(cam, (mine.shape[1], mine.shape[0]),
                               interpolation=cv2.INTER_AREA)
            pair = np.concatenate([cam_s, mine], axis=1)
            pair = cv2.resize(pair, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            p = img_dir / f"{name}.jpg"
            cv2.imwrite(str(p), cv2.cvtColor(pair, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
            m = metrics(mine, cam)
            rows.append((name, f"{args.mode}/{name}.jpg", m))
            print(f"  {name}: d_med={m['d_med']:+.0f} d_a={m['d_a']:+.1f} "
                  f"d_b={m['d_b']:+.1f} neu=({m['neu_a']:+.1f},{m['neu_b']:+.1f})")
        except Exception as e:
            print(f"  {name}: ERROR {e}")

    parts = ["""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>rawlab 对照页</title><style>
body{font-family:system-ui;margin:20px;background:#222;color:#ddd}
h1{font-size:20px}.grid{display:flex;flex-wrap:wrap;gap:24px}
.card{background:#333;padding:10px;border-radius:8px;width:min(64vw,1150px)}
.card img{width:100%;border-radius:4px}
.meta{font:12px monospace;color:#9cf;margin-top:6px}
.ok{color:#8f8}.warn{color:#fa8}.bad{color:#f88}
</style></head><body><h1>rawlab 引擎对照 (左=相机预览 右=引擎渲染)</h1><div class="grid">"""]
    for name, rel, m in rows:
        cls = "ok" if abs(m["d_med"]) <= 12 else ("warn" if abs(m["d_med"]) <= 25 else "bad")
        parts.append(
            f'<div class="card"><img src="{rel}">'
            f'<div class="meta">{name} &nbsp; d_med=<span class="{cls}">{m["d_med"]:+.0f}</span>'
            f' d_a={m["d_a"]:+.1f} d_b={m["d_b"]:+.1f}'
            f' neu_a={m["neu_a"]:+.1f} neu_b={m["neu_b"]:+.1f}</div></div>')
    parts.append("</div></body></html>")
    html = OUT / "index.html"
    html.write_text("".join(parts), encoding="utf-8")
    print(f"\n对照页 -> {html}")


if __name__ == "__main__":
    main()
