"""R20: style_cards 默认开否 —— 54 张语料双臂 loop 评估 (tech_debt R13 后续)。

双臂 (单变量):
  A = enable_style_cards=False (现状默认, R13 裁决)
  B = enable_style_cards=True (拟评估的默认开)
其余全部生产缺省: DEFAULT_RULES (含 region_rules)、prompts 缺省、max_iterations=3、
compose 4:3、preview 512、segmenter=MultiModelSegmenter。

量测:
  - QC 迁移表: qc_class(A) × qc_class(B) (pass/escalate_1x/escalate_2x/...)
    + state (ACCEPTED/MANUAL_REVIEW/REJECTED) + qc_rollback_count;
  - ΔE2000(A_final, B_final) + changed_ratio (卡建议的实际影响面);
  - trace: style_card 规则触发率 (规则 id 前缀 = 6 张 builtin 卡 style_id)、
    条件指标值 (highlight_clip_ratio 等)、decided 参数落位;
  - 提前压光检测 (R13 现象语料级频率): B 中 style_card exposure 决定 ≤ −0.05
    且当轮溢出 ≥0.03 且其后溢出 <0.03 → masked_overflow 事件 (QC 证据被卡提前
    消除), 并对照 A 臂同照片的 QC 终态。
增量 checkpoint: 逐样本重写 OUT_JSON (中断保留已完成样本)。

用法: python .artifacts/style_cards_trial54.py [--limit N]
产出: .artifacts/style_cards_trial_54.json (机读) —— md 人工成文。
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from fit_rp_ccm import iter_corpus  # noqa: E402
from pixo.decide.rules import DEFAULT_RULES  # noqa: E402
from pixo.pipeline.loop import SinglePhotoLoop  # noqa: E402
from pixo.pipeline.perceptual import (  # noqa: E402
    delta_e_2000,
    gamma_srgb_to_linear,
    linear_srgb_to_lab,
)
from pixo.render.core.calibration import load_dcp  # noqa: E402
from pixo.vision.segmenters.multi_router import MultiModelSegmenter  # noqa: E402

DCP = str(ROOT / "resources" / "dcp"
          / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")
CORPUS = "exports/auto/full_scan"
OUT_JSON = ROOT / ".artifacts" / "style_cards_trial_54.json"
COMPOSE = {"mode": "ratio", "ratio": "4:3", "center": [0.5, 0.5],
           "rotation": 0.0, "horizontal_flip": False, "vertical_flip": False}
STYLE_IDS = ("kodak_portra_400", "fuji_pro_400h", "hasselblad_ncs",
             "cinestill_800t", "kodak_trix_400", "ilford_hp5_plus")


def qc_class(reason: str) -> str:
    if "二次超标" in reason:
        return "escalate_2x"
    if "FINAL_QC 转人工" in reason:
        return "escalate_1x"
    if "分割模型不可用" in reason:
        return "segmenter_unavailable"
    if "Decide/分割异常" in reason:
        return "segment_error"
    if "FINAL_QC 达标" in reason:
        return "pass"
    return "other"


def de_stats(a, b) -> dict:
    if a is None or b is None or a.shape != b.shape:
        return {"error": True}
    de = delta_e_2000(
        linear_srgb_to_lab(gamma_srgb_to_linear(a.astype(np.float64) / 255.0)),
        linear_srgb_to_lab(gamma_srgb_to_linear(b.astype(np.float64) / 255.0)))
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return {"de_mean": round(float(de.mean()), 4),
            "de_p95": round(float(np.percentile(de, 95)), 4),
            "changed_ratio": round(float((d >= 1).mean()), 4)}


def style_fires(result) -> list[dict]:
    """B 臂 trace → style_card 规则触发事件 (含条件指标与参数落位)。"""
    out = []
    for ev in result.trace_events or []:
        if ev.get("event_type") != "decide":
            continue
        v = ev.get("value") or {}
        rule_ids = list(v.get("rule_ids") or [])
        hits = [rid for rid in rule_ids if any(str(rid).startswith(s) for s in STYLE_IDS)]
        if not hits:
            continue
        m = v.get("metrics") or {}
        params = v.get("params") or {}
        out.append({
            "iteration": v.get("iteration"),
            "rule_ids": hits,
            "highlight_clip_ratio": m.get("highlight_clip_ratio"),
            "preview_highlight_clip_ratio": m.get("preview_highlight_clip_ratio"),
            "contrast": m.get("contrast"),
            "overflow": m.get("preview_overflow_ratio"),
            "decided_exposure": (params.get("exposure")
                                 if isinstance(params.get("exposure"), (int, float))
                                 else None),
            "decided_keys": sorted(k for k in params.keys()) if isinstance(params, dict) else [],
        })
    return out


def clip_trajectory(result) -> list[dict]:
    """逐轮溢出/裁剪指标轨迹 (提前压光检测用)。"""
    out = []
    for ev in result.trace_events or []:
        if ev.get("event_type") != "decide":
            continue
        v = ev.get("value") or {}
        m = v.get("metrics") or {}
        out.append({
            "iteration": v.get("iteration"),
            "highlight_clip_ratio": m.get("highlight_clip_ratio"),
            "preview_highlight_clip_ratio": m.get("preview_highlight_clip_ratio"),
            "overflow": m.get("preview_overflow_ratio"),
        })
    return out


def analyse(name: str, res_a, res_b, elapsed_s: float) -> dict:
    fires = style_fires(res_b)
    traj_a, traj_b = clip_trajectory(res_a), clip_trajectory(res_b)
    # 提前压光: style exposure 决定 ≤ −0.05 + 当轮溢出≥0.03 + 其后某轮溢出 <0.03
    masked = []
    for f in fires:
        dec = f.get("decided_exposure")
        ovf = f.get("overflow")
        if dec is None or dec > -0.05:
            continue
        if ovf is None or ovf < 0.03:
            continue
        later = [t for t in traj_b
                 if (t.get("iteration") or 0) > (f.get("iteration") or 0)
                 and (t.get("overflow") is not None and t["overflow"] < 0.03)]
        if later:
            masked.append({"iteration": f["iteration"], "decided_exposure": dec,
                           "overflow_at_decision": ovf,
                           "overflow_after": later[0]["overflow"]})
    return {
        "sample": name,
        "a_qc": qc_class(res_a.reason), "b_qc": qc_class(res_b.reason),
        "a_state": res_a.state, "b_state": res_b.state,
        "a_reason": res_a.reason, "b_reason": res_b.reason,
        "a_rollbacks": res_a.qc_rollback_count,
        "b_rollbacks": res_b.qc_rollback_count,
        "a_iterations": res_a.iteration, "b_iterations": res_b.iteration,
        "ab_compare": de_stats(res_a.final_image, res_b.final_image),
        "n_style_fires": len(fires), "style_fires": fires,
        "masked_overflow": masked,
        "a_clip_traj": traj_a, "b_clip_traj": traj_b,
        "final_params_b": (res_b.params or {}).get("exposure"),
        "final_params_a": (res_a.params or {}).get("exposure"),
        "elapsed_s": round(elapsed_s, 1),
    }


def main(argv=None) -> int:
    limit = 0
    if "--limit" in (argv or sys.argv[1:]):
        limit = int((argv or sys.argv[1:])[(argv or sys.argv[1:]).index(
            "--limit") + 1])
    items = iter_corpus(CORPUS, None, limit)
    done: dict = {}
    if OUT_JSON.exists():
        try:
            done = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("runs") or {}
        except Exception:
            done = {}
    pending = [(n, r) for n, r in items
               if n not in done or done[n].get("error")]
    print(f"[r20] 语料 {len(items)} 张; checkpoint {len(done)}, 待跑 {len(pending)}; "
          f"预估 ~50s/样本 ≈ {len(pending) * 50 / 60:.0f} min", flush=True)
    seg = MultiModelSegmenter()
    prof = load_dcp(DCP)
    out = {"corpus": CORPUS, "n_samples": len(items),
           "arms": {"a": "enable_style_cards=False (现状默认)",
                    "b": "enable_style_cards=True"},
           "rules": "DEFAULT_RULES (生产默认, 含 region_rules)",
           "runs": {**done}}
    t_start = time.time()
    for i, (name, raw) in enumerate(pending, 1):
        t0 = time.time()
        entry: dict = {"sample": name, "error": None}
        try:
            runs = {}
            for track, flag in (("a", False), ("b", True)):
                loop = SinglePhotoLoop(
                    prof=prof, segmenter=seg, rules=list(DEFAULT_RULES),
                    max_iterations=3, preview_long_edge=512,
                    manual_on_unreliable=False,
                    enable_style_cards=flag)
                runs[track] = loop.run(f"r20_{track}_{name}",
                                       raw_path=Path(raw),
                                       compose_params=dict(COMPOSE))
            entry = analyse(name, runs["a"], runs["b"], time.time() - t0)
        except Exception as exc:  # noqa: BLE001 - 单样本失败不断全量
            entry = {"sample": name, "error": f"{type(exc).__name__}: {exc}"}
            print(f"[r20] {i}/{len(pending)} {name} ERROR: {entry['error']}",
                  flush=True)
        entry["elapsed_s"] = round(time.time() - t0, 1)
        out["runs"][name] = entry
        OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        b_qc = entry.get("b_qc", "?")
        print(f"[r20] {i}/{len(pending)} {name} A={entry.get('a_qc')} "
              f"B={b_qc} ΔE={entry.get('ab_compare', {}).get('de_mean')} "
              f"fires={entry.get('n_style_fires')} "
              f"({time.time() - t_start:.0f}s)", flush=True)
    print(f"[r20] DONE 全量 {len(out['runs'])} 样本, 总耗时 "
          f"{(time.time() - t_start) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
