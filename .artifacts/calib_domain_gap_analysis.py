"""R19 分析: calib_domain_gap run2 数据 → 分组统计 + 一致性检验 + 结论数字。

用法: python .artifacts/calib_domain_gap_analysis.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ART = Path(__file__).resolve().parent
S = ['s0.0', 's0.45', 's0.9', 's1.35', 's1.8']
S_GRID = [0.0, 0.45, 0.9, 1.35, 1.8]
FIT = (1.7578, 2.3984)
INTERP = (1.6778, 2.4784)


def load(run: str) -> dict:
    rows = [json.loads(l) for l in
            (ART / f"calib_domain_gap_checkpoint{run}.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    by: dict = {}
    for r in rows:
        by.setdefault(r["photo_id"], {})[r["arm"]] = r
    return by


def group_of(w: float) -> str:
    if w < FIT[0]:
        return "OOS-low"
    if w > FIT[1]:
        return "OOS-high"
    return "IN"


def runtime_oos(arms: dict) -> bool:
    d1, df = arms.get("s0.9", {}).get("dE00"), arms.get("fallback", {}).get("dE00")
    if d1 is None or df is None:
        return False
    return abs(d1 - df) > 1e-9


def optimal_s(arms: dict) -> tuple[float, float] | None:
    cands = []
    for j, k in enumerate(S):
        v = arms.get(k, {}).get("dE00")
        if v is not None and np.isfinite(v):
            cands.append((float(v), j))
    if len(cands) < 3:
        return None
    bd, bi = min(cands)
    if 0 < bi < len(cands) - 1:
        y0 = cands[bi - 1][0]
        y2 = cands[bi + 1][0]
        denom = y0 - 2 * bd + y2
        delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
        delta = float(np.clip(delta, -0.5, 0.5))
    else:
        delta = 0.0
    s = S_GRID[bi] + delta * 0.45
    return s, bd


def main() -> None:
    by = load("")   # run2 = 当前 checkpoint
    # ---- 一致性: fallback vs shim (runtime 域内应逐位同差) ----
    repro = []
    for pid, arms in by.items():
        if not all(k in arms for k in S + ["fallback"]):
            continue
        de = [arms[k].get("dE00", np.nan) for k in S]
        if not all(np.isfinite(x) for x in de):
            continue
        d2 = max(abs(de[i + 1] - 2 * de[i] + de[i - 1]) for i in range(1, 4))
        same = abs(arms["fallback"]["dE00"] - arms["s0.9"]["dE00"]) < 1e-9
        repro.append((pid, group_of(arms["s0.9"]["wb_B"]), runtime_oos(arms), same, d2))
    flip = [(p, g, w) for p, g, o, s, d2 in repro if s and g != "OOS?"]
    print("=== 一致性 (run2) ===")
    in_ph = [x for x in repro if not x[2]]
    oos_ph = [x for x in repro if x[2]]
    print(f"runtime 域内: {len(in_ph)} (其中 fallback≠shim 异常: "
          f"{sum(1 for x in in_ph if not x[3])})")
    print(f"runtime OOS : {len(oos_ph)}")
    print(f"s-扫描二阶差分 max>1.0 的照片: {sum(1 for x in repro if x[4] >= 1.0)}")
    print()
    # ---- 分组统计 (按 rawpy wb_B 声明域分组) ----
    print("=== 分组: 垫片(s0.9) vs warmth=0 vs fallback vs 最优 s ===")
    stats = {}
    for pid, arms in by.items():
        if not all(k in arms for k in S):
            continue
        g = group_of(arms["s0.9"]["wb_B"])
        opt = optimal_s(arms)
        if opt is None:
            continue
        s_star, de_star = opt
        row = {
            "dE_shim": arms["s0.9"]["dE00"], "dE_w0": arms["s0.0"]["dE00"],
            "dE_fb": arms.get("fallback", {}).get("dE00", np.nan),
            "dE_star": de_star, "s_star": s_star,
            "da_shim": arms["s0.9"]["da"], "db_shim": arms["s0.9"]["db"],
            "da_star": None, "db_star": None,
            "wb_B": arms["s0.9"]["wb_B"],
            "recover": arms["s0.9"]["dE00"] - de_star,
        }
        # 最优臂的 da/db (最近网格点)
        bi = int(np.argmin([abs(s_star - g) for g in S_GRID]))
        kbest = S[bi]
        row["da_star"] = arms[kbest]["da"]
        row["db_star"] = arms[kbest]["db"]
        stats.setdefault(g, []).append(row)
        stats.setdefault("ALL", []).append(row)
    for g in ("OOS-low", "IN", "OOS-high", "ALL"):
        rs = stats.get(g)
        if not rs:
            print(f"{g}: 无样本")
            continue
        de_shim = np.array([r["dE_shim"] for r in rs])
        de_w0 = np.array([r["dE_w0"] for r in rs])
        de_fb = np.array([abs(r["dE_fb"]) for r in rs if np.isfinite(r["dE_fb"])])
        de_st = np.array([r["dE_star"] for r in rs])
        ss = np.array([r["s_star"] for r in rs])
        da = np.array([abs(r["da_shim"]) for r in rs])
        db = np.array([abs(r["db_shim"]) for r in rs])
        jnd = de_shim >= 2.3
        recov = (row_d := None) or None
        rec = [
            (r["dE_shim"], r["dE_star"]) for r in rs
        ]
        n_rec = sum(1 for a, b in rec if a >= 2.3 and (a - b) >= 0.5 * a)
        print(f"{g} (n={len(rs)}):")
        print(f"  垫片: ΔE median={np.median(de_shim):.2f} |da|={np.median(da):.2f} "
              f"|db|={np.median(db):.2f} | ≥JND: {int(jnd.sum())}/{len(rs)}")
        print(f"  warmth=0: ΔE median={np.median(de_w0):.2f} | 更优照片 {int((de_w0 < de_shim).sum())}/{len(rs)}")
        if len(de_fb):
            print(f"  fallback: ΔE median={np.median(de_fb):.2f}")
        print(f"  最优 s: median={np.median(ss):.2f} IQR[{np.quantile(ss, .25):.2f},"
              f"{np.quantile(ss, .75):.2f}] | 最优 ΔE median={np.median(de_st):.2f} "
              f"| 垫片可恢复 median={np.median(de_shim) - np.median(de_st):.2f}")
        print(f"  受害(≥JND 且最优可恢复≥50%): {n_rec}/{len(rs)}")
    # ---- wb_B 分布 ----
    print()
    print("=== wb_B 分布 (54) ===")
    w = np.array([arms["s0.9"]["wb_B"] for arms in by.values() if "s0.9" in arms])
    for lo, hi, name in ((1.0, 1.25, "<1.25"), (1.25, 1.5, "1.25-1.5"),
                         (1.5, 1.7578, "1.5-1.758"), (1.7578, 2.0, "1.758-2.0"),
                         (2.0, 2.3984, "2.0-2.398"), (2.3984, 3.0, ">2.398")):
        m = (w >= lo) & (w < hi)
        print(f"  {name}: {int(m.sum())} 张 ({m.mean() * 100:.0f}%)")
    print(f"  warmth 插值域 [1.678,2.478] 外: "
          f"{np.mean((w < INTERP[0]) | (w > INTERP[1])) * 100:.0f}% | "
          f"拟合域外: {np.mean((w < FIT[0]) | (w > FIT[1])) * 100:.0f}%")


if __name__ == "__main__":
    main()
