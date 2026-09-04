"""光照估计经典法 语料评估 —— 估计法 WB vs 现行 as_shot WB (阶段三 §2)。

问题 (设计 §2): 现行 WB 链 = DCP as_shot neutral → warmth 曲线微调。as_shot
是相机出厂记录, 非拍摄时实况 —— 低色温人造光下可能偏离实际光源。本评估在
弱监督语料上对照: 用经典光照估计法 (Gray-World / Gray-Edge p=1,2 / White-
Patch) 从 **相机原生线性域解码图** (未 WB, 与 as_shot 系数同域) 估计光源 →
pixo WB 参数域 (est_cct, wb_to_temp_tint 逆链), 渲染后与相机 JPEG 参照比
ΔE2000, 检验"估计 CCT 是否比 as_shot 更接近实况"。

三轨口径:
  A 轨 (现行):  render_preview_full 中性参数 (exposure 0.0 / trim [1,1,1])
                = as_shot neutral + warmth 曲线, 与 fit_rp_ccm.aligned_pair
                基线完全同口径;
  B 轨 (估计法): 同链但 neutral 源 = 估计 (temp_tint_to_wb(prof, est) 后把
                warmth 曲线按估计 wb_B 预折入数值向量 mode —— Stage 的
                manual/向量模式跳过 warmth, 预折入使两轨唯一差异 = neutral
                源, 变量隔离);
  参照:         RAW 内嵌相机 JPEG 缩略图 (EXIF 逆旋转, fit_rp_ccm 同源)。
指标: CIEDE2000 (eval_rp_ccm_ab.delta_e_2000, 开跑先 --selftest 文献对自检),
语料窗口 [0.01,0.90] 线性域网格抽样 (sample_linear_pairs 同式)。
分带: 按 as_shot wb_B 三带 (日光 <1.5 / 中间 1.5–2.0 / 低色温 ≥2.0)。
转正初评 (三证据): ① A/B 收益量化 (本报告; 改善 <1 JND=2.3 ΔE00 → 明确
"无转正价值"); ② 确定性方案 (经典法纯 numpy, 无随机无权重, seed 无关);
③ 域外降级 (guard 轨: 估计 CCT 偏离 as_shot CCT 超 --guard-k 时回退
as_shot —— 数据复用 A 轨结果, 演示兜底策略形态)。

纪律: **只报告不接运行时** —— 不写 configs/, 不建 src/pixo/render/learned/,
src/pixo 零改动 (设计 §3 红线)。

用法:
  python scripts/illumination_est/eval_illum.py --limit 6    # 冒烟
  python scripts/illumination_est/eval_illum.py              # 全语料 (54 张)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS / "illumination_est"), str(_SCRIPTS / "calib"),
           str(_SCRIPTS), str(_SCRIPTS / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval_rp_ccm_ab import delta_e_2000, linear_srgb_to_lab, selftest
import diff_core
from fit_rp_ccm import DCP, aligned_pair, iter_corpus, sample_linear_pairs
from pixo.render.api import Renderer
from pixo.render.core.calibration import load_dcp
from pixo.render.core.color import cct_from_wb, temp_tint_to_wb
from pixo.render.modules.white_balance import apply_warmth

import gray_edge
import gray_world
import white_patch

JND = 2.3                      # 1 JND ≈ 2.3 ΔE00 (转正判据, 同阶段二口径)
WARMTH = 0.9                   # warmth 标量 (whitebalance Stage 默认)
WARM_CAL = (_SCRIPTS / ".." / "configs" / "calibration" / "warmth_curve.json")

# 估计法轨道: (轨道名, 模块, 关键字参数)
METHODS = (
    ("gray_world", gray_world, {}),
    ("gray_edge_p1", gray_edge, {"p": 1.0}),
    ("gray_edge_p2", gray_edge, {"p": 2.0}),
    ("white_patch", white_patch, {}),
)


def load_warm_curve(path: Path) -> np.ndarray:
    """warmth_curve.json knots (A/B 两轨共用同一 warmth 曲线; 非法即报错 ——
    与真实链的"文件存在即生效"不同, 评估不允许静默回退另一条数值路径)。"""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return np.asarray(doc["knots"], dtype=np.float64)


def band_of(wb_b: float) -> str:
    """as_shot wb_B 三带 (阶段二口径): 日光 <1.5 / 中间 1.5–2.0 / 低色温 ≥2.0。"""
    if wb_b < 1.5:
        return "daylight(<1.5)"
    if wb_b < 2.0:
        return "mid(1.5-2.0)"
    return "low_cct(>=2.0)"


def render_with_wb(renderer: Renderer, raw: str, wb: np.ndarray,
                   long_edge: int) -> np.ndarray:
    """以数值向量 mode 渲染 B 轨 (warmth 已折入 wb; Stage 对向量模式不再
    二次施加 warmth —— 两轨唯一差异 = neutral 源, 见模块 docstring)。"""
    wb_list = [float(wb[0]), float(wb[1]), float(wb[2])]
    return renderer.render_preview_full(
        raw, long_edge=long_edge,
        params={"exposure": {"mode": 0.0},
                "whitebalance": {"mode": wb_list, "trim": [1, 1, 1]}})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--preview-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--thumb-rot", default="auto", choices=("auto", "off"))
    ap.add_argument("--guard-k", type=float, default=2500.0,
                    help="域外降级阈值: |cct_est − cct_as_shot| 超此值回退 as_shot")
    ap.add_argument("--out-md", default=".artifacts/illumination_eval.md")
    ap.add_argument("--out-json", default=".artifacts/illumination_eval.json")
    ap.add_argument("--warm-cal", default=str(WARM_CAL.resolve()))
    args = ap.parse_args(argv)

    print("== CIEDE2000 文献对自检 (eval_rp_ccm_ab --selftest)")
    try:
        selftest()
    except SystemExit as exc:
        print(f"selftest 失败: {exc}", file=sys.stderr)
        return 1

    items = iter_corpus(args.corpus, args.raw, args.limit)
    if not items:
        print("语料为空: 检查 --corpus/--raw", file=sys.stderr)
        return 2

    renderer = Renderer(args.dcp)
    prof = load_dcp(args.dcp)
    knots = load_warm_curve(Path(args.warm_cal))
    method_names = [name for name, _, _ in METHODS]

    rows: list[dict] = []
    skipped: list[str] = []
    pools: dict[str, list] = {t: [] for t in ["as_shot", *method_names,
                                              *(f"guard_{m}" for m in method_names)]}
    t0 = time.time()
    for i, (pid, raw) in enumerate(items, 1):
        try:
            pair = aligned_pair(renderer, raw, args.preview_edge,
                                thumb_rot=args.thumb_rot)
            if pair is None:
                raise RuntimeError("对齐失败")
            base, ref = pair
            # 相机原生域解码图 (未 WB, 与 as_shot 系数同域; decode 段与渲染
            # 管线逐行同式, t30 保真门已证) —— 估计输入
            img_cam, wb_cam = diff_core._decode_preview(raw, args.preview_edge)
            wb_b = float(wb_cam[2] / max(wb_cam[1], 1e-9))
            cct_as = float(cct_from_wb(wb_cam, prof))
            band = band_of(wb_b)

            # A 轨 ΔE (as_shot, aligned_pair 基线即渲染结果)。逐照片标量
            # 曝光增益对齐 (gain 由 A 轨算, A/B 两轨共用 —— 中性渲染与相机
            # JPEG 差 ~2EV, 不对齐则 ΔE 被亮度差淹没; eval_rp_ccm_ab 同式,
            # WB 评估只看色度)。
            src_a, dst = sample_linear_pairs(base, ref, stride=args.stride)
            if src_a.shape[0] < 500:
                raise RuntimeError(f"有效样本过少 {src_a.shape[0]}")
            gain = float(dst.mean() / max(src_a.mean(), 1e-9))
            de_a = delta_e_2000(linear_srgb_to_lab(src_a * gain),
                                linear_srgb_to_lab(dst))

            row = {"photo_id": pid, "wb_B": round(wb_b, 4), "band": band,
                   "cct_as_shot": round(cct_as, 1),
                   "ev_align": round(float(np.log2(max(gain, 1e-9))), 3),
                   "a_median": float(np.median(de_a)),
                   "a_p95": float(np.quantile(de_a, 0.95)), "n": int(src_a.shape[0])}
            pools["as_shot"].append(de_a)
            for name, mod, kw in METHODS:
                cct, tint = mod.est_cct(img_cam, prof, **kw)
                wb_n = np.asarray(temp_tint_to_wb(prof, cct, tint),
                                  dtype=np.float64)
                wb_f = apply_warmth(wb_n, prof, WARMTH, {"curve": knots})
                img_b = render_with_wb(renderer, raw, wb_f, args.preview_edge)
                if img_b.dtype == np.uint8:
                    img_b = img_b.astype(np.float64) / 255.0
                src_b, dst_b = sample_linear_pairs(img_b, ref,
                                                   stride=args.stride)
                if src_b.shape[0] < 500:
                    raise RuntimeError(f"{name}: 有效样本过少")
                de_b = delta_e_2000(linear_srgb_to_lab(src_b * gain),
                                    linear_srgb_to_lab(dst_b))
                row[f"{name}_cct"] = round(float(cct), 1)
                row[f"{name}_tint"] = round(float(tint), 2)
                row[f"{name}_median"] = float(np.median(de_b))
                row[f"{name}_p95"] = float(np.quantile(de_b, 0.95))
                # guard 轨 (域外降级演示): 估计 CCT 偏离 as_shot 过大 → 回退 as_shot
                if abs(float(cct) - cct_as) <= args.guard_k:
                    pools[f"guard_{name}"].append(de_b)
                else:
                    pools[f"guard_{name}"].append(de_a)
                pools[name].append(de_b)
            rows.append(row)
            r = rows[-1]
            print(f"[{i}/{len(items)}] {pid} [{band}] as_shot={r['a_median']:.2f} "
                  f"(cct {cct_as:.0f}K ev{row['ev_align']:+.1f}) " +
                  " ".join(f"{m.split('_')[0] if m.startswith('gray_edge') else m}"
                           f"={r[f'{m}_median']:.2f}" for m in method_names),
                  flush=True)
        except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
            skipped.append(f"{pid}: {exc}")
            print(f"[{i}/{len(items)}] {pid} 跳过: {exc}", flush=True)

    if not rows:
        print("无可评估照片", file=sys.stderr)
        return 1

    def _agg(pool_list):
        pool = np.concatenate(pool_list)
        return {"median": float(np.median(pool)),
                "p95": float(np.quantile(pool, 0.95)),
                "mean": float(np.mean(pool))}

    summary = {t: _agg(pl) for t, pl in pools.items() if pl}
    med_a = summary["as_shot"]["median"]
    verdict: dict = {"improvement_jnd_threshold": JND}
    for m in method_names:
        imp = med_a - summary[m]["median"]
        g_imp = med_a - summary[f"guard_{m}"]["median"]
        verdict[m] = {
            "improvement": round(imp, 4),
            "improvement_pct": round(imp / max(med_a, 1e-9) * 100, 2),
            "improvement_jnds": round(imp / JND, 3),
            "pass_1jnd": imp >= JND,
            "guard_improvement": round(g_imp, 4),
            "guard_pass_1jnd": g_imp >= JND,
        }
    any_pass = any(verdict[m]["pass_1jnd"] for m in method_names)
    any_guard_pass = any(verdict[m]["guard_pass_1jnd"] for m in method_names)

    # 分带统计 (as_shot wb_B 三带)
    bands: dict[str, dict] = {}
    for band in sorted({r["band"] for r in rows}):
        sel = [r for r in rows if r["band"] == band]
        entry = {"n_photos": len(sel)}
        for t in ["as_shot", *method_names]:
            key = "a_median" if t == "as_shot" else f"{t}_median"
            entry[t] = {"median": round(float(np.median(
                [r[key] for r in sel])), 4)}
        bands[band] = entry

    write_report(Path(args.out_md), args, rows, skipped, summary, verdict,
                 bands, any_pass, any_guard_pass, time.time() - t0)
    write_json(Path(args.out_json), args, rows, skipped, summary, verdict,
               bands, any_pass, any_guard_pass)
    print(f"== 总体: as_shot {med_a:.3f} | " +
          " | ".join(f"{m} {summary[m]['median']:.3f} "
                     f"({verdict[m]['improvement_pct']:+.1f}%)"
                     for m in method_names))
    print(f"DONE {args.out_md} ({time.time() - t0:.0f}s)")
    return 0


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def write_report(out: Path, args, rows, skipped, summary, verdict, bands,
                 any_pass: bool, any_guard_pass: bool, elapsed: float) -> None:
    med_a = summary["as_shot"]["median"]
    tracks = ["as_shot", *[m for m in verdict if m != "improvement_jnd_threshold"]]
    lines = [
        "# 光照估计经典法 评估报告 (阶段三 §2: 估计法 WB vs 现行 as_shot)",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')} · 耗时 {elapsed:.0f}s",
        f"- 语料: {args.corpus} ({len(rows)} 张评估 / {len(skipped)} 张跳过)"
        f" · DCP {Path(args.dcp).name} @ long_edge={args.preview_edge}, "
        f"stride={args.stride}",
        f"- ΔE 实现: eval_rp_ccm_ab.delta_e_2000 (Sharma 2005, --selftest 通过),"
        f" 窗口 [0.01,0.90] 线性域; 参照 = RAW 内嵌相机 JPEG (EXIF 逆旋转)",
        f"- 估计法: Gray-World / Gray-Edge(Minkowski p=1,2) / White-Patch "
        f"(纯 numpy), 逆链 = temp_tint_to_wb 逆 (wb_to_temp_tint), 对齐 pixo "
        f"WB 参数域; B 轨 warmth 曲线按估计 wb_B 预折入 (两轨唯一差异 = "
        f"neutral 源)",
        "",
        "## 总体 (pooled ΔE2000 样本池)",
        "",
        "| 轨道 | median | p95 | 较 as_shot 改善 | JND 倍数 |",
        "|---|---:|---:|---:|---:|",
        f"| A: as_shot (现行) | {med_a:.3f} | {summary['as_shot']['p95']:.3f} "
        "| — | — |",
    ]
    label = {"gray_world": "Gray-World", "gray_edge_p1": "Gray-Edge p=1",
             "gray_edge_p2": "Gray-Edge p=2", "white_patch": "White-Patch"}
    for m in tracks[1:]:
        v = verdict[m]
        lines.append(
            f"| B: {label.get(m, m)} | {summary[m]['median']:.3f} "
            f"| {summary[m]['p95']:.3f} | **{v['improvement']:+.3f} "
            f"({v['improvement_pct']:+.1f}%)** | {v['improvement_jnds']:+.2f} |")
    lines += [
        "",
        "### 域外降级 guard 轨 (|cct_est − cct_as_shot| > "
        f"{args.guard_k:.0f}K 时回退 as_shot)",
        "",
        "| 估计法 | guard median | 改善 | ≥1 JND |",
        "|---|---:|---:|:---:|",
    ]
    for m in tracks[1:]:
        v = verdict[m]
        lines.append(f"| {label.get(m, m)} | "
                     f"{summary['guard_' + m]['median']:.3f} "
                     f"| {v['guard_improvement']:+.3f} "
                     f"| {'✅' if v['guard_pass_1jnd'] else '❌'} |")
    lines += [
        "",
        "## 分带统计 (as_shot wb_B: 日光 <1.5 / 中间 1.5–2.0 / 低色温 ≥2.0)",
        "",
        "| 带 | n | as_shot | " + " | ".join(label.get(m, m)
                                                  for m in tracks[1:]) + " |",
        "|---|---:|---:|" + "---:|" * len(tracks[1:]),
    ]
    for band, e in bands.items():
        lines.append(
            f"| {band} | {e['n_photos']} | {e['as_shot']['median']:.3f} | "
            + " | ".join(f"{e[m]['median']:.3f}" for m in tracks[1:]) + " |")

    lines += [
        "",
        "## 三证据转正初评 (阶段三 §2 验收)",
        "",
        f"1. **A/B 收益量化**: 最佳估计法改善 "
        f"{max(verdict[m]['improvement'] for m in tracks[1:]):+.3f} ΔE "
        f"({max(verdict[m]['improvement_pct'] for m in tracks[1:]):+.1f}%), "
        f"= {max(verdict[m]['improvement_jnds'] for m in tracks[1:]):+.2f} JND "
        f"(判据 ≥1 JND = 2.3 ΔE00)"
        + (" → **达到**" if any_pass else " → **未达到**") + ";",
        "2. **确定性方案**: 四法均为纯 numpy 确定性实现 (无随机/无权重/"
        "seed 无关), 同输入逐位可复现 → 满足;",
        "3. **域外降级**: guard 轨 (估计 CCT 偏离 as_shot >"
        f"{args.guard_k:.0f}K 回退) 最佳改善 "
        f"{max(verdict[m]['guard_improvement'] for m in tracks[1:]):+.3f} ΔE"
        + (" → **达到**" if any_guard_pass else " → **未达到**") + ";",
        "",
    ]
    if not any_pass and not any_guard_pass:
        lines.append("**结论: 无转正价值** —— 全部估计法改善 <1 JND"
                     " (设计 §2 验收: 如实报告无收益; 不接运行时, as_shot 链"
                     "维持现状)。")
    elif any_pass:
        best = max(tracks[1:], key=lambda m: verdict[m]["improvement"])
        lines.append(f"**结论: 初评有转正讨论价值 ({label.get(best, best)} 达到 "
                     "1 JND 判据)** —— 但本评估为经典统计法原型 (非学习型组件),"
                     " 且仅单相机语料; 转正须补齐多相机复验 + 域外鲁棒性专项"
                     " (三证据 checklist), 本报告不构成切换依据。")
    else:
        lines.append("**结论: 裸估计法未达 1 JND, 但 guard 降级形态达到** "
                     "—— 需先解决估计的域外稳定性才值得继续投入; 单相机语料, "
                     "不构成切换依据。")
    lines += [
        "",
        "## 逐照片",
        "",
        "| photo | 带 | wb_B | as_shot cct | A med | "
        + " | ".join(f"{label.get(m, m)} cct / med" for m in tracks[1:]) + " |",
        "|---|---|---:|---:|---:|" + "---:|" * len(tracks[1:]),
    ]
    for r in rows:
        cells = " | ".join(
            f"{r[f'{m}_cct']:.0f} / {r[f'{m}_median']:.3f}"
            for m in tracks[1:])
        lines.append(f"| {r['photo_id']} | {r['band']} | {r['wb_B']:.3f} "
                     f"| {r['cct_as_shot']:.0f} | {r['a_median']:.3f} "
                     f"| {cells} |")
    if skipped:
        lines += ["", f"跳过 {len(skipped)} 张: " + "; ".join(skipped[:5])
                  + (" ..." if len(skipped) > 5 else "")]
    lines += [
        "",
        "## 注记 (口径)",
        "",
        "- **A 轨与阶段一/二基线同口径**: exposure 0.0 / trim [1,1,1] 的中性"
        "渲染 (as_shot neutral + warmth 曲线), 参照 = RAW 内嵌相机 JPEG",
        " (fit_rp_ccm.aligned_pair 同源同对齐); ΔE2000 复用 eval_rp_ccm_ab 实现。",
        "- **B 轨 warmth 预折入**: whitebalance Stage 对 manual/数值向量模式"
        "跳过 warmth (视为用户显式意图), 估计轨把 warmth 曲线按估计 wb_B 折入"
        "向量后再以向量 mode 渲染 —— 保证两轨唯一差异 = neutral 源。",
        "- **guard 轨是数据复用**: 触发回退的照片 B 轨指标直接替换为 A 轨结果,"
        "不额外渲染 —— 演示域外降级策略的形态, 阈值 ("
        f"{args.guard_k:.0f}K) 为首跑经验值。",
        "- **纪律**: 本报告只作转正初评依据, **不接运行时** (设计 §2/§3); "
        "configs/ 与 src/pixo 未被本脚本修改。",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def write_json(out: Path, args, rows, skipped, summary, verdict, bands,
               any_pass, any_guard_pass) -> None:
    doc = {
        "schema": "pixo.illumination_eval.v1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "args": {k: v for k, v in vars(args).items()},
        "corpus": {"n_eval": len(rows), "skipped": skipped},
        "jnd": JND,
        "summary": summary,
        "verdict": verdict,
        "promotion": {"evidence_1_ab_gain_pass": any_pass,
                      "evidence_2_determinism": True,
                      "evidence_3_out_of_domain_guard_pass": any_guard_pass,
                      "verdict": ("值得继续 (guard 形态达标)" if any_guard_pass
                                  else ("有转正讨论价值" if any_pass
                                        else "无转正价值"))},
        "bands": bands,
        "photos": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
