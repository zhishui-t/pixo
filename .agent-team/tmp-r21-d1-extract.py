"""从 D1 探针原始输出提取紧凑证据表（只读，秒级）。"""
from __future__ import annotations

import json
from pathlib import Path

SRC = Path(r"K:\work\project\pixo\.agent-team\tmp-r21-d1-probe.txt")


def main() -> int:
    for line in SRC.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "sample" not in rec:
            print("RULES", json.dumps(rec, ensure_ascii=False))
            continue
        events = rec.get("decide_events") or []
        # QA 勘误（2026-09-10，R21 总审）：原第 35 行把探针的
        # ``rule_ids_last_nonempty``（"最后一条非空轮"）直接标成
        # ``union_rule_ids``（"全轮并集"）—— 两者在"早期轮命中、末轮命中
        # 且规则集不同"的样本上不等价（实测 DSC_5238：末轮非空
        # =[clarity_flat_rule_031, saturation_high_rule]，
        # 真并集含首轮 dehaze_rule_030）。此处按**全 decide 事件并集**
        # （首次出现顺序、去重）计算真值，并把"最后一条非空轮"单列。
        union: list[str] = []
        for e in events:
            for rid in (e.get("rule_ids") or []):
                if rid not in union:
                    union.append(rid)
        print(json.dumps({
            "sample": rec["sample"],
            "duration_s": rec["duration_s"],
            "state": rec["state"],
            "iteration": rec["iteration"],
            "colorfulness_preview_iter1": (
                events[0]["colorfulness_proxy"] if events else None),
            "colorfulness_preview_last": rec.get("colorfulness_proxy_preview_top"),
            "colorfulness_final_top": rec.get("colorfulness_proxy_final_top"),
            "haze_preview_last": rec.get("haze_proxy_preview_top"),
            "tonal_range_preview_last": rec.get("tonal_range_preview_top"),
            "last_decide_rule_ids": rec.get("rule_ids"),
            "last_nonempty_rule_ids": rec.get("rule_ids_last_nonempty"),
            "union_rule_ids": union,
            "decide_rule_ids_by_iter": [
                {"it": e["iteration"], "ids": e["rule_ids"],
                 "cp": e["colorfulness_proxy"], "last": e["last_iteration"]}
                for e in events
            ],
            "result_params": rec.get("result_params"),
            "final_highlight_clip_ratio": rec.get("final_highlight_clip_ratio"),
            "mask_nonzero_px": rec.get("mask_nonzero_px"),
            "segmenter_last_degraded": rec.get("segmenter_last_degraded"),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
