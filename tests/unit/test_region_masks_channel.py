"""F13 掩码通道 preview/export 双线注入测试。

覆盖:
  - 适配器 (render/pipeline/region_masks.py): 归一/重采样/compose 预测/透传纪律
  - 缓存指纹: 掩码变化 → state 指纹/stage 缓存 key 变化 (ndarray digest);
    同掩码同对象 → 指纹稳定 → 跨渲染命中
  - session 预览线: region_masks 适配到消费帧 + Route B 属性携带
  - export 全质量线: _render_full_quality state_extras 增参 + 向后兼容 +
    ExportManager 转发 (Route B)
  - e2e: 同一掩码 preview/export 两线区域效果方向一致 (tier 口径教训门禁),
    loop 级注入闭环 (preview 粘性注入 / FINAL_QC 导出线补齐)
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import pixo.render.core.io as io_mod
import pixo.render.pipeline.presets as presets_mod
import pixo.render.web.session as sess_mod
from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.render.pipeline.context import DOMAIN_GAMMA_RGB
from pixo.render.pipeline.graph import Stage
from pixo.render.pipeline.region_masks import (adapt_region_masks,
                                                adapt_state_extras)
from pixo.render.web import export as export_mod
from pixo.render.web.export import ExportManager
from pixo.render.web.session import (_ndarray_digest, _state_fingerprint,
                                     RawPreviewSession)
from pixo.vision import MockSegmenter

# region_adjust (dev-3 F12) 为真实消费方; 其 modules/__init__ 导入尚在并行
# 开发中, 此处显式触发注册 (幂等, 待其落地后自然 no-op)。
import pixo.render.modules.region_adjust  # noqa: F401


# ---------------------------------------------------------------------------
# 公共道具
# ---------------------------------------------------------------------------

class MockProf:
    """最小 DcpProfile 替身 (tests/unit/test_pipeline.py 同构): 恒等矩阵。"""

    def __init__(self):
        self.color_matrix1 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.color_matrix2 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.forward_matrix1 = None
        self.forward_matrix2 = None
        self.camera_calibration1 = None
        self.camera_calibration2 = None
        self.calibration_illuminant1 = 17
        self.calibration_illuminant2 = 21
        self.baseline_exposure_offset = 0.0
        self.profile_tone_curve = None


class _FakeRaw:
    def close(self):
        pass


def _top_band_mask(h, w, frac=0.40):
    """二值 0/255 顶部条带 (MockSegmenter sky 同构)。"""
    m = np.zeros((h, w), dtype=np.uint8)
    m[: max(1, int(round(h * frac))), :] = 255
    return m


def _gradient_image(h, w):
    yy, xx = np.mgrid[0:h, 0:w]
    r = 0.25 + 0.30 * xx / max(w - 1, 1)
    g = 0.25 + 0.30 * yy / max(h - 1, 1)
    b = 0.30 + 0.20 * (xx + yy) / max(w + h - 2, 1)
    return np.stack([r, g, b], axis=-1).astype(np.float32)


def _region_means(img, region):
    """u8 图在 region (bool mask) 内/外的均值。"""
    arr = img.astype(np.float32)
    return float(arr[region].mean()), float(arr[~region].mean())


# ---------------------------------------------------------------------------
# 1) 适配器单元
# ---------------------------------------------------------------------------

def test_adapt_normalizes_integer_masks():
    src = {"sky": _top_band_mask(60, 80)}
    out = adapt_region_masks(src)
    assert out["sky"].dtype == np.float32
    assert out["sky"].shape == (60, 80)
    assert out["sky"].min() == 0.0 and out["sky"].max() == 1.0
    # 二值 0/255 → 恰 0/1
    assert set(np.unique(out["sky"])) <= {0.0, 1.0}


def test_adapt_resample_down_and_up():
    src = adapt_region_masks({"sky": _top_band_mask(120, 160)})
    down = adapt_region_masks(src, (48, 64))
    assert down["sky"].shape == (48, 64)
    # INTER_AREA 面积平均: 覆盖比例保持 ≈0.40
    assert down["sky"].mean() == pytest.approx(0.40, abs=0.02)
    up = adapt_region_masks(down, (96, 128))
    assert up["sky"].shape == (96, 128)
    assert up["sky"].mean() == pytest.approx(0.40, abs=0.02)


def test_adapt_pass_through_same_object_when_aligned():
    """透传纪律: float32 + shape 命中 → 原对象 (缓存指纹 data_ptr 稳定)。"""
    src = adapt_region_masks({"sky": _top_band_mask(48, 64)})
    out = adapt_region_masks(src, (48, 64))
    assert out["sky"] is src["sky"]
    out2 = adapt_region_masks(src, (96, 128))
    assert out2["sky"] is not src["sky"]


def test_adapt_float_input_not_rescaled():
    """float 输入视为已 [0,1], 不做 /255。"""
    m = np.full((10, 10), 0.5, dtype=np.float32)
    out = adapt_region_masks({"a": m})
    assert out["a"].max() == pytest.approx(0.5)


def test_adapt_squeezes_hwx1():
    m = np.zeros((12, 16, 1), dtype=np.uint8)
    m[:6] = 255
    out = adapt_region_masks({"a": m}, (24, 32))
    assert out["a"].shape == (24, 32)
    assert out["a"].dtype == np.float32


def test_adapt_compose_prediction():
    # ratio 1:1 on 240x320 (w>h): 全高、宽收窄 → (240, 240)
    out = adapt_region_masks({"sky": np.zeros((60, 80), np.uint8)},
                             (240, 320), {"mode": "ratio", "ratio": "1:1"})
    assert out["sky"].shape == (240, 240)
    # 默认 free 全幅: 预测 = 入口 shape
    out2 = adapt_region_masks({"sky": np.zeros((60, 80), np.uint8)},
                              (240, 320), {"mode": "free"})
    assert out2["sky"].shape == (240, 320)
    # compose_params None → 不预测
    out3 = adapt_region_masks({"sky": np.zeros((60, 80), np.uint8)},
                              (240, 320), None)
    assert out3["sky"].shape == (240, 320)


def test_adapt_skips_broken_mask():
    src = {"good": np.zeros((8, 8), np.uint8), "bad": np.zeros((8, 8, 3), np.uint8)}
    out = adapt_region_masks(src, (16, 16))
    assert "good" in out and "bad" not in out


def test_adapt_state_extras_passthrough_and_copy():
    extras = {"face_boxes": [[0.1, 0.2, 0.3, 0.4]]}
    assert adapt_state_extras(extras, (8, 8)) == extras
    with_masks = {"face_boxes": [], "region_masks": {"sky": np.zeros(
        (4, 4), np.uint8)}}
    out = adapt_state_extras(with_masks, (8, 8))
    assert out["face_boxes"] == []
    assert out["region_masks"]["sky"].shape == (8, 8)
    assert out["region_masks"]["sky"].dtype == np.float32


# ---------------------------------------------------------------------------
# 2) 缓存指纹 (session.py _state_fingerprint / _ndarray_digest)
# ---------------------------------------------------------------------------

def test_state_fingerprint_mask_content_change_invalidates():
    a = np.zeros((32, 32), np.float32)
    a[:12] = 1.0
    b = a.copy()
    b[16, 16] = 1.0
    fa = _state_fingerprint({"region_masks": {"sky": a}})
    fb = _state_fingerprint({"region_masks": {"sky": b}})
    assert fa != fb, "掩码内容变化必须改变 state 指纹"


def test_ndarray_digest_large_mask_middle_only_change():
    """大数组 (>2*4KB 采样阈值) 仅中部变化: data_ptr 兜底使摘要不同。"""
    a = np.zeros((200, 200), np.float32)  # 160KB
    b = np.zeros((200, 200), np.float32)
    b[100, 100] = 1.0  # 中部, 首末 4KB 采样均不可见
    assert _ndarray_digest(a) != _ndarray_digest(b)
    assert _ndarray_digest(a) == _ndarray_digest(a)  # 同对象稳定


def test_state_fingerprint_same_mask_object_stable():
    m = adapt_region_masks({"sky": _top_band_mask(48, 64)})
    f1 = _state_fingerprint({"region_masks": m})
    f2 = _state_fingerprint({"region_masks": m})
    assert f1 == f2, "同掩码对象反复注入必须指纹稳定 (否则缓存永不命中)"


# ---------------------------------------------------------------------------
# 3) session 预览线
# ---------------------------------------------------------------------------

class _StateProbe:
    """伪 stage (session 缓存循环只调 wants/run): 记录 region_masks 概要。"""

    name = "state_probe"

    def __init__(self):
        self.runs: list[dict | None] = []

    def wants(self, ctx):
        return True

    def run(self, ctx):
        masks = ctx.state.get("region_masks")
        if not isinstance(masks, dict) or not masks:
            self.runs.append(None)
        else:
            self.runs.append({
                k: (v.shape, str(v.dtype), float(v.min()), float(v.max()))
                for k, v in masks.items()})
        ctx.domain = DOMAIN_GAMMA_RGB  # 保持入口/出口域恒等


class _FakeCompose:
    """伪 compose stage: 与预测器同源 (compute_crop_rect) 做真裁剪。"""

    name = "compose"

    def __init__(self):
        self.calls = 0

    def wants(self, ctx):
        return True

    def run(self, ctx):
        from pixo.render.modules.compose import compute_crop_rect
        self.calls += 1
        h, w = ctx.image.shape[:2]
        cp = (ctx.config.get("stages") or {}).get("compose") or {}
        x0, y0, cw, ch = compute_crop_rect(
            h, w, mode=cp.get("mode", "free"), ratio=cp.get("ratio"),
            center=cp.get("center", [0.5, 0.5]),
            x=float(cp.get("x", 0.0) or 0.0), y=float(cp.get("y", 0.0) or 0.0),
            width=float(cp.get("width", 0.0) or 0.0),
            height=float(cp.get("height", 0.0) or 0.0))
        ctx.image = ctx.image[y0:y0 + ch, x0:x0 + cw].copy()


DECODE_H, DECODE_W = 240, 320


@pytest.fixture()
def session_env(monkeypatch):
    probe = _StateProbe()
    compose = _FakeCompose()

    class _FakePipe:
        stages = [compose, probe]

    monkeypatch.setattr(sess_mod.rawpy, "imread",
                        staticmethod(lambda path: _FakeRaw()))
    monkeypatch.setattr(
        sess_mod, "decode_cfa_half",
        lambda raw, raw_path=None: _gradient_image(DECODE_H, DECODE_W))
    monkeypatch.setattr(io_mod, "camera_neutral_wb_cached",
                        lambda raw, raw_path: None)
    monkeypatch.setattr(sess_mod, "build_default_pipeline",
                        lambda prof=None, params=None: _FakePipe())
    return {"probe": probe, "compose": compose}


def _sess(**params):
    return RawPreviewSession("t.nef", prof=None, params=params)


def test_session_adapts_region_masks_to_tier(session_env):
    sess = _sess()
    masks = {"sky": _top_band_mask(60, 80)}  # uint8 0/255, 任意分辨率
    out = sess.render(long_edge=128, state_extras={"region_masks": masks})
    assert out.shape[:2] == (96, 128)  # 240x320 → long_edge 128
    rec = session_env["probe"].runs[-1]
    shape, dtype, lo, hi = rec["sky"]
    assert shape == (96, 128) and dtype == "float32"
    assert lo >= 0.0 and hi <= 1.0
    sess.close()


def test_session_cache_hit_same_masks_invalidated_on_change(session_env):
    """缓存稳定契约: 注入**已适配的 float 掩码**（loop 的实际形态, 同一批
    数组对象反复注入）→ 跨渲染命中; 内容变化 → 失效。"""
    sess = _sess()
    masks_a = adapt_region_masks({"sky": _top_band_mask(60, 80)}, (96, 128))
    masks_b = adapt_region_masks({"sky": _top_band_mask(30, 40)}, (96, 128))
    sess.render(long_edge=128, state_extras={"region_masks": masks_a})
    sess.render(long_edge=128, state_extras={"region_masks": masks_a})
    assert len(session_env["probe"].runs) == 1, "同掩码二次渲染应命中缓存"
    sess.render(long_edge=128, state_extras={"region_masks": masks_b})
    assert len(session_env["probe"].runs) == 2, "掩码变化必须使缓存失效"
    sess.close()


def test_session_region_masks_attribute_route_b(session_env):
    sess = _sess()
    sess.region_masks = {"sky": _top_band_mask(60, 80)}
    sess.render(long_edge=128)  # 无 state_extras 参数
    rec = session_env["probe"].runs[-1]
    assert rec is not None and rec["sky"][0] == (96, 128)
    # 参数显式带键时以参数为准
    sess.render(long_edge=128, state_extras={
        "region_masks": {"ground": _top_band_mask(60, 80)}})
    rec2 = session_env["probe"].runs[-1]
    assert "sky" not in rec2 and "ground" in rec2
    sess.close()


def test_session_compose_crop_alignment(session_env):
    sess = _sess(compose={"mode": "ratio", "ratio": "1:1"})
    sess.render(long_edge=128, state_extras={
        "region_masks": {"sky": _top_band_mask(60, 80)}})
    rec = session_env["probe"].runs[-1]
    # 96x128 tier → 1:1 裁剪 → 96x96 消费帧
    assert rec["sky"][0] == (96, 96)
    assert session_env["compose"].calls == 1
    sess.close()


# ---------------------------------------------------------------------------
# 4) export 全质量线
# ---------------------------------------------------------------------------

class _CaptureStage(Stage):
    """真 Stage (可进真 Pipeline): 记录 state 概要, 恒等直通。"""

    name = "f13_capture"
    order = 58
    domain_in = None
    domain_out = None

    def __init__(self):
        super().__init__()
        self.records: list[dict] = []

    def wants(self, ctx):
        return True

    def process(self, ctx):
        masks = ctx.state.get("region_masks")
        self.records.append({
            "has_region_masks": isinstance(masks, dict) and bool(masks),
            "shapes": ({k: v.shape for k, v in masks.items()}
                       if isinstance(masks, dict) else None),
            "dtypes": ({k: str(v.dtype) for k, v in masks.items()}
                       if isinstance(masks, dict) else None),
            "img_shape": tuple(ctx.image.shape[:2]),
        })


REGION_PARAMS = {
    "exposure": {"mode": "off"},
    "whitebalance": {"mode": "off"},
    "region_adjust": {"enabled": True,
                      "regions": {"sky": {"exposure": 0.5}}},
}


@pytest.fixture()
def export_env(monkeypatch):
    capture = _CaptureStage()
    real_bdp = presets_mod.build_default_pipeline

    def wrapped(prof=None, params=None, **kw):
        pipe = real_bdp(prof=prof, params=params, **kw)
        pipe.stages.append(capture)
        pipe.stages.sort(key=lambda s: s.order)
        return pipe

    monkeypatch.setattr(presets_mod, "build_default_pipeline", wrapped)
    monkeypatch.setattr(
        io_mod, "decode_raw",
        lambda path, half_size=False: (_gradient_image(240, 320), _FakeRaw()))
    monkeypatch.setattr(io_mod, "camera_neutral_wb_cached",
                        lambda raw, raw_path: None)
    return capture


def test_render_full_quality_state_extras_masks(export_env):
    from pixo.render.web.export import _render_full_quality
    out = _render_full_quality("t.nef", MockProf(), REGION_PARAMS,
                               output_bps=8,
                               state_extras={"region_masks": {
                                   "sky": _top_band_mask(60, 80)}})
    rec = export_env.records[-1]
    assert rec["has_region_masks"]
    assert rec["shapes"]["sky"] == (240, 320)  # 全分辨率消费帧
    assert rec["dtypes"]["sky"] == "float32"
    assert out.shape[:2] == (240, 320)

    # 区域效果: 掩码渲染 vs 无掩码渲染, 区域内增亮、区域外不动
    baseline = _render_full_quality("t.nef", MockProf(), REGION_PARAMS,
                                    output_bps=8)
    band = _top_band_mask(240, 320) > 127
    in_with, out_with = _region_means(out, band)
    in_base, out_base = _region_means(baseline, band)
    assert in_with - in_base > 8.0, "export 线区域内无区域效果"
    assert abs(out_with - out_base) < 3.0, "export 线区域外被误伤"


def test_render_full_quality_no_extras_backward_compatible(export_env):
    from pixo.render.web.export import _render_full_quality
    out = _render_full_quality("t.nef", MockProf(), REGION_PARAMS,
                               output_bps=8)
    rec = export_env.records[-1]
    assert not rec["has_region_masks"], "state_extras=None 不得注入掩码"
    assert out.dtype == np.uint8


class _FakeExportSession:
    def __init__(self, region_masks=None):
        self.raw_path = Path("t.nef")
        self.session_id = "sess1"
        self.prof = MockProf()
        if region_masks is not None:
            self.region_masks = region_masks

    def canonical_params(self):
        return dict(REGION_PARAMS)


@pytest.fixture()
def manager(tmp_path):
    m = ExportManager(MockProf(), work_dir=tmp_path / "exports", max_workers=1)
    yield m
    m.shutdown()


def test_export_manager_forwards_session_region_masks(manager, monkeypatch):
    captured = {}

    def fake_render(raw_path, prof, params, output_bps=8, state_extras=None):
        captured["state_extras"] = state_extras
        return np.zeros((4, 4, 3), dtype=np.uint8)

    monkeypatch.setattr(export_mod, "_render_full_quality", fake_render)
    masks = {"sky": np.zeros((8, 8), np.float32)}
    task = manager.submit(_FakeExportSession(region_masks=masks), fmt="jpeg")
    st = manager.wait(task, timeout=10)
    assert st["status"] == "completed"
    assert captured["state_extras"] == {"region_masks": masks}
    assert captured["state_extras"]["region_masks"] is masks


def test_export_manager_without_masks_keeps_old_call_face(
        manager, monkeypatch):
    """无 region_masks 属性: 不传新参 (旧签名调用面不变)。"""
    def fake_render(raw_path, prof, params, output_bps=8):
        return np.zeros((4, 4, 3), dtype=np.uint8)

    monkeypatch.setattr(export_mod, "_render_full_quality", fake_render)
    task = manager.submit(_FakeExportSession(), fmt="jpeg")
    st = manager.wait(task, timeout=10)
    assert st["status"] == "completed"


# ---------------------------------------------------------------------------
# 5) e2e: 同掩码两线方向一致 + loop 级注入闭环
# ---------------------------------------------------------------------------

def test_backend_preview_export_same_direction():
    """合成后端两线: 同一 uint8 掩码, preview(下采样)与 export(全分辨率)
    区域效果方向一致且量级漂移 < 0.15 EV (tier 口径差门禁)。"""
    backend = SyntheticRenderBackend(
        _gradient_image(96, 128), stages=("compose", "tone", "region_adjust"))
    masks = {"sky": _top_band_mask(24, 32)}  # “分割分辨率”
    backend.state_extras = {"region_masks": masks}

    prev_with = backend.render_preview(REGION_PARAMS, long_edge=48)
    full_with = backend.render_full(REGION_PARAMS)
    backend.state_extras = {}
    prev_base = backend.render_preview(REGION_PARAMS, long_edge=48)
    full_base = backend.render_full(REGION_PARAMS)

    assert prev_with.shape[:2] != full_with.shape[:2]  # 两线分辨率不同
    for out, base, name in ((prev_with, prev_base, "preview"),
                            (full_with, full_base, "export")):
        band = _top_band_mask(out.shape[0], out.shape[1]) > 127
        in_with, out_with = _region_means(out, band)
        in_base, out_base = _region_means(base, band)
        assert in_with - in_base > 5.0, f"{name} 线区域内无效果"
        assert abs(out_with - out_base) < 3.0, f"{name} 线区域外被误伤"

    ratios = []
    for out, base in ((prev_with, prev_base), (full_with, full_base)):
        band = _top_band_mask(out.shape[0], out.shape[1]) > 127
        in_with, _ = _region_means(out, band)
        in_base, _ = _region_means(base, band)
        ratios.append(in_with / in_base)
    drift = abs(np.log2(ratios[0]) - np.log2(ratios[1]))
    assert drift < 0.15, f"两线区域效果量级漂移 {drift:.4f} EV 超限"


class _RecordingBackend(SyntheticRenderBackend):
    """记录每次渲染的 state_extras 掩码概要与输出 (loop 级观测)。

    stages 追加 _CaptureStage 实例 (order=58, 恒等直通) —— 在**消费点**记录
    ctx.state["region_masks"] 的适配后 shape/dtype (backend 内部适配的
    真实结果), 与 state_extras 快照 (注入面) 互补。
    """

    def __init__(self, img, stages):
        self.capture = _CaptureStage()
        super().__init__(img, stages=list(stages) + [self.capture])
        self.calls: list[dict] = []

    @staticmethod
    def _snapshot(extras):
        rm = getattr(extras, "get", lambda *a: None)("region_masks")
        if not isinstance(rm, dict) or not rm:
            return None
        return {k: (v.shape, str(v.dtype)) for k, v in rm.items()}

    def render_preview(self, params, long_edge=512):
        out = super().render_preview(params, long_edge=long_edge)
        self.calls.append({"kind": "preview",
                           "masks": self._snapshot(self.state_extras),
                           "out": out})
        return out

    def render_full(self, params):
        out = super().render_full(params)
        self.calls.append({"kind": "full",
                           "masks": self._snapshot(self.state_extras),
                           "out": out})
        return out

    def consumed_records(self, img_shape):
        """消费点记录中, 图像 shape == img_shape 的条目 (按渲染线分流)。"""
        return [r for r in self.capture.records
                if r["img_shape"] == tuple(img_shape)]


def _run_loop(backend, image, max_iterations=2):
    loop = SinglePhotoLoop(
        render_backend=backend,
        segmenter=MockSegmenter(),
        prompts=["sky"],
        preview_long_edge=48,
        max_iterations=max_iterations,
        jnd_threshold=None,
        manual_on_unreliable=False,
    )
    return loop.run("f13-e2e", image_rgb=image,
                    params={"region_adjust": {
                        "enabled": True,
                        "regions": {"sky": {"exposure": 0.5}}}})


def test_loop_injects_masks_preview_and_export_lines():
    """loop 闭环: 首轮渲染无掩码 → 分割后 preview 粘性注入 (消费帧 shape,
    float32) → FINAL_QC 导出线注入 (全分辨率 shape), 两线效果方向一致。"""
    image = _gradient_image(96, 128)
    backend = _RecordingBackend(
        image, stages=("compose", "tone", "region_adjust"))
    result = _run_loop(backend, image)

    previews = [c for c in backend.calls if c["kind"] == "preview"]
    fulls = [c for c in backend.calls if c["kind"] == "full"]
    assert len(previews) >= 2, "两轮迭代各渲染一次 preview"
    assert previews[0]["masks"] is None, "首轮渲染在分割之前, 无掩码"
    assert previews[1]["masks"] is not None
    shape, dtype = previews[1]["masks"]["sky"]
    assert shape == previews[1]["out"].shape[:2]
    assert dtype == "float32"

    assert result.state == "ACCEPTED"
    assert fulls, "FINAL_QC 必须发生全分辨率渲染"

    # 消费点 (order=58 捕获): 两线掩码均为 float32 且 shape == 各自消费帧
    prev_consumed = backend.consumed_records(previews[1]["out"].shape[:2])
    full_consumed = backend.consumed_records((96, 128))
    assert prev_consumed, "preview 线消费点无记录"
    rec = prev_consumed[-1]
    assert rec["has_region_masks"]
    assert rec["shapes"]["sky"] == previews[1]["out"].shape[:2]
    assert rec["dtypes"]["sky"] == "float32"
    assert full_consumed, "export 线消费点无记录"
    frec = full_consumed[-1]
    assert frec["shapes"]["sky"] == (96, 128)
    assert frec["dtypes"]["sky"] == "float32"
    assert result.final_image.shape[:2] == (96, 128)

    # 方向一致: 两线同掩码同方向增亮且量级漂移受限
    band_p = _top_band_mask(previews[1]["out"].shape[0],
                            previews[1]["out"].shape[1]) > 127
    p_with, _ = _region_means(previews[1]["out"], band_p)
    p_base, _ = _region_means(previews[0]["out"], band_p)
    band_f = _top_band_mask(96, 128) > 127
    f_with, _ = _region_means(result.final_image, band_f)
    # 导出线基线: 同最终参数、无掩码的全分辨率渲染
    backend.state_extras = {}
    f_base_img = backend.render_full(result.params)
    f_base, _ = _region_means(f_base_img, band_f)
    assert p_with - p_base > 5.0, "preview 线区域无效果"
    assert f_with - f_base > 5.0, "export 线区域无效果"
    drift = abs(np.log2(p_with / p_base) - np.log2(f_with / f_base))
    assert drift < 0.15, f"两线效果量级漂移 {drift:.4f} EV 超限"


def test_loop_single_iteration_final_qc_still_injects():
    """max_iterations=1: 首轮注入发生在分割前 → FINAL_QC 的刷新必须补齐
    导出线掩码 (否则单轮闭环 preview/export 掩码语义分叉)。"""
    image = _gradient_image(96, 128)
    backend = _RecordingBackend(
        image, stages=("compose", "tone", "region_adjust"))
    result = _run_loop(backend, image, max_iterations=1)

    assert result.state == "ACCEPTED"
    previews = [c for c in backend.calls if c["kind"] == "preview"]
    fulls = [c for c in backend.calls if c["kind"] == "full"]
    assert len(previews) == 1 and previews[0]["masks"] is None
    assert fulls and fulls[-1]["masks"] is not None, \
        "单轮闭环 FINAL_QC 前必须刷新 state_extras 掩码"
    # 消费点: 全分辨率帧上确实拿到了掩码
    full_consumed = backend.consumed_records((96, 128))
    assert full_consumed and full_consumed[-1]["has_region_masks"]
    assert full_consumed[-1]["shapes"]["sky"] == (96, 128)
    band = _top_band_mask(96, 128) > 127
    f_with, _ = _region_means(result.final_image, band)
    backend.state_extras = {}
    base = backend.render_full(result.params)
    f_base, _ = _region_means(base, band)
    assert f_with - f_base > 5.0, "单轮闭环导出线区域无效果"


# ---------------------------------------------------------------------------
# 6) I-2 记债钉现状 (M1 评审): free 像素矩形跨分辨率几何失配
# ---------------------------------------------------------------------------

def test_free_px_rect_cross_resolution_geometry_mismatch_recorded():
    """I-2 / tech_debt #17 —— 现状行为钉死 (已知记录, 非正确性断言)。

    free 模式 x/y/width/height 为全画布**像素**矩形: 同一 px-rect 在两个
    渲染分辨率下相对裁剪窗不同 (本例 x0 占比 50% vs 25%)。掩码适配只做
    shape 对齐不做坐标重映射 → 两线消费帧 shape 相同 (px-rect 裁出同尺寸
    窗) 时, 适配器给出**逐位相同**的掩码 —— 同一掩码坐标在两线对应不同
    场景内容, 区域效果落点错位 (tech_debt #17 登记的失配)。

    契约: 未来 compose px→相对坐标归一化或适配器坐标重映射清偿本债时,
    本用例应**有意翻转重写** (断言两线掩码不同/几何一致), 不得静默通过。
    """
    from pixo.render.modules.compose import compute_crop_rect

    compose = {"mode": "free", "x": 50.0, "y": 0.0, "width": 50.0,
               "height": 50.0}
    # 两线: preview tier (100×50 帧) 与导出 (200×100 帧), 同 px-rect 参数
    line_a = adapt_region_masks({"sky": _top_band_mask(50, 100)},
                                (50, 100), compose)
    line_b = adapt_region_masks({"sky": _top_band_mask(100, 200)},
                                (100, 200), compose)
    # 现状: px-rect 尺寸与入参分辨率解耦 → 两线消费帧 shape 相同,
    # 掩码被同构 resize → 逐位相同 (失配的可观测面)
    assert line_a["sky"].shape == line_b["sky"].shape == (50, 50)
    assert np.array_equal(line_a["sky"], line_b["sky"]), (
        "若本断言失败, 说明适配器/compose 已做坐标重映射 —— "
        "tech_debt #17 可能已清偿, 请翻转重写本用例")
    # 而两线真实相对裁剪窗不同 (同一掩码坐标 ≠ 同一场景内容)
    ra = compute_crop_rect(50, 100, "free", x=50.0, y=0.0,
                           width=50.0, height=50.0)
    rb = compute_crop_rect(100, 200, "free", x=50.0, y=0.0,
                           width=50.0, height=50.0)
    rel_a = ra[0] / 100.0
    rel_b = rb[0] / 200.0
    assert abs(rel_a - 0.5) < 1e-6 and abs(rel_b - 0.25) < 1e-6
    assert rel_a != rel_b
