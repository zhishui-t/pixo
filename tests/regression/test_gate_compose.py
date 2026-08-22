"""Gate: compose（构图前置：裁剪/翻转/旋转）功能性质 + 几何元数据。"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

import pixo.render.modules  # noqa: F401  (触发 Stage 注册)

from pixo.render.modules.compose import ComposeStage
from pixo.render.pipeline import available_stages
from pixo.render.pipeline.graph import DOMAIN_LINEAR_RGB, StageContext

pytestmark = pytest.mark.gate


def _make_img(h=48, w=64, seed=20260820):
    rng = np.random.default_rng(seed)
    return rng.random((h, w, 3), dtype=np.float32)


def _run_compose(img, **params):
    ctx = StageContext("x.NEF", config={"stages": {"compose": params}})
    ctx.set_image(img.copy(), DOMAIN_LINEAR_RGB)
    ComposeStage().run(ctx)
    return ctx, ctx.image


def _psnr(a, b):
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    mse = float(np.mean((a - b) ** 2))
    if mse == 0.0:
        return float("inf")
    return 10.0 * np.log10(1.0 / mse)


def _gradient_image(h=240, w=360):
    """平滑渐变合成图：避免硬边，适合预览/全尺寸缩放 A/B。"""
    x = np.linspace(0.0, 1.0, w, dtype=np.float32)
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    return np.stack([xx, yy, (xx + yy) / 2.0], axis=-1).astype(np.float32)


def _resize_long_edge(img, long_edge):
    """按项目预览口径：长边缩到 long_edge（短边等比缩放）。"""
    h, w = img.shape[:2]
    scale = float(long_edge) / max(h, w)
    if abs(scale - 1.0) < 1e-9:
        return img.copy()
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _ab_diff_metrics(a, b):
    """计算两幅 float linear 图的 8bit 通道 P50/P99 绝对差。"""
    a8 = (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8).astype(np.int16)
    b8 = (np.clip(b, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8).astype(np.int16)
    d = np.abs(a8 - b8).astype(np.float64)
    return {
        ch: {"p50": float(np.percentile(d[..., i], 50)),
             "p99": float(np.percentile(d[..., i], 99))}
        for i, ch in enumerate("rgb")
    }


def test_compose_registered_order_and_domain():
    stages = available_stages()
    assert "compose" in stages
    assert stages["compose"].order == 22
    assert stages["compose"].domain_in == DOMAIN_LINEAR_RGB
    assert stages["compose"].domain_out == DOMAIN_LINEAR_RGB
    # 顺序: whitebalance(20) < compose(22) < huesat(25)
    assert stages["compose"].order < stages["huesat"].order


def test_crop_bit_exact():
    img = _make_img()
    ctx, out = _run_compose(img, mode="free", x=7, y=5, width=20, height=15)
    ref = img[5:20, 7:27]
    assert out.shape == ref.shape
    assert np.array_equal(out, ref), "纯裁剪必须逐位一致"
    meta = ctx.state["compose"]
    assert meta["crop_rect"] == {"x": 7, "y": 5, "width": 20, "height": 15}
    assert meta["final_size"] == [15, 20]


def test_flip_bit_exact():
    img = _make_img()
    ctx, out = _run_compose(img, mode="free", x=2, y=3, width=16, height=12,
                            horizontal_flip=True, vertical_flip=True)
    ref = img[3:15, 2:18]
    ref = np.flip(ref, axis=1)
    ref = np.flip(ref, axis=0)
    assert np.array_equal(out, ref), "纯翻转必须逐位一致"
    assert ctx.state["compose"]["horizontal_flip"] is True
    assert ctx.state["compose"]["vertical_flip"] is True


def test_ratio_crop_centered():
    img = _make_img(h=64, w=64)
    ctx, out = _run_compose(img, mode="ratio", ratio="2:1", center=[0.5, 0.5])
    # 64x64 + 2:1 -> 最大内接为 64x32
    assert out.shape == (32, 64, 3)
    x0, y0, cw, ch = (ctx.state["compose"]["crop_rect"]["x"],
                      ctx.state["compose"]["crop_rect"]["y"],
                      ctx.state["compose"]["crop_rect"]["width"],
                      ctx.state["compose"]["crop_rect"]["height"])
    ref = img[y0:y0 + ch, x0:x0 + cw]
    assert np.array_equal(out, ref)


def test_rotation_psnr_gte_60():
    img = _make_img(64, 64, seed=3)
    angle = 7.0
    ctx, out = _run_compose(img, mode="free", x=0, y=0, width=64, height=64,
                            rotation=angle, center=[0.5, 0.5])
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    ref = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_REFLECT_101)
    assert out.shape == ref.shape
    psnr = _psnr(out, ref)
    assert psnr >= 60.0, f"旋转 PSNR {psnr:.2f} dB < 60"
    assert ctx.state["compose"]["border_mode"] == "reflect101"
    assert ctx.state["compose"]["transform_matrix"] is not None


def test_rotation_same_size_same_position_equivalent():
    img = _make_img(48, 64, seed=11)
    h, w = img.shape[:2]
    for angle in (5.0, -15.0, 90.0):
        ctx, out = _run_compose(img, mode="free", x=0, y=0,
                                width=w, height=h, rotation=angle,
                                center=[0.5, 0.5])
        assert out.shape == img.shape, "旋转必须保持同尺寸"
        m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
        ref = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LANCZOS4,
                             borderMode=cv2.BORDER_REFLECT_101)
        assert np.allclose(out, ref, atol=1e-6), f"angle={angle} 同位置旋转不一致"
        assert ctx.state["compose"]["rotation"] == angle
        assert ctx.state["compose"]["transform_matrix"] == m.tolist()


def test_compose_writes_geometry_metadata():
    img = _make_img()
    ctx, out = _run_compose(img, mode="free", x=3, y=4, width=24, height=18,
                            rotation=10.0, horizontal_flip=True)
    meta = ctx.state["compose"]
    assert meta["mode"] == "free"
    assert meta["original_size"] == [48, 64]
    assert meta["final_size"] == [18, 24]
    assert meta["crop_rect"] == {"x": 3, "y": 4, "width": 24, "height": 18}
    assert meta["transform_matrix"] is not None
    assert meta["border_mode"] == "reflect101"
    assert out.shape == (18, 24, 3)
    assert ctx.results[-1].metrics["changed"] is True


def test_preview_full_ab_geometry_and_pixel_metrics():
    """合成图 compose 预览/全尺寸 A/B：几何一致 + 缩放像素差指标。"""
    full = _gradient_image()
    preview = _resize_long_edge(full, 90)
    params = {
        "mode": "ratio",
        "ratio": "4:3",
        "center": [0.5, 0.5],
        "rotation": 5.0,
        "horizontal_flip": True,
        "vertical_flip": False,
    }

    full_ctx, full_out = _run_compose(full, **params)
    preview_ctx, preview_out = _run_compose(preview, **params)
    fm = full_ctx.state["compose"]
    pm = preview_ctx.state["compose"]

    # 1) 归一化裁剪矩形一致（预览/full 像素取整导致的微小差允许 ≤0.02）
    def _norm(meta):
        h, w = meta["original_size"]
        c = meta["crop_rect"]
        return (c["x"] / w, c["y"] / h, c["width"] / w, c["height"] / h)

    for a, b in zip(_norm(fm), _norm(pm)):
        assert abs(a - b) <= 0.02, f"预览/full 归一化裁剪不一致: {a} vs {b}"

    # 2) 最终画面比例一致（缩放取整差 ≤0.02）
    full_aspect = full_out.shape[1] / full_out.shape[0]
    preview_aspect = preview_out.shape[1] / preview_out.shape[0]
    assert abs(full_aspect - preview_aspect) <= 0.02

    # 3) 裁切保留比例一致
    f_keep = (fm["crop_rect"]["width"] * fm["crop_rect"]["height"]) / (
        full.shape[1] * full.shape[0])
    p_keep = (pm["crop_rect"]["width"] * pm["crop_rect"]["height"]) / (
        preview.shape[1] * preview.shape[0])
    assert abs(f_keep - p_keep) <= 0.02

    # 4) 旋转/翻转参数一致
    assert fm["rotation"] == pm["rotation"] == 5.0
    assert fm["horizontal_flip"] == pm["horizontal_flip"] is True
    assert fm["vertical_flip"] == pm["vertical_flip"] is False

    # 5) 像素级 A/B：full 输出缩到 preview 目标尺寸后，与 preview 输出比较。
    #    使用项目既有 A/B 阈值 p50≤2、p99≤10（8bit）。
    target = (preview_out.shape[1], preview_out.shape[0])
    full_scaled = cv2.resize(full_out, target, interpolation=cv2.INTER_AREA)
    assert full_scaled.shape == preview_out.shape
    metrics = _ab_diff_metrics(full_scaled, preview_out)
    for ch, m in metrics.items():
        assert m["p50"] <= 2.0, f"{ch} p50={m['p50']:.2f} 超标"
        assert m["p99"] <= 10.0, f"{ch} p99={m['p99']:.2f} 超标"
