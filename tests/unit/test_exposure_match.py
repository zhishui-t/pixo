"""R32-T7: 曝光 mode="match"（RT getAutoExp 八分位匹配对照吸收）测试。"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.modules.exposure import ExposureStage, auto_match_suggest


def _gauss_hist(center, sigma=0.08, bins=4096, total=1e6):
    x = (np.arange(bins) + 0.5) / bins
    h = np.exp(-0.5 * ((x - center) / sigma) ** 2)
    return h / h.sum() * total


def test_auto_match_midgray_near_zero():
    """中灰直方图 → EV 近零 (匹配目标即中灰)。"""
    r = auto_match_suggest(_gauss_hist(0.1842))
    assert abs(r["expcomp"]) < 0.5
    assert r["contr"] >= 0 and 0 <= r["hlcompr"] <= 100


def test_auto_match_dark_positive_bright_negative():
    """暗场 → 正 EV; 亮场 → 负 EV (方向正确)。"""
    dark = auto_match_suggest(_gauss_hist(0.03))
    bright = auto_match_suggest(_gauss_hist(0.55))
    assert dark["expcomp"] > 0.5
    assert bright["expcomp"] < 0.0
    assert dark["black"] >= 0.0 and bright["black"] >= 0.0


def test_auto_match_blackframe_safe_zeros():
    """黑帧 (空直方图) → 全零建议, 不抛异常 (RT 同为安全零)。"""
    r = auto_match_suggest(np.zeros(4096))
    assert r["expcomp"] == 0.0 and r["black"] == 0.0
    assert r["hlcompr"] == 0 and r["contr"] == 0


def test_exposure_stage_match_mode_end_to_end():
    """mode="match" 端到端: 暗图 → 正 EV + state/metrics 记录。

    注意: 探针网格 256 长边 (≤256 输入走 ::4 跨步) —— 用 256×256 图保证
    八分位统计像素量充足 (16 像素小图会触发 RT 同款整数八分位量化退化,
    返回安全零 —— 实现为忠实移植, 此为已知边界而非缺陷)。
    """
    from pixo.render.pipeline.graph import StageContext, DOMAIN_LINEAR_CAM

    img = (np.random.default_rng(3).random((256, 256, 3)) * 0.08).astype(np.float32)
    ctx = StageContext("x.NEF", prof=None,
                       config={"stages": {"exposure": {"mode": "match"}}})
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    ExposureStage().run(ctx)
    assert ctx.state.get("ev_mode") == "match"
    assert ctx.state.get("ev", 0.0) > 0.0        # 暗图提亮
    metrics = ctx.results[-1].metrics
    assert "exposure_match_expcomp" in metrics


def test_exposure_stage_default_mode_unchanged():
    """缺省 mode="baseline" 不受 match 吸收影响 (向后兼容红线)。"""
    dp = ExposureStage().default_params()
    assert dp["mode"] == "baseline"
    assert "match" not in dp["mode"]
