"""验收基准: 自研渲染 vs 相机内嵌预览 (曝光亮度差 + 白平衡 Lab 偏色)。

--mode baseline : 旧管线 render() (apply_cal=True)
--mode engine   : 新引擎 pipeline (rawlab.engine)
--n N           : 照片数
--out dir       : 输出对比图目录 (并排拼接)

指标 (每张):
  d_med   : 全图中位亮度差 (mine - cam)
  d_a,d_b : Lab a/b 中位差 (mine - cam), 白平衡/色彩偏色
  d_a_neu, d_b_neu : 相机预览低色度区域 (中性区) 上 mine 的 a/b 均值, 直接度量 WB 偏色
"""
import argparse
import glob
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rawlab.dcp import load_dcp
from rawlab.tools.batch_iter import camera_preview

DEFAULT_DCP = r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp"
DEFAULT_RAW_DIRS = [r"K:\data\photo\0711\raw", r"K:\data\photo\2026春节"]
OUT_ROOT = Path(__file__).resolve().parent.parent / "out" / "engine_verify"


def _raw_dirs(args):
    """RAW 目录解析: --raw-dir 多次指定 > 环境变量 RAWLAB_RAW_DIRS(;分隔) > 内置默认。"""
    if args.raw_dir:
        return args.raw_dir
    env = os.environ.get("RAWLAB_RAW_DIRS")
    return [d for d in env.split(";") if d] if env else DEFAULT_RAW_DIRS


def lab_stats(rgb):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab


def metrics(mine, cam):
    """mine/cam: 8bit RGB 同尺寸。返回指标 dict。"""
    cam_s = cv2.resize(cam, (mine.shape[1], mine.shape[0]), interpolation=cv2.INTER_AREA)
    gm = cv2.cvtColor(mine, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gc = cv2.cvtColor(cam_s, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lm, lc = lab_stats(mine), lab_stats(cam_s)
    # 中性区: 相机预览低色度 (C*<12) 且中等亮度
    chroma_c = np.sqrt((lc[:, :, 1] - 128) ** 2 + (lc[:, :, 2] - 128) ** 2)
    neu = (chroma_c < 12) & (lc[:, :, 0] > 40) & (lc[:, :, 0] < 240)
    return {
        "d_med": float(np.median(gm) - np.median(gc)),
        "d_mean": float(gm.mean() - gc.mean()),
        "d_a": float(np.median(lm[:, :, 1]) - np.median(lc[:, :, 1])),
        "d_b": float(np.median(lm[:, :, 2]) - np.median(lc[:, :, 2])),
        "d_a_neu": float(np.median(lm[:, :, 1][neu]) - 128) if neu.sum() > 500 else np.nan,
        "d_b_neu": float(np.median(lm[:, :, 2][neu]) - 128) if neu.sum() > 500 else np.nan,
        "n_neu": int(neu.sum()),
    }


def side_by_side(mine, cam, w=1400):
    """拼接对比图: cam | mine, 等比缩放。"""
    cam_s = cv2.resize(cam, (mine.shape[1], mine.shape[0]), interpolation=cv2.INTER_AREA)
    s = w / (2 * mine.shape[1])
    a = cv2.resize(mine, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    b = cv2.resize(cam_s, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    bar = np.full((a.shape[0], 8, 3), 255, np.uint8)
    return np.concatenate([b, bar, a], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="baseline", choices=["baseline", "engine"])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default=None)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--save-all", action="store_true", help="保存全部对比图")
    ap.add_argument("--dcp", default=os.environ.get("RAWLAB_DCP", DEFAULT_DCP))
    ap.add_argument("--raw-dir", action="append", default=None, help="RAW 目录, 可多次指定")
    args = ap.parse_args()

    prof = load_dcp(args.dcp)
    if args.mode == "engine":
        from rawlab.engine import build_default_pipeline
        pipe = build_default_pipeline(prof=prof)

    files = []
    for d in _raw_dirs(args):
        files.extend(glob.glob(os.path.join(d, "*.NEF")))
    files = sorted(files)[args.start: args.start + args.n]
    out_dir = OUT_ROOT / args.mode
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, t0 = [], time.time()
    for i, f in enumerate(files):
        name = os.path.basename(f)
        try:
            if args.mode == "baseline":
                from rawlab.render import render
                mine = render(f, prof, half_size=True)
            else:
                mine = pipe.run_file(f, half_size=True)
            cam = camera_preview(f)
            if cam is None:
                rows.append({"file": name, "error": "no preview"})
                continue
            m = metrics(mine, cam)
            m["file"] = name
            rows.append(m)
            print(f"  [{i+1:3d}/{len(files)}] {name}: d_med={m['d_med']:+6.1f} "
                  f"d_a={m['d_a']:+5.1f} d_b={m['d_b']:+5.1f} "
                  f"neu_a={m['d_a_neu']:+5.1f} neu_b={m['d_b_neu']:+5.1f}")
            if args.save_all or i < 12:
                pair = side_by_side(mine, cam)
                cv2.imwrite(str(out_dir / f"{name}.cmp.jpg"),
                            cv2.cvtColor(pair, cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_JPEG_QUALITY, 92])
        except Exception as e:
            rows.append({"file": name, "error": str(e)})
            print(f"  [{i+1:3d}] {name}: ERROR {e}")

    ok = [r for r in rows if "d_med" in r]
    print(f"\n=== {args.mode} 汇总 n={len(ok)}  ({time.time()-t0:.0f}s) ===")
    for k in ("d_med", "d_a", "d_b"):
        v = np.array([r[k] for r in ok])
        print(f"  {k:6s}: mean={v.mean():+6.2f}  median={np.median(v):+6.2f}  "
              f"|mean|={np.abs(v).mean():6.2f}  std={v.std():6.2f}")
    va = np.array([r["d_a_neu"] for r in ok if not np.isnan(r["d_a_neu"])])
    vb = np.array([r["d_b_neu"] for r in ok if not np.isnan(r["d_b_neu"])])
    if len(va):
        print(f"  中性区 WB: a={va.mean():+5.2f}±{va.std():.2f}  b={vb.mean():+5.2f}±{vb.std():.2f}")

    report = out_dir / "report.json"
    import json
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report -> {report}")


if __name__ == "__main__":
    main()
