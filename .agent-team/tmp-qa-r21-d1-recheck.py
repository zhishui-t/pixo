"""QA 独立复算（只读）：D1 反例样本 DSC_5237 的逐轮 rule_ids / colorfulness_proxy。

与 F05 门禁同装配（真路由 MultiModelSegmenter、装配层 11 条规则、
manual_on_unreliable=False、preview_long_edge=1024、max_iterations=2、
不设 PIXO_ALLOW_RESTRICTED），验证 tester D1 表中的两个关键论断：
  ① DSC_5237 末轮**命中**（旧「取最后一条」口径在该样本上会通过）
  ② 并集口径对两个方向都必要

只读：不写仓库任何业务文件；输出 JSON 到 stdout。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.pop("PIXO_ALLOW_RESTRICTED", None)
os.environ.pop("PIXO_RULES", None)

REPO = Path(r"K:\work\project\pixo")
sys.path.insert(0, str(REPO / "src"))

from pixo.pipeline.loop import RawRenderBackend, SinglePhotoLoop  # noqa: E402
from pixo.render.core.calibration import load_dcp  # noqa: E402
from pixo.service.runtime import PixoServiceRuntime, _load_auto_loop_rules  # noqa: E402
from pixo.vision.segmenters.multi_router import MultiModelSegmenter  # noqa: E402

NEF = Path(sys.argv[1] if len(sys.argv) > 1 else r"K:\data\photo\0711\raw\DSC_5237.NEF")
PROMPTS = ("face", "sky", "plant")
DCP = REPO / "resources" / "dcp" / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"

rules = _load_auto_loop_rules(PROMPTS)
segmenter = MultiModelSegmenter()
prof = load_dcp(DCP)
backend = RawRenderBackend(NEF, prof)
loop = SinglePhotoLoop(
    render_backend=backend, segmenter=segmenter, rules=rules,
    preview_long_edge=1024, max_iterations=2, prompts=list(PROMPTS),
    manual_on_unreliable=False,
)
result = loop.run("qa_d1_recheck", raw_path=str(NEF), max_iterations=2)

by_iter = PixoServiceRuntime._auto_loop_rule_ids_by_iteration(result)
union = PixoServiceRuntime._auto_loop_rule_ids(result)
last_nonempty = next(
    (e["rule_ids"] for e in reversed([
        {"rule_ids": [str(r) for r in (
            ev.get("value", {}).get("rule_ids") or []
        )], "iteration": ev.get("value", {}).get("iteration"),
         "decision": ev.get("value", {}).get("decision"),
         "last_iteration": bool(ev.get("value", {}).get("last_iteration")),
         "colorfulness_proxy": (ev.get("value", {}).get("metrics") or {}).get(
             "colorfulness_proxy")}
        for ev in result.trace_events if ev.get("event_type") == "decide"
    ]) if e["rule_ids"]), [],
)

decide_events = []
for ev in result.trace_events:
    if ev.get("event_type") != "decide":
        continue
    v = ev.get("value") or {}
    m = v.get("metrics") or {}
    decide_events.append({
        "iteration": v.get("iteration"),
        "decision": v.get("decision"),
        "last_iteration": bool(v.get("last_iteration")),
        "rule_ids": [str(r) for r in (v.get("rule_ids") or [])],
        "colorfulness_proxy": m.get("colorfulness_proxy"),
        "haze_proxy": m.get("haze_proxy"),
        "shadow_clip_ratio": m.get("shadow_clip_ratio"),
    })

print(json.dumps({
    "sample": NEF.name,
    "rules_count": len(rules),
    "state": result.state,
    "iteration": result.iteration,
    "params": result.params,
    "decide_events": decide_events,
    "rule_ids_by_iteration": by_iter,
    "union_rule_ids": union,
    "last_nonempty_rule_ids": last_nonempty,
    "old_last_event_rule_ids": decide_events[-1]["rule_ids"],
    "final_highlight_clip_ratio": (
        (result.final_measurement or {}).get("global") or {}
    ).get("highlight_clip_ratio"),
    "segmenter_last_degraded": list(getattr(segmenter, "last_degraded", []) or []),
}, ensure_ascii=False, default=str, indent=1))
