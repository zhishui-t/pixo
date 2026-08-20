"""T4 单元测试: rawlab_cli.py 的 retouch 子命令。

覆盖 (验收 / 任务 T4):
  - build_parser(): retouch 子命令解析 --edit / --edits / --scene / --no-detect / --out
  - cmd_retouch(): 参数传递 (--no-detect → detect=False, --scene → scene,
    --edit/--edits → intents 非空), 输出 JSON 字段齐全
  - 错误路径: retouch 抛异常 → 输出 {"ok": False, "error": ...} 且不崩

约定: 不跑真实 NEF。monkeypatch rawlab_cli.RetouchAgent 为 mock 类
(记录 __init__ 参数与 retouch 调用), _load_prof 替换为 lambda。
运行: python -m pytest rawlab/tests/test_retouch_cli.py -q
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import rawlab.rawlab_cli as cli


def _retouch_result(scene="portrait"):
    return SimpleNamespace(
        image_path=Path("out/retouch/x/x_r0.jpg"),
        report={"tone": {"brightness": 120.0}, "color": {"saturation": 45.5}},
        params={"tone": {"contrast": 0.08}},
        scene=scene,
        subject_boxes=[[0.1, 0.2, 0.8, 0.9]],
        round_idx=0,
        ev=0.3,
    )


class MockAgent:
    """替身 RetouchAgent: 记录构造参数与 retouch 调用, 不碰真实渲染。"""

    created = []

    def __init__(self, prof, out_dir=None, detect=True, probe_fn=None, engine_fn=None):
        self.prof = prof
        self.out_dir = out_dir
        self.detect = detect
        self._out_dir = Path(out_dir) if out_dir else Path("out/retouch/x")
        self._stem = "x"
        self.retouch_calls = []
        self.saved_session = None
        MockAgent.created.append(self)

    def retouch(self, raw_path, intents=None, scene="auto"):
        self.retouch_calls.append({
            "raw_path": raw_path,
            "intents": list(intents or []),
            "scene": scene,
        })
        return _retouch_result(scene=scene)

    def save_session(self, path):
        self.saved_session = Path(path)
        return self.saved_session


@pytest.fixture
def cli_mocked(monkeypatch):
    MockAgent.created.clear()
    monkeypatch.setattr(cli, "_load_prof", lambda: "PROF")
    monkeypatch.setattr(cli, "RetouchAgent", MockAgent)
    return MockAgent


def _args(**kw):
    d = {"raw": "x.NEF", "edit": None, "edits": None, "scene": "auto",
         "out": None, "no_detect": False}
    d.update(kw)
    return SimpleNamespace(**d)


# ---------------------------------------------------------------------------
# 1) build_parser(): retouch 子命令解析
# ---------------------------------------------------------------------------

def test_parser_retouch_defaults():
    p = cli.build_parser()
    a = p.parse_args(["retouch", "x.NEF"])
    assert a.raw == "x.NEF"
    assert a.edit is None
    assert a.edits is None
    assert a.scene == "auto"
    assert a.out is None
    assert a.no_detect is False


def test_parser_retouch_flags():
    p = cli.build_parser()
    a = p.parse_args(["retouch", "x.NEF", "--edit", "更亮一点",
                      "--edits", "更饱和一点;磨皮", "--scene", "portrait",
                      "--out", "outdir", "--no-detect"])
    assert a.edit == "更亮一点"
    assert a.edits == "更饱和一点;磨皮"
    assert a.scene == "portrait"
    assert a.out == "outdir"
    assert a.no_detect is True


# ---------------------------------------------------------------------------
# 2) cmd_retouch(): 参数传递与输出 JSON
# ---------------------------------------------------------------------------

def test_cmd_retouch_passes_params(cli_mocked, capsys):
    cli.cmd_retouch(_args(scene="portrait", out="outdir", no_detect=True))

    agent = cli_mocked.created[0]
    assert agent.prof == "PROF"
    assert agent.out_dir == "outdir"
    assert agent.detect is False  # --no-detect

    call = agent.retouch_calls[0]
    assert call["raw_path"] == "x.NEF"
    assert call["scene"] == "portrait"
    assert call["intents"] == []

    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["scene"] == "portrait"
    assert data["subject_boxes"] == [[0.1, 0.2, 0.8, 0.9]]
    assert data["ev"] == 0.3
    assert data["round_idx"] == 0
    assert data["output"].endswith("x_r0.jpg")
    assert data["report"] == {"brightness": 120.0, "saturation": 45.5}
    assert data["session"].endswith("x_session.json")


def test_cmd_retouch_default_detect_and_scene(cli_mocked, capsys):
    cli.cmd_retouch(_args())

    agent = cli_mocked.created[0]
    assert agent.detect is True  # 默认开启检测
    assert agent.retouch_calls[0]["scene"] == "auto"

    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True


def test_cmd_retouch_intents_from_edit_and_edits(cli_mocked, capsys):
    cli.cmd_retouch(_args(edit="更亮一点", edits="更饱和一点;磨皮"))

    intents = cli_mocked.created[0].retouch_calls[0]["intents"]
    assert len(intents) > 0
    ops = [it.op for it in intents]
    # --edit 在前, --edits 在后
    assert ops == ["ev", "saturation", "skin_strength"]

    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True


def test_cmd_retouch_no_intents(cli_mocked, capsys):
    cli.cmd_retouch(_args())
    assert cli_mocked.created[0].retouch_calls[0]["intents"] == []


# ---------------------------------------------------------------------------
# 3) 错误路径
# ---------------------------------------------------------------------------

def test_cmd_retouch_error_returns_ok_false(cli_mocked, monkeypatch, capsys):
    def boom(self, raw_path, intents=None, scene="auto"):
        raise RuntimeError("模拟渲染失败")
    monkeypatch.setattr(cli_mocked, "retouch", boom)

    cli.cmd_retouch(_args())

    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["error"] == "模拟渲染失败"
