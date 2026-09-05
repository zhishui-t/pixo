"""Gate L2 golden 生成器（FUNCTION_GATE_SPEC §6）。

用法 (仓库根, 无需 PYTHONPATH —— src 路径内部自举):
  python tests/regression/goldens/generate_gate_goldens.py

  # 只校验漂移，不写盘（退出码非 0 表示与现有 manifest 有漂移）
  python tests/regression/goldens/generate_gate_goldens.py --check

生成后必须由 reviewer 复核 diff 并更新 manifest.reviewer，不得与实现改动
在同一次提交中静默合入。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np

# src-layout 自举 (G-4 修复): 仓库根/src 注入 sys.path, 免 PYTHONPATH=src。
_REPO_SRC = Path(__file__).resolve().parents[3] / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

import gate_cases

# 本生成器（合成 golden，条目为 {file,shape,dtype,sha256}）的 schema id。
SCHEMA = "render-gate-synth-v1"
# render/tools/gate_golden.py（真实 RAW 全链路）的 schema id，条目结构互不兼容。
RAW_SCHEMA = "render-gate-raw-v1"
# 历史 id：两套格式曾共用，读到时按条目结构判别并提示迁移。
LEGACY_SCHEMA = "render-gate-golden-v1"


def _entry_for(feature: str, arr: np.ndarray, write_to: Path | None) -> dict:
    """生成单个 feature 的 manifest 条目；write_to 为 None 时不写盘。"""
    if write_to is not None:
        path = write_to / f"{feature}.npy"
        np.save(path, arr)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        # 与 np.save 的文件字节完全一致（同一 numpy 序列化格式）。
        buf = io.BytesIO()
        np.lib.format.write_array(buf, np.asanyarray(arr), allow_pickle=False)
        digest = hashlib.sha256(buf.getvalue()).hexdigest()
    return {
        "file": f"{feature}.npy",
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "sha256": digest,
    }


def build_manifest(out_dir: Path, *, write: bool = True) -> dict:
    manifest = {
        "schema": SCHEMA,
        "features": {},
        "generator": "tests/regression/goldens/generate_gate_goldens.py",
        "reviewer": "pending",
    }
    for feature in gate_cases.FEATURES:
        arr = np.asarray(gate_cases.compute(feature))
        manifest["features"][feature] = _entry_for(
            feature, arr, out_dir if write else None)
    return manifest


def _schema_error(existing: dict, manifest_path: Path) -> str | None:
    """校验现有 manifest schema；返回错误消息，None 表示通过。"""
    schema = existing.get("schema")
    if schema == SCHEMA:
        return None
    if schema == RAW_SCHEMA:
        return (f"{manifest_path} 的 schema 为 {RAW_SCHEMA}（render/tools 真实 RAW "
                f"golden），与 {SCHEMA}（合成 golden）条目结构互不兼容")
    if schema == LEGACY_SCHEMA:
        feature = next(iter(existing.get("features") or {}), None)
        entry = (existing.get("features") or {}).get(feature) or {}
        target = (RAW_SCHEMA if "sha256_u8" in entry or "params" in entry
                  else SCHEMA)
        return (f"{manifest_path} 使用历史 schema id {LEGACY_SCHEMA}，"
                f"按条目结构应属 {target}；请把 schema 字段更新为 {target}")
    return f"{manifest_path} 的 schema 为 {schema!r}，本工具仅支持 {SCHEMA}"


def _diff_manifests(fresh: dict, existing: dict) -> list[str]:
    """对比新算 manifest 与现有 manifest，返回逐条漂移说明。"""
    drifts: list[str] = []
    if fresh.get("schema") != existing.get("schema"):
        drifts.append(f"schema: {existing.get('schema')!r} -> {fresh.get('schema')!r}")
    fresh_features = fresh.get("features") or {}
    existing_features = existing.get("features") or {}
    for feature in sorted(set(fresh_features) | set(existing_features)):
        if feature not in existing_features:
            drifts.append(f"{feature}: 新增 feature")
            continue
        if feature not in fresh_features:
            drifts.append(f"{feature}: 现有 manifest 中存在但当前无法生成")
            continue
        for key in ("file", "shape", "dtype", "sha256"):
            if fresh_features[feature].get(key) != existing_features[feature].get(key):
                drifts.append(
                    f"{feature}.{key}: {existing_features[feature].get(key)!r} "
                    f"-> {fresh_features[feature].get(key)!r}")
    return drifts


def run_check(out_dir: Path) -> int:
    """--check 模式：不写盘，输出与现有 manifest 的 diff；漂移返回非 0。"""
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"[gate_goldens] manifest 不存在: {manifest_path}", file=sys.stderr)
        return 2
    existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_error = _schema_error(existing, manifest_path)
    if schema_error:
        print(f"[gate_goldens] {schema_error}", file=sys.stderr)
        return 2
    fresh = build_manifest(out_dir, write=False)
    drifts = _diff_manifests(fresh, existing)
    if drifts:
        print(f"[gate_goldens] 检测到 {len(drifts)} 处漂移（vs {manifest_path}）:")
        for line in drifts:
            print(f"  {line}")
        print("[gate_goldens] CHECK: DRIFT（如为预期改动，请重生成并更新 reviewer）")
        return 1
    print(f"[gate_goldens] CHECK: OK（{len(fresh['features'])} features 与现有 manifest 一致）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out", default="tests/regression/goldens/gate",
        help="golden 输出目录 (相对 cwd, 默认即仓库根下的实际金样本目录)")
    ap.add_argument("--check", action="store_true",
                    help="不写盘，仅对比现有 manifest；漂移时退出码非 0")
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    if args.check:
        return run_check(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(out_dir, write=True)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gate_goldens] wrote {len(manifest['features'])} features -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
