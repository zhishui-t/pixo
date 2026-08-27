"""pixo.render 功能 golden 回归生成/对比工具 (t35, t108 扩四条默认路径)。

用法:
  # 生成基线 (单 RAW, 8 个手动参数 feature; t35 原有口径)
  python render/tools/gate_golden.py generate \
      --raw <corpus>/a/raw/DSC_5236.NEF \
      --dcp $PIXO_ROOT/resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp \
      --out data/golden/reference/render_bench/goldens/gate --long-edge 512

  # 对比当前输出与基线
  python render/tools/gate_golden.py compare \
      --raw <corpus>/a/raw/DSC_5236.NEF \
      --dcp $PIXO_ROOT/resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp \
      --out data/golden/reference/render_bench/goldens/gate --long-edge 512

  # 多样本基线 (t108: 四条默认路径 feature × EXIF 多样性样本; samples.json
  # 含真实本机路径不入库, manifest 记 <corpus>/ 匿名 ref 供溯源)
  python render/tools/gate_golden.py generate \
      --samples samples.json \
      --dcp $PIXO_ROOT/resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp \
      --out data/golden/reference/render_bench/goldens/gate_defaults \
      --long-edge 512 \
      --features wb_as_shot_default,compose_param,clarity_default \
      --reviewer "t108-auto-verified (主代理复核, 待用户终审)"

  python render/tools/gate_golden.py compare \
      --samples samples.json \
      --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512

samples.json 格式 (generate/compare 共用; ref 为 manifest 记录用的匿名路径):
  {"samples": {"<sample_id>": {"raw": "K:/.../DSC_xxxx.NEF",
                               "ref": "<corpus>/xiamen/1/DSC_xxxx.NEF",
                               "note": "...", "exif": {...}}}}

阈值：8-bit max|Δ| ≤1/255；16-bit max|Δ| ≤1/65535（确定性路径应逐位）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

# src-layout 迁移 (3b687d8) 后本文件位于 src/pixo/render/tools/, 直接
# `python .../gate_golden.py` 调用时需把仓库 src/ 放上 sys.path。
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pixo.render.api import Renderer

# 每个调整功能一组代表性参数（覆盖 FUNCTION_GATE_SPEC §5 八个 feature）。
FEATURES: Dict[str, Dict[str, Any]] = {
    "exposure": {
        "exposure": {"mode": 0.7, "max_ev": 2.5, "rolloff_knee": 0.9},
    },
    "whitebalance": {
        "whitebalance": {"mode": "manual", "temp": 5500.0, "tint": 5.0},
    },
    "tone": {
        "tone": {"contrast": 0.3, "brightness": 0.5,
                 "highlights": 0.2, "shadows": 0.2,
                 "whites": 0.1, "blacks": -0.1},
    },
    "hsl": {
        "hsl": {
            "enabled": True,
            "bands": json.dumps([
                {"name": "red", "hue_center": 0, "width": 45,
                 "hue_shift": 5.0, "saturation": 10.0, "luminance": 5.0},
                {"name": "blue", "hue_center": 240, "width": 45,
                 "hue_shift": -3.0, "saturation": 8.0, "luminance": 2.0},
            ]),
        },
    },
    "split_tone": {
        "split_tone": {"enabled": True, "shadows_hue": 45.0,
                       "shadows_sat": 30.0, "highlights_hue": 210.0,
                       "highlights_sat": 20.0, "balance": 0.5,
                       "strength": 0.8},
    },
    "calibration": {
        "calibration": {"enabled": True, "shadow_tint": 5.0,
                        "red_hue": 5.0, "red_sat": 10.0,
                        "green_hue": -3.0, "green_sat": 5.0,
                        "blue_hue": 2.0, "blue_sat": 8.0},
    },
    "skin": {
        "skin": {"enabled": True, "strength": 0.5},
    },
    "refine": {
        "refine": {"sharpen": 0.6, "chroma_denoise": 1.2,
                   "highlight_desat": 0.8},
    },
    # ---- t108: 四条默认路径 feature（生产默认口径, 此前无 RAW golden 锁定）----
    # WB 完全默认: as_shot + warmth 分桶拟合曲线 (configs/calibration/
    # warmth_curve.json, 缺省加载) + trim 恒等 —— 生产默认白平衡路径。
    "wb_as_shot_default": {
        "whitebalance": {"mode": "as_shot"},
    },
    # 曝光 auto 默认: 二维标定表 (render/target_offset.json cal_table,
    # med×wb_B 查表) + WB 默认 —— 生产默认曝光路径 (tier EV 一致性口径)。
    "exposure_auto_default": {
        "exposure": {"mode": "auto"},
    },
    # compose 参数: 固定 16:9 中心裁剪 (整数切片零插值) —— compose 像素
    # 输出首次锁定 (旋转 warpAffine 依赖 cv2 版本, 跨平台锁裁剪更稳)。
    "compose_param": {
        "compose": {"mode": "ratio", "ratio": "16:9", "center": [0.5, 0.5]},
    },
    # clarity 默认: enabled=True strength=0.3 (基座默认开启 stage;
    # 预览口径实际封顶 0.25, 由 stage 内部决定, 参数侧锁默认值)。
    "clarity_default": {
        "clarity": {"enabled": True, "strength": 0.3},
    },
}

THRESHOLD_U8 = 1   # 1/255
THRESHOLD_U16 = 1  # 1/65535

# 本工具（真实 RAW 全链路）的 manifest schema id。
SCHEMA = "render-gate-raw-v1"
# tests/regression/goldens/generate_gate_goldens.py（合成 golden）使用的 schema id，
# 两套条目结构互不兼容，读取到对方 id 时必须显式报错而非 KeyError。
SYNTH_SCHEMA = "render-gate-synth-v1"
# 历史 id：两套格式曾共用，读到时按条目结构判别并提示迁移。
LEGACY_SCHEMA = "render-gate-golden-v1"


def _schema_error(manifest: Dict[str, Any], manifest_path: Path) -> str | None:
    """校验 manifest schema；返回错误消息，None 表示通过。"""
    schema = manifest.get("schema")
    if schema == SCHEMA:
        return None
    if schema == SYNTH_SCHEMA:
        return (f"{manifest_path} 的 schema 为 {SYNTH_SCHEMA}"
                f"（tests 合成 golden），与本工具的 {SCHEMA}（真实 RAW 全链路）"
                f"条目结构互不兼容；请改用 tests/regression/test_gate_golden.py 校验")
    if schema == LEGACY_SCHEMA:
        # 旧 id 两套格式共用：按条目字段判别归属并给出迁移指引。
        feature = next(iter(manifest.get("features") or {}), None)
        entry = (manifest.get("features") or {}).get(feature) or {}
        if "sha256_u8" in entry or "params" in entry:
            target = SCHEMA
        else:
            target = SYNTH_SCHEMA
        return (f"{manifest_path} 使用历史 schema id {LEGACY_SCHEMA}，"
                f"按条目结构应属 {target}；请把 schema 字段更新为 {target} 后重试")
    return (f"{manifest_path} 的 schema 为 {schema!r}，"
            f"本工具仅支持 {SCHEMA}")


def _sha256(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def _render(renderer: Renderer, raw_path: Path, long_edge: int,
            params: Dict[str, Any], output_bps: int) -> np.ndarray:
    return renderer.render_preview_full(
        raw_path, long_edge=long_edge, params=params, output_bps=output_bps)


def _render_entry(renderer: Renderer, raw_path: Path, long_edge: int,
                  feature: str, feat_dir: Path,
                  base_dir: Path) -> Dict[str, Any]:
    """渲染 feature 的 u8/u16 并写盘, 返回 files/sha256/shape 条目字段。

    files 路径记录为相对 base_dir（goldens 根目录）, 单样本/多样式两种
    布局共用（多样式为 <feature>/<sample_id>/output_u8.npy）。
    """
    params = FEATURES[feature]
    feat_dir.mkdir(parents=True, exist_ok=True)
    u8 = _render(renderer, raw_path, long_edge, params, 8)
    u16 = _render(renderer, raw_path, long_edge, params, 16)
    p8 = feat_dir / "output_u8.npy"
    p16 = feat_dir / "output_u16.npy"
    np.save(p8, u8)
    np.save(p16, u16)
    return {
        "files": {"u8": str(p8.relative_to(base_dir)),
                  "u16": str(p16.relative_to(base_dir))},
        "sha256_u8": _sha256(u8),
        "sha256_u16": _sha256(u16),
        "shape_u8": list(u8.shape),
        "shape_u16": list(u16.shape),
    }


def _generate_one(renderer: Renderer, raw_path: Path, dcp_path: Path,
                  feature: str, out_dir: Path, long_edge: int) -> Dict[str, Any]:
    entry = _render_entry(renderer, raw_path, long_edge, feature,
                          out_dir / feature, out_dir.parent)
    return {
        "feature": feature,
        "params": FEATURES[feature],
        "long_edge": int(long_edge),
        "raw": str(raw_path),
        "dcp": str(dcp_path),
        **entry,
    }


def _generate_one_sample(renderer: Renderer, raw_path: Path, dcp_path: Path,
                         feature: str, sample_id: str, ref: str,
                         out_dir: Path, long_edge: int) -> Dict[str, Any]:
    """多样本模式下单个 (feature, sample) 的条目（嵌在 feature 的 samples 下）。"""
    entry = _render_entry(renderer, raw_path, long_edge, feature,
                          out_dir / feature / sample_id, out_dir.parent)
    return {"raw": ref, "dcp": str(dcp_path), **entry}


def cmd_generate(args) -> int:
    if getattr(args, "samples", None):
        return _cmd_generate_samples(args)
    raw_path = Path(args.raw) if args.raw else None
    dcp_path = Path(args.dcp) if args.dcp else None
    if raw_path is None or dcp_path is None or not raw_path.exists() \
            or not dcp_path.exists():
        print("[gate_golden] raw/dcp 不存在（单 RAW 模式需同时提供 --raw 与 "
              "--dcp；多样本基线用 --samples）", file=sys.stderr)
        return 2
    # --features / --reviewer 与多样本路径同语义（t108 修复：此前单 RAW
    # 路径忽略这两个参数，全量生成且不写 reviewer）。
    feats = ([f.strip() for f in args.features.split(",") if f.strip()]
             if getattr(args, "features", None) else list(FEATURES))
    unknown = [f for f in feats if f not in FEATURES]
    if unknown:
        print(f"[gate_golden] 未知 feature: {unknown}（合法: {list(FEATURES)}）",
              file=sys.stderr)
        return 2
    renderer = Renderer(dcp_path)
    manifest: Dict[str, Any] = {
        "schema": SCHEMA,
        "long_edge": args.long_edge,
        "raw": str(raw_path),
        "dcp": str(dcp_path),
        "features": {},
    }
    for feature in feats:
        print(f"[gate_golden] generate {feature} ...", flush=True)
        manifest["features"][feature] = _generate_one(
            renderer, raw_path, dcp_path, feature, Path(args.out), args.long_edge)
    manifest["reviewer"] = getattr(args, "reviewer", None) or "pending"
    out_dir = Path(args.out)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print(f"[gate_golden] manifest -> {manifest_path}")
    return 0


_SAMPLE_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")


def _cmd_generate_samples(args) -> int:
    """多样本基线生成: --samples json × FEATURES 子集, 增量并入已有 manifest。

    samples.json 的真实 raw 路径只用于本次渲染, manifest 记 ref 匿名路径
    （隐私口径: 本机语料路径不入库, 见 8961667 anonymize 约定）。
    """
    dcp_path = Path(args.dcp) if args.dcp else None
    if dcp_path is None or not dcp_path.exists():
        print("[gate_golden] --dcp 不存在（多样本模式同样需要 DCP 口径）",
              file=sys.stderr)
        return 2
    try:
        samples_doc = json.loads(
            Path(args.samples).read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        print(f"[gate_golden] samples.json 读取失败: {ex}", file=sys.stderr)
        return 2
    raw_samples = samples_doc.get("samples") if isinstance(samples_doc, dict) else None
    if not isinstance(raw_samples, dict) or not raw_samples:
        print("[gate_golden] samples.json 缺少非空 samples 字段", file=sys.stderr)
        return 2
    feats = ([f.strip() for f in args.features.split(",") if f.strip()]
             if args.features else list(FEATURES))
    unknown = [f for f in feats if f not in FEATURES]
    if unknown:
        print(f"[gate_golden] 未知 feature: {unknown}（可用: {sorted(FEATURES)}）",
              file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    manifest_path = out_dir / "manifest.json"
    manifest: Dict[str, Any] = {"schema": SCHEMA, "features": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema_error = _schema_error(manifest, manifest_path)
        if schema_error:
            print(f"[gate_golden] {schema_error}", file=sys.stderr)
            return 2
        existing = manifest.get("features") or {}
        if "raw" in manifest or any("samples" not in e for e in existing.values()):
            print(f"[gate_golden] {manifest_path} 是单 RAW flat 结构, 与 --samples "
                  f"多样本条目不兼容; 请另指定 --out 目录", file=sys.stderr)
            return 2

    # 样本注册表: 校验 sample_id 可作目录名 + raw 存在; 记 ref/note/exif。
    registry: Dict[str, Any] = {}
    for sid, s in raw_samples.items():
        if not isinstance(s, dict) or not s.get("raw") \
                or not _SAMPLE_ID_RE.fullmatch(str(sid)):
            print(f"[gate_golden] 样本 {sid!r} 非法（需 raw 字段; id 限 "
                  f"[A-Za-z0-9_.-]）", file=sys.stderr)
            return 2
        if not Path(s["raw"]).exists():
            print(f"[gate_golden] 样本 {sid} raw 不存在: {s['raw']}",
                  file=sys.stderr)
            return 2
        registry[sid] = {"ref": s.get("ref") or str(s["raw"]),
                         "note": s.get("note", ""),
                         "exif": s.get("exif") or {}}

    renderer = Renderer(dcp_path)
    manifest.update({"schema": SCHEMA, "long_edge": int(args.long_edge),
                     "dcp": str(dcp_path), "samples": registry})
    for feature in feats:
        print(f"[gate_golden] generate {feature} ({len(registry)} samples) ...",
              flush=True)
        manifest["features"][feature] = {
            "feature": feature,
            "params": FEATURES[feature],
            "long_edge": int(args.long_edge),
            "samples": {
                sid: _generate_one_sample(renderer, Path(s["raw"]), dcp_path,
                                          feature, sid, registry[sid]["ref"],
                                          out_dir, args.long_edge)
                for sid, s in raw_samples.items()},
        }
    manifest["reviewer"] = args.reviewer
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print(f"[gate_golden] manifest -> {manifest_path}")
    return 0


def _verify_baseline(out_dir: Path, label: str,
                     meta: Dict[str, Any]) -> str | None:
    """diff 前校验基线 .npy 内容哈希与 manifest 一致；返回错误消息，None 表示通过。

    label 为基线子目录名: flat 条目 = feature, 多样本条目 = feature/sample_id
    （两种布局都是 out_dir/label/output_{u8,u16}.npy）。
    manifest 记录的是数组字节 sha256（_sha256），故此处对 np.load 结果重算对比，
    可发现基线被误替换/损坏后与 manifest 脱节的情况。
    """
    for hash_key, file_name in (("sha256_u8", "output_u8.npy"),
                                ("sha256_u16", "output_u16.npy")):
        path = out_dir / label / file_name
        if not path.exists():
            return f"基线文件缺失: {path}"
        expected_hash = meta.get(hash_key)
        if not expected_hash:
            return f"manifest[{label}] 缺少 {hash_key}，请重跑 generate 重建 manifest"
        actual_hash = _sha256(np.load(path))
        if actual_hash != expected_hash:
            return (f"{label}/{file_name} 基线 sha256 不一致: "
                    f"manifest={expected_hash} 实际={actual_hash}；"
                    f"基线可能被误替换/损坏，请重跑 generate 并由 reviewer 复核")
    return None


def _diff_one(renderer: Renderer, raw_path: Path, out_dir: Path, label: str,
              meta: Dict[str, Any], long_edge: int) -> tuple[int, int, str | None]:
    """渲染当前输出并与基线 diff; 返回 (d8, d16, 错误消息)。"""
    try:
        curr8 = _render(renderer, raw_path, long_edge, meta["params"], 8)
        curr16 = _render(renderer, raw_path, long_edge, meta["params"], 16)
        gold8 = np.load(out_dir / label / "output_u8.npy")
        gold16 = np.load(out_dir / label / "output_u16.npy")
        d8 = int(np.abs(curr8.astype(np.int16) - gold8.astype(np.int16)).max())
        d16 = int(np.abs(curr16.astype(np.int32) - gold16.astype(np.int32)).max())
        return d8, d16, None
    except Exception as ex:  # 渲染/IO 异常按 FAIL 行上报, 不中断其余条目
        return -1, -1, f"{label}: 渲染/读取失败: {ex}"


def cmd_compare(args) -> int:
    out_dir = Path(args.out)
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"[gate_golden] manifest 不存在: {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_error = _schema_error(manifest, manifest_path)
    if schema_error:
        print(f"[gate_golden] {schema_error}", file=sys.stderr)
        return 2
    if not isinstance(manifest.get("features"), dict):
        print(f"[gate_golden] manifest 缺少 features 字段（schema={SCHEMA} 条目"
              f"应含 params/files/sha256_u8/sha256_u16）", file=sys.stderr)
        return 2
    multi = any("samples" in e for e in manifest["features"].values())
    if multi and any("samples" not in e for e in manifest["features"].values()):
        print(f"[gate_golden] {manifest_path} 混用单 RAW/多样本条目结构, 请重跑 "
              f"generate 重建 manifest", file=sys.stderr)
        return 2

    if multi:
        return _cmd_compare_samples(args, out_dir, manifest)

    raw_path = Path(args.raw) if args.raw else None
    dcp_path = Path(args.dcp) if args.dcp else None
    if raw_path is None or dcp_path is None or not raw_path.exists() \
            or not dcp_path.exists():
        print("[gate_golden] raw/dcp 不存在（单 RAW manifest 需 --raw 与 --dcp）",
              file=sys.stderr)
        return 2
    renderer = Renderer(dcp_path)
    failed = False
    print(f"{'feature':<14s} {'u8_max':>8s} {'u16_max':>8s} verdict")
    for feature, meta in manifest["features"].items():
        integrity_error = _verify_baseline(out_dir, feature, meta)
        if integrity_error is not None:
            failed = True
            print(f"[gate_golden] {integrity_error}", file=sys.stderr)
            print(f"{feature:<14s} {'-':>8s} {'-':>8s} FAIL(基线完整性)")
            continue
        d8, d16, err = _diff_one(renderer, raw_path, out_dir, feature, meta,
                                 args.long_edge)
        if err:
            failed = True
            print(f"[gate_golden] {err}", file=sys.stderr)
            print(f"{feature:<14s} {'-':>8s} {'-':>8s} FAIL(渲染)")
            continue
        ok = d8 <= THRESHOLD_U8 and d16 <= THRESHOLD_U16
        failed = failed or not ok
        print(f"{feature:<14s} {d8:>8d} {d16:>8d} {'PASS' if ok else 'FAIL'}")
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


def _cmd_compare_samples(args, out_dir: Path, manifest: Dict[str, Any]) -> int:
    """多样本 manifest 对比: 逐 feature × sample 渲染并 diff。

    样本 raw 解析顺序: --samples json（真实路径）→ manifest 条目 raw 路径
    （若在本机存在）。DCP: --dcp 优先, 回退 manifest 顶层 dcp。
    """
    dcp_arg = Path(args.dcp) if args.dcp else None
    dcp_path = dcp_arg or Path(manifest.get("dcp") or "")
    if dcp_arg is None and (not manifest.get("dcp")
                            or not Path(manifest["dcp"]).exists()):
        print("[gate_golden] 多样本 manifest 需要 --dcp（或 manifest.dcp 可用）",
              file=sys.stderr)
        return 2
    raw_by_id: Dict[str, Path] = {}
    if getattr(args, "samples", None):
        doc = json.loads(Path(args.samples).read_text(encoding="utf-8"))
        raw_by_id = {sid: Path(s["raw"])
                     for sid, s in (doc.get("samples") or {}).items()
                     if isinstance(s, dict) and s.get("raw")}
    renderer = Renderer(dcp_path)
    failed = False
    long_edge = manifest.get("long_edge") or args.long_edge
    if int(long_edge) != int(args.long_edge):
        print(f"[gate_golden] 提示: --long-edge={args.long_edge} 与 manifest 口径 "
              f"{long_edge} 不一致, 以 manifest 为准", file=sys.stderr)
    print(f"{'feature/sample':<38s} {'u8_max':>8s} {'u16_max':>8s} verdict")
    for feature, meta in manifest["features"].items():
        for sid, smeta in meta["samples"].items():
            label = f"{feature}/{sid}"
            raw_path = raw_by_id.get(sid)
            if raw_path is None or not raw_path.exists():
                fallback = Path(smeta.get("raw") or "")
                raw_path = fallback if fallback.exists() else None
            if raw_path is None:
                failed = True
                print(f"[gate_golden] 样本 {sid} raw 不可解析（--samples 缺失且 "
                      f"manifest ref 非本机路径）", file=sys.stderr)
                print(f"{label:<38s} {'-':>8s} {'-':>8s} FAIL(样本缺失)")
                continue
            integrity_error = _verify_baseline(out_dir, label, smeta)
            if integrity_error is not None:
                failed = True
                print(f"[gate_golden] {integrity_error}", file=sys.stderr)
                print(f"{label:<38s} {'-':>8s} {'-':>8s} FAIL(基线完整性)")
                continue
            d8, d16, err = _diff_one(renderer, raw_path, out_dir, label,
                                     {"params": meta["params"]}, long_edge)
            if err:
                failed = True
                print(f"[gate_golden] {err}", file=sys.stderr)
                print(f"{label:<38s} {'-':>8s} {'-':>8s} FAIL(渲染)")
                continue
            ok = d8 <= THRESHOLD_U8 and d16 <= THRESHOLD_U16
            failed = failed or not ok
            print(f"{label:<38s} {d8:>8d} {d16:>8d} {'PASS' if ok else 'FAIL'}")
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("generate", cmd_generate), ("compare", cmd_compare)):
        p = sub.add_parser(name)
        # 单 RAW 模式: --raw + --dcp; 多样本模式: --samples (+ --dcp)。
        p.add_argument("--raw", help="单 RAW 模式的样本 NEF 路径")
        p.add_argument("--dcp", help="DCP profile 路径（多样本 compare 可回退 manifest）")
        p.add_argument("--out", required=True)
        p.add_argument("--long-edge", type=int, default=512)
        p.add_argument("--samples",
                       help="多样本模式 samples.json（{samples:{id:{raw,ref,note,exif}}}）")
        if name == "generate":
            p.add_argument("--features",
                           help="逗号分隔 feature 子集（缺省全部; 增量并入已有 manifest）")
            p.add_argument("--reviewer", default="pending",
                           help="manifest.reviewer 标注（双人复核纪律）")
        p.set_defaults(func=fn)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
