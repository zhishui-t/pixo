"""Gate L2 golden 生成器（FUNCTION_GATE_SPEC §6）。

用法:
  python render/tests/goldens/generate_gate_goldens.py \
      --out render/tests/goldens/gate

生成后必须由 reviewer 复核 diff 并更新 manifest.reviewer，不得与实现改动
在同一次提交中静默合入。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import gate_cases


def build_manifest(out_dir: Path) -> dict:
    manifest = {
        "schema": "render-gate-golden-v1",
        "features": {},
        "generator": "render/tests/goldens/generate_gate_goldens.py",
        "reviewer": "pending",
    }
    for feature in gate_cases.FEATURES:
        arr = np.asarray(gate_cases.compute(feature))
        path = out_dir / f"{feature}.npy"
        np.save(path, arr)
        manifest["features"][feature] = {
            "file": f"{feature}.npy",
            "shape": list(arr.shape),
            "dtype": str(arr.dtype),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="render/tests/goldens/gate")
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(out_dir)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gate_goldens] wrote {len(manifest['features'])} features -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
