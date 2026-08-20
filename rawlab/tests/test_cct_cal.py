"""T2 单元测试: 按 CCT 分段相机观感标定 (engine/calibration.py + colorcal + fit_camera_look)。

覆盖 (验收: 插值/钳位/旧格式兼容; colorcal 按 cct 选曲线; 拟合工具输出新格式):
  - camera_look_curves: 新格式 by_cct 桶间线性插值 (中点/端点/多桶/乱序桶)
  - camera_look_curves: 桶外钳位 (低于首桶/高于末桶)
  - camera_look_curves: 旧格式 (无 by_cct, 按 dcp_name) 兼容返回静态曲线
  - camera_look_curves: 新格式仅 default (无 by_cct) 静态回退; 空表 → (None, None)
  - camera_look_curves: 单桶 → 直接返回该桶曲线
  - colorcal._neutral_curves: static 模式用 ctx.state['cct_k'] 选曲线; 缺省回退 6500
  - colorcal._neutral_curves: 参数显式给定 > 标定; prof=None → (None, None)
  - fit_camera_look: offsets_to_curve 取负中位+钳幅; compose_cct_cal 输出新格式
  - 拟合工具输出 → camera_look_curves 回读往返一致

运行: python -m pytest rawlab/tests/test_cct_cal.py -q
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

import rawlab.engine.calibration as calibration
from rawlab.engine.core import DOMAIN_GAMMA_RGB, StageContext
from rawlab.engine.stages.colorcal import (
    ColorCalStage,
    _check_scene_skin_trim,
    _check_scene_trim,
    _scene_skin_trim_for_wb,
    _scene_trim_for_wb,
)
from rawlab.tools.fit_camera_look import compose_cct_cal, offsets_to_curve


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

class _Prof:
    """最小 prof 替身: camera_look_curves 只读 .name。"""

    def __init__(self, name="Nikon Z 5 2"):
        self.name = name


def _point_cal(monkeypatch, cal_file):
    """把 engine.calibration 指向合成标定文件并清缓存。"""
    monkeypatch.setattr(calibration, "_CAL_FILE", cal_file)
    monkeypatch.setattr(calibration, "_cached", None)


def _write_cal(tmp_path, obj, monkeypatch):
    cal_file = tmp_path / "cct_cal.json"
    cal_file.write_text(json.dumps(obj), encoding="utf-8")
    _point_cal(monkeypatch, cal_file)
    return cal_file


# 合成新格式标定表: 两个桶, a 曲线逐点等差、b 曲线为常数, 便于手算插值
_LO_A = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0]
_HI_A = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
_MID_A = [5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0]
_LO_B = [100.0] * 7
_HI_B = [200.0] * 7


def _new_cal():
    return {
        "default": {"neutral_a_curve": [0.0] * 7, "neutral_b_curve": [0.0] * 7},
        "by_cct": [
            [3500.0, {"neutral_a_curve": _LO_A, "neutral_b_curve": _LO_B}],
            [5500.0, {"neutral_a_curve": _HI_A, "neutral_b_curve": _HI_B}],
        ],
    }


# ---------------------------------------------------------------------------
# 插值 / 钳位
# ---------------------------------------------------------------------------

def test_interp_midpoint(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    a, b = calibration.camera_look_curves(_Prof(), 4500.0)
    assert np.allclose(a, _MID_A), f"中点插值 a 应为 {_MID_A}, 实得 {a}"
    assert np.allclose(b, [150.0] * 7)


def test_interp_endpoints(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    a_lo, b_lo = calibration.camera_look_curves(_Prof(), 3500.0)
    assert np.allclose(a_lo, _LO_A)
    assert np.allclose(b_lo, _LO_B)
    a_hi, b_hi = calibration.camera_look_curves(_Prof(), 5500.0)
    assert np.allclose(a_hi, _HI_A)
    assert np.allclose(b_hi, _HI_B)


def test_clamp_below_first_bucket(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    a, b = calibration.camera_look_curves(_Prof(), 2000.0)   # < 3500 → 钳位首桶
    assert np.allclose(a, _LO_A)
    assert np.allclose(b, _LO_B)


def test_clamp_above_last_bucket(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    a, b = calibration.camera_look_curves(_Prof(), 9000.0)   # > 5500 → 钳位末桶
    assert np.allclose(a, _HI_A)
    assert np.allclose(b, _HI_B)


def test_three_buckets_unsorted_input(tmp_path, monkeypatch):
    """多桶 + 乱序 by_cct → 内部按 cct 升序, 插值正确。"""
    cal = {
        "default": {"neutral_a_curve": [0.0] * 3, "neutral_b_curve": [0.0] * 3},
        "by_cct": [
            [5500.0, {"neutral_a_curve": [20.0, 20.0, 20.0], "neutral_b_curve": [2.0, 2.0, 2.0]}],
            [3000.0, {"neutral_a_curve": [0.0, 0.0, 0.0], "neutral_b_curve": [0.0, 0.0, 0.0]}],
            [4000.0, {"neutral_a_curve": [10.0, 10.0, 10.0], "neutral_b_curve": [1.0, 1.0, 1.0]}],
        ],
    }
    _write_cal(tmp_path, cal, monkeypatch)
    # 3500 在 3000 与 4000 之间 → 中点: a=[5], b=[0.5]
    a, b = calibration.camera_look_curves(_Prof(), 3500.0)
    assert np.allclose(a, [5.0, 5.0, 5.0])
    assert np.allclose(b, [0.5, 0.5, 0.5])
    # 4500 在 4000 与 5500 之间, t=(4500-4000)/1500=1/3 → a=10+10/3, b=1+1/3
    a, b = calibration.camera_look_curves(_Prof(), 4500.0)
    assert np.allclose(a, [40.0 / 3.0] * 3)
    assert np.allclose(b, [4.0 / 3.0] * 3)


def test_single_bucket_returns_that_curve(tmp_path, monkeypatch):
    cal = {"default": {"neutral_a_curve": [9.0] * 7, "neutral_b_curve": [9.0] * 7},
           "by_cct": [[4200.0, {"neutral_a_curve": _HI_A, "neutral_b_curve": _HI_B}]]}
    _write_cal(tmp_path, cal, monkeypatch)
    for cct in (1000.0, 4200.0, 9000.0):
        a, b = calibration.camera_look_curves(_Prof(), cct)
        assert np.allclose(a, _HI_A)
        assert np.allclose(b, _HI_B)


# ---------------------------------------------------------------------------
# 旧格式兼容 / 静态回退
# ---------------------------------------------------------------------------

def test_old_format_by_name(tmp_path, monkeypatch):
    old = {"Nikon Z 5 2": {"neutral_a_curve": _LO_A, "neutral_b_curve": _LO_B}}
    _write_cal(tmp_path, old, monkeypatch)
    a, b = calibration.camera_look_curves(_Prof("Nikon Z 5 2"), 4500.0)
    assert np.allclose(a, _LO_A)
    assert np.allclose(b, _LO_B)


def test_old_format_unknown_name_falls_back_none(tmp_path, monkeypatch):
    old = {"Nikon Z 5 2": {"neutral_a_curve": _LO_A, "neutral_b_curve": _LO_B}}
    _write_cal(tmp_path, old, monkeypatch)
    a, b = calibration.camera_look_curves(_Prof("Other Camera"), 4500.0)
    assert a is None and b is None


def test_new_format_default_only_static(tmp_path, monkeypatch):
    cal = {"default": {"neutral_a_curve": _LO_A, "neutral_b_curve": _LO_B}}
    _write_cal(tmp_path, cal, monkeypatch)
    a, b = calibration.camera_look_curves(_Prof(), 4500.0)   # 无 by_cct → default 静态
    assert np.allclose(a, _LO_A)
    assert np.allclose(b, _LO_B)


def test_empty_table_returns_none(tmp_path, monkeypatch):
    _write_cal(tmp_path, {}, monkeypatch)
    a, b = calibration.camera_look_curves(_Prof(), 4500.0)
    assert a is None and b is None


def test_none_cct_defaults_6500(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    a, b = calibration.camera_look_curves(_Prof(), None)
    # None → 6500 → 钳位到末桶 (5500)
    assert np.allclose(a, _HI_A)
    assert np.allclose(b, _HI_B)


def test_camera_neutral_trim_still_works_old_format(tmp_path, monkeypatch):
    old = {"Nikon Z 5 2": {"neutral_a_curve": _LO_A, "neutral_b_curve": _LO_B}}
    _write_cal(tmp_path, old, monkeypatch)
    a, b = calibration.camera_neutral_trim(_Prof("Nikon Z 5 2"))
    assert np.allclose(a, _LO_A)
    assert np.allclose(b, _LO_B)


def test_camera_neutral_trim_returns_default_new_format(tmp_path, monkeypatch):
    """新格式: camera_neutral_trim 内部返回 default 曲线 (全集中位静态)。"""
    cal = {"default": {"neutral_a_curve": _LO_A, "neutral_b_curve": _LO_B},
           "by_cct": [[5500.0, {"neutral_a_curve": _HI_A, "neutral_b_curve": _HI_B}]]}
    _write_cal(tmp_path, cal, monkeypatch)
    a, b = calibration.camera_neutral_trim(_Prof("Nikon Z 5 2"))
    assert np.allclose(a, _LO_A)
    assert np.allclose(b, _LO_B)


# ---------------------------------------------------------------------------
# colorcal: 按 ctx cct 选曲线
# ---------------------------------------------------------------------------

def _colorcal_ctx(cct_k=None, prof=None):
    ctx = StageContext("test.nef", prof=prof)
    if cct_k is not None:
        ctx.state["cct_k"] = cct_k
    return ctx


def test_colorcal_static_uses_ctx_cct(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    prof = _Prof()
    stage = ColorCalStage()

    a, b = stage._neutral_curves(_colorcal_ctx(cct_k=4500.0, prof=prof))
    assert np.allclose(a, _MID_A)
    assert np.allclose(b, [150.0] * 7)

    # 不同 cct → 不同曲线 (选到不同桶)
    a2, b2 = stage._neutral_curves(_colorcal_ctx(cct_k=5500.0, prof=prof))
    assert np.allclose(a2, _HI_A)
    assert np.allclose(b2, _HI_B)


def test_colorcal_default_cct_falls_back_6500(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    # 无 cct_k → 6500 → 钳位到末桶 (5500)
    a, b = ColorCalStage()._neutral_curves(_colorcal_ctx(prof=_Prof()))
    assert np.allclose(a, _HI_A)
    assert np.allclose(b, _HI_B)


def test_colorcal_explicit_param_overrides_cal(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    prof = _Prof()
    ctx = StageContext("test.nef", prof=prof,
                       config={"stages": {"colorcal": {
                           "neutral_a_curve": [1.0] * 7, "neutral_b_curve": [2.0] * 7}}})
    a, b = ColorCalStage()._neutral_curves(ctx)
    assert np.allclose(a, [1.0] * 7)
    assert np.allclose(b, [2.0] * 7)


def test_colorcal_no_prof_returns_none(tmp_path, monkeypatch):
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    a, b = ColorCalStage()._neutral_curves(_colorcal_ctx(cct_k=4500.0, prof=None))
    assert a is None and b is None


def test_colorcal_output_varies_with_cct(tmp_path, monkeypatch):
    """合成中性小图走 static 快路径: 不同 ctx cct → 选不同曲线 → 输出随 cct 变。"""
    _write_cal(tmp_path, _new_cal(), monkeypatch)
    stage = ColorCalStage()

    def _render(cct_k: float):
        ctx = StageContext("test.nef", prof=_Prof())
        ctx.state["cct_k"] = cct_k
        ctx.set_image(np.full((64, 64, 3), 0.5, dtype=np.float32), DOMAIN_GAMMA_RGB)
        stage.process(ctx)
        return ctx.image

    out_lo = _render(2000.0)   # < 3500 → 钳位首桶 (_LO_A/_LO_B)
    out_hi = _render(9000.0)   # > 5500 → 钳位末桶 (_HI_A/_HI_B)
    assert out_lo.shape == (64, 64, 3)
    assert out_hi.shape == (64, 64, 3)
    # 中性灰上不同 a/b 曲线 → 不同 RGB tint, 输出应可区分
    diff = float(np.abs(out_lo - out_hi).max())
    assert diff > 1e-3, f"输出应随 cct 变化, max|Δ|={diff}"

    # 中点 cct 落在两桶间插值 → 与任一端点都不同 (非退化)
    out_mid = _render(4500.0)
    assert float(np.abs(out_mid - out_lo).max()) > 1e-3
    assert float(np.abs(out_mid - out_hi).max()) > 1e-3


# ---------------------------------------------------------------------------
# 拟合工具: 输出新格式
# ---------------------------------------------------------------------------

def test_offsets_to_curve_negates_median_and_clamps():
    band_a = [[1.0, 3.0], [2.0], [], [100.0], [0.0], [0.0], [0.0]]
    band_b = [[0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0]]
    a, b = offsets_to_curve(band_a, band_b)
    assert a[0] == -2.0     # 中位 2 → 取负
    assert a[1] == -2.0
    assert a[2] == 0.0      # 空 → 0
    assert a[3] == -50.0    # 100 → 钳幅 *0.5 再取负
    assert len(a) == len(b) == 7


def test_compose_cct_cal_new_format():
    default = ([1.0, 2.0], [3.0, 4.0])
    rows = [(6500.0, ([10.0, 20.0], [30.0, 40.0])),
            (3500.0, ([1.0, 1.0], [2.0, 2.0]))]
    cal = compose_cct_cal(default, rows)
    assert set(cal.keys()) == {"default", "by_cct"}
    assert cal["default"]["neutral_a_curve"] == [1.0, 2.0]
    assert cal["default"]["neutral_b_curve"] == [3.0, 4.0]
    # by_cct 按 cct 升序
    assert [row[0] for row in cal["by_cct"]] == [3500.0, 6500.0]
    assert cal["by_cct"][0][1]["neutral_a_curve"] == [1.0, 1.0]
    assert cal["by_cct"][0][1]["neutral_b_curve"] == [2.0, 2.0]
    assert cal["by_cct"][1][1]["neutral_a_curve"] == [10.0, 20.0]


def test_fit_output_roundtrip_via_camera_look_curves(tmp_path, monkeypatch):
    """拟合工具 compose_cct_cal 输出 → camera_look_curves 回读 → 插值一致。"""
    default = ([0.0] * 7, [0.0] * 7)
    rows = [(3500.0, (_LO_A, _LO_B)), (5500.0, (_HI_A, _HI_B))]
    cal = compose_cct_cal(default, rows)
    _write_cal(tmp_path, cal, monkeypatch)

    a, b = calibration.camera_look_curves(_Prof(), 4500.0)
    assert np.allclose(a, _MID_A)
    assert np.allclose(b, [150.0] * 7)
    # default 静态曲线也可回读
    a_def, b_def = calibration.camera_look_curves(_Prof(), 999999.0)
    assert np.allclose(a_def, _HI_A)   # 999999 钳位末桶


# ---------------------------------------------------------------------------
# scene_trim: (wb_R, wb_B) 场景色偏窗口 (问题清单 B4/A4)
# ---------------------------------------------------------------------------

def test_scene_trim_validation_and_match():
    win = _check_scene_trim([[1.25, 1.28, 2.36, 2.40, -4.0, 14.0]])
    wb_hit = np.array([1.2656, 1.0, 2.377], dtype=np.float32)
    wb_miss = np.array([1.2324, 1.0, 2.3848], dtype=np.float32)
    assert _scene_trim_for_wb(wb_hit, win) == (-4.0, 14.0)
    assert _scene_trim_for_wb(wb_miss, win) == (0.0, 0.0)
    assert _scene_trim_for_wb(None, win) == (0.0, 0.0)
    # 多窗口累加
    win2 = _check_scene_trim([[1.25, 1.28, 2.36, 2.40, -4.0, 14.0],
                              [1.20, 1.30, 2.30, 2.45, 1.0, -2.0]])
    assert _scene_trim_for_wb(wb_hit, win2) == (-3.0, 12.0)
    for bad in ([[1.0, 1.0, 1.0, 1.0, 0.0]],                 # 列数不足
                [[1.3, 1.2, 2.3, 2.4, 0.0, 0.0]],            # r 下界 > 上界
                [[1.0, 1.2, 2.3, 2.4, 30.0, 0.0]]):          # da 越界
        with pytest.raises(ValueError):
            _check_scene_trim(bad)


def test_colorcal_scene_trim_applies_even_neutral_mode_off():
    """neutral_mode='off' 时 scene_trim 命中仍生效 (显式场景修正, 非自动校准)。"""
    stage = ColorCalStage()
    ctx = StageContext("test.nef", prof=_Prof())
    ctx.state["wb_cam"] = np.array([1.2656, 1.0, 2.377], dtype=np.float32)
    ctx.state["wb"] = np.array([1.32, 1.06, 2.00], dtype=np.float32)
    ctx.set_image(np.full((32, 32, 3), 0.5, dtype=np.float32), DOMAIN_GAMMA_RGB)
    ctx.config = {"stages": {"colorcal": {
        "neutral_mode": "off",
        "scene_trim": [[1.25, 1.28, 2.36, 2.40, -4.0, 14.0]],
    }}}
    stage.run(ctx)
    assert ctx.results[-1].metrics.get("scene_trim") == [-4.0, 14.0]
    # 校正前输入严格中性; 命中后应产生可观测的 RGB tint
    assert float(np.abs(ctx.image - 0.5).max()) > 1e-3


def test_colorcal_scene_trim_window_miss_noop():
    stage = ColorCalStage()
    ctx = StageContext("test.nef", prof=_Prof())
    ctx.state["wb_cam"] = np.array([1.2324, 1.0, 2.3848], dtype=np.float32)
    ctx.set_image(np.full((32, 32, 3), 0.5, dtype=np.float32), DOMAIN_GAMMA_RGB)
    ctx.config = {"stages": {"colorcal": {
        "neutral_mode": "off",
        "scene_trim": [[1.25, 1.28, 2.36, 2.40, -4.0, 14.0]],
    }}}
    stage.run(ctx)
    assert "scene_trim" not in ctx.results[-1].metrics
    assert np.array_equal(ctx.image, np.full((32, 32, 3), 0.5, dtype=np.float32))


# ---------------------------------------------------------------------------
# skin_trim: 肤色区 Lab 显式偏移 (用户反馈: 肤色过红)
# ---------------------------------------------------------------------------

def test_colorcal_skin_trim_applies_with_neutral_mode_off():
    """neutral_mode='off' 时 skin_trim 仍生效, 肤色块 a 下降 / b 上升。"""
    import cv2 as _cv2
    skin = np.full((64, 64, 3), (210, 155, 130), dtype=np.uint8)  # 椭圆内肤色
    ctx = StageContext("test.nef", prof=_Prof())
    ctx.set_image(skin.astype(np.float32) / 255.0, DOMAIN_GAMMA_RGB)
    ctx.config = {"stages": {"colorcal": {
        "neutral_mode": "off", "skin_trim": [-4.0, 2.0]}}}
    ColorCalStage().run(ctx)
    assert ctx.results[-1].metrics["skin_trim"] == [-4.0, 2.0]
    lab0 = _cv2.cvtColor(skin, _cv2.COLOR_RGB2LAB).astype(np.float32)
    lab1 = _cv2.cvtColor((np.clip(ctx.image, 0, 1) * 255 + .5).astype(np.uint8),
                         _cv2.COLOR_RGB2LAB).astype(np.float32)
    assert float(np.median(lab1[..., 1])) < float(np.median(lab0[..., 1])) - 2.0
    assert float(np.median(lab1[..., 2])) > float(np.median(lab0[..., 2]))


def test_colorcal_skin_trim_validation():
    stage = ColorCalStage()
    ctx = StageContext("test.nef", prof=_Prof())
    ctx.config = {"stages": {"colorcal": {"skin_trim": [1.0]}}}
    with pytest.raises(ValueError):
        stage._skin_trim_offsets(ctx)
    ctx.config = {"stages": {"colorcal": {"skin_trim": [30.0, 0.0]}}}
    with pytest.raises(ValueError):
        stage._skin_trim_offsets(ctx)


def test_scene_skin_trim_match_and_validation():
    win = _check_scene_skin_trim([[1.39, 1.43, -2.0, -4.0]])
    wb_hit = np.array([1.66, 1.0, 1.41], dtype=np.float32)
    wb_miss = np.array([1.24, 1.0, 1.79], dtype=np.float32)
    assert _scene_skin_trim_for_wb(wb_hit, win) == (-2.0, -4.0)
    assert _scene_skin_trim_for_wb(wb_miss, win) == (0.0, 0.0)
    with pytest.raises(ValueError):
        _check_scene_skin_trim([[1.43, 1.39, 0.0, 0.0]])
