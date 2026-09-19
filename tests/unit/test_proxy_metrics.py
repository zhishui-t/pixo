"""t36 单元测试：三代理指标（haze_proxy/colorfulness_proxy/tonal_range）。

覆盖：
  - 平坦灰图：tonal_range≈0，haze_proxy>0.8（浓雾端）；
  - 线性渐变图：haze_proxy<0.3（通透端）、tonal_range 大；
  - 高饱和图 colorfulness 显著高于同结构灰图；
  - None/非法输入返回空 dict（缺数据不写缺省键）；
  - 闭环集成：preview/FINAL_QC 测量与 decide_context 均携带三键。
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.vision import MockSegmenter
from pixo.vision.measure import compute_proxy_metrics

PROXY_KEYS = ("haze_proxy", "colorfulness_proxy", "tonal_range")
ROOT = Path(__file__).resolve().parents[2]
# 真实 RAW 样本路径经环境变量注入（仓库不携带本地路径/场景名）：
#   PIXO_CORPUS_A_RAW      = <0711 raw 目录>/DSC_5236.NEF
#   PIXO_CORPUS_FESTIVAL_RAW = <春节目录>/DSC_0355.NEF
# 未设置时相关用例自动跳过。
_REAL_A = os.environ.get("PIXO_CORPUS_A_RAW")
_REAL_FEST = os.environ.get("PIXO_CORPUS_FESTIVAL_RAW")
REAL_RAW_SAMPLES = [Path(p) for p in (_REAL_A, _REAL_FEST) if p]


def _flat_gray(level=0.5):
    return np.full((32, 32, 3), float(level), dtype=np.float32)


def _gradient_image():
    ramp = np.linspace(0.0, 1.0, 64, dtype=np.float32)
    img = np.empty((64, 64, 3), dtype=np.float32)
    img[:] = ramp[None, :, None]
    return img


def _high_saturation_image():
    img = np.zeros((32, 32, 3), dtype=np.float32)
    img[:, :16] = (1.0, 0.0, 0.0)
    img[:, 16:] = (0.0, 0.0, 1.0)
    return img


def test_flat_gray_is_hazy_and_range_zero():
    out = compute_proxy_metrics(_flat_gray(0.5))
    assert out["haze_proxy"] > 0.8
    assert out["tonal_range"] == 0.0


def test_gradient_image_is_clear():
    out = compute_proxy_metrics(_gradient_image())
    assert out["haze_proxy"] < 0.3
    assert out["tonal_range"] > 0.5  # 统一 [0,1] 域后接近满量程 (~0.9)
    assert 0.0 <= out["colorfulness_proxy"] <= 100.0


def test_high_saturation_beats_gray_on_colorfulness():
    sat = compute_proxy_metrics(_high_saturation_image())
    weights = (0.2126, 0.7152, 0.0722)
    g_red = float(np.dot((1.0, 0.0, 0.0), weights))
    g_blue = float(np.dot((0.0, 0.0, 1.0), weights))
    gray_img = np.zeros((32, 32, 3), dtype=np.float32)
    gray_img[:, :16] = g_red   # 保持与彩色版相同的双段结构，仅去色
    gray_img[:, 16:] = g_blue
    gray = compute_proxy_metrics(gray_img)
    assert sat["colorfulness_proxy"] > gray["colorfulness_proxy"] + 20.0


def test_invalid_inputs_yield_empty_dict():
    assert compute_proxy_metrics(None) == {}
    assert compute_proxy_metrics(np.zeros((0,), dtype=np.float32)) == {}
    flat2d = np.zeros((8, 8), dtype=np.float32)
    assert compute_proxy_metrics(flat2d) == {}


def test_uint8_and_float_agree():
    a = compute_proxy_metrics((_gradient_image() * 255).astype(np.uint8))
    b = compute_proxy_metrics(_gradient_image())
    for k in PROXY_KEYS:
        assert abs(a[k] - b[k]) < 1.0


def test_loop_measurements_and_decide_context_carry_proxies():
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.35
    loop = SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(img),
        segmenter=MockSegmenter(),
        max_iterations=1,
        preview_long_edge=64,
    )
    result = loop.run("proxy", image_rgb=img)

    assert result.measurements
    for key in PROXY_KEYS:
        assert key in result.measurements[0]
        assert key in (result.final_measurement or {})
    decide_events = [e for e in result.trace_events
                     if e["event_type"] == "decide"]
    assert decide_events
    metrics = decide_events[-1]["value"].get("metrics") or {}
    for key in PROXY_KEYS:
        assert key in metrics


@pytest.mark.skipif(
    not all(p.exists() for p in REAL_RAW_SAMPLES),
    reason="真实 RAW 样本不存在（数据盘未挂载时跳过）",
)
@pytest.mark.parametrize("raw_path", REAL_RAW_SAMPLES)
def test_real_raw_render_proxies_physically_plausible(raw_path):
    """真实 RAW 渲染小图：三指标物理合理且不饱和。"""
    from pixo.render.api import Renderer

    dcp = sorted(ROOT.joinpath("resources", "dcp").glob("*.dcp"))[0]
    renderer = Renderer(dcp)
    img = renderer.render_preview_full(raw_path, long_edge=256)
    out = compute_proxy_metrics(img)

    assert set(PROXY_KEYS) <= set(out)
    assert 0.0 <= out["haze_proxy"] <= 1.0
    assert 0.0 <= out["tonal_range"] <= 1.0
    assert out["colorfulness_proxy"] < 100.0  # 真实渲染不应饱和
    # 非全同值图像：量程与色彩不应同时退化
    assert not (out["tonal_range"] == 0.0
                and out["colorfulness_proxy"] == 0.0)


# ---------------------------------------------------------------------------
# R25 F02: compute_histogram —— BT.709 luma + RGB 计数直方图
# ---------------------------------------------------------------------------

def test_histogram_matches_manual_counts():
    from pixo.vision.measure import compute_histogram
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    img[:2] = 64            # 8 像素 @64
    img[2:] = 200           # 8 像素 @200
    out = compute_histogram(img)
    assert out["bins"] == 256 and out["pixels"] == 16
    lum64 = round(0.2126 * 64 + 0.7152 * 64 + 0.0722 * 64)  # =64 (中性)
    assert out["counts"]["r"][64] == 8 and out["counts"]["r"][200] == 8
    assert out["counts"]["lum"][lum64] == 8 and out["counts"]["lum"][200] == 8
    assert sum(out["counts"]["lum"]) == 16
    assert sum(out["counts"]["b"]) == 16


def test_histogram_saturates_into_last_bin():
    from pixo.vision.measure import compute_histogram
    img = np.full((2, 2, 3), 255, dtype=np.uint8)
    out = compute_histogram(img)
    # 末桶含右端点 255 (np.histogram 末桶闭区间)
    assert out["counts"]["lum"][-1] == 4
    assert out["counts"]["g"][-1] == 4


def test_histogram_uint8_float_agree_and_bins():
    from pixo.vision.measure import compute_histogram
    ramp = np.tile(np.linspace(0.0, 1.0, 64, dtype=np.float32)[None, :, None],
                   (8, 1, 3))
    a = compute_histogram(ramp)
    b = compute_histogram((ramp * 255).astype(np.uint8))
    # float 0-1 与 u8 同口径: 量化使像素移至相邻桶, 逐桶差大 —— 用 CDF 距离
    # (每列至多 8/512 像素因舍入跨界 ⇒ CDF 差 ≤ ~1.6%)
    assert a["pixels"] == b["pixels"]
    ca = np.cumsum(a["counts"]["lum"]) / a["pixels"]
    cb = np.cumsum(b["counts"]["lum"]) / b["pixels"]
    assert float(np.abs(ca - cb).max()) <= 0.02
    # 自定义 bins: 4 桶全覆盖、总数守恒
    c = compute_histogram((ramp * 255).astype(np.uint8), bins=4)
    assert c["bins"] == 4 and sum(c["counts"]["r"]) == 64 * 8


def test_histogram_invalid_inputs_and_bins_guard():
    from pixo.vision.measure import compute_histogram
    assert compute_histogram(None) == {}
    assert compute_histogram(np.zeros((8, 8), dtype=np.float32)) == {}
    assert compute_histogram(np.zeros((0, 0, 3), dtype=np.uint8)) == {}
    with pytest.raises(ValueError):
        compute_histogram(np.zeros((4, 4, 3), dtype=np.uint8), bins=1)
    with pytest.raises(ValueError):
        compute_histogram(np.zeros((4, 4, 3), dtype=np.uint8), bins=4096)
