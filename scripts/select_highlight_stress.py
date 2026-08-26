"""t97 厦门高光压力抽样：从 screen_report.json 筛 highlight_clip>3% 的 669 张，
按子目录分层抽取 20 张（spike 型与平顶型各半）。

判别口径：
- flatness = highlight_clip + mean_luminance/255  （越大=画面大片亮域=平顶型；越小=亮点集中=spike 型）
- 每层内按 flatness 排序，下半=spike 池、上半=平顶池，各取半数；
  池内按文件名 linspace 均匀散布（既覆盖分布又避免极端聚簇）。

用法: python scripts/select_highlight_stress.py [--out File] [--show]
输出: exports/auto/xiamen_screen/highlight_stress_20.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "exports/auto/xiamen_screen/screen_report.json"
# 20 张按层配额：12/3/2/3（=669 中 393/113/52/111 的比例取整），spike/flat 各半
QUOTA = {  # batch -> (count, spike_n, flat_n)
    "1": (12, 6, 6),
    "101XM_02": (3, 2, 1),
    "102XM_03": (2, 1, 1),
    "103XM_04": (3, 1, 2),
}


def linspace_pick(items, n):
    """在已排序列表上按 linspace 均匀取 n 个，返回下标。"""
    if n <= 0:
        return []
    k = min(n, len(items))
    idx = np.linspace(0, len(items) - 1, k).round().astype(int)
    # 去重保序（n>len 时 linspace 会重复）
    seen, out = set(), []
    for i in idx:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPORT.parent / "highlight_stress_20.jsonl"))
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    report = json.load(open(REPORT, encoding="utf-8"))
    hi = [r for r in report if r.get("highlight_clip", 0) > 0.03]
    print(f"candidates clip_hi>3%: {len(hi)}")

    from collections import defaultdict
    by_batch = defaultdict(list)
    for r in hi:
        r["_flatness"] = r["highlight_clip"] + r.get("mean_luminance", 0) / 255.0
        by_batch[r["batch"]].append(r)

    selected = []
    for batch, (cnt, spike_n, flat_n) in QUOTA.items():
        pool = by_batch.get(batch, [])
        pool.sort(key=lambda r: (r["_flatness"], r["file"]))
        mid = len(pool) // 2
        spike_pool = sorted(pool[:mid], key=lambda r: r["file"])
        flat_pool = sorted(pool[mid:], key=lambda r: r["file"])
        take_s = linspace_pick(spike_pool, spike_n)
        take_f = linspace_pick(flat_pool, flat_n)
        picks = [spike_pool[i] for i in take_s] + [flat_pool[i] for i in take_f]
        print(f"  {batch}: {cnt} 张 (spike {spike_n} + flat {flat_n}), "
              f"池 {len(pool)} (spike池 {len(spike_pool)}/flat池 {len(flat_pool)})")
        for r in picks:
            r["_type"] = "spike" if r in spike_pool else "flat"
            selected.append(r)

    selected.sort(key=lambda r: (r["batch"], r["file"]))
    assert len(selected) == 20, f"抽样数应为 20，实得 {len(selected)}"
    types = [r["_type"] for r in selected]
    print(f"selected {len(selected)}: spike {types.count('spike')} / flat {types.count('flat')}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in selected:
            f.write(json.dumps({
                "batch": r["batch"], "file": r["file"], "raw": r["raw"],
                "type": r["_type"],
                "mean_luminance": r.get("mean_luminance"),
                "highlight_clip": r.get("highlight_clip"),
                "flatness": round(r["_flatness"], 4),
            }, ensure_ascii=False) + "\n")
    print(f"written -> {out}")

    if args.show:
        for r in selected:
            print(f"  {r['batch']:9s} {r['file']:14s} type={r['_type']:5s} "
                  f"clip={r['highlight_clip']:.3f} meanL={r.get('mean_luminance')}")


if __name__ == "__main__":
    main()
