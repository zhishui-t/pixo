"""t85 全语料分层 A/B 回归：三层 linspace 抽样 ~40 张，逐张指标+分带验收。

用法:
  python scripts/run_ab_regression.py [--smoke]
  python scripts/run_ab_regression.py --files <JSONL(每行raw)> [--out <jsonl>]  # t97 显式清单
输出: docs/metrics/.ab_results.jsonl（渐进落盘）；--files 时默认 .ab_highlight_stress_results.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ab_vs_camera_thumb import cam_thumb  # noqa: E402
from pixo.meta import extract as ex       # noqa: E402
from pixo.render.api import Renderer      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LAYERS = {
    "0711": [Path("K:/data/photo/0711/raw")],
    "spring": [Path("K:/data/photo/2026春节")],
    "xiamen": [p for p in Path("K:/data/photo/厦门").iterdir() if p.is_dir()],
}
MUST_CONTAIN = {
    "0711": ["DSC_5236", "DSC_5239"],
    "spring": ["DSC_0352", "DSC_0355"],
    "xiamen": ["DSC_0847", "DSC_2746"],
}
N_PER_LAYER = {"0711": 12, "spring": 12, "xiamen": 16}
EXPLICIT_HIGHKEY = {"DSC_0847"}
EXPLICIT_NIGHT = {"DSC_2746"}
INDOOR_FOUR = {"DSC_5236", "DSC_5239", "DSC_0352", "DSC_0355"}


def pool(dirs):
    out = []
    for d in dirs:
        out += [p for p in sorted(d.glob("*.NEF")) if not p.name.startswith("._")]
    return sorted(set(out))


def linspace_pick(files, n, musts):
    files = sorted(files)
    k = min(n, len(files))
    idx = np.linspace(0, len(files) - 1, k).round().astype(int)
    sel = {files[i] for i in idx}
    for m in musts:
        hit = [f for f in files if m in f.name]
        if hit:
            sel.add(hit[0])
    return sorted(sel)


def metrics(name, ours_u8, ref_u8):
    h = min(ours_u8.shape[0], ref_u8.shape[0])
    w = min(ours_u8.shape[1], ref_u8.shape[1])
    a = cv2.resize(ours_u8, (w, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(ref_u8, (w, h), interpolation=cv2.INTER_AREA)
    la = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)
    lb = cv2.cvtColor(b, cv2.COLOR_RGB2LAB).astype(np.float32)
    d = np.linalg.norm(la - lb, axis=2)
    return {
        "dE_mean": round(float(d.mean()), 2),
        "dE_p50": round(float(np.median(d)), 2),
        "dL": round(float((la[..., 0] - lb[..., 0]).mean()), 2),
        "da": round(float((la[..., 1] - lb[..., 1]).mean()), 2),
        "db": round(float((la[..., 2] - lb[..., 2]).mean()), 2),
        "clip_hi_ours": round(float((a.max(axis=2) >= 250).mean()) * 100, 3),
        "clip_hi_cam": round(float((b.max(axis=2) >= 250).mean()) * 100, 3),
    }


def scene_of(stem: str, our_rgb: np.ndarray):
    """场景归类：高调/夜景仅认显式清单(0847/2746)，避免亮图误判高调带；
    暗图自动归夜景（该带宽松 dE<=20）。附亮度特征供超限归因。"""
    lab_l = float(cv2.cvtColor(our_rgb, cv2.COLOR_RGB2LAB)[..., 0].mean())
    if stem in EXPLICIT_HIGHKEY:
        cls, trait = "highkey", f"高调(显式清单;L均值{lab_l:.0f})"
    elif stem in EXPLICIT_NIGHT or lab_l <= 32:
        cls, trait = "night", f"夜景(L均值{lab_l:.0f})"
    else:
        cls = "indoor" if stem in INDOOR_FOUR else "normal"
        trait = f"L均值{lab_l:.0f}"
    return cls, f"{trait}; 分辨率{our_rgb.shape[1]}x{our_rgb.shape[0]}"


def band_check(cls, m):
    # 相机高光占比 <0.05% 时比值无统计意义（分母近零），跳过 clip 判据
    ratio = ((m["clip_hi_ours"] / m["clip_hi_cam"])
             if m["clip_hi_cam"] >= 0.05 else None)
    # t100 判据加固: 常规带补 clip<=cam*1.5 —— 堵 DSC_2761 比值 3.148 型漏网
    #   (相机 clip>=1% 才应用: 分母足够大、比值有统计意义; DSC_2816 cam=0.28%
    #   属绝对值极小边缘样本, cam≈0 时比值发散, 不判超限)。
    clip_ok = True
    if cls == "normal" and m["clip_hi_cam"] >= 1.0:
        clip_ok = ratio is not None and float(ratio) <= 1.5
    if cls == "indoor":
        ok, why = m["dE_mean"] <= 12.0, "室内带 dE<=12"
    elif cls == "night":
        ok, why = m["dE_mean"] <= 20.0, "夜景带 dE<=20"
    elif cls == "highkey":
        ok = abs(m["dL"]) <= 6.0 and (ratio is None or ratio <= 1.5)
        why = "高调带 |dL|<=6 且 clip<=cam*1.5"
    else:
        ok, why = abs(m["dL"]) <= 8.0 and clip_ok, "常规带 |dL|<=8 且 clip<=cam*1.5(cam>=1%)"
    return ok, why, ratio, clip_ok


def load_custom_samples(files_jsonl):
    """t97 扩展：--files 传入 JSONL（每行含 raw/type/batch），逐张走同套指标管线。
    返回 (samples, meta_map)；meta_map 供行级附注用。"""
    import json as _json
    samples, meta = [], {}
    for line in open(files_jsonl, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = _json.loads(line)
        p = Path(rec.get("raw", ""))
        samples.append(("stress", p))
        meta[p.name] = {k: v for k, v in rec.items() if k != "raw"}
    return sorted(set(samples)), meta


def main(smoke: bool, files_jsonl=None, out_jsonl=None):
    dcp = sorted((ROOT / "resources/dcp").glob("*.dcp"))[0]
    if files_jsonl:
        samples, meta = load_custom_samples(files_jsonl)
        print(f"samples total = {len(samples)} (from {files_jsonl})", flush=True)
        out_jsonl = out_jsonl or str(ROOT / "docs/metrics/.ab_highlight_stress_results.jsonl")
    else:
        samples = []
        for layer, dirs in LAYERS.items():
            for p in linspace_pick(pool(dirs), N_PER_LAYER[layer], MUST_CONTAIN[layer]):
                samples.append((layer, p))
        if smoke:
            keep = {"DSC_5236", "DSC_2746", "DSC_0847"}
            samples = [s for s in samples if any(k in s[1].name for k in keep)]
        print(f"samples total = {len(samples)}", flush=True)
        out_jsonl = out_jsonl or str(ROOT / "docs/metrics/.ab_results.jsonl")

    renderer = Renderer(dcp)
    rows = []
    with open(out_jsonl, "w", encoding="utf-8") as jf:
        for i, (layer, p) in enumerate(samples, 1):
            stem = p.stem
            try:
                ref = cam_thumb(p)
                ours = renderer.render_preview_full(p, long_edge=1024)
                alt = renderer.render_preview_full(
                    p, long_edge=1024, params={"tone": {"brightness": 0.25}})
                m = metrics(f"{stem}", ours, ref)
                m_alt = metrics(f"{stem}[b=.25]", alt, ref)
                cls, trait = scene_of(stem, ours)
                ok, why, ratio, clip_ok = band_check(cls, m)
                # t100 超限归因: 高光外推(比值>1.5) / 提亮超带(dL>8) / 压暗超带(dL<-8)
                if ok:
                    attrib = ""
                elif ratio is not None and float(ratio) > 1.5 and m["clip_hi_cam"] >= 1.0:
                    attrib = "高光外推"
                elif cls in ("highkey",) and abs(m["dL"]) > 6.0:
                    attrib = "dL超带"
                elif abs(m["dL"]) > 8.0:
                    attrib = "提亮超带(压暗)" if m["dL"] > 0 else "压暗超带(提亮)"
                else:
                    attrib = "clip超带" if not clip_ok else ""
                row = {
                    "layer": layer, "file": p.name, "class": cls,
                    **m, "dE_alt": m_alt["dE_mean"],
                    "clip_ratio": round(ratio, 3) if ratio else None,
                    "clip_ok": clip_ok, "attribution": attrib,
                    "band_ok": ok, "band_rule": why, "scene_trait": trait,
                }
                if files_jsonl and p.name in meta:
                    for k, v in meta[p.name].items():
                        row[f"src_{k}"] = v
            except Exception as exc:  # noqa: BLE001 - 单张失败不拖垮全集
                row = {"layer": layer, "file": p.name, "error":
                       f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            jf.write(json.dumps(row, ensure_ascii=False) + "\n")
            jf.flush()
            status = "ERR " if "error" in row else ("PASS" if row.get("band_ok") else "OVER ")
            print(f"[{i}/{len(samples)}] {status} {stem} "
                  f"{row.get('dE_mean', '-')}/{row.get('dL', '-')}", flush=True)
    print("JSONL_DONE", flush=True)


if __name__ == "__main__":
    smoke = "--smoke" in sys.argv
    files_jsonl = None
    out_jsonl = None
    if "--files" in sys.argv:
        files_jsonl = sys.argv[sys.argv.index("--files") + 1]
    if "--out" in sys.argv:
        out_jsonl = sys.argv[sys.argv.index("--out") + 1]
    main(smoke, files_jsonl, out_jsonl)
