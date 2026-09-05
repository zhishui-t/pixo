"""JND 感知差异早停单测（perceptual_convergence 终止条件）。

覆盖：
  - ΔE2000 底座（src/pixo/pipeline/perceptual.py）与 Sharma 2005 公开
    校验对一致（文献保真）；
  - JndConvergenceTracker：连续窗口触发 / 高差异清零 / 非有限值防御；
  - 闭环集成：收敛触发早停 / 关闭或大差异时不触发 / 美学达标优先级
    不变 / 分数未达上限仍强制终止 / 触发轮 decide 参数不落地。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.pipeline.perceptual import (
    JndConvergenceTracker,
    delta_e_2000,
    delta_e_median,
    gamma_srgb_to_linear,
    linear_srgb_to_lab,
)
from pixo.vision import MockSegmenter


def _dark_image() -> np.ndarray:
    """低亮度合成图，FINAL_QC 不会高光溢出。"""
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.3
    return img


def _bright_image() -> np.ndarray:
    """与暗图差异远超 JND 的亮图（模拟大幅调整）。"""
    img = np.full((64, 64, 3), 0.7, dtype=np.float32)
    return img


def _make_loop(**kw):
    kw.setdefault("max_iterations", 3)
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        preview_long_edge=64,
        **kw,
    )


def _trace_types(result):
    return [e["event_type"] for e in result.trace_events]


# ---------------------------------------------------------------------------
# ΔE2000 底座：文献保真（Sharma, Wu & Dalal 2005 公开校验对）
# ---------------------------------------------------------------------------

_SHARMA_PAIRS = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
]


@pytest.mark.parametrize("lab1,lab2,expected", _SHARMA_PAIRS)
def test_delta_e_2000_sharma_reference_pairs(lab1, lab2, expected):
    got = float(delta_e_2000(np.array([lab1]), np.array([lab2]))[0])
    assert abs(got - expected) < 1e-3


def test_delta_e_helpers_identity_and_monotonicity():
    """同图 ΔE=0；gamma→linear→Lab 往返形状不变；差异越大 ΔE 越大。"""
    img = _dark_image()
    assert delta_e_median(img, img) == 0.0
    lab = linear_srgb_to_lab(gamma_srgb_to_linear(img))
    assert lab.shape == img.shape
    d_small = delta_e_median(img, img + 0.01)
    d_large = delta_e_median(img, _bright_image())
    assert 0.0 < d_small < d_large


def test_gamma_srgb_to_linear_boundaries():
    assert gamma_srgb_to_linear(0.0) == 0.0
    assert float(gamma_srgb_to_linear(np.array([1.0]))[0]) == pytest.approx(1.0)
    assert float(gamma_srgb_to_linear(np.array([0.5]))[0]) == pytest.approx(
        0.21404, abs=1e-4)
    # 负输入按 0 处理（与 oklab._srgb_to_linear 同纪律）
    assert float(gamma_srgb_to_linear(np.array([-0.3]))[0]) == 0.0


# ---------------------------------------------------------------------------
# JndConvergenceTracker：连续窗口 / 清零 / 非有限值防御
# ---------------------------------------------------------------------------

def test_tracker_requires_consecutive_below_window():
    t = JndConvergenceTracker(threshold=0.5, window=2)
    assert t.update(0.1) is False          # 连续第 1 次
    assert t.update(0.2) is True           # 连续第 2 次 → 收敛
    t2 = JndConvergenceTracker(threshold=0.5, window=2)
    assert t2.update(0.1) is False
    assert t2.update(5.0) is False         # 高差异清零
    assert t2.update(0.1) is False         # 重新计数
    assert t2.update(0.1) is True


def test_tracker_window_one_and_nonfinite():
    t = JndConvergenceTracker(threshold=0.5, window=1)
    assert t.update(0.4) is True
    assert t.update(9.9) is False
    t2 = JndConvergenceTracker(threshold=0.5, window=2)
    assert t2.update(float("nan")) is False    # 非有限值清零不误判收敛
    assert t2.count == 0
    with pytest.raises(ValueError):
        JndConvergenceTracker(threshold=0.0, window=2)
    with pytest.raises(ValueError):
        JndConvergenceTracker(threshold=0.5, window=0)


# ---------------------------------------------------------------------------
# 闭环集成
# ---------------------------------------------------------------------------

class _StaticBackend:
    """恒渲染同一预览（无视参数）——模拟"参数不产生感知效果"的退化场景。"""

    def __init__(self, inner: SyntheticRenderBackend) -> None:
        self._inner = inner

    def render_preview(self, params, long_edge=None):
        return self._inner.render_preview({}, long_edge=long_edge)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _AlternatingBackend(SyntheticRenderBackend):
    """奇偶轮交替渲染暗/亮两图——模拟每次迭代都有远超 JND 的大改。"""

    def __init__(self, img_a, img_b):
        super().__init__(img_a)
        self._alt = SyntheticRenderBackend(img_b)
        self._i = 0

    def render_preview(self, params, long_edge=None):
        self._i += 1
        if self._i % 2 == 0:
            return self._alt.render_preview(params, long_edge=long_edge)
        return super().render_preview(params, long_edge=long_edge)


class _SequenceMeasurer:
    """按预设序列返回全局亮度的假测量器（模拟指标仍在改善的场景）。"""

    def __init__(self, seq: list[float]) -> None:
        self.seq = seq
        self.i = 0

    def measure(self, image, masks, **kw):
        value = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return {
            "global": {
                "mean_luminance": value,
                "highlight_clip_ratio": 0.0,
                "shadow_clip_ratio": 0.0,
                "contrast": 0.5,
            },
            "regions": {},
        }


def test_perceptual_stop_triggers_on_static_previews():
    """像素无感差异（ΔE=0）而指标仍在改善（绕开量化停滞判停）：默认窗口
    2 在第 3 轮（连续第 2 次低于阈值）以 perceptual_convergence 终止，
    且该轮 decide 仍先运行（优先级：decide 判停 > 感知收敛）。"""
    result = _make_loop(
        measurer=_SequenceMeasurer([90.0, 100.0, 110.0]),
    ).run("jnd_hit", image_rgb=_dark_image())

    assert "perceptual_convergence" in result.reason
    assert "perceptual_convergence" in _trace_types(result)
    assert len(result.measurements) == 3
    # decide 先于感知终止运行且未判停（优先级：decide 判停 > 感知收敛）
    decide_events = [e for e in result.trace_events
                     if e["event_type"] == "decide"]
    assert decide_events[-1]["value"]["decision"] == "adjust_and_continue"
    # 逐轮 ΔE 进 measurement（观测性）
    for m in result.measurements[1:]:
        assert m["perceptual"]["delta_median_prev"] == pytest.approx(0.0)


def test_perceptual_stop_window_one_stops_before_cap():
    """window=1：第 2 轮即收敛，早于轮数上限与停滞判停（防过度修图的价值点）。"""
    result = _make_loop(jnd_window=1).run("jnd_early", image_rgb=_dark_image())

    assert "perceptual_convergence" in result.reason
    assert len(result.measurements) == 2


def test_perceptual_disabled_reaches_max_iterations():
    """jnd_threshold=None 关闭：迭代间差异巨大也跑满轮数（旧终止链行为）。"""
    loop = SinglePhotoLoop(
        render_backend=_AlternatingBackend(_dark_image(), _bright_image()),
        segmenter=MockSegmenter(),
        preview_long_edge=64,
        max_iterations=3,
        jnd_threshold=None,
    )
    result = loop.run("jnd_off", image_rgb=_dark_image())

    assert "达到最大迭代轮数" in result.reason
    assert "perceptual_convergence" not in result.reason


def test_perceptual_not_triggered_by_large_changes():
    """迭代间差异远超阈值：不触发早停，跑满轮数。"""
    loop = SinglePhotoLoop(
        render_backend=_AlternatingBackend(_dark_image(), _bright_image()),
        segmenter=MockSegmenter(),
        preview_long_edge=64,
        max_iterations=3,
    )
    result = loop.run("jnd_big", image_rgb=_dark_image())

    assert "达到最大迭代轮数" in result.reason
    assert "perceptual_convergence" not in result.reason
    # 大差异轮的计数被清零
    assert result.measurements[-1]["perceptual"]["consecutive_below_jnd"] == 0


def test_aesthetic_accept_still_wins_over_perceptual():
    """美学达标（decide 判停）优先级最高：第 1 轮达标即停，感知条件未参与。"""
    result = _make_loop(
        aesthetic_scorer=lambda image, masks=None: {"overall": 0.95},
        aesthetic_accept_threshold=0.9,
    ).run("jnd_vs_aesthetic", image_rgb=_dark_image())

    assert "美学总分" in result.reason
    assert "perceptual_convergence" not in result.reason
    assert len(result.measurements) == 1


def test_perceptual_stops_even_when_score_below_accept():
    """分数未达上限但预览无感知差异：仍强制终止（评审建议的核心场景）。
    美学分递增避开美学停滞判停，指标改善避开量化停滞——排除竞争条件。"""
    scores = iter([0.5, 0.55, 0.6])

    def scorer(image, masks=None):
        return {"overall": next(scores, 0.6)}

    result = _make_loop(
        aesthetic_scorer=scorer,
        aesthetic_accept_threshold=0.9,
        measurer=_SequenceMeasurer([90.0, 100.0, 110.0]),
    ).run("jnd_under_score", image_rgb=_dark_image())

    assert "perceptual_convergence" in result.reason
    assert "美学总分" not in result.reason


def test_decided_params_of_trigger_round_not_applied():
    """触发轮的 decide 参数不落地：规则连发 +0.3EV 时只保留已验证的首轮
    效果（导出图 = 最后一张已评分预览，防未验证参数进成品）。"""
    rule = {
        "rule_id": "brighten",
        "condition": {"metric": "mean_luminance", "op": "lt", "value": 120},
        "action": {"param": "exposure_ev", "mode": "delta", "value": 0.3},
    }
    loop = SinglePhotoLoop(
        render_backend=_StaticBackend(SyntheticRenderBackend(_dark_image())),
        segmenter=MockSegmenter(),
        preview_long_edge=64,
        max_iterations=3,
        jnd_window=1,
        rules=[rule],
    )
    result = loop.run("jnd_params", image_rgb=_dark_image())

    assert "perceptual_convergence" in result.reason
    assert result.params["exposure"]["target_offset"] == pytest.approx(0.3)
    updates = [e for e in result.trace_events
               if e["event_type"] == "param_update"
               and e["param"] == "exposure_ev"]
    assert len(updates) == 1, "触发轮的参数更新不应落地"
