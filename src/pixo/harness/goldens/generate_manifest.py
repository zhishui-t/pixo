"""生成 golden_manifest.json（内置合成 + 真实占位）。

用法:
  python -m pixo.harness.goldens.generate_manifest

  # 只校验漂移，不写盘（退出码非 0 表示与现有 manifest 有漂移）
  python -m pixo.harness.goldens.generate_manifest --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .manifest import save_manifest
from .samples import build_manifest_dict

DEFAULT_OUT = (Path(__file__).resolve().parents[4] / "data" / "golden"
                   / "reference" / "harness" / "golden_manifest.json")

# 样本条目中参与漂移比对的字段（input.path 等环境相关字段不比对）。
_SAMPLE_DIFF_KEYS = ("type", "seed", "synthetic", "available", "version",
                     "expected_metrics")


def _diff_manifests(fresh: dict[str, Any], existing: dict[str, Any]) -> list[str]:
    """对比新生成 manifest 与现有 manifest，返回逐条漂移说明。"""
    drifts: list[str] = []
    for key in ("schema", "version"):
        if fresh.get(key) != existing.get(key):
            drifts.append(f"{key}: {existing.get(key)!r} -> {fresh.get(key)!r}")
    fresh_by_id = {s.get("photo_id"): s for s in fresh.get("samples") or []}
    existing_by_id = {s.get("photo_id"): s for s in existing.get("samples") or []}
    for photo_id in sorted(set(fresh_by_id) | set(existing_by_id)):
        if photo_id not in existing_by_id:
            drifts.append(f"{photo_id}: 新增样本")
            continue
        if photo_id not in fresh_by_id:
            drifts.append(f"{photo_id}: 现有 manifest 中存在但当前无法生成")
            continue
        old_sample = existing_by_id[photo_id]
        new_sample = fresh_by_id[photo_id]
        for key in _SAMPLE_DIFF_KEYS:
            if old_sample.get(key) != new_sample.get(key):
                drifts.append(
                    f"{photo_id}.{key}: {old_sample.get(key)!r} "
                    f"-> {new_sample.get(key)!r}")
    return drifts


def run_check(path: Path) -> int:
    """--check 模式：不写盘，输出与现有 manifest 的 diff；漂移返回非 0。"""
    if not path.exists():
        print(f"[goldens] manifest 不存在: {path}", file=sys.stderr)
        return 2
    existing = json.loads(path.read_text(encoding="utf-8"))
    fresh = build_manifest_dict()
    drifts = _diff_manifests(fresh, existing)
    if drifts:
        print(f"[goldens] 检测到 {len(drifts)} 处漂移（vs {path}）:")
        for line in drifts:
            print(f"  {line}")
        print("[goldens] CHECK: DRIFT（如为预期改动，请重生成 manifest）")
        return 1
    print(f"[goldens] CHECK: OK（{len(fresh['samples'])} 个样本与现有 manifest 一致）")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="输出 manifest 路径",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="不写盘，仅对比现有 manifest；漂移时退出码非 0",
    )
    args = parser.parse_args(argv)
    path = Path(args.out)
    if args.check:
        return run_check(path)
    path = save_manifest(build_manifest_dict(), path)
    print(f"[goldens] wrote manifest -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
