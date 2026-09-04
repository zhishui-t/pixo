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
from pixo.render.api import Renderer
from pixo.render.core.calibration import SRGB_TO_XYZ_D65
from pixo.render.core.rp_ccm import apply_rp_ccm, load_rp_ccm

# sRGB(D65) 线性 → XYZ(D65) (行向量语义) 与 Lab 参考 白
_M_SRGB_TO_XYZ = np.asarray(SRGB_TO_XYZ_D65, dtype=np.float64)
_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)
_EPS_K = 216.0 / 24389.0    # CIE Lab 常数 (6/29)³
_KAPPA = 24389.0 / 27.0     # CIE Lab 常数


# ---------------------------------------------------------------------------
# 线性 sRGB → Lab(D65) 与 CIEDE2000 (纯 numpy)
# ---------------------------------------------------------------------------

def linear_srgb_to_lab(lin: np.ndarray) -> np.ndarray:
    """线性 sRGB (...,3) → CIELAB (D65 参考白)。出口 float64。"""
    xyz = np.asarray(lin, dtype=np.float64) @ _M_SRGB_TO_XYZ.T / _D65
    f = np.where(xyz > _EPS_K, np.cbrt(xyz), (_KAPPA * xyz + 16.0) / 116.0)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116.0 * fy - 16.0,
                     500.0 * (fx - fy),
                     200.0 * (fy - fz)], axis=-1)


def delta_e_2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 色差 (Sharma, Wu & Dalal 2005, DST 权重沿用公式原论文)。

    lab1/lab2: (...,3) 同形; 返回 (...,) ΔE00。实现逐项对齐 Sharma 2005
    式 (1)-(15) (含 G/apa/T/RT 项), 角度量全部以度计算后转弧度进三角函数。
    """
    l1, a1, b1 = np.asarray(lab1, np.float64)[..., 0], \
                 np.asarray(lab1, np.float64)[..., 1], \
                 np.asarray(lab1, np.float64)[..., 2]
    l2, a2, b2 = np.asarray(lab2, np.float64)[..., 0], \
                 np.asarray(lab2, np.float64)[..., 1], \
                 np.asarray(lab2, np.float64)[..., 2]
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    cbar = 0.5 * (c1 + c2)
    cbar7 = cbar ** 7
    g = 0.5 * (1.0 - np.sqrt(cbar7 / (cbar7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    h1p = np.where((a1p == 0.0) & (b1 == 0.0), 0.0, h1p)
    h2p = np.where((a2p == 0.0) & (b2 == 0.0), 0.0, h2p)

    dlp = l2 - l1
    dcp = c2p - c1p
    dh = h2p - h1p
    dh = np.where(c1p * c2p == 0.0, 0.0,
                  np.where(np.abs(dh) <= 180.0, dh,
                           np.where(dh > 180.0, dh - 360.0, dh + 360.0)))
    dhp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2.0)

    lbarp = 0.5 * (l1 + l2)
    cbarp = 0.5 * (c1p + c2p)
    hsum = h1p + h2p
    hbarp = np.where(c1p * c2p == 0.0, hsum,
                     np.where(np.abs(h1p - h2p) <= 180.0, 0.5 * hsum,
                              np.where(hsum < 360.0, 0.5 * (hsum + 360.0),
                                       0.5 * (hsum - 360.0))))
    t = (1.0 - 0.17 * np.cos(np.radians(hbarp - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hbarp))
         + 0.32 * np.cos(np.radians(3.0 * hbarp + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hbarp - 63.0)))
    dtheta = 30.0 * np.exp(-(((hbarp - 275.0) / 25.0) ** 2))
    cbarp7 = cbarp ** 7
    rc = 2.0 * np.sqrt(cbarp7 / (cbarp7 + 25.0 ** 7))
    sl = 1.0 + 0.015 * (lbarp - 50.0) ** 2 / np.sqrt(20.0 + (lbarp - 50.0) ** 2)
    sc = 1.0 + 0.045 * cbarp
    sh = 1.0 + 0.015 * cbarp * t
    rt = -np.sin(np.radians(2.0 * dtheta)) * rc
    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp / sh) ** 2
                   + rt * (dcp / sc) * (dhp / sh))


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
