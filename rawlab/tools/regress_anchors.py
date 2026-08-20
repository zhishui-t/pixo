"""regress_anchors —— 四口径锚点回归脚本 (03-specification §3 / 任务 T7)。

对基准 DCP + preset 渲染锚点照片 (默认 0376/5236), 与目标 JPEG (LR 导出/
机内预览) 对齐后计算**四口径**色偏:
  full      全帧中位 a/b + |ΔS| + |Δp50|
  neutral   中性区 (目标 C*<12) 的 a/b
  bands     分亮度段 L∈{[0,50),[50,100),[100,160),[160,256)} 四段中位 a/b
  highlight 高光区 (目标 L>160 掩码) 的 a/b
输出 rawlab/out/profile_fit/regression_<name>.json 与控制台摘要。

阈值 (违反 → 退出码 1, CI 可用):
  0376  全帧    |Δa|≤3  / |Δb|≤3
  5236  高光区  |Δa|≤4  / |Δb|≤5

用法:
  python rawlab/tools/regress_anchors.py \
      --dcp rawlab\\profiles\\Nikon Z 5 2 RawLab Preview Baseline.dcp \
      --preset rawlab\\presets\\preview_baseline.json \
      --targets rawlab\\out\\profile_fit\\lr_corpus \
      --anchors K:\\data\\photo\\0711\\DSC_0376.NEF K:\\data\\photo\\0711\\DSC_5236.NEF
  # --anchors 也可给关键字 (默认 0376/5236), 配合 --raw-dirs 自动定位 RAW:
  python rawlab/tools/regress_anchors.py --dcp <...> --preset <...> \
      --targets <...> --raw-dirs K:\\data\\photo\\0711
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from rawlab.dcp import load_dcp
from rawlab.engine.pipeline import pipeline_from_config
from rawlab.tools.fit_camera_profile import (
    LUM_BANDS,
    four_caliber_stats,
)

DEFAULT_OUT_DIR = ROOT / "rawlab" / "out" / "profile_fit"
DEFAULT_ANCHORS = ["0376", "5236"]

# 锚点阈值 (03-specification.md §3 锚点回归 / 任务 T7):
#   key = 锚点 stem 关键字 (不区分大小写子串匹配);
#   caliber = 判定的四口径名 ("full" | "highlight"); da/db = |Δ| 上限。
ANCHOR_THRESHOLDS = {
    "0376": {"caliber": "full", "da": 3.0, "db": 3.0},
    "5236": {"caliber": "highlight", "da": 4.0, "db": 5.0},
}


# ---------------------------------------------------------------------------
# 纯函数 (可单测, 无真实 DCP/RAW 依赖)
# ---------------------------------------------------------------------------

def rule_for_stem(stem: str, thresholds: dict | None = None) -> dict | None:
    """按照片 stem 匹配锚点规则 (子串不区分大小写); 无匹配 → None (仅报告不判定)。"""
    thresholds = thresholds or ANCHOR_THRESHOLDS
    sl = stem.lower()
    for key, rule in thresholds.items():
        if key.lower() in sl:
            return {"key": key, "caliber": rule["caliber"],
                    "da": float(rule["da"]), "db": float(rule["db"])}
    return None


def evaluate_photo(stats: dict, rule: dict | None) -> tuple[bool, str]:
    """按规则判定单张四口径统计是否达标。

    返回 (pass, reason):
      - 无规则 → (True, "no_rule")  (仅报告);
      - 规则口径数据缺失 (如高光区掩码空) → (False, "empty_caliber");
      - |Δ| 超限 → (False, "threshold"); 达标 → (True, "ok")。
    """
    if rule is None:
        return True, "no_rule"
    caliber = stats.get(rule["caliber"])
    if caliber is None:
        return False, "empty_caliber"
    da, db = float(caliber.get("da", 1e9)), float(caliber.get("db", 1e9))
    if da > rule["da"] or db > rule["db"]:
        return False, "threshold"
    return True, "ok"


def align_target(target_u8: np.ndarray, shape) -> np.ndarray:
    """目标 JPEG resize 对齐到渲染图尺寸 (INTER_AREA 降采样, 升采样同保)。"""
    if target_u8.shape[:2] == tuple(shape):
        return target_u8
    return cv2.resize(target_u8, (shape[1], shape[0]),
                      interpolation=cv2.INTER_AREA)


def load_target_jpeg(targets_dir: str | Path, stem: str) -> np.ndarray | None:
    """读目标 JPEG (RGB uint8); 不存在/损坏 → None。"""
    for ext in (".jpg", ".jpeg"):
        p = Path(targets_dir) / f"{stem}{ext}"
        if p.exists():
            bgr = cv2.imread(str(p))
            if bgr is None:
                return None
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return None


def resolve_anchors(anchors: list[str], raw_dirs: list[str] | None) -> list[str]:
    """把锚点参数解析为实际 RAW 路径列表。

    规则: 已是存在的文件 → 直接用; 否则视为 stem 关键字, 在 --raw-dirs 里
    搜索 stem 含该关键字 (不区分大小写) 的 .NEF (取第一个匹配)。找不到 → 报错。
    """
    out: list[str] = []
    for a in anchors:
        p = Path(a)
        if p.exists():
            out.append(str(p))
            continue
        if not raw_dirs:
            raise SystemExit(
                f"[error] 锚点 {a!r} 不是文件路径; 需提供 --raw-dirs 定位含该"
                f"关键字的 RAW (默认锚点 0376/5236)")
        key = a.lower()
        found = None
        for d in raw_dirs:
            for f in sorted(Path(d).rglob("*.NEF")):
                if f.name.startswith("._"):       # 跳过 AppleDouble 等隐藏副本
                    continue
                if key in f.stem.lower():
                    found = f
                    break
            if found:
                break
        if found is None:
            raise SystemExit(
                f"[error] 在 --raw-dirs 中未找到 stem 含 {a!r} 的 .NEF")
        out.append(str(found))
    return out


# ---------------------------------------------------------------------------
# 渲染 (真实链路; 测试可注入 render_fn 绕过)
# ---------------------------------------------------------------------------

def crop_active_oriented(out, raw) -> np.ndarray:
    """rawpy flip 5/6 兼容的有效画面裁切 (crop_* 是未旋转坐标)。"""
    s = raw.sizes
    l, t, w, h = (int(s.crop_left_margin), int(s.crop_top_margin),
                  int(s.crop_width), int(s.crop_height))
    W, H = int(s.raw_width), int(s.raw_height)
    full_h, full_w = ((W, H) if s.flip in (5, 6) else (H, W))
    if s.flip == 0:
        L, T, Wd, Hd = l, t, w, h
    elif s.flip == 3:
        L, T, Wd, Hd = W - (l + w), H - (t + h), w, h
    elif s.flip == 5:
        L, T, Wd, Hd = t, W - (l + w), h, w
    elif s.flip == 6:
        L, T, Wd, Hd = H - (t + h), l, h, w
    else:
        L, T, Wd, Hd = l, t, w, h
    sx = out.shape[1] / max(full_w, 1)
    sy = out.shape[0] / max(full_h, 1)
    l2, t2 = int(round(L * sx)), int(round(T * sy))
    w2, h2 = int(round(Wd * sx)), int(round(Hd * sy))
    if l2 >= 0 and t2 >= 0 and l2 + w2 <= out.shape[1] and t2 + h2 <= out.shape[0]:
        return out[t2:t2 + h2, l2:l2 + w2]
    return out


def render_anchor(raw_path: str, prof, pipe) -> np.ndarray:
    """渲染锚点 (pipeline_from_config + load_dcp 已由调用方组装) → uint8,
    并按 raw.sizes 裁到有效画面 (flip 5/6 兼容, 与 T4 验证口径一致)。"""
    import rawpy
    out = pipe.run_file(raw_path, prof=prof)          # uint8 (含传感器边距)
    with rawpy.imread(raw_path) as raw:
        out = crop_active_oriented(out, raw)
    return out


def build_runtime(dcp_path: str | None, preset_path: str):
    """加载 preset + 基准 DCP, 组装管线 (与 T4/T6 的 preset→DCP 链路一致)。"""
    pp = Path(preset_path)
    if not pp.exists():
        raise SystemExit(f"[error] preset 不存在: {preset_path}")
    preset = json.loads(pp.read_text(encoding="utf-8"))
    dcp = dcp_path or preset.get("dcp")
    if not dcp or not Path(dcp).exists():
        raise SystemExit(
            f"[error] 基准 DCP 不存在: {dcp!r} (用 --dcp 或 preset['dcp'] 字段)")
    prof = load_dcp(dcp)
    params = dict(preset.get("params") or {})
    wb = params.get("whitebalance") or {}
    params["whitebalance"] = {k: v for k, v in wb.items() if v is not None}
    cfg = {"stages": preset.get("stages"), "params": params}
    pipe = pipeline_from_config(cfg, prof=prof)
    return prof, pipe, cfg, str(dcp)


# ---------------------------------------------------------------------------
# 核心回归流程
# ---------------------------------------------------------------------------

def run_regression(anchors: list[str], targets_dir: str | Path,
                   out_dir: str | Path, name: str,
                   dcp_path: str | None = None, preset_path: str | None = None,
                   render_fn=None, load_target_fn=None,
                   thresholds: dict | None = None) -> dict:
    """对每锚点渲染 → 对齐 → 四口径统计 → 规则判定 → 汇总 JSON 报告。

    返回报告 dict; 退出码语义: report["summary"]["pass"] == False → 退出码 1。
    render_fn(raw_path, prof, pipe) / load_target_fn(targets_dir, stem) 可注入
    (测试用合成目标, 不依赖真实 DCP/RAW); 缺省走真实链路。
    """
    thresholds = thresholds or ANCHOR_THRESHOLDS
    if render_fn is None:
        if not dcp_path and not preset_path:
            raise ValueError("run_regression: 未注入 render_fn 时必须提供 dcp/preset")
        prof, pipe, _, dcp_resolved = build_runtime(dcp_path, preset_path)
    else:
        prof, pipe, dcp_resolved = None, None, dcp_path
    load_target = load_target_fn or load_target_jpeg

    reports = []
    for raw_path in anchors:
        stem = Path(raw_path).stem
        rule = rule_for_stem(stem, thresholds)
        entry = {"photo": str(raw_path), "stem": stem, "rule": rule,
                 "pass": False, "reason": None, "error": None}
        try:
            target = load_target(targets_dir, stem)
            if target is None:
                entry["error"] = f"目标 JPEG 缺失: {Path(targets_dir) / stem}.jpg"
                entry["reason"] = "no_target"
                reports.append(entry)
                continue
            ours = render_anchor(raw_path, prof, pipe) if render_fn is None \
                else render_fn(raw_path, prof, pipe)
            ours = np.asarray(ours)
            if ours.dtype != np.uint8:
                ours = (np.clip(ours, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
            target = align_target(np.asarray(target), ours.shape[:2])
            stats = four_caliber_stats(ours, target)
            ok, reason = evaluate_photo(stats, rule)
            entry.update({"full": stats["full"], "neutral": stats["neutral"],
                          "bands": stats["bands"],
                          "highlight": stats["highlight"],
                          "pass": ok, "reason": reason})
        except Exception as e:  # noqa: BLE001  渲染/解码异常 → 记为该锚点失败
            entry["error"] = f"{type(e).__name__}: {e}"
            entry["reason"] = "exception"
        reports.append(entry)

    n = len(reports)
    n_pass = sum(1 for r in reports if r["pass"])
    summary = {"n": n, "n_pass": n_pass,
               "pass": n > 0 and n_pass == n,
               "thresholds": {k: {"caliber": v["caliber"],
                                  "da": float(v["da"]), "db": float(v["db"])}
                              for k, v in thresholds.items()}}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"regression_{name}.json"
    report = {"name": name, "dcp": dcp_resolved, "preset": preset_path,
              "targets": str(targets_dir), "out": str(out_json),
              "thresholds": summary["thresholds"],
              "summary": summary, "reports": reports}
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # 控制台摘要
    print(f"[regress] 锚点 {n} 张 (targets={targets_dir}):")
    for r in reports:
        tag = "PASS" if r["pass"] else "FAIL"
        if r.get("error"):
            print(f"  [{tag}] {r['stem']}: {r['error']}")
            continue
        f, h = r["full"], r["highlight"]
        line = (f"  [{tag}] {r['stem']}: full Δa={f['da']:.2f} Δb={f['db']:.2f} "
                f"ΔS={f['dS']:.2f} Δp50={f['dp50']:.2f}")
        if r["neutral"]:
            line += f" | neutral Δa={r['neutral']['da']:.2f} Δb={r['neutral']['db']:.2f}"
        if h:
            line += f" | hi Δa={h['da']:.2f} Δb={h['db']:.2f}"
        line += f"  (rule={r['rule']['key'] if r['rule'] else 'none'}, {r['reason']})"
        print(line)
    print(f"[regress] pass = {summary['pass']} ({n_pass}/{n}) "
          f"阈值 {summary['thresholds']}")
    print(f"[regress] 报告 → {out_json}")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="四口径锚点回归 (0376/5236)")
    ap.add_argument("--dcp", default=None, help="基准 DCP (缺省取 preset['dcp'])")
    ap.add_argument("--preset", required=True, help="preset JSON (含 params/stages)")
    ap.add_argument("--targets", default=None,
                    help="目标 JPEG 目录 (<stem>.jpg; 缺省 = lr_corpus)")
    ap.add_argument("--anchors", nargs="+", default=list(DEFAULT_ANCHORS),
                    help="锚点 RAW 路径或 stem 关键字 (默认 0376 5236)")
    ap.add_argument("--raw-dirs", nargs="+", default=None,
                    help="锚点关键字定位 RAW 的搜索目录")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                    help="报告输出目录 (默认 rawlab/out/profile_fit)")
    ap.add_argument("--name", default=None,
                    help="报告名 regression_<name>.json (缺省 = DCP stem)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    targets = args.targets or str(DEFAULT_OUT_DIR / "lr_corpus")
    if not Path(args.preset).exists():
        print(f"[error] preset 不存在: {args.preset}")
        return 1
    anchors = resolve_anchors(args.anchors, args.raw_dirs)
    name = args.name
    if name is None:
        dcp = args.dcp
        if dcp is None and Path(args.preset).exists():
            dcp = json.loads(Path(args.preset).read_text(encoding="utf-8")) \
                .get("dcp")
        name = Path(dcp).stem if dcp else "anchors"
    report = run_regression(anchors, targets, args.out_dir, name,
                            dcp_path=args.dcp, preset_path=args.preset)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
