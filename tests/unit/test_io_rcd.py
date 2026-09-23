"""R32-T1: decode_raw "RCD" 分支测试（native RCD 去马赛克 + 静默回落 AHD）。

覆盖:
  - RCD 分支返回契约 (img, raw) 不变（export.py/graph.py/bench_pipeline.py
    三处解包依赖 —— reviewer 检视观察项 ①）;
  - 缺省 "AHD" 与未知 demosaic 值静默走 AHD，不新增抛错路径（观察项 ②，
    默认链零漂移）;
  - RCD 失败/不支持回落 AHD + record_degradation 可观测;
  - half_size=True 忽略 RCD（预览线不动）;
  - export 线 demosaic 独立 kwargs 通道透传。
"""
from __future__ import annotations

import numpy as np
import pytest

import pixo.render._native as native
import pixo.render.core.io as io


class _RcdFakeRaw:
    """合成 RGGB raw 对象 (40x48, 黑 64/白 4096, 渐变 + 逐色增益)。

    postprocess 合成 "AHD 输出" = (H,W,3) uint16 线性 (每通道 = 场值,
    即理想去马赛克), 与 native RCD 结果可区分。
    """

    def __init__(self, h=40, w=48, pattern=((0, 1), (1, 2)), desc=b"RGBG",
                 flip=0):
        self.raw_pattern = np.array(pattern, dtype=np.int32)
        self.color_desc = desc
        self.black_level_per_channel = [64.0] * 4
        self.white_level = 4096.0
        self.flip = flip
        r = np.arange(h).reshape(-1, 1)
        c = np.arange(w).reshape(1, -1)
        base = 64.0 + r * 30.0 + c * 2.0
        site = np.tile(self.raw_pattern, ((h + 1) // 2, (w + 1) // 2))[:h, :w]
        gain = np.array([0.0, 60.0, 120.0], dtype=np.float64)[site]
        self.raw_image_visible = np.clip(base + gain, 0, 65535).astype(np.uint16)
        self.postprocess_calls: list[dict] = []
        self._ideal = np.clip(
            np.stack([base, base + 60.0, base + 120.0], axis=-1), 0, 65535
        ).astype(np.uint16)
        # dcraw flip 码的形状语义 (bit2=转置) —— 与 postprocess 输出对齐
        out = self._ideal
        if flip & 4:
            out = out.transpose(1, 0, 2)
        if flip & 2:
            out = out[::-1]
        if flip & 1:
            out = out[:, ::-1]
        self._ideal = np.ascontiguousarray(out)

    @property
    def sizes(self):
        class _Sz:
            pass

        sz = _Sz()
        sz.flip = self.flip
        return sz

    def postprocess(self, **kwargs):
        self.postprocess_calls.append(kwargs)
        return self._ideal.copy()

    def close(self):
        pass


@pytest.fixture()
def fake_raw(monkeypatch, tmp_path):
    raw = _RcdFakeRaw()
    monkeypatch.setattr(io.rawpy, "imread", lambda _p: raw)
    return raw, tmp_path / "fake.nef"


def _native_spy(monkeypatch, impl=None):
    calls: list[tuple] = []
    original = native.demosaic_rcd

    def wrapper(mosaic, pattern):
        calls.append((np.asarray(mosaic).shape, tuple(np.asarray(pattern))))
        if impl is not None:
            return impl(mosaic, pattern)
        return original(mosaic, pattern)

    monkeypatch.setattr(native, "demosaic_rcd", wrapper)
    return calls


def _degradation_spy(monkeypatch):
    events: list[dict] = []

    def spy(source, exc=None, **kw):
        events.append({"source": source, "exc": exc, **kw})

    monkeypatch.setattr(io, "record_degradation", spy)
    return events


@pytest.mark.skipif(not native.available(), reason="native DLL 不可用")
class TestRcdBranch:
    def test_returns_img_raw_tuple_contract(self, monkeypatch, fake_raw):
        """(img, raw) 返回契约不变; native 真实使用 (postprocess 未调)。"""
        raw, path = fake_raw
        calls = _native_spy(monkeypatch)
        img, out_raw = io.decode_raw(path, demosaic="RCD")
        assert out_raw is raw
        assert img.shape == (40, 48, 3) and img.dtype == np.float32
        assert np.isfinite(img).all()
        assert float(img.max()) <= 1.0 + 1e-6  # 白电平相对域
        assert raw.postprocess_calls == []  # 未走 rawpy AHD
        assert len(calls) == 1
        # R 位置像素 ≈ (v-64)/(4096-64) (RGGB: (0,0) 为 R 位, 场值 v=base)
        expect0 = (float(raw.raw_image_visible[0, 0]) - 64.0) / (4096.0 - 64.0)
        assert img[0, 0, 0] == pytest.approx(expect0, abs=1e-5)

    def test_rcd_differs_from_ahd(self, monkeypatch, fake_raw):
        """RCD 与 rawpy AHD 合成输出可区分 (确认不是静默走了 AHD)。"""
        raw, path = fake_raw
        img, _ = io.decode_raw(path, demosaic="RCD")
        ahd = raw.postprocess(use_camera_wb=False)
        assert not np.array_equal(
            img, ahd.astype(np.float32) / 65535.0)

    def test_default_ahd_unchanged(self, monkeypatch, fake_raw):
        """缺省参数走 AHD postprocess, native 不参与 (默认链零漂移)。"""
        raw, path = fake_raw
        calls = _native_spy(monkeypatch)
        img, out_raw = io.decode_raw(path)
        assert out_raw is raw
        assert len(raw.postprocess_calls) == 1
        assert raw.postprocess_calls[0]["demosaic_algorithm"] is not None
        assert raw.postprocess_calls[0]["gamma"] == (1.0, 1.0)
        assert calls == []

    def test_unknown_demosaic_value_silent_ahd(self, monkeypatch, fake_raw):
        """未知 demosaic 值: 静默按 AHD (io.py:142 既有 .get 缺省口径),
        不抛错、不进 native (观察项 ②)。"""
        raw, path = fake_raw
        calls = _native_spy(monkeypatch)
        events = _degradation_spy(monkeypatch)
        img, _ = io.decode_raw(path, demosaic="BOGUS")
        assert img.shape == (40, 48, 3)
        assert len(raw.postprocess_calls) == 1
        assert calls == []
        assert events == []  # 静默回落, 无降级事件

    def test_fallback_on_native_error(self, monkeypatch, fake_raw):
        """native 异常 → 回落 AHD + record_degradation。"""
        raw, path = fake_raw

        def boom(_m, _p):
            raise RuntimeError("native status -3")

        _native_spy(monkeypatch, impl=boom)
        events = _degradation_spy(monkeypatch)
        img, out_raw = io.decode_raw(path, demosaic="RCD")
        assert out_raw is raw
        assert len(raw.postprocess_calls) == 1  # 回落 AHD
        assert img.shape == (40, 48, 3)
        assert len(events) == 1
        assert events[0]["source"] == "render.io.decode_raw.rcd"
        assert isinstance(events[0]["exc"], RuntimeError)

    def test_fallback_on_unsupported(self, monkeypatch, fake_raw):
        """不支持输入 (FallbackRequested → None) → 回落 AHD + 降级事件。"""
        raw, path = fake_raw
        _native_spy(monkeypatch, impl=lambda _m, _p: None)
        events = _degradation_spy(monkeypatch)
        img, _ = io.decode_raw(path, demosaic="RCD")
        assert len(raw.postprocess_calls) == 1
        assert img.shape == (40, 48, 3)
        assert len(events) == 1
        assert events[0]["exc"] is None
        assert "fallback" in str(events[0].get("reason", "")) or \
            events[0].get("reason") == "fallback"

    def test_half_size_ignores_rcd(self, monkeypatch, fake_raw):
        """half_size=True (预览线) 忽略 RCD, 走既有 rawpy 路径。"""
        raw, path = fake_raw
        calls = _native_spy(monkeypatch)
        img, _ = io.decode_raw(path, half_size=True, demosaic="RCD")
        assert img.shape == (40, 48, 3)  # fake 不真半采样, 只看路径
        assert len(raw.postprocess_calls) == 1
        assert calls == []

    def test_xtrans_falls_back(self, monkeypatch, tmp_path):
        """非 2x2 RGBG (X-Trans 6x6) → ValueError → 静默回落 AHD。"""
        raw = _RcdFakeRaw(pattern=np.arange(36).reshape(6, 6) % 3,
                          desc=b"RGB")
        monkeypatch.setattr(io.rawpy, "imread", lambda _p: raw)
        _native_spy(monkeypatch)
        events = _degradation_spy(monkeypatch)
        img, _ = io.decode_raw(tmp_path / "xtrans.raf", demosaic="RCD")
        assert len(raw.postprocess_calls) == 1
        assert img.shape == (40, 48, 3)
        assert len(events) == 1

    @pytest.mark.skipif(not native.available(), reason="native DLL 不可用")
    @pytest.mark.parametrize("flip,shape", [(0, (40, 48)), (3, (40, 48)),
                                            (5, (48, 40)), (6, (48, 40))])
    def test_dcraw_flip_orientation(self, monkeypatch, tmp_path, flip, shape):
        """dcraw flip 码: RCD 输出方向与 postprocess (bit 语义) 对齐。

        R32-T1 A/B 实测发现 portrait RAW (flip=5) 不翻转则横竖颠倒 —— 回归锁。
        """
        raw = _RcdFakeRaw(flip=flip)
        monkeypatch.setattr(io.rawpy, "imread", lambda _p: raw)
        img, _ = io.decode_raw(tmp_path / "f.nef", demosaic="RCD")
        assert img.shape[:2] == shape
        ideal = raw.postprocess().astype(np.float32) / 65535.0
        assert img.shape == ideal.shape
        # 逐色增益合成场: 两臂同向 (相对形状与色彩布局一致)
        assert np.abs(img - ideal).mean() < 0.2


class TestExportChannel:
    def test_render_full_quality_demosaic_kwarg(self, monkeypatch, tmp_path):
        """_render_full_quality 的 demosaic 显式 kwargs 透传 decode_raw。"""
        import pixo.render.web.export as exp

        seen: dict = {}

        def fake_decode_raw(raw_path, half_size=False, demosaic="AHD"):
            seen["demosaic"] = demosaic
            seen["half_size"] = half_size
            return (np.zeros((8, 8, 3), dtype=np.float32), _RcdFakeRaw(8, 8))

        def fake_build(**_kw):
            return object()

        def fake_run(img, prof, params, **kw):
            return np.zeros((4, 4), dtype=np.uint8)

        monkeypatch.setattr(io, "decode_raw", fake_decode_raw)
        monkeypatch.setattr(
            "pixo.render.pipeline.presets.build_default_pipeline", fake_build)
        monkeypatch.setattr(
            "pixo.render.pipeline.runner.run_full_pipeline", fake_run)
        exp._render_full_quality(tmp_path / "x.nef", None, {},
                                 demosaic="RCD")
        assert seen == {"demosaic": "RCD", "half_size": False}
        # 缺省: AHD (默认链零漂移)
        exp._render_full_quality(tmp_path / "x.nef", None, {})
        assert seen["demosaic"] == "AHD"

    def test_export_manager_reads_session_attribute(self, monkeypatch, tmp_path):
        """ExportManager 通道: session.demosaic 非 AHD 时显式 kwargs 转发。"""
        import pixo.render.web.export as exp
        from pixo.render.web.session import RawPreviewSession

        class _Mgr(exp.ExportManager):
            def __init__(self):
                self.captured = {}
                self._lock = __import__("threading").Lock()
                self._tasks = {}

        mgr_seen: dict = {}
        monkeypatch.setattr(
            exp, "_render_full_quality",
            lambda *a, **kw: mgr_seen.update(demosaic=kw.get("demosaic", "AHD"))
            or np.zeros((2, 2), dtype=np.uint8))
        monkeypatch.setattr(exp, "encode_image",
                            lambda img, fmt, quality=None: b"x")
        # Session 构造重 (依赖服务层); 用轻量 stub 走 _run 核心段
        class _Session:
            raw_path = tmp_path / "x.nef"
            demosaic = "RCD"
            region_masks = None

            def canonical_params(self):
                return {}

        mgr = exp.ExportManager.__new__(exp.ExportManager)
        mgr.prof = None
        mgr.work_dir = tmp_path
        mgr._tasks = {"t1": {"task_id": "t1", "status": "pending"}}
        mgr._lock = __import__("threading").Lock()
        ex = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"])
        mgr._executor = ex.ThreadPoolExecutor(max_workers=1)
        mgr._run("t1", _Session(), "tiff16", None, tmp_path)
        assert mgr_seen["demosaic"] == "RCD"

    def test_session_default_demosaic_attribute(self):
        """RawPreviewSession 缺省 demosaic="AHD" (观察项 ② 的 session 面)。"""
        from pixo.render.web.session import RawPreviewSession

        s = RawPreviewSession.__new__(RawPreviewSession)
        # 只验证类级缺省存在 (构造器逻辑由既有 session 测试覆盖)
        import inspect
        src = inspect.getsource(RawPreviewSession)
        assert 'self.demosaic: str = "AHD"' in src
