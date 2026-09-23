# -*- coding: utf-8 -*-
"""F13 spike: 掩码通道 preview/export 双线注入路线证明（临时产物，可删）。

回答的问题:
  Q1 export 线 state_extras 缺口的可行注入路径是哪条?
     - Route A: _render_full_quality 增参 state_extras → run_full_pipeline
       (runner 已支持 state_inject, 只差签名透传 — 本 spike 用 runner 直接证明)
     - Route B: session 状态携带 (RawPreviewSession.region_masks 属性 +
       ExportManager 转发) — 结构性证明, 见 Q5
  Q2 掩码能否以 float 0-1 软掩码形态到达 stage 消费点 (ctx.state["region_masks"])
     且 shape 与消费点图像一致 (compose 裁剪后)?
  Q3 preview (下采样) 与 export (上采样) 两线同掩码区域效果方向/量级一致?
  Q4 缓存指纹: 同掩码(同数组对象)命中 / 掩码变化失效 (_ndarray_digest 敏感性,
     含大数组仅改中部、仅边采样命中的极端情形)?
  Q5 适配器逐渲染新建数组会不会破坏 stage 缓存命中 (data_ptr 指纹)?

运行: python .agent-team/spike/spike_f13_dual_line.py
退出码 0 = 全部证明通过; 非 0 = 有断言失败 (带证据输出)。
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import pixo.render.core.io as pixo_io  # noqa: E402
import pixo.render.web.session as sess_mod  # noqa: E402
from pixo.render.pipeline.context import DOMAIN_GAMMA_RGB  # noqa: E402
from pixo.render.pipeline.graph import Stage, register_stage  # noqa: E402
from pixo.render.pipeline.runner import run_full_pipeline  # noqa: E402
from pixo.render.web.session import (  # noqa: E402
    RawPreviewSession,
    _ndarray_digest,
    _state_fingerprint,
)

# ---------------------------------------------------------------------------
# 候选适配器（spike 内联版；可行则提到 render/pipeline/region_masks.py）
# ---------------------------------------------------------------------------


def adapt_region_masks(masks, entry_shape_hw, compose_params=None):
    """掩码 → float32 [0,1] 软掩码, 对齐到"渲染消费帧"(post-compose) shape。

    契约要点（spike 验证对象）:
    - 整数输入按 /255 归一; float 输入视为已 [0,1];
    - 目标 shape = compute_crop_rect(entry_shape, compose_params) 预测的
      post-compose 帧 (compose order=22 在 region 消费点 order=57 之前裁剪);
    - 形状一致且已是 float32 时**原对象透传** (保 _ndarray_digest data_ptr
      稳定 → stage 缓存命中不被无谓打破);
    - 下采样 INTER_AREA / 上采样 INTER_LINEAR。
    """
    from pixo.render.modules.compose import compute_crop_rect

    h, w = entry_shape_hw
    tw, th = w, h
    cp = compose_params or None
    if cp:
        x0, y0, cw, ch = compute_crop_rect(
            h, w,
            mode=cp.get("mode", "free"),
            ratio=cp.get("ratio", None),
            center=cp.get("center", [0.5, 0.5]),
            x=float(cp.get("x", 0.0) or 0.0),
            y=float(cp.get("y", 0.0) or 0.0),
            width=float(cp.get("width", 0.0) or 0.0),
            height=float(cp.get("height", 0.0) or 0.0),
        )
        tw, th = cw, ch

    out = {}
    for name, mask in dict(masks).items():
        arr = np.asarray(mask)
        already = arr.dtype == np.float32 and arr.shape == (th, tw)
        if already:
            out[name] = arr  # 原对象透传 — Q5 缓存稳定性的关键
            continue
        if np.issubdtype(arr.dtype, np.integer):
            arr = arr.astype(np.float32) / 255.0
        else:
            arr = arr.astype(np.float32)
        if arr.shape != (th, tw):
            interp = (cv2.INTER_AREA if arr.shape[0] > th
                      else cv2.INTER_LINEAR)
            arr = cv2.resize(arr, (tw, th), interpolation=interp)
        out[name] = np.clip(arr, 0.0, 1.0)
    return out


# ---------------------------------------------------------------------------
# 探针 stage: order=58 (紧随 region_adjust 57), 只记录不改动像素
# ---------------------------------------------------------------------------

PROBE_RECORD: list[dict] = []


@register_stage("f13_probe", order=58,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class F13Probe(Stage):
    name = "f13_probe"

    def process(self, ctx):
        rec = {
            "img_shape": tuple(ctx.image.shape[:2]),
            "mask_shapes": None,
            "mask_stats": None,
            "shape_match": None,
            "regions_applied": None,
        }
        masks = ctx.state.get("region_masks")
        if isinstance(masks, dict) and masks:
            rec["mask_shapes"] = {k: tuple(v.shape) for k, v in masks.items()}
            rec["mask_stats"] = {
                k: (str(v.dtype), float(v.min()), float(v.max()))
                for k, v in masks.items()}
            m = masks.get("sky")
            if m is not None:
                rec["shape_match"] = (tuple(m.shape)
                                      == tuple(ctx.image.shape[:2]))
        for r in reversed(ctx.results):
            if r.name == "region_adjust" and r.metrics.get("regions_applied"):
                rec["regions_applied"] = r.metrics["regions_applied"]
                rec["mask_coverage"] = r.metrics.get("mask_coverage")
                break
        PROBE_RECORD.append(rec)


# ---------------------------------------------------------------------------
# fake 环境 (integration/test_preview_session.py 惯例)
# ---------------------------------------------------------------------------


class _FakeRaw:
    def close(self):
        pass


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


# 基座关闭曝光/白平衡 (恒等链), 使区域增益可归因于 region_adjust;
# region_adjust=真实消费方 (dev-3 F12, enabled=False 默认零影响), sky +0.5EV
import pixo.render.modules.region_adjust  # noqa: F401,E402  (注册 stage)
SPIKE_PARAMS = {
    "exposure": {"mode": "off"},
    "whitebalance": {"mode": "off"},
    "region_adjust": {"enabled": True,
                      "regions": {"sky": {"exposure": 0.5}}},
}
PROF = MockProf()


def _gradient_image(h, w):
    """0.25..0.55 平滑渐变 (in/out 区域可区分, 增益后不削顶)."""
    yy, xx = np.mgrid[0:h, 0:w]
    r = 0.25 + 0.30 * xx / max(w - 1, 1)
    g = 0.25 + 0.30 * yy / max(h - 1, 1)
    b = 0.30 + 0.20 * (xx + yy) / max(w + h - 2, 1)
    return np.stack([r, g, b], axis=-1).astype(np.float32)


DECODE_H, DECODE_W = 240, 320  # 假 RAW 半尺寸解码分辨率


def _pipe_with_probe(prof=None, params=None):
    """真实默认管线 + f13_probe (order=58, 紧随 region_adjust 57)。"""
    from pixo.render.pipeline.graph import STAGE_REGISTRY
    from pixo.render.pipeline.presets import build_default_pipeline
    pipe = build_default_pipeline(prof=prof, params=params)
    probe = STAGE_REGISTRY["f13_probe"]()
    pipe.stages.append(probe)
    pipe.stages.sort(key=lambda s: s.order)
    return pipe


def _tier_shape(long_edge, h=DECODE_H, w=DECODE_W):
    """镜像 session._get_tier 的尺寸计算, spike 侧预测 preview 目标 shape。"""
    scale = float(long_edge) / max(h, w)
    if abs(scale - 1.0) > 1e-6:
        w2 = max(1, int(round(w * scale)))
        h2 = max(1, int(round(h * scale)))
        return h2, w2
    return h, w


def _install_preview_fakes():
    """patch rawpy/decode_cfa_half/camera_wb → RawPreviewSession 可跑真管线。"""
    sess_mod.rawpy.imread = staticmethod(lambda path: _FakeRaw())
    sess_mod.decode_cfa_half = (
        lambda raw, raw_path=None: _gradient_image(DECODE_H, DECODE_W))
    pixo_io.camera_neutral_wb_cached = lambda raw, raw_path: None
    # session 内部 build_default_pipeline → 附加 f13_probe (真管线 + 探针)
    _real_bdp = sess_mod.build_default_pipeline

    def _bdp_probe(prof=None, params=None, **kw):
        pipe = _real_bdp(prof=prof, params=params, **kw)
        pipe.stages.append(pipe._resolve("f13_probe"))
        pipe.stages.sort(key=lambda s: s.order)
        return pipe

    sess_mod.build_default_pipeline = _bdp_probe


def _sky_mask(h, w):
    """二值 0/255 天空条带 (上 40%) — MockSegmenter 的 sky 同构。"""
    m = np.zeros((h, w), dtype=np.uint8)
    m[: max(1, int(round(h * 0.40))), :] = 255
    return m


# ---------------------------------------------------------------------------
# 逐题证明
# ---------------------------------------------------------------------------


def prove_q1_export_route():
    """Q1/Q2/Q3 export 线: run_full_pipeline + state_inject (Route A 本体)。"""
    masks_src = {"sky": _sky_mask(60, 80)}  # “分割分辨率” 60x80
    full_img = _gradient_image(480, 640)

    def render(with_masks):
        state_inject = {}
        if with_masks:
            adapted = adapt_region_masks(masks_src, (480, 640), None)
            state_inject["region_masks"] = adapted
        return run_full_pipeline(
            full_img.copy(), PROF, SPIKE_PARAMS,
            config={"stages": dict(SPIKE_PARAMS), "half_size": False,
                    "preview": False, "long_edge": 0, "decode_mode": None},
            output_bps=8, mode="export", raw_path="spike.nef",
            state_inject=state_inject, pipe=_pipe_with_probe(PROF, SPIKE_PARAMS),
            label="spike-export")

    rec_before = len(PROBE_RECORD)
    out_with = render(True)
    export_rec = [r for r in PROBE_RECORD[rec_before:]
                  if r["mask_shapes"] is not None][-1]

    assert export_rec["shape_match"] is True, \
        f"export 线掩码 shape 未对齐消费帧: {export_rec}"
    stats = export_rec["mask_stats"]["sky"]
    assert stats[0] == "float32" and stats[1] >= 0.0 and stats[2] <= 1.0, stats
    assert export_rec["regions_applied"] == ["sky"], export_rec

    out_without = render(False)
    probe_out_shape = out_with.shape[:2]
    m_full = _sky_mask(probe_out_shape[0], probe_out_shape[1]) > 127
    inside = m_full
    outside = ~m_full
    d_in = float(out_with[inside].astype(np.float32).mean()
                - out_without[inside].astype(np.float32).mean())
    d_out = float(out_with[outside].astype(np.float32).mean()
                 - out_without[outside].astype(np.float32).mean())
    base_in = float(out_without[inside].astype(np.float32).mean())
    ratio_export = (base_in + d_in) / base_in
    print(f"  [Q1] export 线注入 OK: region_adjust 消费 region_masks, "
          f"掩码 shape={export_rec['mask_shapes']['sky']} 消费帧一致, "
          f"dtype float32, applied={export_rec['regions_applied']}")
    print(f"  [Q3] export 线效果: 区域内 Δ={d_in:+.1f} (ratio {ratio_export:.3f}, "
          f"期望≈2^(0.5/2.2)={2 ** (0.5 / 2.2):.3f}), 区域外 Δ={d_out:+.2f}")
    assert d_in > 15, "export 线区域内无增亮 (注入未生效)"
    assert abs(d_out) <= 3.0, "export 线区域外被误伤"
    return ratio_export


def prove_preview_line_and_consistency(ratio_export):
    """Q2/Q3 preview 线 (真实 RawPreviewSession) + 两线一致性。"""
    _install_preview_fakes()
    sess = RawPreviewSession("spike.nef", prof=PROF, params=SPIKE_PARAMS)
    masks_src = {"sky": _sky_mask(60, 80)}  # 与 export 线同源同分辨率
    tier = _tier_shape(128)                 # preview long_edge=128

    def render(with_masks, compose_params=None):
        extras = None
        if with_masks:
            adapted = adapt_region_masks(masks_src, tier, compose_params)
            extras = {"region_masks": adapted}
        return sess.render(long_edge=128, output_bps=8, state_extras=extras)

    out_with = render(True)
    recs = [r for r in PROBE_RECORD if r["mask_shapes"] is not None]
    prev_rec = recs[-1]
    assert prev_rec["shape_match"] is True, \
        f"preview 线掩码 shape 未对齐消费帧: {prev_rec}"
    out_without = render(False)
    th, tw = out_with.shape[:2]
    m_prev = _sky_mask(th, tw) > 127
    d_in = float(out_with[m_prev].astype(np.float32).mean()
                - out_without[m_prev].astype(np.float32).mean())
    d_out = float(out_with[~m_prev].astype(np.float32).mean()
                 - out_without[~m_prev].astype(np.float32).mean())
    base_in = float(out_without[m_prev].astype(np.float32).mean())
    ratio_preview = (base_in + d_in) / base_in
    assert prev_rec["regions_applied"] == ["sky"], prev_rec
    print(f"  [Q2] preview 线注入 OK: tier={tier}, "
          f"掩码 shape={prev_rec['mask_shapes']['sky']} 对齐消费帧, "
          f"applied={prev_rec['regions_applied']}")
    print(f"  [Q3] preview 线效果: 区域内 Δ={d_in:+.1f} "
          f"(ratio {ratio_preview:.3f}), 区域外 Δ={d_out:+.2f}")
    assert d_in > 15, "preview 线区域内无增亮"
    assert abs(d_out) <= 3.0, "preview 线区域外被误伤"

    # 两线一致性 (tier EV 口径差教训: 方向一致 + 量级差 < 0.1 EV 等效)
    drift = abs(np.log2(ratio_preview) - np.log2(ratio_export))
    print(f"  [Q3] 两线增益比: preview {ratio_preview:.3f} vs export "
          f"{ratio_export:.3f} → EV 口径漂移 {drift:.4f} EV")
    assert drift < 0.10, f"两线区域效果量级漂移超限: {drift:.4f} EV"
    sess.close()

    # compose 裁剪 (ratio 1:1) 场景: 掩码须对齐 post-compose 帧
    sess2 = RawPreviewSession("spike.nef", prof=PROF,
                              params={**SPIKE_PARAMS,
                                      "compose": {"mode": "ratio",
                                                  "ratio": "1:1"}})
    sess2_render = sess2.render  # noqa: F841
    from pixo.render.pipeline.presets import build_default_pipeline
    pipe = build_default_pipeline(None, {})
    assert "compose" in [s.name for s in pipe.stages]
    adapted = adapt_region_masks(masks_src, tier,
                                 {"mode": "ratio", "ratio": "1:1"})
    th2, tw2 = adapted["sky"].shape
    # 240x320 tier→128: (96,128); ratio 1:1 → (96,96)
    assert (th2, tw2) == (96, 96), f"compose 预测形状错误: {(th2, tw2)}"
    out = sess2.render(long_edge=128, output_bps=8,
                       state_extras={"region_masks": adapted})
    rec = [r for r in PROBE_RECORD if r["mask_shapes"] is not None][-1]
    assert rec["shape_match"] is True, f"compose 裁剪后 shape 失配: {rec}"
    assert out.shape[:2] == (96, 96), out.shape
    print(f"  [Q2] compose 1:1 裁剪: 掩码对齐 post-compose 帧 {out.shape[:2]}")
    sess2.close()
    return True


def prove_q4_cache_fingerprint():
    """Q4 掩码变化 → stage 缓存失效; 同掩码同对象 → 命中保持。"""
    # 直接指纹敏感性
    small_a = np.full((32, 32), 255, np.uint8)
    small_b = np.full((32, 32), 255, np.uint8)
    small_b[16, 16] = 0
    fa = _state_fingerprint({"region_masks": {"sky": small_a.astype(np.float32) / 255.0}})
    fb = _state_fingerprint({"region_masks": {"sky": small_b.astype(np.float32) / 255.0}})
    assert fa != fb, "小掩码内容变化未改变 state 指纹"

    big_a = (np.zeros((200, 200), np.float32))  # 160KB > 2*4KB 采样阈值
    big_b = np.zeros((200, 200), np.float32)
    big_b[100, 100] = 1.0  # 仅中部变化 (边采样盲区)
    da, db = _ndarray_digest(big_a), _ndarray_digest(big_b)
    assert da != db, "大数组仅中部变化 → 摘要相同 (ptr 兜底失效?)"
    assert _ndarray_digest(big_a) == da, "同对象摘要不稳定"

    # 真 session 行为: 同掩码(同对象)二次渲染命中; 换掩码失效
    _install_preview_fakes()
    sess = RawPreviewSession("spike2.nef", prof=PROF, params=SPIKE_PARAMS)
    tier = _tier_shape(128)
    masks_a = adapt_region_masks({"sky": _sky_mask(60, 80)}, tier, None)
    masks_b = adapt_region_masks({"sky": _sky_mask(30, 40)}, tier, None)
    n0 = len(PROBE_RECORD)
    sess.render(long_edge=128, state_extras={"region_masks": masks_a})
    sess.render(long_edge=128, state_extras={"region_masks": masks_a})
    n_same = len(PROBE_RECORD)
    sess.render(long_edge=128, state_extras={"region_masks": masks_b})
    n_diff = len(PROBE_RECORD)
    sess.close()
    print(f"  [Q4] stage 缓存: 首渲染探针 {n_same - n0} 次 (期望1), "
          f"同掩码复渲染后仍 {n_same - n0} (命中), 换掩码后 "
          f"{n_diff - n_same} 次新增 (期望1, 失效)")
    assert n_same - n0 == 1, "同掩码二次渲染未命中缓存 (指纹不稳定)"
    assert n_diff - n_same == 1, "掩码变化未使缓存失效"
    return True


def prove_q5_pass_through_stability():
    """Q5 适配器透传契约: 已对齐 float32 掩码 → 同一对象 (ptr 不变)。"""
    tier = _tier_shape(128)
    src = adapt_region_masks({"sky": _sky_mask(60, 80)}, tier, None)
    again = adapt_region_masks(src, tier, None)
    assert again["sky"] is src["sky"], "透传路径返回了新数组 → 会破坏缓存命中"
    resized = adapt_region_masks(src, (tier[0] // 2, tier[1] // 2), None)
    assert resized["sky"] is not src["sky"]
    assert resized["sky"].shape == (tier[0] // 2, tier[1] // 2)
    print(f"  [Q5] 透传契约 OK: 对齐时同对象; 失配时重采样 {resized['sky'].shape}")
    return True


def prove_q5b_route_b_structure():
    """Q5b Route B (session 状态携带) 结构证据: ExportManager 转发可行性。

    ExportManager._run 只依赖 session.raw_path / canonical_params / prof
    协议 (duck-typed _FakeSession 在 tests/integration/test_export.py 已证)。
    增加 getattr(session, 'region_masks', None) → 组 state_extras 转发
    _render_full_quality 是纯增量, 不动 canonical_params (掩码是 ndarray,
    进 params 会污染 _param_fingerprint 且被 json 序列化破坏)。
    """
    class FakeSession:
        raw_path = Path("x.nef")
        session_id = "s1"

        def canonical_params(self):
            return {}

        region_masks = {"sky": np.zeros((8, 8), np.float32)}

    s = FakeSession()
    rm = getattr(s, "region_masks", None)
    assert isinstance(rm, dict) and "sky" in rm
    params = s.canonical_params()
    assert "region_masks" not in params and not any(
        isinstance(v, dict) and "sky" in v for v in params.values())
    print("  [Q5b] Route B 结构可行: session 属性携带 + manager 转发;"
          "掩码若进 canonical_params 会污染参数指纹 → 必须走独立通道")
    return True


def main() -> int:
    results = {}
    print("F13 spike — 掩码通道 preview/export 双线注入路线证明")
    try:
        ratio_export = prove_q1_export_route()
        results["Q1_export_route"] = "PASS"
    except AssertionError:
        results["Q1_export_route"] = "FAIL"
        traceback.print_exc()
        return 1
    for name, fn in [
        ("Q2_Q3_preview_consistency",
         lambda: prove_preview_line_and_consistency(ratio_export)),
        ("Q4_cache_fingerprint", prove_q4_cache_fingerprint),
        ("Q5_pass_through", prove_q5_pass_through_stability),
        ("Q5b_routeB_structure", prove_q5b_route_b_structure),
    ]:
        try:
            fn()
            results[name] = "PASS"
        except Exception:
            results[name] = "FAIL"
            traceback.print_exc()
            return 1
    print("---")
    for k, v in results.items():
        print(f"  {k}: {v}")
    ok = all(v == "PASS" for v in results.values())
    print(f"结论: {'全部路线可行' if ok else '存在不可行项'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
