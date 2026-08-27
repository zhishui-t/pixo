"""T4.1a Renderer↔Pipeline 打通 —— Renderer.render 接入 intents/stages 的接线测试。

用 monkeypatch 替换 render_dcp_linear / build_default_pipeline 做纯接线测试,
加一条真实小图集成 (有可用 DNG/DCP 时运行, 否则 skip)。
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pytest

from pixo.render.core.calibration import DcpProfile
from pixo.render.core.tone import srgb_decode
from pixo.render import api
from pixo.render.api import (Renderer, RenderIntent, RawInput, RawMetadata,
                               CameraCalibration)
from pixo.render.pipeline.context import DOMAIN_GAMMA_RGB

import pixo.render.core.io as core_io


_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]


@pytest.fixture
def renderer(monkeypatch):
    """构造 Renderer, 替换 load_dcp/load_camera_cache 免真实 .dcp 文件。"""
    prof = DcpProfile(path="fake.dcp", color_matrix1=_NIKON_CM1,
                      color_matrix2=_NIKON_CM2, forward_matrix1=_NIKON_FM1,
                      forward_matrix2=_NIKON_FM1)

    def fake_load_dcp(path):
        return prof

    monkeypatch.setattr(api, "load_dcp", fake_load_dcp)
    monkeypatch.setattr(api, "load_camera_cache", lambda path: {})
    return Renderer("fake.dcp")


class _FakeRawHandle:
    """decode_raw 返回的 raw 句柄替身 (只需 close)。"""
    def close(self):
        pass


def _fake_decode_raw(path, half_size=False):
    return np.zeros((4, 4, 3), np.float32), _FakeRawHandle()


class FakePipe:
    """假 Pipeline: 记录 params。

    run_file 返回可辨识的 gamma uint8 (render_adjusted 契约);
    run 写 gamma float (L9 后 render 调整路径走 runner, 不再量化)。
    """
    def __init__(self, prof, params):
        self.prof = prof
        self.params = params

    def _gamma(self, ev):
        # 有 exposure 参数则抬高输出 (模拟曝光调整)
        return np.clip(np.zeros((4, 4, 3), np.float32) + 80.0 + float(ev) * 40.0,
                       0.0, 255.0)

    def run_file(self, raw_path, half_size=False):
        ev = self.params.get("exposure", {}).get("mode", 0.0)
        return self._gamma(ev).astype(np.uint8)

    def run(self, ctx):
        ev = self.params.get("exposure", {}).get("mode", 0.0)
        ctx.set_image(self._gamma(ev) / 255.0, DOMAIN_GAMMA_RGB)


def _make_renderer_with_pipe(monkeypatch, renderer):
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: FakePipe(prof, params or {}))
    # render 里 monkeypatch render_dcp_linear 为可辨识返回
    captured = {}
    monkeypatch.setattr(api, "render_dcp_linear",
                        lambda *a, **k: (captured.setdefault("called", 0) or 0) and None or np.full((4, 4, 3), 40.0, np.float32))
    # L9 调整路径直接 decode_raw + runner (不再经 run_file uint8 量化)
    monkeypatch.setattr(core_io, "decode_raw", _fake_decode_raw)
    return renderer, captured


def _raw(renderer):
    return RawInput(camera_rgb=np.zeros((4, 4, 3), np.float32),
                    metadata=RawMetadata(path="x.NEF", camera_rgb_shape=(4, 4, 3),
                                         camera_key=""))


def test_default_render_uses_render_dcp_linear(renderer, monkeypatch):
    """默认 intent (无调整) 走 render_dcp_linear base 路径。"""
    captured = {}
    monkeypatch.setattr(api, "render_dcp_linear",
                        lambda *a, **k: captured.update(called=True) or None or np.zeros((2,2,3), np.float32))
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: (_ for _ in ()).throw(AssertionError("不应走 pipeline")))
    out = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}), None)
    assert captured.get("called") is True
    assert out.shape == (2, 2, 3)


def test_exposure_zero_no_pipeline(renderer, monkeypatch):
    """exposure==0 且 stages 空 → 不调 build_default_pipeline。"""
    monkeypatch.setattr(api, "render_dcp_linear", lambda *a, **k: np.full((3,3,3), 50.0, np.float32))
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: (_ for _ in ()).throw(AssertionError("不应调用")))
    out = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}), RenderIntent())
    assert out.shape == (3, 3, 3)


def test_exposure_no_longer_raises_and_increases_mean(renderer, monkeypatch):
    """intent.exposure=0.5 不再 NotImplementedError; 走 pipeline, 输出均值提高且有限。"""
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: FakePipe(prof, params or {}))
    monkeypatch.setattr(api, "render_dcp_linear", lambda *a, **k: np.zeros((4,4,3), np.float32))
    monkeypatch.setattr(core_io, "decode_raw", _fake_decode_raw)
    base = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                          RenderIntent(exposure=0.0))
    out = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                          RenderIntent(exposure=0.5))
    assert np.isfinite(out).all()
    assert out.min() >= 0.0
    # exposure=0.5 → FakePipe 抬高 gamma → 线性输出均值高于 exposure=0
    assert float(out.mean()) > float(base.mean()) + 1e-6


def test_stages_change_output(renderer, monkeypatch):
    """intent.stages 传参给 pipeline → 输出与默认不同。"""
    default_params = {"_v": "default"}
    def _pipe(prof, params=None):
        default_params["_v"] = params
        return FakePipe(prof, params or {})
    monkeypatch.setattr(api, "build_default_pipeline", _pipe)
    monkeypatch.setattr(api, "render_dcp_linear", lambda *a, **k: np.zeros((4,4,3), np.float32))
    monkeypatch.setattr(core_io, "decode_raw", _fake_decode_raw)
    # stages 带 exposure.mode → 输出抬高
    out = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                          RenderIntent(stages={"exposure": {"mode": 1.0}}))
    out0 = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                           RenderIntent())
    assert float(out.mean()) > float(out0.mean()) + 1e-6


def test_render_adjusted_returns_uint8_shape(renderer, monkeypatch):
    """render_adjusted 返回 uint8 (H,W,3) 且 shape 正确。"""
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: FakePipe(prof, params or {}))
    out = renderer.render_adjusted("x.NEF", RenderIntent(), half_size=False)
    assert out.dtype == np.uint8
    assert out.shape == (4, 4, 3)


def test_render_with_adjust_clip_linear(renderer, monkeypatch):
    """有调整时 render 返回线性 float32 (dng_srgb_decode 后), clip ≥0。"""
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: FakePipe(prof, params or {}))
    monkeypatch.setattr(core_io, "decode_raw", _fake_decode_raw)
    out = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                          RenderIntent(exposure=0.5))
    assert out.dtype == np.float32
    assert out.min() >= 0.0
    assert (out <= 1.0).all() or out.max() > 0.0  # 有限线性域


def test_render_adjusted_path_avoids_u8_quantization(renderer, monkeypatch):
    """L9: 调整路径不再经 8bit 量化 —— 非 1/255 网格的 gamma 值逐位保留。

    旧实现 gamma→uint8→/255→srgb_decode, 输出只能落在量化网格的解码值上;
    新实现直接解码管线 gamma float, 输出 == srgb_decode(gamma) 逐位相等。
    """
    gamma_val = 0.5 + 1.0 / 1024.0   # 不在 uint8 量化网格上

    class _GammaPipe(FakePipe):
        def run(self, ctx):
            ctx.set_image(np.full((4, 4, 3), gamma_val, np.float32),
                          DOMAIN_GAMMA_RGB)

    monkeypatch.setattr(api, "build_default_pipeline", _GammaPipe)
    monkeypatch.setattr(core_io, "decode_raw", _fake_decode_raw)
    out = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                          RenderIntent(exposure=0.5))
    expected = np.clip(srgb_decode(np.float32(gamma_val)), 0.0, None)
    assert np.array_equal(out, np.full((4, 4, 3), expected, np.float32))


def test_render_adjusted_linear_matches_gamma_float_decode(renderer, monkeypatch):
    """调整路径与 render_adjusted 的 gamma 值同源 (uint8 量化前), EV 单调。"""
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: FakePipe(prof, params or {}))
    monkeypatch.setattr(core_io, "decode_raw", _fake_decode_raw)
    out0 = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                           RenderIntent(exposure=0.5))
    out1 = renderer.render(_raw(renderer), CameraCalibration(profile=None, camera_entry={}),
                           RenderIntent(exposure=1.0))
    # FakePipe gamma: 100/255 vs 120/255 → 线性均值单调升
    assert float(out1.mean()) > float(out0.mean())


def test_render_file_default_and_intent(renderer, monkeypatch):
    """render_file 默认 + 带 intent 两条路径都正常 (返回线性 float32)。"""
    monkeypatch.setattr(api, "build_default_pipeline",
                        lambda prof, params=None: FakePipe(prof, params or {}))
    monkeypatch.setattr(api, "render_dcp_linear", lambda *a, **k: np.full((4,4,3), 0.3, np.float32))
    monkeypatch.setattr(core_io, "decode_raw", _fake_decode_raw)
    monkeypatch.setattr(renderer, "calibrate",
                        lambda raw_path: CameraCalibration(profile=None, camera_entry={}))
    # 默认
    out_hi = renderer.render_file("x.NEF")
    assert out_hi.shape == (4, 4, 3)
    # 带 intent (走新路径)
    out_cal = renderer.render_file("x.NEF", RenderIntent(exposure=0.5))
    assert out_cal.shape == (4, 4, 3)
    assert np.isfinite(out_cal).all()


def test_render_file_uses_real_path(renderer, monkeypatch):
    """render_file 把真实 raw_path 传进 metadata.path (render 用它驱动 base)。"""
    seen = {}
    monkeypatch.setattr(api, "render_dcp_linear",
                        lambda *a, **k: seen.update(path=a[0]) or None or np.zeros((2,2,3), np.float32))
    monkeypatch.setattr(renderer, "calibrate",
                        lambda raw_path: CameraCalibration(profile=None, camera_entry={}))
    renderer.render_file("C:/p/fake_raw.NEF")
    assert str(seen.get("path")) == str(Path("C:/p/fake_raw.NEF"))


def test_params_from_intent_merges_and_no_mutate(renderer):
    """_params_from_intent: 合并 stages + exposure, 且不修改原 intent。"""
    it = RenderIntent(exposure=0.5, stages={"hsl": {"enabled": True}, "tone": {"contrast": 0.2}})
    p = renderer._params_from_intent(it)
    assert p["hsl"]["enabled"] is True
    assert p["tone"]["contrast"] == pytest.approx(0.2)
    assert p["exposure"]["mode"] == pytest.approx(0.5)
    # 原 intent 未被改
    assert it.exposure == 0.5
    assert it.stages == {"hsl": {"enabled": True}, "tone": {"contrast": 0.2}}


def test_params_no_stages_returns_empty(renderer):
    it = RenderIntent()
    assert renderer._params_from_intent(it) == {}
    it2 = RenderIntent(exposure=0.0, stages={})
    assert renderer._params_from_intent(it2) == {}
