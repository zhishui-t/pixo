"""pixo.render 功能 golden 回归生成/对比工具 (t35)。

用法:
  # 生成基线
  python render/tools/gate_golden.py generate \
      --raw K:/data/photo/0711/raw/DSC_5236.NEF \
      --dcp K:/work/project/pixo/pixo/render/profiles/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp \
      --out render/bench/goldens/gate --long-edge 512

  # 对比当前输出与基线
  python render/tools/gate_golden.py compare \
      --raw K:/data/photo/0711/raw/DSC_5236.NEF \
      --dcp K:/work/project/pixo/pixo/render/profiles/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp \
      --out render/bench/goldens/gate --long-edge 512

阈值：8-bit max|Δ| ≤1/255；16-bit max|Δ| ≤1/65535（确定性路径应逐位）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pixo.render.api import Renderer

# 每个调整功能一组代表性参数（覆盖 FUNCTION_GATE_SPEC §5 八个 feature）。
FEATURES: Dict[str, Dict[str, Any]] = {
    "exposure": {
        "exposure": {"mode": 0.7, "max_ev": 2.5, "rolloff_knee": 0.9},
    },
    "whitebalance": {
        "whitebalance": {"mode": "manual", "temp": 5500.0, "tint": 5.0},
    },
    "tone": {
        "tone": {"contrast": 0.3, "brightness": 0.5,
                 "highlights": 0.2, "shadows": 0.2,
                 "whites": 0.1, "blacks": -0.1},
    },
    "hsl": {
        "hsl": {
            "enabled": True,
            "bands": json.dumps([
                {"name": "red", "hue_center": 0, "width": 45,
                 "hue_shift": 5.0, "saturation": 10.0, "luminance": 5.0},
                {"name": "blue", "hue_center": 240, "width": 45,
                 "hue_shift": -3.0, "saturation": 8.0, "luminance": 2.0},
            ]),
        },
    },
    "split_tone": {
        "split_tone": {"enabled": True, "shadows_hue": 45.0,
                       "shadows_sat": 30.0, "highlights_hue": 210.0,
                       "highlights_sat": 20.0, "balance": 0.5,
                       "strength": 0.8},
    },
    "calibration": {
        "calibration": {"enabled": True, "shadow_tint": 5.0,
                        "red_hue": 5.0, "red_sat": 10.0,
                        "green_hue": -3.0, "green_sat": 5.0,
                        "blue_hue": 2.0, "blue_sat": 8.0},
    },
    "skin": {
        "skin": {"enabled": True, "strength": 0.5},
    },
    "refine": {
        "refine": {"sharpen": 0.6, "chroma_denoise": 1.2,
                   "highlight_desat": 0.8},
    },
}

THRESHOLD_U8 = 1   # 1/255
THRESHOLD_U16 = 1  # 1/65535


def _sha256(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def _render(renderer: Renderer, raw_path: Path, long_edge: int,
            params: Dict[str, Any], output_bps: int) -> np.ndarray:
    return renderer.render_preview_full(
        raw_path, long_edge=long_edge, params=params, output_bps=output_bps)


def _generate_one(renderer: Renderer, raw_path: Path, dcp_path: Path,
                  feature: str, out_dir: Path, long_edge: int) -> Dict[str, Any]:
    feat_dir = out_dir / feature
    feat_dir.mkdir(parents=True, exist_ok=True)
    params = FEATURES[feature]
    u8 = _render(renderer, raw_path, long_edge, params, 8)
    u16 = _render(renderer, raw_path, long_edge, params, 16)
    p8 = feat_dir / "output_u8.npy"
    p16 = feat_dir / "output_u16.npy"
    np.save(p8, u8)
    np.save(p16, u16)
    return {
        "feature": feature,
        "params": params,
        "long_edge": int(long_edge),
        "raw": str(raw_path),
        "dcp": str(dcp_path),
        "files": {"u8": str(p8.relative_to(out_dir.parent)),
                  "u16": str(p16.relative_to(out_dir.parent))},
        "sha256_u8": _sha256(u8),
        "sha256_u16": _sha256(u16),
        "shape_u8": list(u8.shape),
        "shape_u16": list(u16.shape),
    }


def cmd_generate(args) -> int:
    raw_path = Path(args.raw)
    dcp_path = Path(args.dcp)
    out_dir = Path(args.out)
    if not raw_path.exists() or not dcp_path.exists():
        print("[gate_golden] raw/dcp 不存在", file=sys.stderr)
        return 2
    renderer = Renderer(dcp_path)
    manifest: Dict[str, Any] = {
        "schema": "render-gate-golden-v1",
        "long_edge": args.long_edge,
        "raw": str(raw_path),
        "dcp": str(dcp_path),
        "features": {},
    }
    for feature in FEATURES:
        print(f"[gate_golden] generate {feature} ...", flush=True)
        manifest["features"][feature] = _generate_one(
            renderer, raw_path, dcp_path, feature, out_dir, args.long_edge)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print(f"[gate_golden] manifest -> {manifest_path}")
    return 0


def cmd_compare(args) -> int:
    raw_path = Path(args.raw)
    dcp_path = Path(args.dcp)
    out_dir = Path(args.out)
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"[gate_golden] manifest 不存在: {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    renderer = Renderer(dcp_path)
    failed = False
    print(f"{'feature':<14s} {'u8_max':>8s} {'u16_max':>8s} verdict")
    for feature, meta in manifest["features"].items():
        params = meta["params"]
        curr8 = _render(renderer, raw_path, args.long_edge, params, 8)
        curr16 = _render(renderer, raw_path, args.long_edge, params, 16)
        gold8 = np.load(out_dir / feature / "output_u8.npy")
        gold16 = np.load(out_dir / feature / "output_u16.npy")
        d8 = int(np.abs(curr8.astype(np.int16) - gold8.astype(np.int16)).max())
        d16 = int(np.abs(curr16.astype(np.int32) - gold16.astype(np.int32)).max())
        ok = d8 <= THRESHOLD_U8 and d16 <= THRESHOLD_U16
        failed = failed or not ok
        print(f"{feature:<14s} {d8:>8d} {d16:>8d} {'PASS' if ok else 'FAIL'}")
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("generate", cmd_generate), ("compare", cmd_compare)):
        p = sub.add_parser(name)
        p.add_argument("--raw", required=True)
        p.add_argument("--dcp", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--long-edge", type=int, default=512)
        p.set_defaults(func=fn)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
