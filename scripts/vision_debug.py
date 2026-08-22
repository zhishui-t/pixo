"""脚本：pixo.vision segment / measure / health 诊断。

用法：
    python scripts/vision_debug.py [--size 128] [--prompts face,sky,plant]
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


def _synthetic_image(h: int, w: int):
    """生成简单合成图用于无输入诊断。"""
    import numpy as np

    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[: h // 3, :] = (120, 160, 220)      # 天空
    img[h // 3 : 2 * h // 3, :] = (80, 140, 70)  # 地面
    img[2 * h // 3 :, :] = (70, 90, 60)
    img[h // 4 : h // 2, w // 4 : w // 2] = (200, 160, 140)  # 人脸块
    return img


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--prompts", default="face,sky,plant")
    args = parser.parse_args(argv)

    from pixo.vision import (
        MockSegmenter,
        VisionMeasure,
        vision_health,
    )

    image = _synthetic_image(args.size, args.size)
    prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]
    segmenter = MockSegmenter()
    masks = segmenter.segment(image, prompts)
    measure = VisionMeasure().measure(
        image, masks, image_id="vision_debug",
        render_version="debug", detection_version="mock",
    )
    health = vision_health()

    print(json.dumps({
        "image": {"shape": list(image.shape), "dtype": str(image.dtype)},
        "prompts": prompts,
        "masks": {k: {"shape": list(v.shape), "dtype": str(v.dtype)}
                  for k, v in masks.items()},
        "measurement": measure,
        "health": health,
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
