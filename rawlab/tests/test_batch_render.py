"""T4.2 batch_render 批量渲染 (新 Pipeline) 单元测试。

全部用 tmp_path + monkeypatch, 不跑真实 NEF。覆盖: discover 排序/过滤/limit、
output 命名、resume 跳过已存在、失败记 failed 且继续、cfg/half_size 传给
pipeline_from_config、零文件返回空、CLI 分支存在。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rawlab.tools import batch_render


def _write_raw(files, names):
    """写伪 RAW 文件 (非真实格式, 仅测 discover/output 逻辑)。"""
    out = []
    for n in names:
        p = files / n
        p.write_bytes(b"DUMMY-RAW-BYTES")
        out.append(Path(p))
    return out


def test_discover_sorted_filtered():
    d = pytest # placeholder ref
    import tempfile, os
    tmp = Path(tempfile.mkdtemp())
    try:
        _write_raw(tmp, ["b.NEF", "a.dng", "C.DNG", "note.txt"])
        files = batch_render.discover_raw_files(tmp)
        # 只认 4 种 raw 后缀、去重、按绝对路径排序 (b.NEF 在前? 排序按 resolve 路径)
        assert len(files) == 3
        assert all(f.suffix.lower() in (".nef", ".dng") for f in files)
        assert files == sorted(files)
        # 不与 .txt 混淆
        assert all(f.suffix != ".txt" for f in files)
    finally:
        import shutil; shutil.rmtree(tmp)


def test_discover_limit():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        _write_raw(tmp, [f"{i}.NEF" for i in range(5)])
        files = batch_render.discover_raw_files(tmp, limit=2)
        assert len(files) == 2
    finally:
        import shutil; shutil.rmtree(tmp)


def test_output_path_for_naming(tmp_path):
    raw = tmp_path / "DSC_5607.NEF"
    out = batch_render.output_path_for(raw, tmp_path / "outdir")
    assert out.name == "DSC_5607_rawlux.jpg"
    assert out.parent == tmp_path / "outdir"      # 自建输出目录, 同名保序
    # 自定义后缀/扩展名
    out2 = batch_render.output_path_for(raw, tmp_path / "o", suffix="_x", ext="tif")
    assert out2.name == "DSC_5607_x.tif"


class _FakePipe:
    """伪造 Pipeline: 记录 run_file 调用的 half_size, 可选抛错。"""
    def __init__(self, record: list, fail_for=None):
        self.record = record
        self.fail_for = set(fail_for or [])
    def run_file(self, raw_path, half_size=False):
        self.record.append((Path(raw_path).name, half_size))
        stem = Path(raw_path).stem
        if stem in self.fail_for:
            raise RuntimeError(f"boom {stem}")
        return np.zeros((16, 16, 3), dtype=np.uint8)


def test_resume_skips_existing(monkeypatch, tmp_path):
    raws = _write_raw(tmp_path, ["a.NEF", "b.NEF"])
    out_dir = tmp_path / "out"; out_dir.mkdir()
    # 预写 a 的输出 (非零字节) → resume 应跳过 a
    predone = batch_render.output_path_for(raws[0], out_dir)
    predone.write_bytes(b"EXISTING")
    record = []
    monkeypatch.setattr(batch_render, "pipeline_from_config",
                        lambda cfg, prof=None: _FakePipe(record))
    results = batch_render.render_batch(raws, out_dir, cfg={}, half_size=True)
    assert results["a"] == "skipped"
    assert results["b"] == "rendered"
    # a 未重新渲染 (run_file 只被 b 调用)
    assert [n for n, _ in record] == ["b.NEF"]


def test_failed_recorded_and_continue(monkeypatch, tmp_path):
    raws = _write_raw(tmp_path, ["bad.NEF", "good.NEF", "ok.NEF"])
    out_dir = tmp_path / "out"
    record = []
    monkeypatch.setattr(batch_render, "pipeline_from_config",
                        lambda cfg, prof=None: _FakePipe(record, fail_for=["bad"]))
    results = batch_render.render_batch(raws, out_dir, cfg={})
    assert results["bad"] == "failed"
    assert results["good"] == "rendered"
    assert results["ok"] == "rendered"


def test_cfg_passed_to_pipeline_from_config(monkeypatch, tmp_path):
    raws = _write_raw(tmp_path, ["a.NEF"])
    out_dir = tmp_path / "out"
    seen = {}
    def fake_pf(cfg, prof=None):
        seen["cfg"] = cfg; seen["prof"] = prof
        return _FakePipe([])
    monkeypatch.setattr(batch_render, "pipeline_from_config", fake_pf)
    cfg = {"stages": ["exposure", "tone"], "params": {"tone": {"contrast": 0.2}}}
    prof = object()
    batch_render.render_batch(raws, out_dir, cfg=cfg, prof=prof)
    assert seen["cfg"] is cfg
    assert seen["prof"] is prof


def test_half_size_passed(monkeypatch, tmp_path):
    raws = _write_raw(tmp_path, ["a.NEF"])
    record = []
    monkeypatch.setattr(batch_render, "pipeline_from_config",
                        lambda cfg, prof=None: _FakePipe(record))
    batch_render.render_batch(raws, tmp_path / "out", cfg={}, half_size=False)
    assert record == [("a.NEF", False)]
    batch_render.render_batch(raws, tmp_path / "out2", cfg={}, half_size=True)
    assert record[-1] == ("a.NEF", True)


def test_zero_files_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(batch_render, "pipeline_from_config",
                        lambda cfg, prof=None: _FakePipe([]))
    res = batch_render.render_batch([], tmp_path / "out", cfg={})
    assert res == {}


def test_no_resume_overwrites(monkeypatch, tmp_path):
    raws = _write_raw(tmp_path, ["a.NEF"])
    out_dir = tmp_path / "out"
    predone = batch_render.output_path_for(raws[0], out_dir)
    predone.write_bytes(b"OLD")
    record = []
    monkeypatch.setattr(batch_render, "pipeline_from_config",
                        lambda cfg, prof=None: _FakePipe(record))
    batch_render.render_batch(raws, out_dir, cfg={}, resume=False)
    assert record == [("a.NEF", True)]   # resume=False → 重渲染


def test_cli_branch_exists():
    """build_parser 应有 batch-pipeline 子命令 (可解出 cmd)。"""
    import rawlab.rawlab_cli as cli
    ap = cli.build_parser()
    assert "batch-pipeline" in ap._subparsers._actions[-1].choices
    args = ap.parse_args(["batch-pipeline", str(Path("/tmp/x")), "--limit", "3",
                          "--half-size", "--no-resume"])
    assert args.cmd == "batch-pipeline"
    assert args.limit == 3
    assert args.half_size is True
    assert args.no_resume is True
