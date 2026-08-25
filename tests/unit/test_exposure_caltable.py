"""曝光标定表双格式单测 (t18): 一维 [m_log2, ev] / 二维 [m_log2, wb_B, ev]。

覆盖:
  - _load_cal_table: 1D/2D 加载、2D 排序规范化与同 med 折叠均值、
    非法输入拒收 (<3 结点 / 1D 重复 med / NaN·inf / 行长混用)
  - _cal_ev: med 主键插值、±0.3 邻域 wb_B 二次插值、端点钳制不外推、
    邻域不足回退主键、1D 忽略 wb_b
  - _auto_ev 接线: ev_mode = cal_table / cal_table_2d, 二维时 wb 轴真正驱动 EV

运行: python -m pytest tests/unit/test_exposure_caltable.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import pixo.render.modules.exposure as exposure_mod
from pixo.render.core.calibration import DcpProfile
from pixo.render.modules.exposure import (
    ExposureStage,
    _cal_ev,
    _load_cal_table,
    _probe_linear_srgb,
)
from pixo.render.pipeline.graph import DOMAIN_LINEAR_CAM, StageContext


@pytest.fixture(autouse=True)
def _cal_env(tmp_path, monkeypatch):
    """每个用例独立临时标定文件, 并屏蔽真实环境表。"""
    cal = tmp_path / "target_offset.json"
    monkeypatch.setattr(exposure_mod, "_CAL_FILE", cal)
    monkeypatch.setattr(exposure_mod, "_cached_table", None)
    monkeypatch.setattr(exposure_mod, "_cached_offset", None)
    return cal


def _write(tbl):
    exposure_mod._CAL_FILE.write_text(
        json.dumps({"cal_table": tbl}), encoding="utf-8")
    exposure_mod._cached_table = None
    return _load_cal_table()


# --- 加载: 格式识别与规范化 ------------------------------------------------

def test_load_1d_returns_monotonic_pair():
    t = _write([[-2.0, 0.5], [-1.0, 1.0], [0.0, 1.5]])
    assert t is not None and len(t) == 2
    assert np.all(np.diff(t[0]) > 0)


def test_load_2d_sorts_and_folds_duplicate_meds():
    # 故意乱序 + 同 med 两行 → 折叠取均值, med 列升序
    t = _write([[0.0, 0.9, 3.0], [-1.0, 0.9, 2.0], [-1.0, 0.5, 1.0]])
    assert t is not None and len(t) == 3
    xs, ws, ys = t
    assert xs.tolist() == [-1.0, 0.0]
    assert ws[0] == pytest.approx(0.7)   # (0.5+0.9)/2
    assert ys[0] == pytest.approx(1.5)   # (1.0+2.0)/2


@pytest.mark.parametrize("tbl", [
    [[-1, 1], [0, 2]],                          # <3 结点
    [[-1, 1], [0, 2], [0, 3]],                  # 1D 重复 med
    [[-1, 1], [0, float("nan")], [1, 3]],       # ys 含 NaN
    [[float("inf"), 1], [0, 2], [1, 3]],        # xs 含 inf
    [[-1, 1], [0, 2, 3], [1, 3]],               # 行长混用
])
def test_load_rejects_invalid(tbl):
    assert _write(tbl) is None


# --- 查表语义 ---------------------------------------------------------------

_1D = [[-2.0, 0.5], [-1.0, 1.0], [0.0, 1.5]]
_2D = [[-1.05, 0.45, 1.20], [-0.95, 0.95, 1.60], [2.00, 0.90, 0.10]]


def test_cal_ev_1d_interpolates_and_ignores_wb():
    t = _write(_1D)
    assert _cal_ev(-1.0, t, None) == pytest.approx(1.0)      # 结点命中
    assert _cal_ev(-0.5, t, None) == pytest.approx(1.25)     # 中点插值
    assert _cal_ev(-5.0, t, 0.7) == pytest.approx(0.5)       # 越界钳制且忽略 wb
    assert _cal_ev(2.0, t, 0.7) == pytest.approx(1.5)


def test_cal_ev_2d_med_primary_then_wb_secondary():
    t = _write(_2D)
    base = _cal_ev(-1.0, t, None)                # med 主键 ≈ 邻域两结点均值
    assert base == pytest.approx(1.40, abs=0.11)
    assert _cal_ev(-1.0, t, 0.45) == pytest.approx(1.20, abs=1e-9)   # 邻域 wb 下端
    assert _cal_ev(-1.0, t, 0.70) == pytest.approx(1.40, abs=0.02)   # wb 线性中点
    assert _cal_ev(-1.0, t, 1.50) == pytest.approx(1.60, abs=1e-9)   # 越上界端点钳制


def test_cal_ev_2d_neighborhood_too_small_falls_back():
    t = _write(_2D)
    # med=2.0 处 ±0.3 邻域仅 1 结点 → 不做 wb 插值, 保持 med 主键结果
    assert _cal_ev(2.0, t, 0.45) == pytest.approx(0.10, abs=1e-9)


# --- _auto_ev 接线 -----------------------------------------------------------

_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]


class _FakeRaw:
    def __init__(self):
        self.camera_whitebalance = [2.0, 1.0, 1.5, 1.0]


def _mk_ctx(image):
    prof = DcpProfile(
        path=Path("test.dcp"),
        color_matrix1=_NIKON_CM1,
        color_matrix2=_NIKON_CM2,
        forward_matrix1=_NIKON_FM1,
        forward_matrix2=_NIKON_FM1,
        baseline_exposure_offset=0.0,
    )
    ctx = StageContext(
        "test.nef",
        raw=_FakeRaw(),
        prof=prof,
        config={"stages": {"whitebalance": {"mode": "off"},
                           "exposure": {"target_offset": 0.0}}},
    )
    ctx.set_image(image.astype(np.float32), DOMAIN_LINEAR_CAM)
    return ctx


def _scene_med(image):
    ctx = _mk_ctx(image)
    return float(np.median(np.log2(
        np.maximum(_probe_linear_srgb(ctx, ctx.image), 1e-6)))), ctx


def test_auto_ev_modes_and_wb_axis_drives_ev():
    image = np.full((64, 64, 3), 0.25, dtype=np.float32)
    med, _ = _scene_med(image)

    # 一维表 → cal_table, EV 与 _cal_ev(med) 一致
    t1 = _write(_1D)
    ctx = _mk_ctx(image)
    ev = ExposureStage()._auto_ev(ctx)
    assert ctx.state["ev_mode"] == "cal_table"
    assert ev == pytest.approx(_cal_ev(med, t1, None))

    # 二维表: 三个不同 med 结点均落在 ±0.3 邻域内, wb_B 决定命中哪一结点
    tbl = [[med - 0.06, 0.50, 0.80],
           [med + 0.02, 1.60, 1.20],
           [med + 0.28, 0.70, 1.00]]
    _write(tbl)
    # 邻域三结点 (wb 0.5/0.7/1.6) 全部参与插值; wb_B=1.5 落在 0.7~1.6 段
    exp_warm = float(np.interp(1.5, [0.50, 0.70, 1.60], [0.80, 1.00, 1.20]))
    ctx_warm = _mk_ctx(image)
    ctx_warm.state["camera_wb"] = np.array([1.0, 1.0, 1.5], dtype=np.float32)
    ev_warm = ExposureStage()._auto_ev(ctx_warm)
    assert ctx_warm.state["ev_mode"] == "cal_table_2d"
    assert ev_warm == pytest.approx(exp_warm, abs=1e-9)

    # wb_B=0.5 精确命中最低 wb 结点
    ctx_day = _mk_ctx(image)
    ctx_day.state["camera_wb"] = np.array([1.0, 1.0, 0.5], dtype=np.float32)
    ev_day = ExposureStage()._auto_ev(ctx_day)
    assert ev_day == pytest.approx(0.80, abs=1e-6)

    # wb 轴真正驱动 EV: 两场景同亮度不同 WB, EV 必须不同
    assert abs(ev_warm - ev_day) > 0.3
