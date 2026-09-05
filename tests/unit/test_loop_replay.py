"""loop_replay.py 单测 —— 合成 trace 序列回放输出格式正确 (阶段三评审项)。

用 SQLiteStateTraceStore (:memory:) 写入合成事件序列 (覆盖 param_update /
decide / aesthetic_score / agent_suggest_accepted / qc_rollback /
meta_extracted 词汇), 断言:
  - 查询/解析: 事件条数、iter 分组、param delta 摘要、score/metrics 摘要
    (含 {name}_area_ratio 掩码面积)、LLM 建议参数列表;
  - markdown: 每步一行表 (iter#/事件/delta/score/备注)、终态行、最终参数
    快照段;
  - --export-dir: 假渲染后端注入, 逐参数快照落盘 + side_by_side;
  - RAW 推断: photo_id 即路径 / meta_extracted.file_path / 不可达跳过。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO / "scripts"), str(_REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

loop_replay = importlib.import_module("loop_replay")

from pixo.state.store import SQLiteStateTraceStore  # noqa: E402
from pixo.state.machine import StateRecord  # noqa: E402

PID = "K:/data/photo/raw/DSC_0001.NEF"


def _seed_db(tmp_path: Path, **overrides) -> Path:
    """合成一次 Loop 的 trace 序列 (与 loop.py 写入口径同构)。"""
    db = tmp_path / "state.db"
    store = SQLiteStateTraceStore(str(db))
    t = "2026-09-04T10:00:00"

    def add(**kw):
        store.add_trace(photo_id=PID, timestamp=t, source="single_photo_loop",
                        **kw)

    add(event_type="meta_extracted", reason="Pixo Meta 提取完成",
        value={"file_path": PID, "camera": {"model": "NIKON Z5_2"}},
        metadata={"meta": {"file_path": PID}})
    add(event_type="compose_params", reason="构图参数确定", value={"mode": "free"})
    add(event_type="param_update", param="exposure_ev", reason="Decide 参数更新",
        value=0.3, old_value=0.0, new_value=0.3, iteration=1,
        metadata={"iteration": 1, "rule_ids": ["underexpose"]})
    add(event_type="decide", reason="欠曝提亮", iteration=1,
        value={"iteration": 1, "decision": "CONTINUE", "reasons": ["underexpose"],
               "rule_ids": ["underexpose"],
               "params": {"exposure": {"mode": "auto", "target_offset": 0.3},
                          "whitebalance": {"trim": [1, 1, 1]}},
               "metrics": {"mean_luminance": 0.38, "aesthetic": 3.1,
                           "subject_area_ratio": 0.21,
                           "preview_highlight_clip_estimate": 0.004}})
    add(event_type="aesthetic_score", reason="美学评分", value=3.1, iteration=1)
    add(event_type="agent_suggest_accepted", reason="2 个补丁入建议态",
        iteration=1, metadata={"params": ["whitesaturation", "tone"],
                               "patches": [{"param": "whitesaturation"}]})
    add(event_type="param_update", param="whitesaturation",
        reason="LLM 建议采纳", value=1.15, old_value=1.0, new_value=1.15,
        iteration=2)
    add(event_type="decide", reason="收敛", iteration=2,
        value={"iteration": 2, "decision": "CONVERGED", "reasons": ["ok"],
               "rule_ids": [],
               "params": {"exposure": {"mode": "auto", "target_offset": 0.3},
                          "whitebalance": {"trim": [1, 1, 1]},
                          "huesat": {"whitesaturation": 1.15}},
               "metrics": {"mean_luminance": 0.51, "aesthetic": 3.6,
                           "subject_area_ratio": 0.21,
                           "preview_highlight_clip_estimate": 0.011}})
    add(event_type="qc_rollback", reason="FINAL_QC 高光超标回退", param="Exposure",
        old_value=0.3, new_value=0.2, iteration=3,
        metadata={"qc_overflow_ratio": 0.031})
    store.save_state(StateRecord(
        photo_id=PID, state="QC_ROLLED_BACK", iteration=3,
        current_params={"exposure": {"mode": "auto", "target_offset": 0.2}},
        last_measurement={"mean_luminance": 0.49}, rule_hits=[],
        next_action="", agent_decision="", qc_rollback_count=1,
        updated_at=t))
    store.close()
    return db


@pytest.fixture()
def db(tmp_path):
    return _seed_db(tmp_path)


# ---------------------------------------------------------------------------
# 查询 / 解析
# ---------------------------------------------------------------------------

class TestLoadAndParse:
    def test_load_events_ordered(self, db):
        events = loop_replay.load_events(db, PID)
        assert len(events) == 9
        assert [e.iteration for e in events] == sorted(
            e.iteration for e in events)

    def test_build_steps_param_delta(self, db):
        steps = loop_replay.build_steps(loop_replay.load_events(db, PID))
        upd = [s for s in steps if s.event_type == "param_update"]
        assert "exposure_ev: 0 → 0.3" in upd[0].delta
        assert "whitesaturation: 1 → 1.15" in upd[1].delta

    def test_build_steps_decide_snapshot_delta_and_score(self, db):
        steps = loop_replay.build_steps(loop_replay.load_events(db, PID))
        dec = [s for s in steps if s.event_type == "decide"]
        # 首个 decide: 无前快照 → delta 为空; score 摘要含掩码面积/亮度
        assert "mean_luminance=0.38" in dec[0].score
        assert "subject_area_ratio=0.21" in dec[0].score
        assert "aesthetic=3.1" in dec[0].score
        # 第二个 decide: 与前快照的 delta (一层拍平)
        assert "exposure.target_offset: 0.3 → 0.3" not in dec[1].delta
        assert "huesat.whitesaturation: None → 1.15" in dec[1].delta
        assert "mean_luminance=0.51" in dec[1].score

    def test_build_steps_llm_suggestion_params(self, db):
        steps = loop_replay.build_steps(loop_replay.load_events(db, PID))
        llm = [s for s in steps if s.event_type == "agent_suggest_accepted"]
        assert "whitesaturation" in llm[0].delta and "tone" in llm[0].delta

    def test_build_steps_qc_rollback_delta(self, db):
        steps = loop_replay.build_steps(loop_replay.load_events(db, PID))
        qc = [s for s in steps if s.event_type == "qc_rollback"]
        assert "Exposure: 0.3 → 0.2" == qc[0].delta

    def test_load_final_state(self, db):
        st = loop_replay.load_final_state(db, PID)
        assert st["state"] == "QC_ROLLED_BACK"
        assert st["iteration"] == 3
        assert st["current_params"]["exposure"]["target_offset"] == 0.2

    def test_empty_db_returns_exit_code(self, tmp_path, capsys):
        empty = tmp_path / "empty.db"
        SQLiteStateTraceStore(str(empty)).close()
        assert loop_replay.main(["--photo-id", "x", "--db", str(empty)]) == 2


# ---------------------------------------------------------------------------
# markdown 渲染
# ---------------------------------------------------------------------------

class TestMarkdown:
    def test_markdown_timeline_format(self, db):
        events = loop_replay.load_events(db, PID)
        steps = loop_replay.build_steps(events)
        md = loop_replay.render_markdown(
            PID, steps, loop_replay.load_final_state(db, PID), PID)
        assert md.startswith(f"# 迭代轨迹回放: {PID}")
        assert "| iter | 事件 | param delta | score/metrics | 备注 |" in md
        assert "| 1 | param | exposure_ev: 0 → 0.3 | — | Decide 参数更新 |" in md
        assert "终态: **QC_ROLLED_BACK**" in md
        assert "## 最终参数快照" in md and '"target_offset": 0.2' in md
        # 每步一行: 时间线表行数 = 表头 + 事件数 (分隔行 |---| 不计)
        body = [l for l in md.splitlines() if l.startswith("| ")]
        assert len(body) == len(steps) + 1

    def test_markdown_reason_pipe_escaped(self):
        steps = [loop_replay.StepRow(iteration=1, event_type="decide",
                                     label="decide", reason="a|b|c")]
        md = loop_replay.render_markdown("p", steps, None, None)
        assert "a\\|b\\|c" in md


# ---------------------------------------------------------------------------
# RAW 推断
# ---------------------------------------------------------------------------

class TestRawPath:
    def test_override_wins(self, db, tmp_path):
        fake = tmp_path / "r.NEF"
        fake.write_bytes(b"x")
        assert loop_replay.find_raw_path(
            loop_replay.load_events(db, PID), PID, str(fake)) == str(fake)

    def test_meta_file_path_fallback(self, tmp_path):
        raw = tmp_path / "DSC_x.NEF"
        raw.write_bytes(b"x")
        pid = "unrelated_id"
        store = SQLiteStateTraceStore(str(tmp_path / "m.db"))
        store.add_trace(photo_id=pid, timestamp="t", event_type="meta_extracted",
                        value={"file_path": str(raw)})
        store.close()
        assert loop_replay.find_raw_path(
            loop_replay.load_events(tmp_path / "m.db", pid), pid) == str(raw)

    def test_unreachable_returns_none(self, db):
        assert loop_replay.find_raw_path(
            loop_replay.load_events(db, PID), "no/such/file.NEF") is None


# ---------------------------------------------------------------------------
# --export-dir: 假渲染后端导出 (不依赖真实 RAW 解码)
# ---------------------------------------------------------------------------

class TestExport:
    def test_export_previews_with_fake_backend(self, db, tmp_path):
        events = loop_replay.load_events(db, PID)
        state = loop_replay.load_final_state(db, PID)
        calls: list[tuple[str, dict, int]] = []

        def fake_render(raw, params, edge):
            calls.append((raw, params, edge))
            return np.zeros((16, 24, 3), dtype=np.uint8)

        out_dir = tmp_path / "exp"
        exported, note = loop_replay.export_previews(
            events, state, PID, out_dir, long_edge=512,
            render_fn=fake_render)
        # 快照 = 2 个 decide.params + final (current_params 与快照不同)
        assert len(calls) == 3
        assert calls[0][1]["exposure"]["target_offset"] == 0.3
        assert calls[1][1]["huesat"]["whitesaturation"] == 1.15
        assert calls[2][1]["exposure"]["target_offset"] == 0.2
        names = [p.name for p in exported]
        assert names[0] == "iter01.png" and names[1] == "iter02.png"
        assert "final.png" in names and "side_by_side.png" in names
        assert all(p.is_file() for p in exported)
        assert "3 个参数快照渲染" in note

    def test_export_skips_without_snapshots(self, tmp_path):
        db = tmp_path / "n.db"
        store = SQLiteStateTraceStore(str(db))
        store.add_trace(photo_id="p", timestamp="t", event_type="meta_extracted")
        store.close()
        exported, note = loop_replay.export_previews(
            loop_replay.load_events(db, "p"), None, "p.NEF", tmp_path / "e",
            render_fn=lambda *a: np.zeros((4, 4, 3), dtype=np.uint8))
        assert exported == [] and "无参数快照" in note

    def test_snapshot_dedup(self, db):
        events = loop_replay.load_events(db, PID)
        state = loop_replay.load_final_state(db, PID)
        snaps = loop_replay._snapshot_params(events, state["current_params"])
        labels = [s[0] for s in snaps]
        assert len(labels) == len(set(labels))
        assert snaps[-1][0] == "final"


# ---------------------------------------------------------------------------
# CLI (合成 db 全链路)
# ---------------------------------------------------------------------------

class TestCli:
    def test_cli_stdout(self, db, capsys):
        rc = loop_replay.main(["--photo-id", PID, "--db", str(db)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "迭代轨迹回放" in out and "param_update" in out or "param" in out

    def test_cli_writes_file(self, db, tmp_path, capsys):
        out_md = tmp_path / "replay.md"
        rc = loop_replay.main(["--photo-id", PID, "--db", str(db),
                               "--out", str(out_md)])
        assert rc == 0
        assert out_md.is_file()
        assert "时间线" in out_md.read_text(encoding="utf-8")
