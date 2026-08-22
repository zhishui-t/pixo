"""脚本：pixo.render 基本渲染诊断。

用法：
    python scripts/render_debug.py [--raw <NEF>] [--dcp <DCP>] [--long-edge 1024]

无 --raw 时仅打印 pixo.render 可用性与版本。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SRC = _SCRIPT_DIR.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _default_dcp() -> Path:
    """返回仓库内置默认 DCP。"""
    return _SCRIPT_DIR.parent / "resources" / "dcp" / (
        "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
    )


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=None, help="RAW/NEF 路径")
    parser.add_argument("--dcp", default=None, help="DCP 路径")
    parser.add_argument("--long-edge", type=int, default=1024)
    parser.add_argument("--full", action="store_true", help="额外执行全分辨率渲染")
    args = parser.parse_args(argv)

    import pixo.render

    report: dict = {
        "module": pixo.render.__name__,
        "version": getattr(pixo.render, "__version__", "unknown"),
        "raw": args.raw,
        "long_edge": args.long_edge,
    }

    if args.raw:
        from pixo.render.api import Renderer
        from pixo.render.core.calibration import load_dcp

        dcp = Path(args.dcp or _default_dcp())
        if not dcp.exists():
            print(json.dumps({"error": f"DCP 不存在: {dcp}"}, ensure_ascii=False))
            return 2
        prof = load_dcp(dcp)
        renderer = Renderer(dcp)
        preview = renderer.render_preview_full(
            Path(args.raw), long_edge=args.long_edge, output_bps=8
        )
        report["preview_shape"] = list(preview.shape)
        report["preview_dtype"] = str(preview.dtype)
        if args.full:
            try:
                full = renderer.render_adjusted(Path(args.raw))
                report["full_shape"] = list(full.shape)
                report["full_dtype"] = str(full.dtype)
            except Exception as exc:  # noqa: BLE001 - 诊断脚本不因全量失败中断
                report["full_error"] = str(exc)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
