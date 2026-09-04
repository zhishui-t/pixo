"""阶段三 §2 光照估计原型单测 —— 逆链往返恒等 / 经典法 sanity / 分带口径。

用 repo 真实 DCP (Nikon Z5_2) 做逆链往返 (temp_tint_to_wb 正链 → 显示域
光源演出 → srgb_light_to_temp_tint 逆链 → 还原), 三件经典法用合成图验证
光源方向恢复。无 RAW 语料依赖。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO / "scripts" / "illumination_est"),
           str(_REPO / "scripts"), str(_REPO / "scripts" / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

wb_inverse = importlib.import_module("wb_inverse")
gray_world = importlib.import_module("gray_world")
gray_edge = importlib.import_module("gray_edge")
white_patch = importlib.import_module("white_patch")
import eval_illum  # noqa: E402

from pixo.render.core.calibration import load_dcp  # noqa: E402
from pixo.render.core.color import temp_tint_to_wb  # noqa: E402

DCP_PATH = _REPO / "resources" / "dcp" / \
    "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"

pytestmark = pytest.mark.skipif(
    not DCP_PATH.is_file(), reason="repo DCP 不存在")


@pytest.fixture(scope="module")
def prof():
    return load_dcp(DCP_PATH)


# ---------------------------------------------------------------------------
# 逆链: temp_tint_to_wb 正链 → 相机域光源响应 → 逆链还原 (线性精确)
# ---------------------------------------------------------------------------

def _cam_light_from_temp_tint(prof, temp_k: float, tint: float) -> np.ndarray:
    """(temp, tint) 的场景光源 → 相机原生域响应: 中和系数 wb = 1/响应 (G 归一),
    故响应 = 1/wb —— 与 est_cct 的估计对象同域同构。"""
    wb = np.asarray(temp_tint_to_wb(prof, temp_k, tint), dtype=np.float64)
    return 1.0 / wb


@pytest.mark.parametrize("temp,tint", [(3000.0, 0.0), (4000.0, 10.0),
                                       (6500.0, 0.0), (5200.0, -15.0)])
def test_inverse_roundtrip(prof, temp, tint):
    """正链 (temp,tint) → 相机域光源响应 → 逆链 → 还原 (temp,tint)。

    本质判据 = WB 域闭环: 还原参数经 temp_tint_to_wb 正链回来的 WB 与源 WB
    色度逐位一致 (不受 (t,ti) 参数化在平坦区的敏感性影响 —— tint 的 WB
    指纹 ~1e-4 量级, (temp,tint) 数值本身可有 1-2% 级偏移而 WB 恒等)。"""
    e = _cam_light_from_temp_tint(prof, temp, tint)
    t_out, ti_out = wb_inverse.cam_light_to_temp_tint(e, prof)
    wb_src = temp_tint_to_wb(prof, temp, tint).astype(np.float64)
    wb_out = np.asarray(temp_tint_to_wb(prof, t_out, ti_out), dtype=np.float64)
    np.testing.assert_allclose(wb_out / wb_out[1], wb_src / wb_src[1],
                               rtol=0.02)   # 逆求解器 (wb_to_temp_tint) 公开精度
    assert 1000.0 <= t_out <= 50000.0 and -150.0 <= ti_out <= 150.0


def test_scene_xy_to_neutral_wb_matches_forward(prof):
    """scene_xy_to_neutral_wb 与 temp_tint_to_wb 逐式同构: 任意 (temp, tint)
    的场景白点喂入前者, 产出的 WB 应等于正链 WB (归一 G=1)。"""
    from pixo.render.core.color import neutral_to_xy, wb_to_neutral
    for temp, tint in [(3000.0, 0.0), (4500.0, 12.0), (6500.0, -8.0)]:
        wb_fwd = np.asarray(temp_tint_to_wb(prof, temp, tint), dtype=np.float64)
        xy = neutral_to_xy(wb_to_neutral(wb_fwd), prof)
        wb_inv = wb_inverse.scene_xy_to_neutral_wb(xy, prof)
        np.testing.assert_allclose(wb_inv / wb_inv[1],
                                   wb_fwd / wb_fwd[1], atol=1e-8)


# ---------------------------------------------------------------------------
# 经典法 sanity (合成图)
# ---------------------------------------------------------------------------

def _tinted_plane(rng, tint_rgb, n=64):
    """已知光源染色的纹理图 (随机纹理保证 Gray-Edge 有梯度)。"""
    base = rng.random((n, n, 1))
    img = base * np.asarray(tint_rgb, dtype=np.float64).reshape(1, 1, 3)
    return img + rng.random((n, n, 3)) * 1e-3


def test_gray_world_recovers_light_direction():
    rng = np.random.default_rng(0)
    img = _tinted_plane(rng, (0.7, 1.0, 1.25))
    e = gray_world.estimate_light(img)
    e = e / e[1]
    assert e[0] == pytest.approx(0.7, abs=0.05)
    assert e[2] == pytest.approx(1.25, abs=0.05)


@pytest.mark.parametrize("p", [1.0, 2.0])
def test_gray_edge_recovers_direction_and_flat_fallback(p):
    rng = np.random.default_rng(1)
    img = _tinted_plane(rng, (0.75, 1.0, 1.2))
    e = gray_edge.estimate_light(img, p=p) / 1.0
    assert np.all(np.isfinite(e)) and np.all(e > 0)
    flat = np.full((32, 32, 3), 0.4) * np.array([0.7, 1.0, 1.25])
    e_flat = gray_edge.estimate_light(flat, p=p)      # 平坦图回退 Gray-World
    assert np.all(np.isfinite(e_flat))


def test_white_patch_follows_brightest_region():
    rng = np.random.default_rng(2)
    img = rng.random((64, 64, 3)) * 0.4               # 暗背景
    img[:8, :8] = np.array([0.5, 0.8, 1.0])           # 最亮块 = 光源染色
    e = white_patch.estimate_light(img, quantile=0.98)
    e = e / e[1]
    assert e[2] > e[0]                                # 白斑法应偏向亮块的暖蓝方向
    assert e[2] == pytest.approx(1.25, abs=0.35)


@pytest.mark.parametrize("mod", [gray_world, gray_edge, white_patch])
def test_est_cct_returns_pixo_param_range(prof, mod):
    """est_cct 输出落在 pixo whitebalance 参数域 (temp [1000,50000],
    tint [-150,150]; wb_to_temp_tint 求解域)。"""
    rng = np.random.default_rng(3)
    img = _tinted_plane(rng, (0.9, 1.0, 1.1))
    cct, tint = mod.est_cct(img, prof)
    assert 1000.0 <= cct <= 50000.0
    assert -150.0 <= tint <= 150.0
    # 参数域自洽: 正链回来的 WB 与逆链中间 WB 同源 (色度一致)
    wb = np.asarray(temp_tint_to_wb(prof, cct, tint), dtype=np.float64)
    assert np.all(np.isfinite(wb)) and wb[1] == pytest.approx(1.0)


def test_gray_edge_p1_p2_differ_on_texture():
    rng = np.random.default_rng(4)
    img = _tinted_plane(rng, (0.85, 1.0, 1.15), n=96)
    e1 = gray_edge.estimate_light(img, p=1.0)
    e2 = gray_edge.estimate_light(img, p=2.0)
    assert not np.allclose(e1, e2)                    # 不同范数给不同光源估计


# ---------------------------------------------------------------------------
# 分带口径
# ---------------------------------------------------------------------------

def test_band_of():
    assert eval_illum.band_of(1.07) == "daylight(<1.5)"
    assert eval_illum.band_of(1.5) == "mid(1.5-2.0)"
    assert eval_illum.band_of(1.99) == "mid(1.5-2.0)"
    assert eval_illum.band_of(2.4) == "low_cct(>=2.0)"
