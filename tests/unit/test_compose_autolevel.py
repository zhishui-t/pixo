"""t28 compose.auto_level 地平线检测 —— 合成场景单测。

覆盖: 斜线场景恢复角误差 ≤0.5°、无直线场景恒等回退 (人像/静物不动构图)、
|θ|>8° 超角钳制回退、min_confidence 门限、几何元数据与 trace 字段完整。
"""
from __future__ import annotations

import numpy as np

from pixo.render.modules.compose import (AUTO_LEVEL_MAX_ANGLE, ComposeStage,
                                         detect_horizon_angle)
from pixo.render.pipeline.context import DOMAIN_LINEAR_RGB, StageContext


def _scene(h: int = 240, w: int = 320, phi_deg: float = 4.0,
           c: float = 120) -> np.ndarray:
    """天空亮/地面暗的合成斜线场景; 边界行 r(x)=c+tan(phi)*x。"""
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]
    b = c + np.tan(np.radians(phi_deg)) * xx
    m = (yy >= b).astype(np.float32)
    img = np.empty((h, w, 3), dtype=np.float32)
    img[:] = (1.0 - m[..., None]) * 0.6 + m[..., None] * 0.08
    return img


def _run(img: np.ndarray, params: dict) -> StageContext:
    ctx = StageContext("t.NEF", raw=None, prof=None,
                       config={"stages": {"compose": dict(params)}})
    ctx.set_image(np.ascontiguousarray(img), DOMAIN_LINEAR_RGB)
    ComposeStage().run(ctx)
    return ctx


def test_slanted_horizon_recovered_within_half_degree():
    for phi in (-5.5, -2.0, 3.0, 4.0, 6.5):
        img = _scene(phi_deg=phi)
        ctx = _run(img, {"mode": "auto_level"})
        g = ctx.state["compose"]
        assert abs(g["auto_level_detected_angle"] - phi) <= 0.5, phi
        assert g["auto_level_confidence"] == "high"
        assert abs(g["rotation"] - phi) <= 0.5
        t = np.asarray(g["affine_matrix"], dtype=np.float64)
        assert not np.allclose(t, np.eye(2, 3), atol=1e-6)
        # 摆平后复检应≈水平 (符号约定自洽)
        phi2, _ = detect_horizon_angle(ctx.image)
        assert abs(phi2) <= 0.75, (phi, phi2)


def test_no_line_scene_identity_fallback():
    """无地平线场景 (平滑渐变≈人像特写/静物): 不动构图, 恒等回退。"""
    img = np.tile(np.linspace(0.5, 0.1, 240, dtype=np.float32)[:, None],
                  (1, 320, 3))
    ctx = _run(img, {"mode": "auto_level"})
    g = ctx.state["compose"]
    assert g["rotation"] == 0.0
    assert g["auto_level_confidence"] == "low"
    assert np.array_equal(ctx.image, img)          # 逐位一致
    assert np.allclose(np.asarray(g["transform_matrix"]),
                       np.eye(2, 3), atol=1e-9)
    metrics = ctx.results[-1].metrics
    assert metrics["changed"] is False


def test_over_angle_clamped_to_identity():
    """20° 斜线超出 |θ|≤8° 钳制: 回退 θ=0, 标注 low, 记录原始检测角。"""
    img = _scene(phi_deg=20.0, c=100)
    phi, conf = detect_horizon_angle(img)
    assert abs(phi) > AUTO_LEVEL_MAX_ANGLE         # 检出超角
    ctx = _run(img, {"mode": "auto_level"})
    g = ctx.state["compose"]
    assert g["rotation"] == 0.0
    assert g["auto_level_confidence"] == "low"
    assert abs(g["auto_level_detected_angle"]) > AUTO_LEVEL_MAX_ANGLE
    assert np.array_equal(ctx.image, img)


def test_min_confidence_gate():
    """min_confidence 可调: 高门限把可靠检测也判为低置信回退。"""
    img = _scene(phi_deg=4.0)
    ctx = _run(img, {"mode": "auto_level", "min_confidence": 0.99})
    g = ctx.state["compose"]
    assert g["auto_level_confidence"] == "low"
    assert g["rotation"] == 0.0
    assert np.array_equal(ctx.image, img)
    ctx2 = _run(img, {"mode": "auto_level", "min_confidence": 0.0})
    assert ctx2.state["compose"]["auto_level_confidence"] == "high"


def test_metadata_fields_complete():
    img = _scene(phi_deg=3.0)
    ctx = _run(img, {"mode": "auto_level"})
    g = ctx.state["compose"]
    for key in ("auto_level", "auto_level_detected_angle",
                "auto_level_applied", "auto_level_confidence",
                "auto_level_confidence_value", "original_size",
                "final_size", "crop_rect", "transform_matrix",
                "affine_matrix", "border_mode"):
        assert key in g, key
    assert g["auto_level"] is True
    assert ctx.state.get("compose_geometry") is g
    m = ctx.results[-1].metrics
    assert m["changed"] is True and m["rotation"] == g["rotation"]


def test_other_modes_untouched_by_autolevel_fields():
    """非 auto_level 模式元数据不带 auto_level_* 字段 (行为兼容)。"""
    img = _scene(phi_deg=4.0)
    ctx = _run(img, {"mode": "free"})
    g = ctx.state["compose"]
    assert not any(k.startswith("auto_level") for k in g)
