"""F01 结果深析: 把 f01_batch_results.json 解成可决策的结论.

不重新渲染, 全部由已落盘字段 (A/B/C_raw/C_al/C_bug/dL/da/db/端点/dhash) 计算。

核心分解
--------
整图系统色偏 A = |(dL, da, db)|
  ├─ 影调分量 |dL|      —— 可由整体曝光增益/曲线修正
  └─ 色度分量 |(da,db)| —— 纯色彩问题 (口径同 eval_rp_ccm_ab 的"曝光增益对齐后"),
                          故可直接与该报告的 ΔE2000 median 5.946 对照

输出: .artifacts/f01_deep_report.md
用法: python .artifacts/f01_analyze.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".artifacts/f01_batch_results.json"
OUT = ROOT / ".artifacts/f01_deep_report.md"
JND = 2.3


def q(v, p):
    return float(np.percentile(v, p)) if len(v) else float("nan")


def col(rows, k):
    return [r[k] for r in rows if isinstance(r.get(k), (int, float)) and r[k] == r[k]]


def fmt(v, w=7, p=2):
    return f"{v:>{w}.{p}f}" if v == v else f"{'-':>{w}}"


def main() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    ok = [r for r in rows if "err" not in r]
    ok = [r for r in ok if isinstance(r.get("A"), (int, float))]
    bad = [r for r in rows if "err" in r]
    if not ok:
        raise SystemExit("无有效样本")

    for r in ok:
        r["chroma"] = float(np.hypot(r["da"], r["db"]))
        r["tone"] = abs(float(r["dL"]))

    L: list[str] = []
    L.append("# F01 深析报告 (引擎 vs 相机预览)\n")
    L.append(f"- 有效样本 **{len(ok)}** / 失败 {len(bad)}")
    L.append(f"- JND 参考 ΔE76 ≈ {JND}")
    L.append(f"- 朝向表 `{ {3: 2, 6: 1, 8: -1} }` (np.rot90 k)\n")

    # ---------- 1. 分位
    L.append("## 1. 指标分布 (分位)\n")
    L.append("| 指标 | p10 | p25 | median | p75 | p90 |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for k in ("A", "B", "C_raw", "C_al", "C_bug", "tone", "chroma"):
        v = col(ok, k)
        if not v:
            continue
        L.append(f"| {k} | " + " | ".join(fmt(q(v, p)) for p in (10, 25, 50, 75, 90)) + " |")
    L.append("")

    # ---------- 2. 分解: 影调 vs 色度
    a, tone, chroma = col(ok, "A"), col(ok, "tone"), col(ok, "chroma")
    L.append("## 2. 色偏分解: 影调 vs 色度\n")
    L.append("| 分量 | median | 占 A 的比例 | 含义 |")
    L.append("|---|---:|---:|---|")
    L.append(f"| A 整图系统色偏 | {np.median(a):.2f} | 100% | 合计 |")
    L.append(f"| ├ 影调 \\|dL\\| | {np.median(tone):.2f} | "
             f"{np.median(tone) / max(np.median(a), 1e-6) * 100:.0f}% | 可由曝光/曲线修正 |")
    L.append(f"| └ 色度 \\|(da,db)\\| | {np.median(chroma):.2f} | "
             f"{np.median(chroma) / max(np.median(a), 1e-6) * 100:.0f}% | 纯色彩问题 |")
    L.append("")
    L.append(f"- 色度分量 median **{np.median(chroma):.2f}** vs JND {JND} → "
             f"{'超出' if np.median(chroma) > JND else '在'}感知阈值"
             f" ({np.median(chroma) / JND:.1f}x)")
    L.append("")

    # ---------- 3. 方向一致性
    L.append("## 3. 色偏方向一致性 (系统偏差 or 区域偏差)\n")
    L.append("| 分量 | 正号 | 负号 | 一致率 | 判定 |")
    L.append("|---|---:|---:|---:|---|")
    for k, lab in (("dL", "明度"), ("da", "红-绿"), ("db", "黄-蓝"), ("chroma", "色度模")):
        v = col(ok, k)
        if not v:
            continue
        if k == "chroma":
            continue
        pos = sum(1 for x in v if x > 0)
        r = max(pos, len(v) - pos) / len(v)
        L.append(f"| {k} {lab} | {pos} | {len(v) - pos} | {r * 100:.1f}% | "
                 f"{'系统偏差' if r > 0.8 else '区域/场景相关'} |")
    L.append("")

    # ---------- 4. 分会话 × 朝向
    def group_table(keyfn, title):
        g: dict = defaultdict(list)
        for r in ok:
            g[keyfn(r)].append(r)
        L.append(f"## {title}\n")
        L.append("| 组 | n | 场景 | A | 色度 | \\|dL\\| | cc |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        for k in sorted(g, key=lambda x: -len(g[x])):
            v = g[k]
            L.append(f"| {k} | {len(v)} | {scene_count(v)} | {np.median(col(v, 'A')):.2f} | "
                     f"{np.median(col(v, 'chroma')):.2f} | {np.median(col(v, 'tone')):.2f} | "
                     f"{np.median(col(v, 'cc')):.3f} |")
        L.append("")

    group_table(lambda r: r["session"], "4. 分会话")
    group_table(lambda r: {1: "横拍 EXIF=1", 3: "EXIF=3", 6: "竖拍 EXIF=6",
                           8: "竖拍 EXIF=8"}.get(r["orient"], f"EXIF={r['orient']}"),
                "5. 分朝向")

    # ---------- 6. 朝向 bug 的代价
    port = [r for r in ok if r["orient"] in (6, 8)]
    if port:
        L.append("## 6. 朝向 bug 的代价 (竖拍子集)\n")
        L.append("| 口径 | median |")
        L.append("|---|---:|")
        L.append(f"| C_raw 正确朝向 | {np.median(col(port, 'C_raw')):.2f} |")
        L.append(f"| C_bug 旧错误朝向 | {np.median(col(port, 'C_bug')):.2f} |")
        L.append(f"| 虚高倍数 | "
                 f"{np.median(col(port, 'C_bug')) / max(np.median(col(port, 'C_raw')), 1e-6):.2f}x |")
        L.append(f"\n竖拍占全样本 {len(port) / len(ok) * 100:.1f}% → "
                 f"历史基于逐像素 ΔE 的结论对这部分样本系统性偏高。\n")

    # ---------- 7. 色偏 vs 场景亮度 (验证"越暗越偏")
    L.append("## 7. 色偏 vs 场景亮度\n")
    pairs = [(((r["cam_p05"] + r["cam_p995"]) / 2), r["dL"]) for r in ok
             if isinstance(r.get("cam_p05"), (int, float))
             and isinstance(r.get("cam_p995"), (int, float))]
    if len(pairs) > 10:
        x = np.array([p[0] for p in pairs], float)
        y = np.array([p[1] for p in pairs], float)
        rho = float(np.corrcoef(x, y)[0, 1])
        med_x = float(np.median(x))
        lo = [b for aa, b in pairs if aa <= med_x]
        hi = [b for aa, b in pairs if aa > med_x]
        L.append(f"- 相关系数 (场景端点均值 vs dL): **{rho:+.3f}**")
        L.append(f"- 暗场景半区 median dL = {np.median(lo):+.2f} (n={len(lo)})")
        L.append(f"- 亮场景半区 median dL = {np.median(hi):+.2f} (n={len(hi)})")
        L.append(f"- 结论: {'暗场景偏暗更重, 曝光策略问题' if abs(rho) > 0.3 and np.median(lo) < np.median(hi) else '无显著亮度相关'}\n")

    # ---------- 8. 端点 (通透线输入)
    L.append("## 8. 端点对照 (供 F02/F03 通透线)\n")
    L.append("配对统计优先 (同一张照片的 we-cam)，避免两分布中位数相减的失真。\n")
    L.append("| 项 | 我们 median | 相机 median | 差(中位相减) | 配对差 median | 配对差>0 占比 |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for k, lab in (("p05", "黑点 p0.5"), ("p995", "白点 p99.5"),
                   ("clip_lo", "暗部裁切 %"), ("clip_hi", "高光裁切 %")):
        o, c = col(ok, f"our_{k}"), col(ok, f"cam_{k}")
        if not o:
            continue
        d = [r[f"our_{k}"] - r[f"cam_{k}"] for r in ok
             if isinstance(r.get(f"our_{k}"), (int, float))
             and isinstance(r.get(f"cam_{k}"), (int, float))]
        L.append(f"| {lab} | {np.median(o):.2f} | {np.median(c):.2f} | "
                 f"{np.median(o) - np.median(c):+.2f} | {np.median(d):+.2f} | "
                 f"{sum(1 for x in d if x > 0) / len(d) * 100:.0f}% |")
    L.append("")

    # ---------- 8.5 全局修正天花板
    dv = np.array([[r["dL"], r["da"], r["db"]] for r in ok
                   if all(isinstance(r.get(k), (int, float)) for k in ("dL", "da", "db"))])
    if len(dv):
        L.append("## 8.5 全局修正的天花板 (关键决策项)\n")
        L.append("问: 一个**全局**色彩/曝光修正 (对所有照片施加同一个 dL/da/db 偏移) 能消掉多少偏差?\n")
        dvm = np.median(dv, axis=0)
        before = np.linalg.norm(dv, axis=1)
        after = np.linalg.norm(dv - dvm, axis=1)
        L.append(f"- 最优全局偏移 = (dL {dvm[0]:+.2f}, da {dvm[1]:+.2f}, db {dvm[2]:+.2f})")
        L.append(f"- A before = {np.median(before):.2f} → A after = {np.median(after):.2f}"
                 f"  (**降 {100 * (1 - np.median(after) / max(np.median(before), 1e-6)):.0f}%**)")
        L.append(f"- 残留占比 {np.median(after) / max(np.median(before), 1e-6) * 100:.0f}% "
                 f"→ {'偏差主要是场景相关, 单一全局修正不够' if np.median(after) > 0.6 * np.median(before) else '偏差有共同成分, 全局修正有效'}")
        L.append("")
        L.append("| 分量 | 全局最优 | 修正前 median \\|·\\| | 修正后 median \\|·\\| | 降幅 |")
        L.append("|---|---:|---:|---:|---:|")
        for i, (k, lab) in enumerate((("dL", "明度"), ("da", "红-绿"), ("db", "黄-蓝"))):
            b = np.median(np.abs(dv[:, i]))
            a2 = np.median(np.abs(dv[:, i] - dvm[i]))
            L.append(f"| {k} {lab} | {dvm[i]:+.2f} | {b:.2f} | {a2:.2f} | "
                     f"{100 * (1 - a2 / max(b, 1e-6)):.0f}% |")
        L.append("")

        # 各分量十分位 (看是否单峰/是否长尾)
        L.append("### 各分量十分位\n")
        L.append("| 分量 | p10 | p25 | p50 | p75 | p90 | 标准差 |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        for i, k in enumerate(("dL", "da", "db")):
            v = dv[:, i]
            L.append(f"| {k} | " + " | ".join(f"{(np.percentile(v, p)):+.2f}"
                                              for p in (10, 25, 50, 75, 90))
                     + f" | {v.std():.2f} |")
        L.append("")

        # 与会话/场景的相关性
        if len(dv) > 20:
            L.append("### da (绿偏) 与各量的相关\n")
            sc = [(r["cam_p05"] + r["cam_p995"]) / 2 for r in ok
                  if all(isinstance(r.get(k), (int, float))
                         for k in ("dL", "da", "db", "cam_p05", "cam_p995"))]
            if len(sc) == len(dv):
                x = np.array(sc)
                L.append("| 对 | Pearson r |")
                L.append("|---|---:|")
                for i, k in enumerate(("dL", "da", "db")):
                    L.append(f"| 场景亮度 ↔ {k} | {np.corrcoef(x, dv[:, i])[0, 1]:+.3f} |")
                L.append(f"| dL ↔ da | {np.corrcoef(dv[:, 0], dv[:, 1])[0, 1]:+.3f} |")
                L.append(f"| da ↔ db | {np.corrcoef(dv[:, 1], dv[:, 2])[0, 1]:+.3f} |")
                # 秩相关 (对长尾稳健) + 亮度代理换成 cam_p995
                from scipy.stats import spearmanr  # type: ignore
                L.append("")
                L.append("秩相关 (Spearman, 对长尾稳健):\n")
                L.append("| 对 | rho |")
                L.append("|---|---:|")
                for i, k in enumerate(("dL", "da", "db")):
                    L.append(f"| 场景亮度 ↔ {k} | {spearmanr(x, dv[:, i]).statistic:+.3f} |")
                # 亮度分箱
                med_x = float(np.median(x))
                L.append("")
                L.append("| 场景亮度分箱 | n | da median | dL median |")
                L.append("|---|---:|---:|---:|")

                for lab, m in (("暗半区", x <= med_x), ("亮半区", x > med_x)):
                    sub = dv[m]
                    L.append(f"| {lab} | {int(m.sum())} | {np.median(sub[:, 1]):+.2f} | "
                             f"{np.median(sub[:, 0]):+.2f} |")
                L.append("")

    # ---------- 8.6 分组明细 (子目录)
    g2: dict = defaultdict(list)
    for r in ok:
        g2[f"{r['session']}/{r['group']}"].append(r)
    if len(g2) > 1:
        L.append("## 8.6 子目录明细\n")
        L.append("| 组 | n | 场景 | A | 色度 | dL | da | db |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for k in sorted(g2, key=lambda x: -len(g2[x])):
            v = g2[k]
            L.append(f"| {k} | {len(v)} | {scene_count(v)} | {np.median(col(v, 'A')):.2f} | "
                     f"{np.median(col(v, 'chroma')):.2f} | {np.median(col(v, 'dL')):+.2f} | "
                     f"{np.median(col(v, 'da')):+.2f} | {np.median(col(v, 'db')):+.2f} |")
        L.append("")

    # ---------- 9. 最差样本
    L.append("## 9. 最差 / 最好样本\n")
    s = sorted(ok, key=lambda r: -r["A"])
    L.append("| 序 | 文件 | 会话 | A | 色度 | dL | da | db |")
    L.append("|---:|---|---|---:|---:|---:|---:|---:|")
    for i, r in enumerate(s[:8] + [None] + s[-5:], 1):
        if r is None:
            L.append("| … | … | … | … | … | … | … | … |")
            continue
        L.append(f"| {i} | {r['name']} | {r['session']} | {r['A']:.2f} | {r['chroma']:.2f} | "
                 f"{r['dL']:+.2f} | {r['da']:+.2f} | {r['db']:+.2f} |")
    L.append("")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:40]))
    print(f"\n→ {OUT}")


def scene_count(rows: list[dict], ham_max: int = 10) -> int:
    seen: list[int] = []
    for r in sorted(rows, key=lambda x: x.get("name", "")):
        h = r.get("dhash")
        if not isinstance(h, str):
            continue
        v = int(h, 16)
        if any(bin(v ^ s).count("1") <= ham_max for s in seen):
            continue
        seen.append(v)
    return len(seen)


if __name__ == "__main__":
    main()
