"""生成 golden_manifest.json（内置合成 + 真实占位）。

用法:
  python -m pixo.harness.goldens.generate_manifest
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .manifest import save_manifest
from .samples import build_manifest_dict

DEFAULT_OUT = (Path(__file__).resolve().parents[4] / "data" / "golden"
                   / "reference" / "harness" / "golden_manifest.json")


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="输出 manifest 路径",
    )
    args = parser.parse_args(argv)
    path = save_manifest(build_manifest_dict(), args.out)
    print(f"[goldens] wrote manifest -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
