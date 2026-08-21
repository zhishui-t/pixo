"""T11/P1: render_preview_full 全链路预览引擎测试。

覆盖:
  - 使用完整默认链（build_default_pipeline），不是 preview_fast
  - 优先 C++ CFA half 解码，失败回退 rawpy AHD half
  - 等比缩放到 long_edge
  - 8-bit / 16-bit 输出
  - render_preview_degraded 保留旧 preview_fast
"""
from __future__ import annotations

import numpy as np
import pytest

import rawpy
import render.api as api
from render.api import Renderer
from render.pipeline.context import DOMAIN_GAMMA_RGB

_DCP = r"K:\work\project\RawFlow\render\profiles\Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"


class _FakeRaw:
    def __init__(self, rgb16=None):
        self._rgb16 = rgb16
        self.closed = False
        self.postprocess_kwargs = None

    def postprocess(self, **kwargs):
        self.postprocess_kwargs = kwargs
        if self._rgb16 is None:
            return np.zeros((32, 32, 3), dtype=np.uint16)
        return self._rgb16

    def close(self):
        self.closed = True


class _FakePipe:
    def __init__(self, record):
        self.record = record
        self.prof = None

    def run(self, ctx):
        self.record.append(ctx)
        # 默认让管线输出一个 gamma 图；测试可改写 ctx.image 验证缩放。
        ctx.domain = DOMAIN_GAMMA_RGB
        if ctx.image is not None and ctx.image.ndim == 3:
            ctx.image = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)


def _make_renderer():
    return Renderer(_DCP)


def test_render_preview_full_uses_default_pipeline_and_native_decode(monkeypatch):
    import render.core.io as core_io

    record = []
    seen = {}
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof=None, params=None: _set_pipe(seen, prof, params, record))
    fake_raw = _FakeRaw()
    monkeypatch.setattr(rawpy, "imread", staticmethod(lambda path: fake_raw))

    def fake_decode(raw, raw_path=None):
        assert raw is fake_raw
        return np.full((32, 32, 3), 0.25, dtype=np.float32)

    monkeypatch.setattr(core_io, "decode_cfa_half", fake_decode)

    r = _make_renderer()
    out = r.render_preview_full("x.nef", long_edge=16, params={"exposure": {"mode": 0.5}},
                                output_bps=8)
    assert out.dtype == np.uint8
    assert out.shape == (16, 16, 3)
    assert seen["prof"] is r.profile
    assert seen["params"]["exposure"]["mode"] == 0.5
    ctx = record[0]
    assert ctx.state["half_size"] is True
    assert ctx.config["decode_mode"] == "cfa_half_native"
    assert fake_raw.closed is True


def test_render_preview_full_16bit_output(monkeypatch):
    import render.core.io as core_io

    record = []
    seen = {}
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof=None, params=None: _set_pipe(seen, prof, params, record))
    fake_raw = _FakeRaw()
    monkeypatch.setattr(rawpy, "imread", staticmethod(lambda path: fake_raw))
    monkeypatch.setattr(core_io, "decode_cfa_half",
                        lambda raw, raw_path=None: np.full((32, 32, 3), 0.5, dtype=np.float32))

    r = _make_renderer()
    out = r.render_preview_full("x.nef", long_edge=16, output_bps=16)
    assert out.dtype == np.uint16
    assert out.shape == (16, 16, 3)
    assert out.max() <= 65535


def test_render_preview_full_falls_back_to_rawpy_half(monkeypatch):
    import render.core.io as core_io

    record = []
    seen = {}
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof=None, params=None: _set_pipe(seen, prof, params, record))
    fake_raw = _FakeRaw(rgb16=(np.full((32, 32, 3), 30000, dtype=np.uint16)))
    monkeypatch.setattr(rawpy, "imread", staticmethod(lambda path: fake_raw))
    monkeypatch.setattr(core_io, "decode_cfa_half",
                        lambda raw, raw_path=None: (_ for _ in ()).throw(RuntimeError("native unavailable")))

    r = _make_renderer()
    out = r.render_preview_full("x.nef", long_edge=16, output_bps=8)
    assert out.dtype == np.uint8
    assert fake_raw.postprocess_kwargs is not None
    assert fake_raw.postprocess_kwargs["half_size"] is True
    assert out.shape == (16, 16, 3)


def test_render_preview_full_resizes_to_long_edge(monkeypatch):
    import render.core.io as core_io

    record = []
    seen = {}
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof=None, params=None: _set_pipe(seen, prof, params, record))
    fake_raw = _FakeRaw()
    monkeypatch.setattr(rawpy, "imread", staticmethod(lambda path: fake_raw))
    monkeypatch.setattr(core_io, "decode_cfa_half",
                        lambda raw, raw_path=None: np.full((64, 128, 3), 0.5, dtype=np.float32))

    r = _make_renderer()
    out = r.render_preview_full("x.nef", long_edge=32, output_bps=8)
    # 原图 64x128，长边 32 -> 16x32
    assert out.shape == (16, 32, 3)


def test_render_preview_degraded_keeps_old_preview(monkeypatch):
    import render.api as shim_api
    from render.api import Renderer as ShimRenderer

    class _FakeRunFilePipe:
        def run_file(self, raw_path, half_size=False):
            return np.zeros((10, 10, 3), dtype=np.uint8)

    monkeypatch.setattr(shim_api, "pipeline_from_config",
                        lambda cfg, prof=None: _FakeRunFilePipe())
    r = ShimRenderer(_DCP)
    out = r.render_preview_degraded("some.nef", half_size=True)
    assert out.dtype == np.uint8


def _set_pipe(seen, prof, params, record):
    seen["prof"] = prof
    seen["params"] = params
    return _FakePipe(record)
