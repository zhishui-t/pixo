"""T32: 最终全质量 export 层测试。

覆盖：
- submit 返回 task_id，wait 后 completed 且产物文件存在
- 16-bit 格式强制 16-bit 渲染并写出 PNG-16
- 渲染异常时任务进入 failed 并带 error
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from pixo.render.web import export as export_mod
from pixo.render.web.export import ExportManager


class _FakeProf:
    path = "fake.dcp"


class _FakeSession:
    def __init__(self, raw_path="x.nef", session_id="sess1"):
        self.raw_path = Path(raw_path)
        self.session_id = session_id
        self.prof = _FakeProf()

    def canonical_params(self):
        return {"exposure": {"mode": 0.0}, "tone": {"eotf": "srgb"}}


@pytest.fixture()
def manager(tmp_path):
    m = ExportManager(_FakeProf(), work_dir=tmp_path / "exports", max_workers=2)
    yield m
    m.shutdown()


def test_export_tiff16_completed(manager, tmp_path, monkeypatch):
    captured = {}

    def fake_render(raw_path, prof, params, output_bps=8):
        captured["output_bps"] = output_bps
        arr = np.zeros((8, 8, 3), dtype=np.uint16)
        arr[..., 0] = 1000
        arr[..., 1] = 2000
        arr[..., 2] = 3000
        return arr

    monkeypatch.setattr(export_mod, "_render_full_quality", fake_render)
    task_id = manager.submit(_FakeSession(), fmt="tiff16")
    st = manager.wait(task_id, timeout=10)
    assert st["status"] == "completed"
    assert captured["output_bps"] == 16
    assert st["output_path"] and Path(st["output_path"]).exists()
    data = Path(st["output_path"]).read_bytes()
    assert len(data) > 0


def test_export_jpeg_uses_8bit(manager, monkeypatch):
    captured = {}

    def fake_render(raw_path, prof, params, output_bps=8):
        captured["output_bps"] = output_bps
        return (np.zeros((4, 4, 3), dtype=np.float32) + 0.5)

    monkeypatch.setattr(export_mod, "_render_full_quality", fake_render)
    task_id = manager.submit(_FakeSession(), fmt="jpeg", quality=90)
    st = manager.wait(task_id, timeout=10)
    assert st["status"] == "completed"
    assert captured["output_bps"] == 8
    assert Path(st["output_path"]).suffix == ".jpg"


def test_export_failure_records_error(manager, monkeypatch):
    def fake_render(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(export_mod, "_render_full_quality", fake_render)
    task_id = manager.submit(_FakeSession(), fmt="png16")
    st = manager.wait(task_id, timeout=10)
    assert st["status"] == "failed"
    assert "boom" in st["error"]


def test_export_status_unknown_raises(manager):
    with pytest.raises(KeyError):
        manager.status("no-such-task")
