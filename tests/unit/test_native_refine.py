"""T26: M3 refine 原生内核数值等价与回退测试。

覆盖 PixoRenderRefineApply 的:
  - 单独 sharpen / chroma_denoise / highlight_desat
  - 三者全开（blurUp 来自 sharpen 之后图像，与 Python 顺序一致）
  - native DLL 不可用时包装函数抛 RuntimeError，Stage 回退纯 Python
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from render import _native as native
from render.modules.refine import RefineStage


@pytest.fixture()
def native_required():
    if not native.available():
        pytest.skip("native DLL 不可用, 跳过 refine 原生等价测试")


@pytest.fixture()
def native_disabled(monkeypatch):
    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    return native


def _img(shape=(32, 48, 3), seed=20260820):
    rng = np.random.default_rng(seed)
    return rng.random(shape, dtype=np.float32)


def _gray(img):
    return RefineStage._gray(img)


def _sat(img):
    return RefineStage._sat_protection(img)


def _chroma_inputs(img, cd):
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(w // 4, 4), max(h // 4, 4)),
                       interpolation=cv2.INTER_AREA)
    small_blur = cv2.GaussianBlur(small, (0, 0), cd)
    gray_blur_s = RefineStage._gray(small_blur)
    gray_blur = cv2.resize(gray_blur_s, (w, h),
                           interpolation=cv2.INTER_LINEAR)[:, :, np.newaxis]
    blur_up = cv2.resize(small_blur, (w, h), interpolation=cv2.INTER_LINEAR)
    return blur_up, gray_blur


def test_refine_apply_sharpen_only_matches_python(native_required):
    img = _img()
    sh, cd, hd = 0.35, 0.0, 0.0
    gray = _gray(img)
    sat = _sat(img)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    out_n = native.refine_apply(img, gray, sat, blur, None, None, sh, cd, hd)
    out_p = RefineStage._sharpen_gray(img, sh, gray, sat)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_refine_apply_chroma_only_matches_python(native_required):
    img = _img()
    sh, cd, hd = 0.0, 0.8, 0.0
    gray = _gray(img)
    sat = _sat(img)
    blur_up, gray_blur = _chroma_inputs(img, cd)
    out_n = native.refine_apply(img, gray, sat, None, blur_up, gray_blur,
                                sh, cd, hd)
    out_p = RefineStage._chroma_denoise_small(img, cd, gray, sat)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_refine_apply_highlight_only_matches_python(native_required):
    img = _img()
    sh, cd, hd = 0.0, 0.0, 0.6
    gray = _gray(img)
    sat = _sat(img)
    out_n = native.refine_apply(img, gray, sat, None, None, None, sh, cd, hd)
    out_p = RefineStage._highlight_desat(img, hd, gray, sat)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_refine_apply_all_steps_matches_python(native_required):
    img = _img()
    sh, cd, hd = 0.35, 0.8, 0.6
    gray = _gray(img)
    sat = _sat(img)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)

    # Python 参考顺序：sharpen -> chroma_denoise -> highlight_desat
    sharp = RefineStage._sharpen_gray(img, sh, gray, sat)
    blur_up, gray_blur = _chroma_inputs(sharp, cd)
    chroma = RefineStage._chroma_denoise_small(sharp, cd, gray, sat)
    out_p = RefineStage._highlight_desat(chroma, hd, gray, sat)

    out_n = native.refine_apply(img, gray, sat, blur, blur_up, gray_blur,
                                sh, cd, hd)
    assert np.abs(out_n - out_p).max() <= 1e-6


def test_refine_apply_raises_when_native_disabled(native_disabled):
    img = _img((8, 8, 3))
    gray = _gray(img)
    sat = _sat(img)
    with pytest.raises(RuntimeError, match="native DLL unavailable"):
        native.refine_apply(img, gray, sat, None, None, None, 0.0, 0.0, 0.0)


def test_refine_stage_fallback_matches_native(native_required, monkeypatch):
    """native 关闭时 RefineStage 走纯 Python，输出与 native 开启一致。"""
    from render.pipeline.context import DOMAIN_GAMMA_RGB, StageContext

    img = _img((32, 48, 3), seed=7)
    params = {"sharpen": 0.35, "chroma_denoise": 0.8, "highlight_desat": 0.6}
    stage = RefineStage(params)

    ctx = StageContext("t.npy")
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx)
    out_native = ctx.image.copy()

    monkeypatch.setattr(native, "_lib", None)
    monkeypatch.setattr(native, "_load_error", "simulated missing dll")
    ctx2 = StageContext("t.npy")
    ctx2.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage2 = RefineStage(params)
    stage2.run(ctx2)
    out_fallback = ctx2.image.copy()

    assert np.abs(out_native - out_fallback).max() <= 1e-6
