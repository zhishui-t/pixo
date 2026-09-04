"""surrogate 保真门 —— torch 代理 vs 真实管线 ΔE2000 报告 (阶段二设计 §1, 硬前置)。

口径:
  - 同输入同 θ (θ0 = 现行 configs 标定值): surrogate(PhotoSurrogate.build,
    warmth_curve.json / z5ii_neutral_trim.json / tone 默认) vs
    Renderer.render_preview_full(中性参数);
  - **链口径**: 设计 §1 代理链为逐像素色彩链; 真实链中性参数下 clarity /
    refine / skin 三个 θ 无关的空间观感 stage 默认开启 (实测对逐像素链贡献
    ΔE2000 median ~2.1, 门不可达), 对照渲染将其显式关闭 (GATE_PARAMS)。
    exposure 0.0 / wb trim [1,1,1] 与 fit_rp_ccm.aligned_pair 口径一致。
  - 指标: CIEDE2000 (eval_rp_ccm_ab.delta_e_2000, 开跑先 --selftest 文献对
    自检), 语料窗口 [0.01,0.90] 线性域网格抽样 (sample_linear_pairs 同式)。
  - 门限: 总体 median ≤ 0.05 且 p95 ≤ 0.3; 抽样 ≥ --min-photos (默认 10) 张。
    不过门禁止任何 θ 优化 (设计 §1)。

用法:
  python scripts/calib/surrogate_fidelity.py                 # 语料前 12 张
  python scripts/calib/surrogate_fidelity.py --limit 20      # 前 20 张
  python scripts/calib/surrogate_fidelity.py --raw K:/a.NEF  # 显式 RAW
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS / "calib"), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import diff_core

from eval_rp_ccm_ab import delta_e_2000, linear_srgb_to_lab, selftest
from fit_rp_ccm import DCP, iter_corpus, sample_linear_pairs
from pixo.render.api import Renderer

# 真实链对照口径: 中性参数 + 显式关闭 θ 无关空间观感 stage (见模块 docstring)。
GATE_PARAMS = {
    "exposure": {"mode": 0.0},
    "whitebalance": {"trim": [1, 1, 1]},
    "clarity": {"enabled": False},
    "refine": {"sharpen": 0.0, "highlight_desat": 0.0, "chroma_denoise": 0.0},
    "skin": {"enabled": False},
}

THRESHOLD_MEDIAN = 0.05
THRESHOLD_P95 = 0.3


def gate_params_docs() -> str:
    rows = "\n".join(f"  - `{k}`: {v}" for k, v in GATE_PARAMS.items())
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None, help="显式 RAW (可多次)")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--min-photos", type=int, default=10)
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--long-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--out", default=".artifacts/surrogate_fidelity.md")
    args = ap.parse_args()

    items = iter_corpus(args.corpus, args.raw, args.limit or 0)
    if not items:
        print("语料为空: 检查 --corpus/--raw", file=sys.stderr)
        sys.exit(2)
    if len(items) < args.min_photos:
        print(f"抽样 {len(items)} 张 < 要求 {args.min_photos} 张", file=sys.stderr)
        sys.exit(2)

    print("== CIEDE2000 文献对自检 (eval_rp_ccm_ab --selftest)")
    try:
        selftest()
    except SystemExit as exc:  # selftest 失败即门失效
        print(f"selftest 失败: {exc}", file=sys.stderr)
        sys.exit(1)

    renderer = Renderer(args.dcp)
    rows: list[dict] = []
    skipped: list[str] = []
    all_de: list[np.ndarray] = []
    t0 = time.time()
    for i, (pid, raw) in enumerate(items, 1):
        try:
            real = renderer.render_preview_full(raw, long_edge=args.long_edge,
                                                params=dict(GATE_PARAMS))
            real_f = real.astype(np.float64) / 255.0
            sur = diff_core.PhotoSurrogate.build(raw, args.dcp,
                                                 long_edge=args.long_edge)
            with torch.no_grad():
                u8 = sur.quantize(sur()).cpu().numpy().astype(np.uint8)
            if u8.shape != real.shape:
                raise RuntimeError(f"形状不一致 surrogate {u8.shape} vs real {real.shape}")
            sur_f = u8.astype(np.float64) / 255.0
            b_lin, r_lin = sample_linear_pairs(sur_f, real_f, stride=args.stride)
            if b_lin.shape[0] < 500:
                raise RuntimeError(f"有效样本过少 {b_lin.shape[0]}")
            de = delta_e_2000(linear_srgb_to_lab(b_lin), linear_srgb_to_lab(r_lin))
            all_de.append(de)
            rows.append({
                "photo_id": pid,
                "n": int(b_lin.shape[0]),
                "median": float(np.median(de)),
                "p95": float(np.quantile(de, 0.95)),
                "max": float(de.max()),
                "identical_frac": float(np.mean(de <= 1e-9)),
            })
            r = rows[-1]
            print(f"[{i}/{len(items)}] {pid} n={r['n']} "
                  f"median={r['median']:.4f} p95={r['p95']:.4f} "
                  f"max={r['max']:.3f} 同码率={r['identical_frac'] * 100:.1f}%",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
            skipped.append(f"{pid}: {exc}")
            print(f"[{i}/{len(items)}] {pid} 跳过: {exc}", flush=True)

    if len(rows) < args.min_photos:
        print(f"有效照片 {len(rows)} < 要求 {args.min_photos}", file=sys.stderr)
        sys.exit(1)

    pool = np.concatenate(all_de)
    med = float(np.median(pool))
    p95 = float(np.quantile(pool, 0.95))
    ok = (med <= THRESHOLD_MEDIAN) and (p95 <= THRESHOLD_P95)
    verdict = "PASS ✅" if ok else "FAIL ❌"

    worst = max(rows, key=lambda r: r["median"])
    lines = [
        "# Surrogate 保真门报告 (torch 可微代理 vs 真实管线)",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 结论: **{verdict}** — 总体 ΔE2000 median {med:.4f} / p95 {p95:.4f} "
        f"(门限 median ≤{THRESHOLD_MEDIAN} / p95 ≤{THRESHOLD_P95})",
        f"- 语料: {args.corpus} ({len(rows)} 张评估 / {len(skipped)} 张跳过; "
        f"要求 ≥{args.min_photos})",
        f"- DCP: {Path(args.dcp).name} @ long_edge={args.long_edge}, "
        f"stride={args.stride}, θ0=现行 configs 标定值",
        f"- ΔE 实现: eval_rp_ccm_ab.delta_e_2000 (Sharma 2005, --selftest 通过), "
        f"窗口 [0.01,0.90] 线性域 (语料口径 sample_linear_pairs)",
        f"- 耗时: {time.time() - t0:.1f}s",
        "",
        "## 链口径",
        "",
        "代理链 (设计 §1) = decode → exposure(ev) → whitebalance(camera_wb ×"
        " warmth × 矩阵 + 高光中性化) → [RP-CCM] → tone(brightness + sRGB EOTF"
        " LUT 线性插值) → colorcal 中性快速路径 (CCT 分桶曲线) → u8 量化。",
        "真实对照 = render_preview_full 中性参数 (下表), 其中 clarity/refine/skin",
        "为 θ 无关的空间观感 stage (默认开启, 实测对逐像素链 ΔE median ~2.1),",
        "按代理链口径显式关闭:",
        "",
        "```json",
        json.dumps(GATE_PARAMS, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 可微近似 (前向逐位复刻, 反向平滑)",
        "",
        "- tone LUT: 真实链最近邻 (native 内核), 代理线性插值 (设计 §1) ——",
        "  ≤半格偏差, 本报告即其量化代价;",
        "- clip: 前向硬 clip (逐位), 反向 tanh 软梯度 (soft-clip 语义在反向);",
        "- colorcal tint: 前向 cv2 u8 逐位 (整数 tint), 反向 float Lab→RGB 雅可比;",
        "- 静态量 (饱和掩码/colorcal 权重与 L 混合索引/基 tint/CCT 分桶) θ0 冻结。",
        "",
        "## 总体 (全样本池)",
        "",
        "| 指标 | 值 | 门限 | 判定 |",
        "|---|---:|---:|:---:|",
        f"| ΔE2000 median | {med:.4f} | ≤ {THRESHOLD_MEDIAN} | "
        f"{'✅' if med <= THRESHOLD_MEDIAN else '❌'} |",
        f"| ΔE2000 p95 | {p95:.4f} | ≤ {THRESHOLD_P95} | "
        f"{'✅' if p95 <= THRESHOLD_P95 else '❌'} |",
        f"| ΔE2000 max | {float(pool.max()):.4f} | — | — |",
        f"| u8 同码像素占比 | {float(np.mean(pool <= 1e-9)) * 100:.2f}% | — | — |",
        "",
        "## 分照片",
        "",
        "| photo | n | median | p95 | max | 同码率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(f"| {r['photo_id']} | {r['n']} | {r['median']:.4f} "
                     f"| {r['p95']:.4f} | {r['max']:.3f} "
                     f"| {r['identical_frac'] * 100:.1f}% |")
    lines += [
        "",
        f"最差照片 (median): {worst['photo_id']} = {worst['median']:.4f}。",
    ]
    if skipped:
        lines += ["", f"跳过 {len(skipped)} 张: " + "; ".join(skipped[:3])
                  + (" ..." if len(skipped) > 3 else "")]
    lines += [
        "",
        "> 纪律: 本门为 θ 优化的硬前置 (设计 §1 —— 不过门禁止优化); 报告只读,",
        "> 未修改任何 configs/ 运行时配置与 src/pixo/render。",
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"== 总体: median {med:.4f} / p95 {p95:.4f} → {verdict}")
    if skipped:
        print(f"   跳过 {len(skipped)}: " + "; ".join(skipped[:3]))
    print(f"DONE {out} ({time.time() - t0:.1f}s)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
