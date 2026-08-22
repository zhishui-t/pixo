"""pixo.manifests CLI：校验两个 Vision 清单。

用法: python -m pixo.manifests
"""
from __future__ import annotations

import sys

from . import load_all_manifests


def main() -> int:
    """校验并打印清单摘要。"""
    try:
        data = load_all_manifests()
    except (FileNotFoundError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    models = data["vision_models"]["models"]
    datasets = data["vision_datasets"]["datasets"]
    print(
        f"OK: models={len(models)}, datasets={len(datasets)}, "
        f"models_schema={data['vision_models']['schema_version']}, "
        f"datasets_schema={data['vision_datasets']['schema_version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
