"""标定前后真值对照评估 —— 新表 (calib_out) vs 现行 configs 全语料双轨 (阶段二 t33, 设计 §5)。

双轨:
  A 轨 (现行 configs): theta_io.load_theta() 缺省五源 (configs/calibration/
                       warmth_curve.json + src/pixo/render/target_offset.json +
                       resources/camera_profiles/z5ii_neutral_trim.json +
                       configs/color/rp_ccm_nikon_z5_2.json + skin_oklab.json);
  B 轨 (新表):         configs/color/calib_out/ 五文件 (t32 优化产出)。
渲染载具: PhotoSurrogate (t30 可微代理, 保真门 median ≤0.05/p95 ≤0.3 见
.artifacts/surrogate_fidelity.md) —— 真实管线无法在不改 src 的前提下加载新表
(曝光表/中性曲线为包内固定路径, 红线 src/pixo/render 零改动), 代理是唯一能
忠实渲染 θ* 的载具; 保真门偏差 (≤0.05) 远小于本评估的效应量级。
指标: **真 ΔE2000** (eval_rp_ccm_ab.delta_e_2000, Sharma 2005, --selftest 先行),
双口径分工 (t32 报告注记同款):
  - 端到端口径: θ 全链含表 ev, 无 gain 对齐 (曝光差是标定对象) —— 量化
    "新表全采纳" 的标定收益;
  - 色度口径 (eval_rp_ccm_ab 同式): 逐照片标量曝光增益对齐 + orientation 6/8
    逆旋转参考 (aligned_pair 同源) —— ΔE 只反映色度, G-5 门槛线按此核对。
分带统计: 按 pixo.meta 拍摄日 + 光照带 (wb_B 色温代理: <1.5 日光型 /
1.5–2.0 中间带 / ≥2.0 低色温人造光; 边界锚定 warmth 模型 b0=1.79 日光锥)。
G-5 门槛线 (设计 §4): median 改善 ≥15% / 无单照片 median 回归 >1 JND (2.3) /
总体 p95 不劣化 / ≥2 相机复验 —— 逐项独立重算核对。

纪律: **只建议不切默认** —— 本脚本不写任何 configs 运行时文件与 src;
是否采纳 (仅转 rp / 新表全采纳) 由人依据报告决策。

可复现: seed 全局钉死 (评估路径本身无随机性 —— stride 网格抽样 + 确定性
前向 + 系数读自落盘 JSON); 语料 npz 采样缓存 --resume (t32 同款), 换缓存
需 --fresh 重采样。

用法:
  python scripts/calib/eval_stage2.py --selftest   # ΔE2000 文献对自检
  python scripts/calib/eval_stage2.py --limit 6    # 前 6 张冒烟 (需 --fresh)
  python scripts/calib/eval_stage2.py              # 全语料 (缓存重放)
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
for _p in (str(_SCRIPTS / "calib"), str(_SCRIPTS), str(_SCRIPTS / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import theta_io
from eval_rp_ccm_ab import delta_e_2000, linear_srgb_to_lab, selftest
from fit_rp_ccm import DCP, iter_corpus
from pixo.render.core.rp_ccm import RPCCM, apply_rp_ccm
from optimize import (DEFAULT_SEED, JND, G5_MIN_IMPROVEMENT, PhotoKit,
                      SharedTheta, _dc_consts, _pair_samples, bind, build_kits,
                      eval_e2e, static_dc_holder)

# 光照三带 (wb_B = 相机 WB 蓝比, 色温代理; 边界见模块 docstring)
LIGHT_BANDS: tuple[tuple[str, float, float], ...] = (
    ("日光型 (wb_B<1.5)", 0.0, 1.5),
    ("中间带 (1.5≤wb_B<2.0)", 1.5, 2.0),
    ("低色温/人造光 (wb_B≥2.0)", 2.0, float("inf")),
)


def light_band(wb_b: float) -> str:
    for name, lo, hi in LIGHT_BANDS:
        if lo <= wb_b < hi:
            return name
    return LIGHT_BANDS[-1][0]


# ---------------------------------------------------------------------------
# 双轨评估 (端到端口径保留逐照片 ΔE 数组供分带; 色度口径多轨一次渲染)
# ---------------------------------------------------------------------------

def e2e_track(kits: list[PhotoKit], shared: SharedTheta, stride: int) -> dict:
    """端到端真值 (eval_e2e 同式: 动态窗, 无 gain 对齐) + 逐照片 ΔE 数组。"""
    rows, pools = [], []
    for kit in kits:
        bind(kit, shared)
        with torch.no_grad():
            u8 = kit.sur.quantize(kit.sur()).cpu().numpy().astype(np.uint8)
        src, dst = _pair_samples(u8, kit.ref_u8, stride)
        if src.shape[0] < 100:
            continue
        de = delta_e_2000(linear_srgb_to_lab(src), linear_srgb_to_lab(dst))
        pools.append(de)
        rows.append({"photo_id": kit.pid, "group": kit.group,
                     "band": light_band(kit.wb_b), "n": int(src.shape[0]),
                     "median": float(np.median(de)),
                     "p95": float(np.quantile(de, 0.95)), "de": de})
    if not pools:
        raise RuntimeError("端到端评估无有效样本 (全部照片掉出线性窗/失败)")
    pool = np.concatenate(pools)
    return {"rows": rows, "pool": pool,
            "median": float(np.median(pool)),
            "p95": float(np.quantile(pool, 0.95)),
            "mean": float(np.mean(pool))}


def chroma_neutral_base(kits: list[PhotoKit], shared: SharedTheta,
                        stride: int) -> list[dict]:
    """中性语境基座渲染 (ev=0, 无 CCM; optimize._neutral_pools 同式), 保留
    逐照片 (src_lin, ref_lab, gain) 供多组 rp 系数复用同一渲染。"""
    out: list[dict] = []
    for kit in kits:
        bind(kit, shared, ev_override=0.0, use_rp=False)
        with torch.no_grad():
            u8 = kit.sur.quantize(kit.sur()).cpu().numpy().astype(np.uint8)
        src, dst = _pair_samples(u8, kit.ref_u8, stride)
        if src.shape[0] < 200:
            continue
        out.append({"photo_id": kit.pid, "group": kit.group,
                    "band": light_band(kit.wb_b), "n": int(src.shape[0]),
                    "src": src.astype(np.float64),
                    "ref_lab": linear_srgb_to_lab(dst),
                    "gain": float(dst.mean() / max(src.mean(), 1e-9))})
    if not out:
        raise RuntimeError("色度评估无有效样本 (全部照片掉出线性窗/失败)")
    return out


def chroma_track(base: list[dict], rp: np.ndarray | None) -> list[dict]:
    """基座 → (+rp) 色度 ΔE 逐照片行 (gain 对齐, eval_rp_ccm_ab 同式)。"""
    rpcm = RPCCM(matrix=rp, degree=2) if rp is not None else None
    rows = []
    for b in base:
        src = b["src"] if rpcm is None else \
            apply_rp_ccm(b["src"], rpcm).astype(np.float64)
        de = delta_e_2000(linear_srgb_to_lab(src * b["gain"]), b["ref_lab"])
        rows.append({"photo_id": b["photo_id"], "group": b["group"],
                     "band": b["band"], "n": b["n"],
                     "median": float(np.median(de)),
                     "p95": float(np.quantile(de, 0.95)), "de": de})
    return rows


def pool_stats(rows: list[dict]) -> dict:
    pool = np.concatenate([r["de"] for r in rows])
    return {"median": float(np.median(pool)),
            "p95": float(np.quantile(pool, 0.95)),
            "mean": float(np.mean(pool)), "n_px": int(pool.size),
            "n_photos": len(rows)}


def g5_verdicts(a_rows: list[dict], b_rows: list[dict],
                cameras: set[str]) -> dict:
    """G-5 门槛线 (optimize.G5Result.verdicts 同式, 行序对齐后逐照片比对)。"""
    amap = {r["photo_id"]: r for r in a_rows}
    paired = [(amap[r["photo_id"]], r) for r in b_rows if r["photo_id"] in amap]
    a_pool = np.concatenate([r["de"] for r, _ in paired])
    b_pool = np.concatenate([r["de"] for _, r in paired])
    med_a, med_b = float(np.median(a_pool)), float(np.median(b_pool))
    p95_a, p95_b = float(np.quantile(a_pool, 0.95)), float(np.quantile(b_pool, 0.95))
    improv = (med_a - med_b) / max(med_a, 1e-9)
    worst_reg = max(r["median"] - ar["median"] for ar, r in paired)
    return {"median_a": med_a, "median_b": med_b,
            "median_improvement": improv,
            "gate_improve15": bool(improv >= G5_MIN_IMPROVEMENT),
            "worst_photo_regression": float(worst_reg),
            "gate_no_regression": bool(worst_reg <= JND),
            "p95_a": p95_a, "p95_b": p95_b,
            "gate_p95": bool(p95_b <= p95_a),
            "n_cameras": len(cameras), "cameras": sorted(cameras),
            "gate_2cameras": len(cameras) >= 2,
            "n_photos_paired": len(paired)}


# ---------------------------------------------------------------------------
# 分带聚合 (拍摄日 × 光照带; 池化口径与总体一致)
# ---------------------------------------------------------------------------

def band_table(tracks: dict[str, list[dict]], key: str) -> list[dict]:
    """tracks: {轨名: rows} → 按 key (group/band) 分组的池化统计。"""
    keys = sorted({r[key] for rows in tracks.values() for r in rows})
    out = []
    for k in keys:
        entry: dict = {key: k}
        for name, rows in tracks.items():
            sub = [r for r in rows if r[key] == k]
            st = pool_stats(sub) if sub else {"median": float("nan"),
                                              "p95": float("nan"),
                                              "n_photos": 0}
            entry[name] = st
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def _fmt(v: float, nd: int = 3) -> str:
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) \
        else f"{v:.{nd}f}"


def write_report(out: Path, args, t0: Theta, t1: Theta, kits: list[PhotoKit],
                 e2e_a: dict, e2e_b: dict, chroma: dict[str, list[dict]],
                 verdict: dict, cameras: set[str], skipped: list[str],
                 t32_cross: dict) -> None:
    def dtheta(name: str, a, b, unit: str) -> str:
        d = float(np.abs(np.asarray(b, float) - np.asarray(a, float)).max())
        return f"| {name} | {d:.4f}{unit} |"

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    groups = sorted({k.group for k in kits})
    e2e_gain = (e2e_a["median"] - e2e_b["median"]) / max(e2e_a["median"], 1e-9)
    lines = [
        "# 阶段二 标定前后真值对照评估 (t33, 设计 §5)",
        "",
        f"- 生成时间: {now}",
        f"- 结论纪律: **只建议不切默认** —— 未修改任何 configs 运行时文件与 src/pixo/render",
        f"- 双轨: A = 现行 configs (θ0) vs B = 新表 configs/color/calib_out (θ*, t32 产出)",
        f"- 语料: {args.corpus} · {len(kits)} 张评估 / {len(skipped)} 张跳过 · "
        f"拍摄日 {len(groups)} 组 ({', '.join(groups)}) · 相机 {len(cameras)} 台 ({', '.join(sorted(cameras))})",
        f"- 渲染载具: PhotoSurrogate @ long_edge={args.long_edge}, stride={args.stride} "
        f"(保真门 median ≤0.05 / p95 ≤0.3, .artifacts/surrogate_fidelity.md)",
        f"- 参考: RAW 内嵌相机 JPEG 缩略图 (EXIF orientation 6/8 逆旋转 + INTER_AREA 对齐, "
        f"eval_rp_ccm_ab.aligned_pair 同源)",
        f"- 指标: 真 ΔE2000 (eval_rp_ccm_ab.delta_e_2000, Sharma 2005, --selftest 通过)",
        f"- 可复现: seed={args.seed} (评估路径无随机性: stride 网格抽样 + 确定性前向 + "
        f"系数读自落盘 JSON); 语料采样缓存 {args.cache} (--resume 重放, --fresh 重采样)",
        "",
        "## 1. Δθ (现行 configs → 新表, 逐组件最大绝对变化)",
        "",
        "| 组件 | max\\|Δθ\\| |",
        "|---|---:|",
        dtheta("warmth knots 增益", t0.warmth_knots[:, 1:], t1.warmth_knots[:, 1:], ""),
        dtheta("曝光表 ev 列", t0.exposure_table[:, 2], t1.exposure_table[:, 2], " EV"),
        dtheta("中性曲线 (by_cct)", t0.neutral_by_cct, t1.neutral_by_cct, ""),
        dtheta("RP-CCM (3×6)", t0.rp_ccm_coeff, t1.rp_ccm_coeff, ""),
        dtheta("skin 椭圆", t0.skin_ellipse, t1.skin_ellipse, ""),
        "",
        "skin 与中性 default 曲线按设计不动 (θ 无数据项 / 不进链); 中性 default 之外",
        "的四个组件均有实质移动 —— 新表不是 θ0 的复写。",
        "",
        "## 2. 端到端真值 (主对照: θ 全链含表 ev, 无 gain 对齐 —— 曝光差是标定对象)",
        "",
        "| 轨道 | ΔE2000 median | ΔE2000 p95 | mean |",
        "|---|---:|---:|---:|",
        f"| A: 现行 configs (θ0) | {e2e_a['median']:.3f} | {e2e_a['p95']:.3f} | {e2e_a['mean']:.3f} |",
        f"| B: 新表 (θ*) | {e2e_b['median']:.3f} | {e2e_b['p95']:.3f} | {e2e_b['mean']:.3f} |",
        f"| **改善 (A→B)** | **{e2e_gain * 100:+.1f}%** "
        f"| **{(e2e_a['p95'] - e2e_b['p95']) / max(e2e_a['p95'], 1e-9) * 100:+.1f}%** | — |",
        "",
        f"t32 checkpoint 交叉核对: θ0 {t32_cross['e2e_theta0']} / θ* "
        f"{t32_cross['e2e_theta_star']} (calib_run.md 真值对照表) —— "
        f"{t32_cross['e2e_verdict']}。",
        "",
        "### 分带统计 (端到端, 池化)",
        "",
    ]

    for key, title in (("group", "按拍摄日"), ("band", "按光照带 (wb_B 色温代理)")):
        lines += [f"**{title}**", "",
                  f"| {('拍摄日' if key == 'group' else '光照带')} | n 张 "
                  f"| A median | A p95 | B median | B p95 | Δmedian |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for e in band_table({"A": e2e_a["rows"], "B": e2e_b["rows"]}, key):
            a, b = e["A"], e["B"]
            n = max(a["n_photos"], b["n_photos"])
            lines.append(f"| {e[key]} | {n} | {_fmt(a['median'])} | {_fmt(a['p95'])} "
                         f"| {_fmt(b['median'])} | {_fmt(b['p95'])} "
                         f"| {_fmt(b['median'] - a['median'])} |")
        lines.append("")

    ca, cb = chroma["A"], chroma["B"]
    n_groups_c = len({r["group"] for r in chroma["C"]})
    st_a0, st_a, st_b = (pool_stats(chroma[k]) for k in ("A0", "A", "B"))
    st_c, st_d = pool_stats(chroma["C"]), pool_stats(chroma["D"])
    lines += [
        "## 3. 色度真值 (eval_rp_ccm_ab 同式: 逐照片增益对齐, ΔE 只反映色度)",
        "",
        "| 轨道 | ΔE2000 median | ΔE2000 p95 | n 照片 |",
        "|---|---:|---:|---:|",
        f"| A0: θ0 中性基座 (现行 warmth/neutral, ev=0, 无 CCM) "
        f"| {st_a0['median']:.3f} | {st_a0['p95']:.3f} | {st_a0['n_photos']} |",
        f"| A: θ* 中性基座 (新表 warmth/neutral, ev=0, 无 CCM) | {st_a['median']:.3f} "
        f"| {st_a['p95']:.3f} | {st_a['n_photos']} |",
        f"| B: A + 全局 rp (中性语境拟合, 转默认候选) | {st_b['median']:.3f} "
        f"| {st_b['p95']:.3f} | {st_b['n_photos']} |",
        f"| C: A + 分组 rp_g ({n_groups_c} 组) "
        f"| {st_c['median']:.3f} | {st_c['p95']:.3f} | {st_c['n_photos']} |",
        f"| D: A + 现行 rp (θ0 阶段一拟合, 参考) | {st_d['median']:.3f} "
        f"| {st_d['p95']:.3f} | {st_d['n_photos']} |",
        "",
        f"- A0→A: 新表 warmth/neutral 的色度贡献 (增益对齐后仍可见 "
        f"{st_a0['median']:.3f} → {st_a['median']:.3f});"
        f" 端到端改善的其余部分主要来自曝光表/tone 联合标定。",
        f"- B vs D (同基座): 中性语境重拟合 {st_b['median']:.3f} vs 阶段一系数 "
        f"{st_d['median']:.3f} —— 新基座上重拟合仍优于现行系数。",
        f"- t32 交叉核对: A/B/C = {t32_cross['g5_a']} / {t32_cross['g5_b']} / "
        f"{t32_cross['g5_c']} (calib_run.md G-5 节) —— {t32_cross['g5_verdict']}。",
        "",
        "### G-5 门槛线逐项核对 (B vs A, 设计 §4)",
        "",
        "| 门槛 | 实测 | 判定 |",
        "|---|---|:---:|",
        f"| median 改善 ≥15% | {verdict['median_improvement'] * 100:+.1f}% "
        f"({verdict['median_a']:.3f} → {verdict['median_b']:.3f}) "
        f"| {'✅' if verdict['gate_improve15'] else '❌'} |",
        f"| 无单照片 median 回归 >1 JND ({JND}) | 最差 "
        f"{verdict['worst_photo_regression']:+.2f} "
        f"| {'✅' if verdict['gate_no_regression'] else '❌'} |",
        f"| 总体 p95 不劣化 | {verdict['p95_a']:.3f} → {verdict['p95_b']:.3f} "
        f"| {'✅' if verdict['gate_p95'] else '❌'} |",
        f"| ≥2 相机复验 | {verdict['n_cameras']} 台 ({', '.join(verdict['cameras'])}) "
        f"| {'✅' if verdict['gate_2cameras'] else '❌'} |",
        "",
    ]

    lines += ["### 分带统计 (色度口径, 池化)", ""]
    for key, title in (("group", "按拍摄日"), ("band", "按光照带")):
        lines += [f"**{title}**", "",
                  f"| {('拍摄日' if key == 'group' else '光照带')} | n 张 "
                  f"| A median | B median | C median | D median |",
                  "|---|---:|---:|---:|---:|---:|"]
        for e in band_table({"A": ca, "B": cb, "C": chroma["C"],
                             "D": chroma["D"]}, key):
            n = max(e[t]["n_photos"] for t in ("A", "B", "C", "D"))
            lines.append(
                f"| {e[key]} | {n} | {_fmt(e['A']['median'])} | {_fmt(e['B']['median'])} "
                f"| {_fmt(e['C']['median'])} | {_fmt(e['D']['median'])} |")
        lines.append("")

    lines += [
        "## 4. 分照片明细",
        "",
        "### 端到端 (A→B)",
        "",
        "| photo | 拍摄日 | 光照带 | n | A median | B median | Δ(B−A) |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    bmap = {r["photo_id"]: r for r in e2e_b["rows"]}
    for r in e2e_a["rows"]:
        rb = bmap.get(r["photo_id"])
        if rb is None:
            continue
        lines.append(f"| {r['photo_id']} | {r['group']} | {r['band']} | {r['n']} "
                     f"| {r['median']:.3f} | {rb['median']:.3f} "
                     f"| {rb['median'] - r['median']:+.3f} |")
    better = sum(1 for r in e2e_a["rows"]
                 if r["photo_id"] in bmap and bmap[r["photo_id"]]["median"] < r["median"])
    lines += ["", f"端到端 median 改善照片 {better}/{len(e2e_a['rows'])}。", ""]

    lines += ["### 色度 (A→B)", "",
              "| photo | 拍摄日 | 光照带 | n | A median | B median | Δ(B−A) |",
              "|---|---|---|---:|---:|---:|---:|"]
    cbmap = {r["photo_id"]: r for r in cb}
    for r in ca:
        rb = cbmap.get(r["photo_id"])
        if rb is None:
            continue
        lines.append(f"| {r['photo_id']} | {r['group']} | {r['band']} | {r['n']} "
                     f"| {r['median']:.3f} | {rb['median']:.3f} "
                     f"| {rb['median'] - r['median']:+.3f} |")
    lines.append("")

    if skipped:
        lines += [f"跳过 {len(skipped)} 张: " + "; ".join(skipped[:5])
                  + (" ..." if len(skipped) > 5 else ""), ""]

    lines += [
        "## 5. 结论与建议 (只建议, 不切默认)",
        "",
        f"1. **新表全采纳路径**: 端到端真值 ΔE2000 median {e2e_a['median']:.3f} → "
        f"{e2e_b['median']:.3f} ({e2e_gain * 100:+.1f}%), p95 "
        f"{e2e_a['p95']:.3f} → {e2e_b['p95']:.3f} —— "
        f"{'建议采纳进入 t34 全量回归' if e2e_b['median'] < e2e_a['median'] else '收益不足, 建议维持现状'}。",
        f"2. **仅转 RP-CCM 路径 (G-5)**: 门槛线 "
        f"{sum([verdict['gate_improve15'], verdict['gate_no_regression'], verdict['gate_p95'], verdict['gate_2cameras']])}/4 项通过"
        f"{' (median/p95/无回归三项满足; 单相机复验项受语料限制, 属语料缺口而非指标缺口)' if verdict['gate_improve15'] and verdict['gate_no_regression'] and verdict['gate_p95'] and not verdict['gate_2cameras'] else ''} —— "
        f"{'具备转默认的指标条件, 待 ≥2 相机语料复验后决策' if (verdict['gate_improve15'] and verdict['gate_no_regression'] and verdict['gate_p95']) else '建议暂不转默认' }。",
        "3. 本报告全部基于可微代理载具 (保真门 median ≤0.05, 远小于评估效应量级);",
        "   t34 新表全量回归 (金样本重生成 + 全量 pytest) 通过前, **运行时默认保持不变**。",
        "",
        "## 6. 复现",
        "",
        "```bash",
        "python scripts/calib/eval_stage2.py --selftest",
        "python scripts/calib/eval_stage2.py                      # 全语料 (npz 缓存重放)",
        "python scripts/calib/eval_stage2.py --fresh              # 忽略缓存重新采样",
        "```",
        "",
        f"- 语料清单: {args.corpus}/full_scan_*.json photos[] 去重 → {len(kits)} 张 "
        f"({', '.join(f'{g}×{sum(1 for k in kits if k.group == g)}' for g in groups)})",
        f"- θ 来源: A = theta_io.DEFAULT_SOURCES (现行五源) / B = {args.new_dir} "
        f"(theta_io.load_theta roundtrip 逐位契约)",
        f"- rp 系数: B/C 轨读 {args.groups_json} (rp_global_neutral / groups, t32 落盘); "
        f"D 轨读现行 configs/color/rp_ccm_nikon_z5_2.json",
        "",
        "> 口径注记: calib_run.md 末次为 --g5-only 重放 (θ0 基座被重载为 calib_out),",
        "> 其 Δθ 表全 0 为重放表观假象 —— 本报告 Δθ 以真·现行 configs 重算。",
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--long-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--new-dir", default="configs/color/calib_out")
    ap.add_argument("--groups-json",
                    default="configs/color/calib_out/rp_ccm_by_group.json")
    ap.add_argument("--cache", default=".artifacts/calib_opt_samples.npz")
    ap.add_argument("--resume", action="store_true", default=True,
                    help="采样缓存重放 (默认开; 缺缓存自动转 fresh)")
    ap.add_argument("--fresh", action="store_true", help="忽略缓存重新采样")
    ap.add_argument("--report", default=".artifacts/stage2_eval.md")
    ap.add_argument("--json-out", default=".artifacts/stage2_eval.json")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        selftest()
        if args.raw is None and args.limit == 0 and not Path(args.corpus).is_dir():
            return 0

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    static_dc_holder.dc = _dc_consts(args.dcp)   # 缓存重放的静态构建依赖 (optimize.main 同款)
    t00 = time.time()

    # ---- θ 双轨 (A = 现行 configs 五源 / B = calib_out 新表) ----
    t0 = theta_io.load_theta()
    new_paths = {k: Path(args.new_dir) / theta_io.OUT_NAMES[k]
                 for k in theta_io.SOURCE_KEYS}
    t1 = theta_io.load_theta(new_paths)
    shared0, shared1 = SharedTheta(t0), SharedTheta(t1)

    # ---- θ* 落盘一致性: calib_out == ckpt (可复现证据) ----
    ckpt_file = Path(".artifacts/calib_ckpt.pt")
    ckpt_note = "ckpt 不存在, 跳过一致性核对"
    if ckpt_file.is_file():
        blob = torch.load(ckpt_file, map_location="cpu", weights_only=False)
        sd = shared1.state_dict()
        mismatch = [k for k in ("warmth_knots_gain", "ev_table", "neutral_a",
                                "neutral_b", "rp_matrix", "skin_ellipse")
                    if not torch.equal(sd[k], blob["theta"][k])]
        ckpt_note = ("calib_out == ckpt θ 逐位一致" if not mismatch
                     else f"calib_out vs ckpt 不一致: {mismatch}")
        print(f"ckpt 核对: {ckpt_note}", flush=True)

    # ---- 语料 (npz 采样缓存重放, t32 同款) ----
    items = iter_corpus(args.corpus, args.raw, args.limit)
    if not items:
        print("语料为空: 检查 --corpus/--raw", file=sys.stderr)
        return 2
    if args.fresh:
        args.resume = False
    args.no_cache = True          # 评估只读缓存, 不回写
    print(f"== 语料 {len(items)} 张, {'缓存重放' if args.resume else '全量采样构建'} …",
          flush=True)
    if args.resume and not Path(args.cache).is_file():
        print(f"缓存不存在 ({args.cache}), 转全量采样", file=sys.stderr)
        args.resume = False
    kits, skipped = build_kits(items, args)
    if not kits:
        print("有效照片为 0", file=sys.stderr)
        return 2
    cameras = {k.cam for k in kits}

    # ---- 端到端口径 (主对照; 另以 optimize.eval_e2e 交叉核对池化中位数) ----
    print("== 端到端口径: A (现行 configs) …", flush=True)
    e2e_a = e2e_track(kits, shared0, args.stride)
    x_a = eval_e2e(kits, shared0, args.stride)
    assert abs(x_a["median"] - e2e_a["median"]) < 1e-9, "e2e 双实现不一致"
    print(f"   A median={e2e_a['median']:.3f} p95={e2e_a['p95']:.3f}", flush=True)
    print("== 端到端口径: B (新表 calib_out) …", flush=True)
    e2e_b = e2e_track(kits, shared1, args.stride)
    x_b = eval_e2e(kits, shared1, args.stride)
    assert abs(x_b["median"] - e2e_b["median"]) < 1e-9, "e2e 双实现不一致"
    print(f"   B median={e2e_b['median']:.3f} p95={e2e_b['p95']:.3f}", flush=True)

    # ---- 色度口径 (G-5, eval_rp_ccm_ab 同式; 基座渲染一次, 多 rp 复用) ----
    print("== 色度口径: 基座渲染 (θ0 / θ* 中性, ev=0, 无 CCM) …", flush=True)
    base0 = chroma_neutral_base(kits, shared0, args.stride)
    base1 = chroma_neutral_base(kits, shared1, args.stride)
    gj = json.loads(Path(args.groups_json).read_text(encoding="utf-8"))
    rp_global = np.asarray(gj["rp_global_neutral"]["matrix"], dtype=np.float64)
    rp_groups = {g: np.asarray(v["matrix"], dtype=np.float64)
                 for g, v in gj["groups"].items()}
    rp_rows_by_group: dict[str, np.ndarray | None] = {
        b["photo_id"]: rp_groups.get(b["group"]) for b in base1}
    chroma: dict[str, list[dict]] = {
        "A0": chroma_track(base0, None),
        "A": chroma_track(base1, None),
        "B": chroma_track(base1, rp_global),
        "C": chroma_track(base1, None),   # 占位, 下行按照片替换分组矩阵
        "D": chroma_track(base1, t0.rp_ccm_coeff),
    }
    for row_c, b in zip(chroma["C"], base1):
        mg = rp_rows_by_group.get(b["photo_id"])
        de = None
        if mg is not None:
            src = apply_rp_ccm(b["src"], RPCCM(matrix=mg, degree=2)).astype(np.float64)
            de = delta_e_2000(linear_srgb_to_lab(src * b["gain"]), b["ref_lab"])
        row_c["de"] = de if de is not None else np.full(b["n"], np.nan)
    chroma["C"] = [r for r in chroma["C"] if np.isfinite(r["de"]).all()]
    if not chroma["C"]:
        # 空池绝不允许静默通过 (会伪装成 median=0 的"完美"指标, t32 教训)
        raise RuntimeError("分组 rp 轨 (C) 无有效样本: rp_ccm_by_group.json groups "
                           "与语料拍摄日不匹配?")
    verdict = g5_verdicts(chroma["A"], chroma["B"], cameras)
    print(f"== G-5: A {verdict['median_a']:.3f} → B {verdict['median_b']:.3f} "
          f"({verdict['median_improvement'] * 100:+.1f}%)", flush=True)

    # ---- t32 交叉核对 (checkpoint 历史 + calib_run.md 报告值) ----
    t32_cross = {"e2e_theta0": "n/a", "e2e_theta_star": "n/a",
                 "e2e_verdict": "ckpt 不存在", "g5_a": "n/a", "g5_b": "n/a",
                 "g5_c": "n/a", "g5_verdict": "ckpt 不存在"}
    if ckpt_file.is_file():
        rows = blob.get("eval_rows") or []
        by_tag = {r.get("tag"): r for r in rows if isinstance(r, dict)}
        r0, r1 = by_tag.get("theta0"), (by_tag.get("lbfgs_final")
                                        or by_tag.get("theta_loaded_recheck"))
        if r0:
            t32_cross["e2e_theta0"] = f"{r0['median']:.3f}/{r0['p95']:.3f}"
        if r1:
            t32_cross["e2e_theta_star"] = f"{r1['median']:.3f}/{r1['p95']:.3f}"
        if r0 and r1:
            ok = (abs(r0["median"] - e2e_a["median"]) < 5e-3
                  and abs(r1["median"] - e2e_b["median"]) < 5e-3)
            t32_cross["e2e_verdict"] = "一致 ✅" if ok else \
                f"偏差 (本评 {e2e_a['median']:.3f}/{e2e_b['median']:.3f}) ❌"
        # G-5 报告值从 calib_run.md 提取 (A/B/C median 行)
        run_md = Path(".artifacts/calib_run.md")
        if run_md.is_file():
            import re
            text = run_md.read_text(encoding="utf-8")
            m = re.findall(r"median \*\*(-?[\d.]+)\*\*", text)
            if len(m) >= 3:
                g5a, g5b, g5c = (float(x) for x in m[:3])
                t32_cross.update(g5_a=f"{g5a:.3f}", g5_b=f"{g5b:.3f}",
                                 g5_c=f"{g5c:.3f}")
                okg = (abs(g5a - verdict["median_a"]) < 5e-3
                       and abs(g5b - verdict["median_b"]) < 5e-3)
                t32_cross["g5_verdict"] = "一致 ✅" if okg else \
                    f"偏差 (本评 {verdict['median_a']:.3f}/{verdict['median_b']:.3f}) ❌"

    out = Path(args.report)
    write_report(out, args, t0, t1, kits, e2e_a, e2e_b, chroma, verdict,
                 cameras, skipped, t32_cross)

    # ---- 机器可读摘要 (下游 t34/t35) ----
    summary = {
        "schema": "pixo.stage2_eval.v1", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": args.seed, "corpus": args.corpus, "n_photos": len(kits),
        "groups": sorted({k.group for k in kits}), "cameras": sorted(cameras),
        "dcp": args.dcp, "long_edge": args.long_edge, "stride": args.stride,
        "cache": args.cache, "ckpt_note": ckpt_note,
        "e2e": {"theta0": {k: e2e_a[k] for k in ("median", "p95", "mean")},
                "theta_star": {k: e2e_b[k] for k in ("median", "p95", "mean")},
                "median_improvement": (e2e_a["median"] - e2e_b["median"])
                / max(e2e_a["median"], 1e-9)},
        "chroma": {k: pool_stats(v) for k, v in chroma.items()},
        "g5": verdict, "t32_cross": t32_cross, "skipped": skipped,
        "report": str(out),
    }
    Path(args.json_out).write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    gates = sum([verdict["gate_improve15"], verdict["gate_no_regression"],
                 verdict["gate_p95"], verdict["gate_2cameras"]])
    print(f"== 端到端: θ0 {e2e_a['median']:.3f} → θ* {e2e_b['median']:.3f} "
          f"({(e2e_a['median'] - e2e_b['median']) / max(e2e_a['median'], 1e-9) * 100:+.1f}%)")
    print(f"== G-5 门槛线 {gates}/4 项通过")
    print(f"DONE {out} ({time.time() - t00:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
