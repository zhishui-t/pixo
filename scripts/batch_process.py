"""脚本：pixo.pipeline.batch 批量诊断/执行。

用法：
    python scripts/batch_process.py [--count 4] [--top-n 2] [--synthetic]
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


def _synthetic_inputs(count: int, size: int = 64):
    """生成一批合成 BatchInput。"""
    import numpy as np

    from pixo.pipeline.batch import BatchInput

    inputs = []
    for i in range(count):
        img = np.full((size, size, 3), 0.15 * (i + 1), dtype=np.float32)
        img[16:40, 20:44] = (0.35, 0.4, 0.45)
        inputs.append(BatchInput(photo_id=f"synthetic_{i:03d}", image_rgb=img))
    return inputs


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--size", type=int, default=64)
    args = parser.parse_args(argv)

    from pixo.pipeline.batch import BatchPipeline

    photos = _synthetic_inputs(args.count, args.size)
    pipeline = BatchPipeline(top_n=args.top_n)
    result = pipeline.process(photos)

    print(json.dumps({
        "count": len(photos),
        "top_n": args.top_n,
        "groups": [g.to_dict() for g in result.groups],
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
