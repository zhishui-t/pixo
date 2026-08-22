"""T2.3 修复: 手动WB mode=manual 时 exposure 自动曝光探针崩溃 (t23 FAIL)。

根因: exposure.py `_probe_linear_srgb` 非 off/auto/as_shot 时把 mode 当数值
向量 np.array("manual") → "could not convert string to float: 'manual'"。
本测试覆盖修复后的 manual temp/tint 分支 + 旧模式回归 + 缺 temp 报错。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pixo.render.core.calibration import DcpProfile
from pixo.render.core.color import cam_to_xyz, temp_tint_to_wb
from pixo.render.pipeline.graph import StageContext, DOMAIN_LINEAR_CAM
from pixo.render.modules.exposure import (
    ExposureStage,
    _probe_linear_srgb,
)
import pixo.render.modules.exposure as _exposure_mod

# 真实 Nikon Z 5 II Camera Standard 矩阵 (与 test_exposure / test_wb_temp_tint 一致)
_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]


class _FakeRaw:
    def __init__(self, wb=(2.0, 1.0, 1.5)):
        self.camera_whitebalance = [wb[0], wb[1], wb[2], 1.0]


@pytest.fixture(autouse=True)
def _no_cal_file(monkeypatch):
    """屏蔽每机标定文件, 走锚点路径 (与 test_exposure 一致)。"""
    monkeypatch.setattr(_exposure_mod, "_CAL_FILE",
                        _exposure_mod._CAL_FILE.parent / "__nonexistent_cal__.json")
    monkeypatch.setattr(_exposure_mod, "_cached_table", None)
    monkeypatch.setattr(_exposure_mod, "_cached_offset", None)


def _profile() -> DcpProfile:
    return DcpProfile(path=Path("test.dcp"), color_matrix1=_NIKON_CM1,
                      color_matrix2=_NIKON_CM2, forward_matrix1=_NIKON_FM1,
                      forward_matrix2=_NIKON_FM1)


def _make_ctx(image, wb_mode="manual", temp=None, tint=None, exp_mode="auto"):
    prof = _profile()
    wb_cfg = {"mode": wb_mode}
    if temp is not None:
        wb_cfg["temp"] = temp
    if tint is not None:
        wb_cfg["tint"] = tint
    ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                       config={"stages": {"whitebalance": wb_cfg,
                                          "exposure": {"mode": exp_mode,
                                                       "target_offset": 0.0}}})
    ctx.set_image(image.astype(np.float32), DOMAIN_LINEAR_CAM)
    return ctx


def _cam_image(h=16, w=16):
    rng = np.random.default_rng(0)
    return rng.random((h, w, 3), dtype=np.float32)


def test_auto_probe_manual_temp_tint_no_crash():
    """exposure auto + whitebalance manual(5500/10) 探针不崩溃, 输出有限且形状正确。"""
    img = _cam_image()
    ctx = _make_ctx(img, wb_mode="manual", temp=5500.0, tint=10.0, exp_mode="auto")
    y = _probe_linear_srgb(ctx, img)
    assert y.shape == (img.shape[0] // 4, img.shape[1] // 4)
    assert np.isfinite(y).all()
    # 完整自动曝光 EV 计算也不崩溃
    ev = ExposureStage({"mode": "auto"})._auto_ev(ctx)
    assert np.isfinite(float(ev))


def test_off_manual_normal():
    """exposure off + whitebalance manual 正常 (off 不触发探针, 图像不变)。"""
    img = np.full((8, 8, 3), 0.5, dtype=np.float32)
    ctx = _make_ctx(img, wb_mode="manual", temp=5500.0, tint=10.0, exp_mode="off")
    in_copy = ctx.image.copy()
    ExposureStage({"mode": "off"}).run(ctx)      # off → process 提前 return
    assert np.array_equal(ctx.image, in_copy)     # 无探针调用, 无崩溃


def test_manual_probe_wb_equals_temp_tint_to_wb():
    """manual 探针实际使用的 wb == temp_tint_to_wb(prof,5500,10) 归一化结果。

    _probe_linear_srgb 返回亮度 y=luma(cam_to_xyz(small,wb,prof)); 因此
    manual 路径 y 应等于用 temp_tint_to_wb 归一化 wb 重算的亮度。
    """
    img = _cam_image()
    ctx = _make_ctx(img, wb_mode="manual", temp=5500.0, tint=10.0)
    y_manual = _probe_linear_srgb(ctx, img)
    # 期望 wb 与亮度
    prof = _profile()
    expected_wb = temp_tint_to_wb(prof, 5500.0, 10.0)
    expected_wb = expected_wb / expected_wb[1]
    rgb_exp = cam_to_xyz(img[::4, ::4], expected_wb, _profile())
    y_exp = (0.2126 * rgb_exp[..., 0] + 0.7152 * rgb_exp[..., 1]
             + 0.0722 * rgb_exp[..., 2]).astype(np.float32)
    assert float(np.abs(y_manual - y_exp).max()) < 1e-5


@pytest.mark.parametrize("wb_mode", ["as_shot", "auto", "off", [2.0, 1.0, 1.5]])
def test_old_modes_regression(wb_mode):
    """as_shot/auto/off/数值向量 四种旧模式行为回归 (不崩溃、输出有限形状对)。"""
    img = _cam_image()
    ctx = _make_ctx(img, wb_mode=wb_mode)
    y = _probe_linear_srgb(ctx, img)
    assert y.shape == (img.shape[0] // 4, img.shape[1] // 4)
    assert np.isfinite(y).all()


def test_manual_missing_temp_raises():
    """manual 缺 temp 时抛 ValueError 且信息含 temp。"""
    img = _cam_image()
    ctx = _make_ctx(img, wb_mode="manual")          # temp=None
    with pytest.raises(ValueError, match="temp"):
        _probe_linear_srgb(ctx, img)
