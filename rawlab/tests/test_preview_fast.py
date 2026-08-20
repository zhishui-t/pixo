"""T4.3 低分辨率快速预览测试。

覆盖: preview_fast.json 结构/可构建、render_preview 调 run_file(half_size)、
默认 render/render_adjusted 不受影响、CLI --preview 分支、预览链比默认短且无
heavy stage、合成小图跑真实预览链输出 uint8 形状正确。全部 tmp_path/monkeypatch,
不跑真实 NEF。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rawlab.engine import pipeline_from_config
from rawlab.engine.pipeline import DEFAULT_STAGES

_DCP = r"K:\work\project\RawFlow\rawlab\profiles\Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"


def _load_fast_cfg():
    p = Path(__file__).resolve().parents[1] / "presets" / "preview_fast.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_fast_json_valid_and_buildable():
    cfg = _load_fast_cfg()
    assert cfg["stages"] == ["exposure", "whitebalance", "huesat", "tone"]
    assert cfg["params"]["huesat"]["enabled"] is False
    assert cfg["params"]["tone"]["eotf"] == "srgb"
    pipe = pipeline_from_config(cfg)
    assert [s.name for s in pipe.stages] == cfg["stages"]


class _FakePipe:
    def __init__(self, record):
        self.record = record
    def run_file(self, raw_path, half_size=False):
        self.record.append((raw_path, half_size))
        return np.zeros((10, 10, 3), dtype=np.uint8)


def test_render_preview_calls_run_file_halfsize(monkeypatch):
    import rawlab.engine.api as api
    from rawlab.engine.api import Renderer
    record = []
    monkeypatch.setattr(api, "pipeline_from_config", lambda cfg, prof=None: _FakePipe(record))
    r = Renderer(_DCP)
    out = r.render_preview("some.nef", half_size=True)
    assert out.dtype == np.uint8
    p, hs = record[0]
    assert p == "some.nef" and hs is True


def test_default_render_adjusted_unchanged(monkeypatch):
    import rawlab.engine.api as api
    from rawlab.engine.api import Renderer, RenderIntent
    seen = {}
    def fake_bbp(prof=None, params=None):
        seen["prof"] = prof; seen["params"] = params
        return _FakePipe([])
    monkeypatch.setattr(api, "build_default_pipeline", fake_bbp)
    r = Renderer(_DCP)
    r.render_adjusted("x.nef", RenderIntent(exposure=0.5), half_size=True)
    # 默认 render_adjusted 仍走 build_default_pipeline (不被 preview 接管)
    assert seen["params"]["exposure"]["mode"] == 0.5


def test_cli_preview_branch_exists():
    import rawlab.rawlab_cli as cli
    ap = cli.build_parser()
    assert "pipeline" in ap._subparsers._actions[-1].choices
    args = ap.parse_args(["pipeline", "x.nef", "--preview"])
    assert args.preview is True


def test_preview_chain_shorter_no_heavy():
    cfg = _load_fast_cfg()
    fast = set(cfg["stages"])
    assert len(fast) < len(DEFAULT_STAGES)
    for heavy in ("refine", "skin", "stylize"):
        assert heavy not in fast


class _FakeRaw:
    camera_whitebalance = [2.0, 1.0, 1.5]
    def close(self): pass


def test_synthetic_preview_chain_uint8():
    """用合成线性相机图跑真实预览链 (exposure/whitebalance/huesat/tone) → uint8。"""
    from rawlab.dcp import load_dcp
    from rawlab.engine import pipeline_from_config
    from rawlab.engine.core import StageContext, DOMAIN_LINEAR_CAM

    prof = load_dcp(_DCP)
    cfg = _load_fast_cfg()
    pipe = pipeline_from_config(cfg, prof=prof)
    rng = np.random.default_rng(0)
    img = (rng.random((64, 64, 3)) * 0.6).astype(np.float32)
    ctx = StageContext("t.NEF", raw=_FakeRaw(), prof=prof, config={"stages": {}})
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    out = pipe.run(ctx)
    # run_file 语义: gamma 域 → uint8
    uint8 = (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    assert out.shape == (64, 64, 3) and out.shape == uint8.shape
    assert uint8.dtype == np.uint8
    assert uint8.max() <= 255
