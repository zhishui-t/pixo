"""Phase 1 集成: 默认 13 段链与旧 9 段链逐位一致 + 新增 Stage 注册/order。"""
from __future__ import annotations

import numpy as np
import pytest

from pathlib import Path

from pixo.render.core.calibration import DcpProfile
from pixo.render.pipeline.graph import StageContext, DOMAIN_LINEAR_CAM, DOMAIN_LINEAR_RGB
from pixo.render.pipeline.graph import available_stages, STAGE_REGISTRY
from pixo.render.pipeline.presets import Pipeline, DEFAULT_STAGES
from pixo.render.modules.exposure import ExposureStage
from pixo.render.modules.white_balance import WhiteBalanceStage
from pixo.render.modules.tone_map import ToneStage
import pixo.render.modules  # noqa: F401  (触发注册)


# 真实 Nikon Z 5 II Camera Standard 矩阵 (与其它单测一致, 确定性)
_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]


class _FakeRaw:
    def __init__(self, wb=(1.291, 1.0, 2.287)):
        self.camera_whitebalance = [wb[0], wb[1], wb[2], 1.0]


def _profile() -> DcpProfile:
    return DcpProfile(path=Path("test.dcp"),
                      color_matrix1=_NIKON_CM1, color_matrix2=_NIKON_CM2,
                      forward_matrix1=_NIKON_FM1, forward_matrix2=_NIKON_FM1)


OLD_9 = ["exposure", "whitebalance", "huesat", "tone", "clarity",
         "colorcal", "skin", "stylize", "refine"]


def _run_chain(stages, prof):
    img = np.random.default_rng(7).random((64, 64, 3)).astype(np.float32) * 0.9
    ctx = StageContext("test.nef", raw=_FakeRaw(), prof=prof)
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    Pipeline(stages=stages).run(ctx)
    return ctx.image


def test_default_chain_13_vs_9_pixel_identical():
    """默认 13 段链与旧 9 段链像素输出逐位一致 (新增 Stage 默认 no-op/恒等)。"""
    prof = _profile()
    out9 = _run_chain(OLD_9, prof)
    out13 = _run_chain(DEFAULT_STAGES, prof)
    assert out9.shape == out13.shape
    diff = float(np.abs(out9 - out13).max())
    assert diff == 0.0, f"默认链 9 段 vs 13 段输出不一致 max|Δ|={diff}"


def test_default_chain_contains_13_stages():
    assert len(DEFAULT_STAGES) == 13
    assert DEFAULT_STAGES == ["exposure", "whitebalance", "compose", "huesat",
                              "tone", "clarity", "colorcal", "calibration",
                              "hsl", "split_tone", "skin", "stylize", "refine"]


def test_phase1_stages_registered_order_increasing():
    """calibration / hsl / split_tone 已注册且 order 递增 (51<52<54<60)。"""
    for name in ("calibration", "hsl", "split_tone", "skin", "stylize"):
        assert name in STAGE_REGISTRY, name
    ords = {n: STAGE_REGISTRY[n].order for n in
            ("calibration", "hsl", "split_tone", "skin", "stylize")}
    assert ords["calibration"] == 51
    assert ords["hsl"] == 52
    assert ords["split_tone"] == 54
    assert ords["skin"] == 55
    assert ords["stylize"] == 60
    seq = [STAGE_REGISTRY[n].order for n in ("calibration", "hsl", "split_tone", "skin", "stylize")]
    assert all(b > a for a, b in zip(seq, seq[1:])), seq


def test_new_stages_noop_by_default_wants_false():
    """新 Stage (calibration/hsl/split_tone) 默认 wants()=False → 不进默认链。"""
    ctx = StageContext("x.NEF", raw=_FakeRaw(), prof=_profile())
    for name in ("calibration", "hsl", "split_tone"):
        sg = STAGE_REGISTRY[name]()
        assert sg.wants(ctx) is False, name
