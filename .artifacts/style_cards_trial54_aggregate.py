"""R20 聚合: style_cards_trial_54.json → QC 迁移表/触发面/ΔE/提前压光统计。

用法: python .artifacts/style_cards_trial54_aggregate.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ART = Path(__file__).resolve().parent
SRC = ART / "style_cards_trial_54.json"


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    runs = d.get("runs", {})
    ok = [v for v in runs.values() if not v.get("error")]
    print(f"样本: {len(runs)} (有效 {len(ok)}, error {len(runs) - len(ok)})")

    # 1) QC 迁移表
    migrate: dict = {}
    for v in ok:
        k = (v.get("a_qc"), v.get("b_qc"))
        migrate[k] = migrate.get(k, 0) + 1
    print("\n=== QC 迁移表 (A 现状 → B 开卡) ===")
    for (a, b), n in sorted(migrate.items(), key=lambda x: -x[1]):
        mark = "  <-- 变化" if a != b else ""
        print(f"  {a:22s} -> {b:22s}: {n}{mark}")

    # state 迁移
    smig: dict = {}
    for v in ok:
        k = (v.get("a_state"), v.get("b_state"))
        smig[k] = smig.get(k, 0) + 1
    print("\n=== state 迁移 ===")
    for (a, b), n in sorted(smig.items(), key=lambda x: -x[1]):
        if a != b:
            print(f"  {a} -> {b}: {n}  <-- 变化")
    same_state = sum(n for (a, b), n in smig.items() if a == b)
    print(f"  state 不变: {same_state}/{len(ok)}")

    # rollbacks / iterations
    ra = [v.get("a_rollbacks", 0) for v in ok]
    rb = [v.get("b_rollbacks", 0) for v in ok]
    ia = [v.get("a_iterations", 0) for v in ok]
    ib = [v.get("b_iterations", 0) for v in ok]
    print(f"\nqc_rollback: A median={np.median(ra)} sum={sum(ra)} | "
          f"B median={np.median(rb)} sum={sum(rb)}")
    print(f"iterations : A median={np.median(ia)} | B median={np.median(ib)}")

    # 2) ΔE 分布
    des = [v["ab_compare"] for v in ok if isinstance(v.get("ab_compare"), dict)
           and "de_mean" in v["ab_compare"]]
    dm = np.array([x["de_mean"] for x in des])
    dp = np.array([x["de_p95"] for x in des])
    cr = np.array([x["changed_ratio"] for x in des])
    changed = dm[dm > 0]
    print(f"\n=== ΔE2000 (A vs B final) ===")
    print(f"  有变化照片 (de_mean>0): {len(changed)}/{len(des)}")
    if len(changed):
        print(f"  变化子集 de_mean: median={np.median(changed):.3f} "
              f"p90={np.quantile(changed, .9):.3f} max={changed.max():.3f}")
        print(f"  changed_ratio: median={np.median(cr[dm > 0]):.3f}")
    print(f"  全体 de_mean: median={np.median(dm):.3f} p95={np.quantile(dm, .95):.3f} max={dm.max():.3f}")

    # 3) 触发面
    print("\n=== style_card 规则触发面 ===")
    rule_stat: dict = {}
    fires_by_photo = []
    for v in ok:
        fires = v.get("style_fires") or []
        ids = set()
        for f in fires:
            for rid in f.get("rule_ids", []):
                ids.add(rid)
                rule_stat.setdefault(rid, {"photos": set(), "iters": 0})
                rule_stat[rid]["photos"].add(v["sample"])
                rule_stat[rid]["iters"] += 1
        fires_by_photo.append(len(fires))
    print(f"  有触发的照片: {sum(1 for f in fires_by_photo if f > 0)}/{len(ok)}")
    for rid, st in sorted(rule_stat.items(), key=lambda x: -x[1]["iters"]):
        print(f"  {rid}: {len(st['photos'])} 照片 / {st['iters']} 轮次")

    # decided exposure 落位 (有执行位的建议)
    exp_land = []
    for v in ok:
        for f in v.get("style_fires") or []:
            if f.get("decided_exposure") is not None:
                exp_land.append((v["sample"], f["iteration"],
                                 f["decided_exposure"],
                                 f.get("highlight_clip_ratio")))
    print(f"\n=== decided exposure 落位 (有执行位的卡建议) ===")
    print(f"  事件数: {len(exp_land)} | 涉及照片: {len(set(x[0] for x in exp_land))}")
    for s, it, dec, clip in exp_land[:20]:
        print(f"  {s} it={it} exposure={dec} clip={clip}")

    # 4) 提前压光
    masked = [(v["sample"], v.get("masked_overflow") or [])
              for v in ok if v.get("masked_overflow")]
    print(f"\n=== 提前压光 (R13 现象: 卡压曝光后溢出证据消失) ===")
    print(f"  涉及照片: {len(masked)}")
    for s, evs in masked:
        for e in evs:
            a_qc = next(v.get("a_qc") for v in ok if v["sample"] == s)
            b_qc = next(v.get("b_qc") for v in ok if v["sample"] == s)
            print(f"  {s}: it={e['iteration']} exp={e['decided_exposure']} "
                  f"overflow {e['overflow_at_decision']}→{e['overflow_after']} "
                  f"| A_qc={a_qc} B_qc={b_qc}")

    # 5) QC 达标率汇总
    print("\n=== 达标率 ===")
    for arm in ("a", "b"):
        n_pass = sum(1 for v in ok if v.get(f"{arm}_qc") == "pass")
        n1 = sum(1 for v in ok if v.get(f"{arm}_qc") == "escalate_1x")
        n2 = sum(1 for v in ok if v.get(f"{arm}_qc") == "escalate_2x")
        other = len(ok) - n_pass - n1 - n2
        print(f"  {arm}: pass={n_pass} escalate_1x={n1} escalate_2x={n2} "
              f"other={other} | 达标率={n_pass / len(ok) * 100:.1f}%")


if __name__ == "__main__":
    main()
