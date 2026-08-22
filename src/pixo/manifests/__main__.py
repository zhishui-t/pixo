"""pixo.manifests CLI：校验 Vision 模型清单。

用法: python -m pixo.manifests
"""
from __future__ import annotations

import sys

from . import load_all_manifests


def main() -> int:
    """校验并打印模型清单摘要。"""
    try:
        data = load_all_manifests()
    except (FileNotFoundError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    models = data["vision_models"]["models"]
    print(
        f"OK: models={len(models)}, "
        f"models_schema={data['vision_models']['schema_version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
