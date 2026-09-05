"""HSM→OKLCh 接线 语料评估 —— hsv-HSM vs oklch-形变 渲染对照 (阶段三)。

问题: 路线图"阶段二起用 OKLCh 连续形变替代 DCP HSM"的运行时接线
(core.huesat_oklch + HueSatStage color_domain 分派) 已落地, 本评估量化
**两域实现的分歧**与各自对相机 JPEG 参照的偏差, 作为接线保真度与后续
切换决策的数据基础。

三轨口径 (fit_rp_ccm.aligned_pair 同源):
  A 轨: huesat enabled + color_domain=hsv —— DCP HSM 的 HSV 三线性链
        (现行为);
  B 轨: huesat enabled + color_domain=oklch —— t17 点云 (2765 点) 的
        OKLCh 连续形变 (IDW 栅格化 + 三线性);
  参照: RAW 内嵌相机 JPEG 缩略图 (EXIF 逆旋转)。
ΔE2000 (eval_rp_ccm_ab.delta_e_2000, --selftest 先行), 语料窗口
[0.01,0.90] 线性域网格抽样, 逐照片标量增益对齐 (A 轨算, 三轨共用 ——
HSM 亮度效应留在差值内, 曝光差不淹没色度信号)。

三个读数:
  ΔE(A,B) —— 两域实现分歧 (接线保真度: 越小 = 点云转译+插值越忠实复刻
             DCP HSM; 含栅格化/三线性两级插值的近似代价);
  ΔE(A,R) / ΔE(B,R) —— 各自 vs 相机 JPEG (参照分歧; HSM 是 Adobe look
             而非相机机内链路, 该读数提供 look 偏离基线)。
分带: as_shot wb_B 三带 (日光 <1.5 / 中间 1.5-2.0 / 低色温 ≥2.0)。

纪律: 评估只读, hueSatStage 缺省 color_domain=hsv 不变 —— 本脚本不修改
任何 configs/ 与 src/pixo (渲染差异经渲染参数显式传入)。

用法:
  python scripts/hsm_oklch_eval.py --limit 5     # 冒烟
  python scripts/hsm_oklch_eval.py               # 全语料 (54 张)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(_SCRIPTS), str(_SCRIPTS / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval_rp_ccm_ab import delta_e_2000, linear_srgb_to_lab, selftest
from pixo.render.core.tone import srgb_decode
from fit_rp_ccm import SAMPLE_LIN_HI, SAMPLE_LIN_LO
from fit_rp_ccm import DCP, aligned_pair, iter_corpus, sample_linear_pairs
from pixo.render.api import Renderer
from pixo.render.core.calibration import load_dcp
from pixo.render.core.io import camera_neutral_wb
from pixo.render.core.huesat_oklch import (load_oklch_deform,
                                           is_identity_deform)

JND = 2.3
BANDS = ((1.5, "daylight(<1.5)"), (2.0, "mid(1.5-2.0)"))


def band_of(wb_b: float) -> str:
    for hi, name in BANDS:
        if wb_b < hi:
            return name
    return "low_cct(>=2.0)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--preview-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--thumb-rot", default="auto", choices=("auto", "off"))
    ap.add_argument("--points", default=None,
                    help="点云路径 (缺省按 DCP 名自动推导)")
    ap.add_argument("--out-md", default=".artifacts/hsm_oklch_eval.md")
    ap.add_argument("--out-json", default=".artifacts/hsm_oklch_eval.json")
    args = ap.parse_args(argv)

    print("== CIEDE2000 文献对自检 (eval_rp_ccm_ab --selftest)")
    try:
        selftest()
    except SystemExit as exc:
        print(f"selftest 失败: {exc}", file=sys.stderr)
        return 1

    if not POINTS_OK(args.points):
        print("点云不可用", file=sys.stderr)
        return 2

    items = iter_corpus(args.corpus, args.raw, args.limit)
    if not items:
        print("语料为空", file=sys.stderr)
        return 2
    renderer = Renderer(args.dcp)
    prof = load_dcp(args.dcp)

    rows: list[dict] = []
    skipped: list[str] = []
    pools: dict[str, list] = {"ab": [], "a_ref": [], "b_ref": []}
    t0 = time.time()
    for i, (pid, raw) in enumerate(items, 1):
        try:
            pair = aligned_pair(renderer, raw, args.preview_edge,
                                thumb_rot=args.thumb_rot)
            if pair is None:
                raise RuntimeError("对齐失败")
            base, ref = pair
            import rawpy
            with rawpy.imread(str(raw)) as rp:
                wb_cam = np.asarray(camera_neutral_wb(rp), dtype=np.float64)
            band = band_of(float(wb_cam[2] / max(wb_cam[1], 1e-9)))
            track_a = renderer.render_preview_full(
                raw, long_edge=args.preview_edge,
                params={"huesat": {"enabled": True, "color_domain": "hsv"}})
            track_b = renderer.render_preview_full(
                raw, long_edge=args.preview_edge,
                params={"huesat": {"enabled": True, "color_domain": "oklch"}})
            a_g = track_a.astype(np.float64) / 255.0
            b_g = track_b.astype(np.float64) / 255.0
            # 固定窗: 基座 (无 HSM 中性渲染) vs 参照 定窗, A/B 用同一掩码
            # 取像素 (两域输出不同, 各自过窗会产生不同样本集无法逐像素对照;
            # sample_linear_pairs 同式: stride 网格 + 双侧线性窗)。
            gs = (slice(None, None, args.stride),) * 2
            lin_base = srgb_decode(np.ascontiguousarray(
                base[gs].astype(np.float32))).reshape(-1, 3).astype(np.float64)
            lin_a = srgb_decode(np.ascontiguousarray(
                a_g[gs].astype(np.float32))).reshape(-1, 3).astype(np.float64)
            lin_b = srgb_decode(np.ascontiguousarray(
                b_g[gs].astype(np.float32))).reshape(-1, 3).astype(np.float64)
            lin_r = srgb_decode(np.ascontiguousarray(
                ref[gs].astype(np.float32))).reshape(-1, 3).astype(np.float64)
            ok = np.all((lin_base >= SAMPLE_LIN_LO) & (lin_base <= SAMPLE_LIN_HI),
                        axis=1) &                  np.all((lin_r >= SAMPLE_LIN_LO) & (lin_r <= SAMPLE_LIN_HI),
                        axis=1)
            if int(ok.sum()) < 500:
                raise RuntimeError(f"有效样本过少 {int(ok.sum())}")
            gain = float(lin_r[ok].mean() / max(lin_base[ok].mean(), 1e-9))
            sa, sb, ra = lin_a[ok], lin_b[ok], lin_r[ok]
            d_ab = delta_e_2000(linear_srgb_to_lab(sa * gain),
                                linear_srgb_to_lab(sb * gain))
            d_ar = delta_e_2000(linear_srgb_to_lab(sa * gain),
                                linear_srgb_to_lab(ra))
            d_br = delta_e_2000(linear_srgb_to_lab(sb * gain),
                                linear_srgb_to_lab(ra))
            pools["ab"].append(d_ab)
            pools["a_ref"].append(d_ar)
            pools["b_ref"].append(d_br)
            rows.append({
                "photo_id": pid, "band": band,
                "ab_median": float(np.median(d_ab)),
                "ab_p95": float(np.quantile(d_ab, 0.95)),
                "a_ref_median": float(np.median(d_ar)),
                "a_ref_p95": float(np.quantile(d_ar, 0.95)),
                "b_ref_median": float(np.median(d_br)),
                "b_ref_p95": float(np.quantile(d_br, 0.95)),
                "n": int(sa.shape[0])})
            r = rows[-1]
            print(f"[{i}/{len(items)}] {pid} [{band}] A↔B={r['ab_median']:.2f} "
                  f"A↔R={r['a_ref_median']:.2f} B↔R={r['b_ref_median']:.2f}",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
            skipped.append(f"{pid}: {exc}")
            print(f"[{i}/{len(items)}] {pid} 跳过: {exc}", flush=True)

    if not rows:
        print("无可评估照片", file=sys.stderr)
        return 1

    summary = {}
    for k, pl in pools.items():
        pool = np.concatenate(pl)
        summary[k] = {"median": float(np.median(pool)),
                      "p95": float(np.quantile(pool, 0.95)),
                      "mean": float(np.mean(pool))}
    bands: dict[str, dict] = {}
    for band in sorted({r["band"] for r in rows}):
        sel = [r for r in rows if r["band"] == band]
        bands[band] = {"n_photos": len(sel), **{
            k: round(float(np.median([r[f"{k}_median"] for r in sel])), 4)
            for k in pools}}

    write_md(Path(args.out_md), args, rows, skipped, summary, bands,
             time.time() - t0)
    Path(args.out_json).write_text(json.dumps({
        "schema": "pixo.hsm_oklch_eval.v1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "args": {k: v for k, v in vars(args).items()},
        "summary": summary, "bands": bands, "photos": rows,
        "skipped": skipped}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"== A↔B {summary['ab']['median']:.3f} | "
          f"A↔R {summary['a_ref']['median']:.3f} | "
          f"B↔R {summary['b_ref']['median']:.3f} "
          f"({summary['ab']['median'] / max(summary['a_ref']['median'], 1e-9) * 100:.1f}% of A↔R)")
    print(f"DONE {args.out_md} ({time.time() - t0:.0f}s)")
    return 0


def POINTS_OK(points_arg: str | None) -> bool:
    from pixo.render.core.calibration import load_dcp
    from pixo.render.modules.huesat import _resolve_oklch_spec
    prof = load_dcp(DCP)
    spec = _resolve_oklch_spec(prof, points_arg)
    return spec is not None and not is_identity_deform(spec)


def write_md(out: Path, args, rows, skipped, summary, bands, elapsed) -> None:
    jnd_ab = summary["ab"]["median"] / JND
    lines = [
        "# HSM→OKLCh 接线 语料对照报告 (hsv-HSM vs oklch-形变)",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')} · 耗时 {elapsed:.0f}s",
        f"- 语料: {args.corpus} ({len(rows)} 张 / 跳过 {len(skipped)})"
        f" · DCP {Path(args.dcp).name} @ long_edge={args.preview_edge},"
        f" stride={args.stride}",
        f"- A 轨 = huesat enabled + color_domain=hsv (DCP HSM 的 HSV 三线性,"
        f" 现行为); B 轨 = color_domain=oklch (t17 点云 2765 点 → IDW 栅格化"
        f" 72×24×24 + OKLCh 三线性形变); 参照 = RAW 内嵌相机 JPEG (EXIF 逆旋转)",
        "- ΔE2000 (Sharma 2005, --selftest 通过), 窗口 [0.01,0.90] 线性域,"
        " 逐照片增益对齐 (中性渲染 vs 参照算 gain, A/B 共用)",
        "",
        "## 总体 (pooled ΔE2000)",
        "",
        "| 读数 | median | p95 | 含义 |",
        "|---|---:|---:|---|",
        f"| A↔B (两域分歧) | {summary['ab']['median']:.3f} "
        f"| {summary['ab']['p95']:.3f} | 接线保真度: 越小 = OKLCh 形变越忠实"
        f"复刻 DCP HSM ({jnd_ab:.2f} JND) |",
        f"| A↔R (hsv vs 参照) | {summary['a_ref']['median']:.3f} "
        f"| {summary['a_ref']['p95']:.3f} | Adobe look vs 相机机内链路 |",
        f"| B↔R (oklch vs 参照) | {summary['b_ref']['median']:.3f} "
        f"| {summary['b_ref']['p95']:.3f} | 形变 look vs 相机机内链路 |",
        "",
        f"两域分歧占 A↔R 的 "
        f"{summary['ab']['median'] / max(summary['a_ref']['median'], 1e-9) * 100:.1f}%"
        " —— 即 oklch 形变对 hsv-HSM 的复刻偏差相对 look 本身的幅度。",
        "",
        "## 分带 (as_shot wb_B 三带, ΔE median)",
        "",
        "| 带 | n | A↔B | A↔R | B↔R |",
        "|---|---:|---:|---:|---:|",
    ]
    for band, e in bands.items():
        lines.append(f"| {band} | {e['n_photos']} | {e['ab']:.3f} "
                     f"| {e['a_ref']:.3f} | {e['b_ref']:.3f} |")
    lines += [
        "",
        "## 逐照片",
        "",
        "| photo | 带 | A↔B median | A↔R median | B↔R median | n |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(f"| {r['photo_id']} | {r['band']} | {r['ab_median']:.3f} "
                     f"| {r['a_ref_median']:.3f} | {r['b_ref_median']:.3f} "
                     f"| {r['n']} |")
    if skipped:
        lines += ["", f"跳过 {len(skipped)} 张: " + "; ".join(skipped[:5])
                  + (" ..." if len(skipped) > 5 else "")]
    lines += [
        "",
        "## 注记 (口径)",
        "",
        "- **两域差异来源**: 点云转译 (HSV 作用量 → OKLCh 增量, 节点处精确)"
        " + 两级插值近似 (IDW 栅格化 + 运行时三线性) + 软限幅路径差异"
        " (HSV 硬 S 钳 vs OKLCh tanh 软限幅)。",
        "- **参照读数的语义**: DCP HSM/Look 是 Adobe Camera 观感而非相机机内"
        "链路 (huesat Stage 默认关闭的依据, 见其 docstring), A↔R/B↔R 只作"
        " look 偏离基线, 不作好坏判据; 接线验收主读数是 A↔B。",
        "- **缺省不变**: HueSatStage 缺省 color_domain=hsv, 本评估经渲染参数"
        "显式分派, 不修改 configs/ 与 src/pixo 行为。",
        "- **运行时接线**: color_domain=oklch 时点云按 DCP 名 token 子序列"
        "自动匹配 configs/color/hsm_oklch_*.json; 点云缺失回退 hsv 链"
        " (一次性告警)。",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
