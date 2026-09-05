"""RP-CCM A/B 评估 —— 同语料 DCP vs DCP+RP-CCM 双轨渲染 ΔE2000 报告 (设计 §4)。

双轨口径:
  A 轨 (DCP, 现行默认): Renderer 中性渲染 (exposure 0.0 / trim [1,1,1]);
  B 轨 (DCP+RP-CCM):   A 轨线性 sRGB 经 core.rp_ccm.apply_rp_ccm (相机系数
                       configs/color/rp_ccm_<camera>.json);
  参考: RAW 内嵌相机 JPEG 缩略图 (弱监督参考, 与拟合脚本同源同对齐)。
指标: CIEDE2000 (Sharma, Wu & Dalal 2005 实现, 含 --selftest 文献对自检),
按照片与整体汇总 median/p95, markdown 落 .artifacts/。

纪律: **只报告不切默认** —— 本脚本不写任何 configs/ 运行时配置, DCP 默认链
不受影响; 是否切换由人依据报告决策 (设计 §4 / §6)。

用法:
  python scripts/eval_rp_ccm_ab.py --selftest          # CIEDE2000 文献对自检
  python scripts/eval_rp_ccm_ab.py --limit 5           # 前 5 张语料 A/B
  python scripts/eval_rp_ccm_ab.py                     # 全语料
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fit_rp_ccm import (DCP, SAMPLE_LIN_HI, SAMPLE_LIN_LO, aligned_pair,
                        camera_slug, iter_corpus, sample_linear_pairs)
from pixo.pipeline.perceptual import delta_e_2000, linear_srgb_to_lab
from pixo.render.api import Renderer
from pixo.render.core.rp_ccm import apply_rp_ccm, load_rp_ccm


# Sharma, Wu & Dalal 2005 补充数据集公开校验对 (Lab1, Lab2, 期望 ΔE00)
_SHARMA_PAIRS = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
]


def selftest() -> None:
    """CIEDE2000 文献对自检 (Sharma 2005 补充数据集; 容差 1e-3 覆盖 4 位舍入)。"""
    ok = True
    for lab1, lab2, expect in _SHARMA_PAIRS:
        got = float(delta_e_2000(np.array([lab1]), np.array([lab2]))[0])
        flag = abs(got - expect) < 1e-3
        ok &= flag
        print(f"  ΔE00({lab1}, {lab2}) = {got:.4f} (期望 {expect}) "
              f"{'OK' if flag else 'FAIL'}")
    if not ok:
        sys.exit("CIEDE2000 自检失败: 与 Sharma 2005 公开对不一致")
    print("CIEDE2000 自检通过")


# ---------------------------------------------------------------------------
# 双轨 A/B 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--ccm-dir", default="configs/color")
    ap.add_argument("--preview-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--thumb-rot", default="auto", choices=("auto", "off"),
                    help="缩略图朝向复原 (auto=按 EXIF 逆旋转, off=原样)")
    ap.add_argument("--out-dir", default=".artifacts")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        if args.raw is None and args.limit == 0 and not Path(args.corpus).is_dir():
            return

    items = iter_corpus(args.corpus, args.raw, args.limit)
    if not items:
        print("语料为空: 检查 --corpus/--raw", file=sys.stderr)
        sys.exit(2)
    renderer = Renderer(args.dcp)

    rows: list[dict] = []
    skipped: list[str] = []
    all_a: list[np.ndarray] = []
    all_b: list[np.ndarray] = []
    for i, (pid, raw) in enumerate(items, 1):
        try:
            slug = camera_slug(raw)
            ccm_path = Path(args.ccm_dir) / f"rp_ccm_{slug}.json"
            if not ccm_path.is_file():
                skipped.append(f"{pid}: 缺 {ccm_path}")
                continue
            coeff = load_rp_ccm(ccm_path)
            base, ref = aligned_pair(renderer, raw, args.preview_edge,
                                     thumb_rot=args.thumb_rot)
            if base is None or base.shape != ref.shape:
                skipped.append(f"{pid}: 对齐失败")
                continue
            # 与拟合同口径: 网格抽样 + 有效线性样本窗 (相机 JPEG 高光裁剪/深阴影剔除)
            b_lin, r_lin = sample_linear_pairs(base, ref, stride=args.stride)
            if b_lin.shape[0] < 500:
                skipped.append(f"{pid}: 有效样本过少 {b_lin.shape[0]}")
                continue
            # 逐照片标量曝光增益对齐 (拟合/评估同口径, 见 fit_rp_ccm.py 说明):
            # RP-CCM 曝光不变 → 先在像素曝光下做色度校正, 再统一乘增益比 ΔE,
            # 两轨曝光处理一致, ΔE 只反映色度保真差异。
            gain = float(r_lin.mean() / max(b_lin.mean(), 1e-9))
            ev = float(np.log2(gain))
            rp_lin = apply_rp_ccm(b_lin, coeff).astype(np.float64)
            d_a = delta_e_2000(linear_srgb_to_lab(b_lin * gain),
                               linear_srgb_to_lab(r_lin))
            d_b = delta_e_2000(linear_srgb_to_lab(rp_lin * gain),
                               linear_srgb_to_lab(r_lin))
            rows.append({"photo_id": pid, "camera": slug, "n": int(b_lin.shape[0]),
                         "ev": ev,
                         "a_median": float(np.median(d_a)),
                         "a_p95": float(np.quantile(d_a, 0.95)),
                         "b_median": float(np.median(d_b)),
                         "b_p95": float(np.quantile(d_b, 0.95))})
            all_a.append(d_a)
            all_b.append(d_b)
            print(f"[{i}/{len(items)}] {pid} n={rows[-1]['n']} "
                  f"DCP={rows[-1]['a_median']:.2f}/{rows[-1]['a_p95']:.2f} "
                  f"RP={rows[-1]['b_median']:.2f}/{rows[-1]['b_p95']:.2f}",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
            skipped.append(f"{pid}: {exc}")
            print(f"[{i}/{len(items)}] {pid} 跳过: {exc}", flush=True)

    if not rows:
        print("无可评估照片 (缺系数文件或全部失败)", file=sys.stderr)
        sys.exit(1)

    va = np.concatenate(all_a)
    vb = np.concatenate(all_b)
    slugs = sorted({r["camera"] for r in rows})
    slug = ",".join(slugs)
    med_a, med_b = float(np.median(va)), float(np.median(vb))
    p95_a, p95_b = float(np.quantile(va, 0.95)), float(np.quantile(vb, 0.95))
    ccm_names = ", ".join(f"rp_ccm_{s}.json" for s in slugs)
    lines = [
        "# RP-CCM A/B 评估报告 (DCP vs DCP+RP-CCM)",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 语料: {args.corpus} ({len(rows)} 张评估 / {len(skipped)} 张跳过)",
        f"- 相机: {slug} · 系数: {ccm_names}",
        f"- 渲染: {Path(args.dcp).name} @ long_edge={args.preview_edge}, stride={args.stride}",
        f"- 缩略图对齐: thumb_rot={args.thumb_rot} (auto=Nikon 实证 EXIF 逆旋转规则)",
        f"- 指标: CIEDE2000 (D65), 有效线性样本窗 [{SAMPLE_LIN_LO}, {SAMPLE_LIN_HI}], "
        f"逐照片标量曝光增益对齐 (均值比, 口径同 calibrate_to_camera)",
        "",
        "## 总体 (全像素样本池)",
        "",
        "| 轨道 | ΔE2000 median | ΔE2000 p95 |",
        "|---|---:|---:|",
        f"| A: DCP (现行默认) | {med_a:.3f} | {p95_a:.3f} |",
        f"| B: DCP+RP-CCM | {med_b:.3f} | {p95_b:.3f} |",
        f"| **B−A** | **{med_b - med_a:+.3f} ({(med_b - med_a) / max(med_a, 1e-9) * 100:+.1f}%)** "
        f"| **{p95_b - p95_a:+.3f} ({(p95_b - p95_a) / max(p95_a, 1e-9) * 100:+.1f}%)** |",
        "",
        "## 分照片",
        "",
        "| photo | n | ev | A median | A p95 | B median | B p95 | Δmedian |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['photo_id']} | {r['n']} | {r['ev']:+.2f} | {r['a_median']:.3f} | {r['a_p95']:.3f} "
            f"| {r['b_median']:.3f} | {r['b_p95']:.3f} | {r['b_median'] - r['a_median']:+.3f} |")
    better = sum(1 for r in rows if r["b_median"] < r["a_median"])
    lines += [
        "",
        f"结论: B 轨 median 优于 A 轨的照片 {better}/{len(rows)}; "
        f"总体 ΔE2000 median {med_a:.3f} → {med_b:.3f}。",
        "",
        "> 纪律: 本报告仅作决策依据, **不切换运行时默认** (设计 §4); "
        "DCP 基线渲染与 configs 默认未被本脚本修改。",
    ]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug_tag = slugs[0] if len(slugs) == 1 else "multi"
    out = out_dir / f"eval_rp_ccm_ab_{slug_tag}_{time.strftime('%Y%m%d_%H%M%S')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"== 总体: DCP {med_a:.3f}/{p95_a:.3f} → RP-CCM {med_b:.3f}/{p95_b:.3f} "
          f"(median {((med_b - med_a) / max(med_a, 1e-9)) * 100:+.1f}%)")
    if skipped:
        print(f"   跳过 {len(skipped)}: " + "; ".join(skipped[:3]) +
              (" ..." if len(skipped) > 3 else ""))
    print(f"DONE {out}")


if __name__ == "__main__":
    main()
