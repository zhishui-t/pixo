"""R21 D1 证据探针：固定 3 样本的真 RAW 闭环实测。

用途（design §7 D1 队长追证）：给出 `DSC_5236/5237/5238.NEF`（字典序前 3）
的实测 `colorfulness_proxy`（measurement **顶层**，规则引擎同层可见）与
`rule_ids`（最后一条 `event_type=="decide"` 的 `value["rule_ids"]`），供队长
判断 `saturation_high_rule`（阈值 6.13）的 1% 余量是否真实。

装配与 F05 门禁完全一致（真路由 MultiModelSegmenter、装配层 11 条规则、
manual_on_unreliable=False、preview_long_edge=1024、max_iterations=2）；
**不设** PIXO_ALLOW_RESTRICTED；离线（HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE）。

运行：`python .agent-team/tmp-r21-d1-probe.py`（只读，不落仓库产物）
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(r"K:\work\project\pixo")
RAW_DIR = Path(r"K:\data\photo\0711\raw")
SAMPLES = ["DSC_5236.NEF", "DSC_5237.NEF", "DSC_5238.NEF"]
MAX_ITER = 2

sys.path.insert(0, str(REPO / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.pop("PIXO_ALLOW_RESTRICTED", None)
os.environ.pop("PIXO_RULES", None)

from pixo.pipeline.loop import RawRenderBackend, SinglePhotoLoop  # noqa: E402
from pixo.render.core.calibration import load_dcp  # noqa: E402
from pixo.service.runtime import _load_auto_loop_rules  # noqa: E402
from pixo.vision.segmenters.multi_router import MultiModelSegmenter  # noqa: E402

_DCP = (REPO / "resources" / "dcp"
        / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")


def last_decide(result) -> dict:
    found: dict = {}
    for ev in result.trace_events or []:
        if isinstance(ev, dict) and ev.get("event_type") == "decide":
            v = ev.get("value")
            if isinstance(v, dict):
                found = v
    return found


def all_decide_events(result) -> list[dict]:
    """逐条 decide 事件摘要（诊断「最后一条 rule_ids 为空」的根因）。"""
    out: list[dict] = []
    for ev in result.trace_events or []:
        if not isinstance(ev, dict) or ev.get("event_type") != "decide":
            continue
        v = ev.get("value") or {}
        m = v.get("metrics") or {}
        out.append({
            "iteration": v.get("iteration"),
            "decision": v.get("decision"),
            "rule_ids": list(v.get("rule_ids") or []),
            "last_iteration": bool(v.get("last_iteration")),
            "params": v.get("params"),
            "colorfulness_proxy": m.get("colorfulness_proxy"),
            "haze_proxy": m.get("haze_proxy"),
        })
    return out


def main() -> int:
    prof = load_dcp(_DCP)
    rules = _load_auto_loop_rules(("face", "sky", "plant"))
    print(json.dumps({"rules_count": len(rules),
                      "rules_ids": [r.get("id") for r in rules]},
                     ensure_ascii=False), flush=True)

    for name in SAMPLES:
        raw = RAW_DIR / name
        if not raw.exists():
            print(json.dumps({"sample": name, "error": "NEF 不存在"},
                             ensure_ascii=False), flush=True)
            continue
        seg = MultiModelSegmenter()
        backend = RawRenderBackend(raw, prof)
        loop = SinglePhotoLoop(
            render_backend=backend,
            segmenter=seg,
            rules=rules,
            preview_long_edge=1024,
            max_iterations=MAX_ITER,
            prompts=["face", "sky", "plant"],
            manual_on_unreliable=False,
        )
        t0 = time.monotonic()
        res = loop.run(name, raw_path=str(raw), max_iterations=MAX_ITER)
        dur = round(time.monotonic() - t0, 2)

        dec = last_decide(res)
        preview_metrics = res.measurements[-1] if res.measurements else {}
        final_metrics = res.final_measurement or {}
        # 掩码非零像素（区域规则可达性）
        masks_nz = {}
        try:
            img = backend.render_preview({}, long_edge=1024)
            m = seg.segment(img, ["face", "sky", "plant"])
            masks_nz = {k: int((v > 0).sum()) for k, v in (m or {}).items()}
        except Exception as exc:  # noqa: BLE001
            masks_nz = {"error": f"{type(exc).__name__}: {exc}"}

        rec = {
            "sample": name,
            "duration_s": dur,
            "state": res.state,
            "reason": res.reason,
            "iteration": res.iteration,
            "measurements": len(res.measurements or []),
            "colorfulness_proxy_preview_top": preview_metrics.get(
                "colorfulness_proxy"),
            "colorfulness_proxy_final_top": final_metrics.get(
                "colorfulness_proxy"),
            "haze_proxy_preview_top": preview_metrics.get("haze_proxy"),
            "tonal_range_preview_top": preview_metrics.get("tonal_range"),
            "global_preview": (preview_metrics.get("global") or {}),
            "rule_ids": list(dec.get("rule_ids") or []),
            "rule_ids_last_nonempty": next(
                (list(e["rule_ids"]) for e in reversed(all_decide_events(res))
                 if e["rule_ids"]), []),
            "decide_events": all_decide_events(res),
            "preview_colorfulness_all": [
                (m or {}).get("colorfulness_proxy") for m in res.measurements
            ],
            "decide_params": dec.get("params"),
            "result_params": res.params,
            "final_highlight_clip_ratio": (
                (final_metrics.get("global") or {}).get("highlight_clip_ratio")),
            "mask_nonzero_px": masks_nz,
            "segmenter_last_degraded": list(
                getattr(seg, "last_degraded", []) or []),
        }
        print(json.dumps(rec, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
