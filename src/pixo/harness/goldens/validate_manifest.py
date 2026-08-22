"""校验 golden_manifest.json。

用法:
  python -m pixo.harness.goldens.validate_manifest [path]
"""
from __future__ import annotations

import sys
from pathlib import Path

from .manifest import load_manifest

DEFAULT_MANIFEST = (Path(__file__).resolve().parents[4] / "data" / "golden"
                        / "reference" / "harness" / "golden_manifest.json")


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    args = list(argv if argv is not None else sys.argv[1:])
    path = Path(args[0]) if args else DEFAULT_MANIFEST
    try:
        manifest = load_manifest(path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK: schema={manifest.schema}, samples={len(manifest.samples)}, "
        f"available={sum(1 for s in manifest.samples if s.available)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
