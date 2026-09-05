"""迭代轨迹回放调试工具 —— 按 photo_id 回放自动修图 Loop 的 trace 序列。

数据层: src/pixo/state/store.py (SQLiteStateTraceStore.trace_events /
photo_states, 只读复用)。评审建议"记录每次 Loop 的 {params, score,
mask_area, llm_suggestion} 序列, 提供调试工具回放修图过程"。

功能:
  1. 按 photo_id 查询 trace_events 全序列 (store.query_traces, id 升序);
  2. 逐事件解析为时间线 markdown —— 每事件一行: iter#、事件类型、
     param delta 摘要 (param_update 的 old→new)、score 变化 (decide.metrics
     的 mean_luminance / aesthetic / {name}_area_ratio 掩码面积)、LLM 建议
     (agent_suggest_accepted/rejected)、状态转移 (decide.decision /
     qc_rollback);
  3. ``--export-dir`` 可选: 语料 RAW 可达时逐参数快照重新渲染预览图落盘
     (复用 render_preview_full, 快照 = 各轮 decide.value.params 即渲染
     stage 参数嵌套桶) + 与 final 快照的 side-by-side 对照图序列。RAW 来源
     依次: --raw 参数 → photo_id 本身 (batch 分组键即 file_path) →
     meta_extracted 事件的 file_path 字段; 均不可达则跳过导出并说明。
  4. CLI: ``python scripts/loop_replay.py --photo-id X --db path
     [--export-dir Y] [--raw Z]``

事件词汇表 (写入方 src/pixo/pipeline/loop.py / batch.py / service/runtime.py):
  param_update / compose_params / decide / qc_rollback / meta_extracted /
  crop_suggest / crop_adopted / agent_suggest_{accepted,rejected,skipped,
  error} / aesthetic_score / agent_manual / batch_hard_filter / param_patch。

纯 scripts/ 工具: 只读 db, 不修改 src/, 不接运行时。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(_SCRIPTS), str(_SCRIPTS / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# score 变化展示的 metrics 键 (掩码面积 = {name}_area_ratio, 同步展示)
_SCORE_KEYS = ("mean_luminance", "aesthetic",
               "preview_highlight_clip_estimate", "highlight_clip_ratio")
_MAX_DELTA_ITEMS = 4          # param delta 摘要最多列几个参数
_MAX_REASON_LEN = 80

# 事件类型 → 时间线展示名 (未知类型原样展示)
EVENT_LABELS = {
    "param_update": "param",
    "compose_params": "compose",
    "decide": "decide",
    "qc_rollback": "qc_rollback",
    "meta_extracted": "meta",
    "crop_suggest": "crop_sugg",
    "crop_adopted": "crop",
    "agent_suggest_accepted": "llm_ok",
    "agent_suggest_rejected": "llm_rej",
    "agent_suggest_skipped": "llm_skip",
    "agent_suggest_error": "llm_err",
    "aesthetic_score": "score",
    "agent_manual": "manual",
    "batch_hard_filter": "hard_filter",
    "param_patch": "patch",
}


# ---------------------------------------------------------------------------
# 数据层 (只读)
# ---------------------------------------------------------------------------

def _open_store(db_path: str | Path):
    from pixo.state.store import SQLiteStateTraceStore
    return SQLiteStateTraceStore(str(db_path))


def load_events(db_path: str | Path, photo_id: str) -> list:
    """按 photo_id 查询 trace_events 全序列 (id 升序)。"""
    store = _open_store(db_path)
    try:
        return store.query_traces(photo_id)
    finally:
        store.close()


def load_final_state(db_path: str | Path, photo_id: str) -> dict | None:
    """photo_states 终态记录 (state/iteration/current_params/...)。"""
    store = _open_store(db_path)
    try:
        rec = store.load_state(photo_id)
        if rec is None:
            return None
        return {
            "state": rec.state,
            "iteration": rec.iteration,
            "current_params": rec.current_params,
            "last_measurement": rec.last_measurement,
            "next_action": rec.next_action,
            "agent_decision": rec.agent_decision,
            "qc_rollback_count": rec.qc_rollback_count,
            "updated_at": rec.updated_at,
        }
    finally:
        store.close()


def find_raw_path(events: list, photo_id: str,
                  override: str | None = None) -> str | None:
    """语料 RAW 路径推断: --raw 覆盖 → photo_id 本身 → meta_extracted 的
    file_path (batch 分组键 = meta.file_path)。返回存在的文件路径或 None。"""
    candidates: list[str] = []
    if override:
        candidates.append(override)
    candidates.append(photo_id)
    for ev in events:
        if ev.event_type == "meta_extracted":
            for payload in (ev.value, ev.metadata.get("meta")):
                if isinstance(payload, dict):
                    fp = payload.get("file_path") or payload.get("raw")
                    if fp:
                        candidates.append(str(fp))
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


# ---------------------------------------------------------------------------
# 事件解析 → 时间行
# ---------------------------------------------------------------------------

def _fmt_val(v: Any) -> str:
    """标量紧凑格式化 (bool/float/嵌套结构)。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False)
        return s if len(s) <= 40 else s[:37] + "..."
    return str(v)


def param_delta_summary(ev) -> str:
    """param_update 等事件 → "key: old → new" 逗号摘要 (单事件单参数)。"""
    if ev.param is not None:
        old, new = ev.old_value, ev.new_value
        if old is None and new is None:
            return _fmt_val(ev.value)
        return f"{ev.param}: {_fmt_val(old)} → {_fmt_val(new)}"
    return ""


def decide_delta_summary(prev_params: dict | None, cur_params: dict | None
                         ) -> str:
    """两轮参数快照的扁平 delta 摘要 (decide.value.params 嵌套桶, 一层拍平)。"""
    def _flat(p: dict | None) -> dict:
        out: dict = {}
        for k, v in (p or {}).items():
            if isinstance(v, dict):
                for kk, vv in v.items():
                    out[f"{k}.{kk}"] = vv
            else:
                out[k] = v
        return out
    a, b = _flat(prev_params), _flat(cur_params)
    diffs = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            diffs.append(f"{k}: {_fmt_val(a.get(k))} → {_fmt_val(b.get(k))}")
    return ", ".join(diffs[:_MAX_DELTA_ITEMS]) + (
        f" (+{len(diffs) - _MAX_DELTA_ITEMS} more)" if len(diffs) > _MAX_DELTA_ITEMS else "")


def score_summary(metrics: dict | None) -> str:
    """decide.metrics → score 摘要 (亮度/美学/高光裁切/掩码面积比)。"""
    if not isinstance(metrics, dict):
        return ""
    parts: list[str] = []
    for k in _SCORE_KEYS:
        if k in metrics and metrics[k] is not None:
            parts.append(f"{k}={_fmt_val(metrics[k])}")
    for k in sorted(metrics):
        if k.endswith("_area_ratio") and metrics[k] is not None:
            parts.append(f"{k}={_fmt_val(metrics[k])}")
    return " ".join(parts)


@dataclass
class StepRow:
    """时间线一行 (对应一条 trace 事件)。"""
    iteration: int
    event_type: str
    label: str
    delta: str = ""
    score: str = ""
    reason: str = ""
    timestamp: str = ""


def build_steps(events: list) -> list[StepRow]:
    """事件流 → 时间行 (含 decide 间参数快照 delta)。"""
    steps: list[StepRow] = []
    prev_params: dict | None = None
    for ev in events:
        label = EVENT_LABELS.get(ev.event_type, ev.event_type)
        delta, score = "", ""
        if ev.event_type == "param_update":
            delta = param_delta_summary(ev)
        elif ev.event_type == "decide":
            payload = ev.value if isinstance(ev.value, dict) else {}
            cur = payload.get("params")
            delta = decide_delta_summary(prev_params, cur)
            prev_params = cur if isinstance(cur, dict) else prev_params
            score = score_summary(payload.get("metrics"))
        elif ev.event_type == "aesthetic_score":
            delta = _fmt_val(ev.value)
        elif ev.event_type in ("agent_suggest_accepted", "agent_suggest_rejected"):
            meta = ev.metadata if isinstance(ev.metadata, dict) else {}
            names = meta.get("params")
            if names:
                delta = ",".join(str(x) for x in names[:_MAX_DELTA_ITEMS])
        elif ev.event_type == "qc_rollback":
            delta = param_delta_summary(ev)
        reason = (ev.reason or "").replace("|", "\\|").replace("\n", " ")
        if len(reason) > _MAX_REASON_LEN:
            reason = reason[:_MAX_REASON_LEN - 3] + "..."
        steps.append(StepRow(iteration=int(ev.iteration), event_type=ev.event_type,
                             label=label, delta=delta, score=score,
                             reason=reason, timestamp=ev.timestamp))
    return steps


def _md_cell(text: str) -> str:
    """markdown 表格单元格转义 (管道符会断列)。"""
    return text.replace("|", "\|")


def render_markdown(photo_id: str, steps: list[StepRow],
                    state: dict | None, raw_path: str | None,
                    exported: list[Path] | None = None,
                    export_note: str = "") -> str:
    """时间行 → markdown 报告。"""
    n_iters = len({s.iteration for s in steps})
    lines = [
        f"# 迭代轨迹回放: {photo_id}",
        "",
        f"- 事件 {len(steps)} 条 / 迭代 {n_iters} 轮"
        + (f" · RAW: `{raw_path}`" if raw_path else " · RAW: 不可达 (导出跳过)"),
    ]
    if state:
        lines.append(
            f"- 终态: **{state['state']}** iteration={state['iteration']} "
            f"qc_rollback={state['qc_rollback_count']} "
            f"next_action=`{state['next_action'] or '—'}` "
            f"updated={state['updated_at']}")
    if export_note:
        lines.append(f"- 导出: {export_note}")
    lines += [
        "",
        "## 时间线",
        "",
        "| iter | 事件 | param delta | score/metrics | 备注 |",
        "|---|---|---|---|---|",
    ]
    for s in steps:
        cells = [_md_cell(x) if x else "—" for x in
                 (s.delta, s.score, s.reason)]
        lines.append(f"| {s.iteration} | {_md_cell(s.label)} "
                     f"| {cells[0]} | {cells[1]} | {cells[2]} |")
    if state and state.get("current_params"):
        lines += [
            "",
            "## 最终参数快照 (photo_states.current_params)",
            "",
            "```json",
            json.dumps(state["current_params"], ensure_ascii=False, indent=1),
            "```",
        ]
    if exported:
        lines += ["", "## 重放渲染对照", ""]
        for p in exported:
            lines.append(f"- `{p}`")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# --export-dir: 参数快照重渲染 + side-by-side
# ---------------------------------------------------------------------------

def _snapshot_params(events: list, final_params: dict | None
                     ) -> list[tuple[str, dict]]:
    """decide.value.params 快照序列 (label, params); 末尾补 final 快照
    (photo_states.current_params, 若与最后快照不同)。"""
    out: list[tuple[str, dict]] = []
    seen: list[str] = []
    for ev in events:
        if ev.event_type == "decide" and isinstance(ev.value, dict) \
                and isinstance(ev.value.get("params"), dict) \
                and ev.value["params"]:
            label = f"iter{int(ev.iteration):02d}"
            if label not in seen:
                out.append((label, ev.value["params"]))
                seen.append(label)
    if final_params and final_params not in [p for _, p in out]:
        out.append(("final", final_params))
    return out


def _side_by_side(imgs: list, labels: list[str]) -> "np.ndarray":
    """横向拼接 + 顶部标签条 (调试对照图; 依赖 cv2/numpy)。"""
    import cv2
    import numpy as np
    bar_h = 24
    parts = []
    for img, lab in zip(imgs, labels):
        img = np.asarray(img)
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        h, w = img.shape[:2]
        bar = np.full((bar_h, w, 3), 255, dtype=np.uint8)
        cv2.putText(bar, lab, (4, bar_h - 7), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 1, cv2.LINE_AA)
        parts.append(np.vstack([bar, img]))
    h = max(p.shape[0] for p in parts)
    parts = [np.vstack([p, np.zeros((h - p.shape[0], p.shape[1], 3),
                                     dtype=np.uint8)]) for p in parts]
    return np.hstack(parts)


def export_previews(events: list, state: dict | None, raw_path: str,
                    export_dir: Path, long_edge: int = 512,
                    render_fn: Callable[[str, dict, int], Any] | None = None
                    ) -> tuple[list[Path], str]:
    """逐参数快照渲染预览 → export_dir/<stem>/iterNN.png + side_by_side.png。

    render_fn(raw_path, params, long_edge) -> BGR/RGB uint8 图 (可注入替身;
    CLI 缺省用 Renderer.render_preview_full)。
    """
    import cv2

    final_params = (state or {}).get("current_params")
    snaps = _snapshot_params(events, final_params)
    if not snaps:
        return [], "无参数快照 (trace 中无 decide.params), 跳过渲染"
    out_dir = export_dir / Path(raw_path).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    import numpy as np

    if render_fn is None:
        from pixo.render.api import Renderer

        renderer = Renderer(_DEFAULT_DCP_PATH)
        render_fn = lambda raw, params, edge: renderer.render_preview_full(  # noqa: E731
            raw, long_edge=edge, params=dict(params))

    exported: list[Path] = []
    imgs: list = []
    labels: list[str] = []
    for label, params in snaps:
        img = render_fn(raw_path, params, long_edge)
        img = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR) \
            if np.asarray(img).ndim == 3 else np.asarray(img)
        out = out_dir / f"{label}.png"
        cv2.imwrite(str(out), img)
        exported.append(out)
        imgs.append(img)
        labels.append(label)
    if len(imgs) >= 2:
        sbs = _side_by_side(imgs, labels)
        out = out_dir / "side_by_side.png"
        cv2.imwrite(str(out), sbs)
        exported.append(out)
    return exported, f"{len(snaps)} 个参数快照渲染 → {out_dir}"


_DEFAULT_DCP_PATH = str(
    _SCRIPTS.parent / "resources" / "dcp"
    / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--photo-id", required=True)
    ap.add_argument("--db", required=True, help="SQLite 状态库路径")
    ap.add_argument("--export-dir", default=None,
                    help="重渲染预览图导出目录 (可选; RAW 可达时生效)")
    ap.add_argument("--raw", default=None, help="语料 RAW 路径覆盖")
    ap.add_argument("--long-edge", type=int, default=512)
    ap.add_argument("--out", default=None, help="markdown 输出路径 (缺省打印)")
    args = ap.parse_args(argv)

    events = load_events(args.db, args.photo_id)
    if not events:
        print(f"无 trace 事件: photo_id={args.photo_id!r} db={args.db}",
              file=sys.stderr)
        return 2
    state = load_final_state(args.db, args.photo_id)
    steps = build_steps(events)

    exported: list[Path] = []
    export_note = ""
    if args.export_dir:
        raw = find_raw_path(events, args.photo_id, args.raw)
        if raw is None:
            export_note = "跳过 (RAW 不可达: --raw 未给且 photo_id/meta 无有效路径)"
        else:
            exported, export_note = export_previews(
                events, state, raw, Path(args.export_dir),
                long_edge=args.long_edge)

    md = render_markdown(args.photo_id, steps, state,
                         find_raw_path(events, args.photo_id, args.raw),
                         exported, export_note)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"-> {out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
