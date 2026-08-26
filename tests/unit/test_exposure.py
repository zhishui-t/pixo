"""T4 单元测试: 曝光锚定 + 高光软滚降 (render/modules/exposure.py)。

覆盖 (验收: 锚定≈117、裁切<2%、主体加权、max_ev 钳位):
  - soft_highlight_rolloff 单调 / 不硬裁 / knee 以下不变
  - log2 中位锚定 (ev = anchor - median)
  - 锚定中灰 ≈117 (curve_anchor_target + 曲线基)
  - BaselineExposureOffset 符号 (T2 结论: ev += offset)
  - 主体加权 (subject_boxes)
  - max_ev 钳位
  - 高光保护裁切 <2%

运行: python -m pytest tests/test_exposure.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pixo.render.core.calibration import DcpProfile
from pixo.render.pipeline.graph import StageContext, DOMAIN_LINEAR_CAM
from pixo.render.core.curves import apply_lut1d, curve_anchor_target, make_power_lut
from pixo.render.modules.exposure import (
    ExposureStage,
    _baseline_curve_ev,
    _baseline_scene_ev,
    _check_baseline_ev_curve,
    _check_baseline_scene_ev,
    _probe_linear_srgb,
    soft_highlight_rolloff,
)
import pixo.render.modules.exposure as _exposure_mod


@pytest.fixture(autouse=True)
def _no_cal_file(monkeypatch):
    """单测不依赖每机标定文件 (engine/target_offset.json): 屏蔽之, 走锚点路径。

    标定文件是环境数据, 若存在会改变 _auto_ev 走查表路径, 使锚点类断言
    全部失效。加载行为的专项测试 (test_target_offset_default_loads_...) 会
    自行 monkeypatch 覆盖。
    """
    monkeypatch.setattr(_exposure_mod, "_CAL_FILE",
                        _exposure_mod._CAL_FILE.parent / "__nonexistent_cal__.json")
    monkeypatch.setattr(_exposure_mod, "_cached_table", None)
    monkeypatch.setattr(_exposure_mod, "_cached_offset", None)

# 真实 Nikon Z 5 II Camera Standard 矩阵 (与 T2 测试一致, 确定性用例)
_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]


class _FakeRaw:
    def __init__(self, wb=(2.0, 1.0, 1.5)):
        self.camera_whitebalance = [wb[0], wb[1], wb[2], 1.0]


def _make_profile(baseline: float = 0.0) -> DcpProfile:
    return DcpProfile(
        path=Path("test.dcp"),
        color_matrix1=_NIKON_CM1,
        color_matrix2=_NIKON_CM2,
        forward_matrix1=_NIKON_FM1,
        forward_matrix2=_NIKON_FM1,
        baseline_exposure_offset=baseline,
    )


def _make_ctx(image, prof=None, wb_mode="off", subject_boxes=None) -> StageContext:
    prof = prof if prof is not None else _make_profile()
    ctx = StageContext(
        "test.nef",
        raw=_FakeRaw(),
        prof=prof,
        # target_offset 显式钉 0.0: 标定文件 (engine/target_offset.json) 是
        # 每机环境数据, 单测不依赖它 (默认加载行为有专门测试)。
        config={"stages": {"whitebalance": {"mode": wb_mode},
                           "exposure": {"target_offset": 0.0}}},
    )
    ctx.set_image(image.astype(np.float32), DOMAIN_LINEAR_CAM)
    if subject_boxes is not None:
        ctx.state["subject_boxes"] = subject_boxes
    return ctx


def _neutral_image(h, w, value):
    return np.full((h, w, 3), value, dtype=np.float32)


# ---------------------------------------------------------------------------
# 高光软滚降
# ---------------------------------------------------------------------------

def test_rolloff_monotonic_and_no_hard_clip():
    x = np.linspace(0.0, 3.0, 1001, dtype=np.float32)
    y = soft_highlight_rolloff(x, knee=0.9)
    assert np.all(np.diff(y.astype(np.float64)) >= -1e-7), "软滚降非单调"
    assert np.all(y <= 1.0 + 1e-6), "软滚降越界"
    # 肩部平滑滚降而非硬裁: knee 之上输出连续上升, 不立即跳到白
    y_knee = float(soft_highlight_rolloff(np.array([0.95], np.float32), 0.9)[0])
    assert 0.9 < y_knee < 1.0
    # 渐近白: 大输入趋近 1.0
    big = float(soft_highlight_rolloff(np.array([10.0], np.float32), 0.9)[0])
    assert big > 0.995


def test_rolloff_below_knee_unchanged():
    x = np.array([0.0, 0.3, 0.8, 0.9], dtype=np.float32)
    assert np.array_equal(soft_highlight_rolloff(x, knee=0.9), x)


def test_rolloff_continuity_at_knee():
    knee = 0.9
    y = soft_highlight_rolloff(np.array([knee], dtype=np.float32), knee)
    assert abs(float(y[0]) - knee) < 1e-6


# ---------------------------------------------------------------------------
# 锚定≈117
# ---------------------------------------------------------------------------

def test_anchor_midgray_maps_to_117():
    anchor = curve_anchor_target(None)          # 回退 log2(0.18)
    lin = 2.0 ** anchor
    assert abs(lin - 0.18) < 1e-6
    gamma = apply_lut1d(np.array([lin], dtype=np.float32), make_power_lut(2.2, 4096))
    assert abs(float(gamma[0]) * 255.0 - 117.0) < 1.0


# ---------------------------------------------------------------------------
# log2 中位锚定
# ---------------------------------------------------------------------------

def test_auto_ev_median_anchor():
    prof = _make_profile()
    ctx = _make_ctx(_neutral_image(64, 64, 0.3), prof=prof, wb_mode="off")
    probe = _probe_linear_srgb(ctx, ctx.image)
    median_log2 = float(np.median(np.log2(np.maximum(probe, 1e-6))))
    anchor = curve_anchor_target(prof)
    ev = ExposureStage()._auto_ev(ctx)
    # 均匀场景: 高光保护不触发 (p98≈中位), ev = anchor - median
    assert abs(ev - (anchor - median_log2)) < 1e-3


def test_target_offset_adds_ev():
    prof = _make_profile()
    img = _neutral_image(64, 64, 0.3)

    def make_ctx_no_pin():
        # 不钉 target_offset: 让实例参数层生效 (覆盖优先级: ctx > 实例 > 默认)
        ctx = StageContext("test.nef", raw=_FakeRaw(), prof=prof,
                           config={"stages": {"whitebalance": {"mode": "off"}}})
        ctx.set_image(img.astype(np.float32), DOMAIN_LINEAR_CAM)
        return ctx

    ev0 = ExposureStage({"target_offset": 0.0})._auto_ev(make_ctx_no_pin())
    ev1 = ExposureStage({"target_offset": 0.5})._auto_ev(make_ctx_no_pin())
    assert abs((ev1 - ev0) - 0.5) < 1e-6


def test_target_offset_default_loads_calibration_file(tmp_path, monkeypatch):
    """默认 target_offset 从 engine/target_offset.json 加载 (ADR-06)。"""
    import json as _json
    import pixo.render.modules.exposure as exposure_mod

    cal = tmp_path / "target_offset.json"
    cal.write_text(_json.dumps({"target_offset": -1.25}), encoding="utf-8")
    monkeypatch.setattr(exposure_mod, "_CAL_FILE", cal)
    monkeypatch.setattr(exposure_mod, "_cached_offset", None)

    stage = ExposureStage()
    assert abs(stage.default_params()["target_offset"] - (-1.25)) < 1e-9

    # 文件缺失 → 0.0
    monkeypatch.setattr(exposure_mod, "_CAL_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(exposure_mod, "_cached_offset", None)
    assert ExposureStage().default_params()["target_offset"] == 0.0


# ---------------------------------------------------------------------------
# BaselineExposureOffset 符号 (T2 结论)
# ---------------------------------------------------------------------------

def test_baseline_exposure_offset_sign():
    img = _neutral_image(64, 64, 0.3)
    ev0 = ExposureStage()._auto_ev(_make_ctx(img, prof=_make_profile(baseline=0.0)))
    evm = ExposureStage()._auto_ev(_make_ctx(img, prof=_make_profile(baseline=-0.15)))
    # 负偏移 → ev 更小 (图像更暗), 符号与 dcp.py 0xC7A5 注释一致
    assert abs((evm - ev0) - (-0.15)) < 1e-6


# ---------------------------------------------------------------------------
# 主体加权
# ---------------------------------------------------------------------------

def test_subject_weighting_uses_box_region():
    h = w = 128
    img = _neutral_image(h, w, 0.05)
    img[:, w // 2:, :] = 0.5  # 右半亮, 左半暗
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off",
                    subject_boxes=[(0.5, 0.0, 1.0, 1.0)])  # [l, t, r, b] = 右半
    stage = ExposureStage({"subject_mode": "box"})
    probe = _probe_linear_srgb(ctx, img)
    region = probe[:, probe.shape[1] // 2:]
    median_sub = float(np.median(np.log2(np.maximum(region, 1e-6))))
    anchor = curve_anchor_target(prof)
    ev = stage._auto_ev(ctx)
    assert abs(ev - (anchor - median_sub)) < 1e-3


def test_subject_weighting_differs_from_full_frame():
    h = w = 128
    img = _neutral_image(h, w, 0.05)
    img[:, w // 2:, :] = 0.5
    prof = _make_profile()
    ctx_box = _make_ctx(img, prof=prof, wb_mode="off",
                        subject_boxes=[(0.5, 0.0, 1.0, 1.0)])
    ctx_full = _make_ctx(img, prof=prof, wb_mode="off")
    ev_box = ExposureStage({"subject_mode": "box"})._auto_ev(ctx_box)
    ev_full = ExposureStage({"subject_mode": "box"})._auto_ev(ctx_full)
    assert abs(ev_box - ev_full) > 1e-3, "主体加权应改变 EV"


def test_face_priority_over_subject_boxes():
    # 用例设计：face 框放亮带、subject 框放暗区，且此时候选 EV 为负（高光/低调闸不绑定），
    # 使 face 优先可被 EV 的准确数值区分。
    h = w = 128
    img = _neutral_image(h, w, 0.05)
    img[:32, :, :] = 0.5                 # 顶部 1/4 亮（face 框区域）
    img[32:, w // 2:, :] = 0.005         # 右下 3/4 半幅暗（更大的 subject 框）
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off",
                    subject_boxes=[(0.0, 0.5, 1.0, 1.0)])  # 暗的下半部（更大）
    ctx.state["face_boxes"] = [(0.0, 0.0, 1.0, 0.25)]      # face 优先：亮带
    stage = ExposureStage({"subject_mode": "box"})
    probe = _probe_linear_srgb(ctx, img)
    h1, _w1 = probe.shape[:2]
    y0, y1 = 0, max(1, int(0.25 * h1))
    median_face = float(np.median(np.log2(np.maximum(probe[y0:y1, :], 1e-6))))
    anchor = curve_anchor_target(prof)
    ev = stage._auto_ev(ctx)
    assert abs(ev - (anchor - median_face)) < 1e-3, "face 框应优先于更大 subject 框"


def test_tiny_box_ignored_falls_back_full_frame():
    h = w = 128
    img = _neutral_image(h, w, 0.05)
    img[:, w // 2:, :] = 0.5
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off",
                    subject_boxes=[(0.5, 0.5, 0.51, 0.51)])  # 面积 1e-4 < 1%
    stage = ExposureStage({"subject_mode": "box"})
    probe = _probe_linear_srgb(ctx, img)
    med_full = float(np.median(np.log2(np.maximum(probe, 1e-6))))
    anchor = curve_anchor_target(prof)
    ev = stage._auto_ev(ctx)
    assert abs(ev - (anchor - med_full)) < 1e-3, "微小框应被忽略，回退全图中位"


# ---------------------------------------------------------------------------
# max_ev 钳位
# ---------------------------------------------------------------------------

def test_max_ev_clamp():
    prof = _make_profile()
    dark = _make_ctx(_neutral_image(64, 64, 1e-6), prof=prof, wb_mode="off")
    bright = _make_ctx(_neutral_image(64, 64, 100.0), prof=prof, wb_mode="off")
    stage = ExposureStage({"max_ev": 2.5})
    assert stage._auto_ev(dark) > 2.5    # 未钳位前超出上限
    assert stage._auto_ev(bright) < -2.5  # 未钳位前超出下限
    stage.run(dark)
    assert abs(dark.state["ev"] - 2.5) < 1e-6
    stage.run(bright)
    assert abs(bright.state["ev"] - (-2.5)) < 1e-6


# ---------------------------------------------------------------------------
# 高光保护: 裁切 <2%
# ---------------------------------------------------------------------------

def test_highlight_protection_caps_ev():
    h = w = 100
    img = _neutral_image(h, w, 0.1)
    n_bright = int(h * w * 0.10)
    img.reshape(-1, 3)[:n_bright] = 5.0  # 10% 极亮
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off")
    stage = ExposureStage({"clip_p": 98.0})
    ev = stage._auto_ev(ctx)
    probe = _probe_linear_srgb(ctx, img)
    p_hi = float(np.percentile(probe, 98.0))
    # 98 分位不越白 → 只有 <2% 的像素会越过白电平 (裁切预算)
    assert p_hi * (2.0 ** ev) <= 1.0 + 1e-5
    # 上限应真正绑定: 两道闸取最紧 —— 软帽 log2(1/p98) 与高光预算
    # log2((1-tau)/p99) (tech_debt#9, 默认 tau=0.02)
    p99 = float(np.percentile(probe, 99.0))
    tau = float(ExposureStage().default_params()["highlight_budget"])
    expected = min(np.log2(1.0 / p_hi),
                   np.log2(max(1.0 - tau, 0.0) / max(p99, 1e-9)))
    assert abs(ev - expected) < 1e-6


def test_process_no_hard_clip_after_rolloff():
    img = _neutral_image(64, 64, 0.6)
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off")
    ExposureStage({"mode": 1.0}).run(ctx)  # +1 EV → 0.6*2=1.2 越白电平
    out = ctx.image
    # 软滚降把 1.2 平滑压到白电平以内, 且严格小于 1.0 (不硬裁到白)
    assert np.all(out <= 1.0 + 1e-6), "软滚降越界"
    assert float(out.max()) < 1.0, "软滚降不应硬裁到 1.0"
    assert float(out.max()) > 0.9, "越白像素应被肩部承接 (而非压回中灰)"
    assert np.all(out >= 0.0)


# ---------------------------------------------------------------------------
# 探针与 whitebalance 共享 cam_to_xyz
# ---------------------------------------------------------------------------

def test_probe_shares_cam_to_xyz_chain():
    from pixo.render.core.color import cam_to_xyz
    img = np.random.default_rng(0).random((64, 64, 3)).astype(np.float32) * 0.5
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off")
    small = img[::4, ::4]
    # 探针亮度 == 直接 cam_to_xyz (wb=[1,1,1]) 的 Rec.709 亮度
    rgb = cam_to_xyz(small, np.ones(3, dtype=np.float32), prof)
    expected = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2])
    got = _probe_linear_srgb(ctx, img)
    assert float(np.abs(got - expected).max()) < 1e-4


# ---------------------------------------------------------------------------
# baseline 曝光曲线/场景窗口 (问题清单 A2/B3: 暖尾人脸过亮、亮暖场景过暗)
# ---------------------------------------------------------------------------

def test_baseline_ev_curve_validation_and_interp():
    curve = _check_baseline_ev_curve([[1.0, 0.0], [2.0, -0.5], [3.0, 0.2]])
    assert _baseline_curve_ev(1.5, curve) == pytest.approx(-0.25)
    assert _baseline_curve_ev(0.5, curve) == 0.0           # 端点外钳位
    assert _baseline_curve_ev(4.0, curve) == 0.2
    for bad in ([[1.0, 0.0]],
                [[2.0, 0.0], [1.0, 0.0]],                 # 非递增
                [[1.0, 0.0], [2.0, 1.5]]):                # ev 越界
        with pytest.raises(ValueError):
            _check_baseline_ev_curve(bad)


def test_baseline_scene_ev_validation_and_accumulate():
    win = _check_baseline_scene_ev([[1.7, 2.0, -2.9, -2.0, -0.4],
                                    [1.0, 2.5, -3.0, -1.0, 0.1]])
    assert _baseline_scene_ev(1.79, -2.5, win) == pytest.approx(-0.3)
    assert _baseline_scene_ev(2.287, -1.5, win) == 0.1     # wb_B 不在第一窗
    assert _baseline_scene_ev(1.5, -3.2, win) == 0.0       # 两窗都不命中
    with pytest.raises(ValueError):
        _check_baseline_scene_ev([[1.7, 2.0, -2.9, -2.0, -0.4],
                                  [1.0, 0.5, 0.0, 1.0, 0.1]])  # wb_lo > wb_hi


def test_baseline_curve_applied_to_process():
    prof = _make_profile(baseline=-0.15)
    img = _neutral_image(64, 64, 0.3)
    ctx = _make_ctx(img, prof=prof)
    ctx.config["stages"]["exposure"] = {
        "mode": "baseline",
        "baseline_ev_curve": [[2.0, 0.0], [2.4, -0.5]],
    }
    ctx.raw = _FakeRaw(wb=(1.0, 1.0, 2.39))
    ExposureStage().run(ctx)
    assert ctx.state["baseline_curve_ev"] == pytest.approx(-0.4875)
    assert ctx.state["ev"] == pytest.approx(-0.15 - 0.4875)


def test_baseline_scene_window_anchor_safe():
    prof = _make_profile(baseline=-0.15)
    windows = [[1.7, 2.0, -2.9, -2.0, -0.4]]
    # 0479 类场景: wb_B=1.78 且中灰亮度落在窗口内 → 触发
    bright_ctx = _make_ctx(_neutral_image(64, 64, 0.15), prof=prof)
    bright_ctx.config["stages"]["exposure"] = {
        "mode": "baseline", "baseline_scene_ev": windows}
    bright_ctx.raw = _FakeRaw(wb=(1.0, 1.0, 1.78))
    ExposureStage().run(bright_ctx)
    assert bright_ctx.state["baseline_scene_ev"] == pytest.approx(-0.4)
    # 5236 类更暗场景: 亮度窗口外 → 不触发 (锚点安全)
    dark_ctx = _make_ctx(_neutral_image(64, 64, 1e-4), prof=prof)
    dark_ctx.config["stages"]["exposure"] = {
        "mode": "baseline", "baseline_scene_ev": windows}
    dark_ctx.raw = _FakeRaw(wb=(1.0, 1.0, 1.791))
    ExposureStage().run(dark_ctx)
    assert dark_ctx.state["baseline_scene_ev"] == 0.0


# ---------------------------------------------------------------------------
# t100 spike 高光钳界放宽 (标定表路径): 探针 p99 真实饱和 + 中位偏暗 → +0.15 EV;
# 平顶亮景 (med 高) 或探针未饱和 → 不触发。
# ---------------------------------------------------------------------------

def _use_table(monkeypatch, table_rows, tmp_path):
    """把 _CAL_FILE 指向临时一维标定表, 使表路径生效并清缓存。"""
    import json as _json
    import pixo.render.modules.exposure as _mod
    p = tmp_path / "cal_t100.json"
    p.write_text(_json.dumps({"cal_table": table_rows}), encoding="utf-8")
    monkeypatch.setattr(_mod, "_CAL_FILE", p)
    monkeypatch.setattr(_mod, "_cached_table", None)
    monkeypatch.setattr(_mod, "_cached_offset", None)


def test_spike_lift_applies_on_saturated_dark_median(monkeypatch, tmp_path):
    # 尖峰景: 中位暗 (0.05→log2=-4.32 ≤ -3.3), 5% 像素饱和 (p99≈8 ≥ 1.0)
    img = _neutral_image(100, 100, 0.05)
    img.reshape(-1, 3)[:int(100 * 100 * 0.05)] = 8.0
    _use_table(monkeypatch, [[-5.0, 1.0], [-4.0, 1.4], [-3.0, 1.8]], tmp_path)
    ctx = _make_ctx(img, prof=_make_profile(), wb_mode="off")
    stage = ExposureStage({})
    ev = stage._auto_ev(ctx)
    assert ctx.state.get("ev_spike_lift") is True, "spike 场景应触发 lift"
    from pixo.render.modules.exposure import _load_cal_table, _cal_ev
    tbl = _load_cal_table()
    y = _probe_linear_srgb(ctx, img)
    med = float(np.median(np.log2(np.maximum(y, 1e-6))))
    base = _cal_ev(med, tbl, None)
    assert abs(ev - (base + 0.15)) < 1e-6, f"ev={ev} base={base}"


def test_spike_lift_skipped_for_bright_median_flat_top(monkeypatch, tmp_path):
    # 平顶亮景: med 高 (-0.4 > -3.3) 即使 p99 饱和也不触发
    img = _neutral_image(100, 100, 0.6)
    img.reshape(-1, 3)[:int(100 * 100 * 0.3)] = 8.0
    _use_table(monkeypatch, [[-5.0, 1.0], [-4.0, 1.4], [-3.0, 1.8]], tmp_path)
    ctx = _make_ctx(img, prof=_make_profile(), wb_mode="off")
    stage = ExposureStage({})
    ev = stage._auto_ev(ctx)
    assert not ctx.state.get("ev_spike_lift"), "平顶亮景不应触发 lift"
    from pixo.render.modules.exposure import _load_cal_table, _cal_ev
    tbl = _load_cal_table()
    y = _probe_linear_srgb(ctx, img)
    med = float(np.median(np.log2(np.maximum(y, 1e-6))))
    base = _cal_ev(med, tbl, None)
    assert abs(ev - base) < 1e-6


def test_spike_lift_skipped_when_probe_not_saturated(monkeypatch, tmp_path):
    # 尖峰形状但探针未饱和 (p99=0.5) → 相机不会大量 clip, 不触发
    img = _neutral_image(100, 100, 0.05)
    img.reshape(-1, 3)[:int(100 * 100 * 0.05)] = 0.5
    _use_table(monkeypatch, [[-5.0, 1.0], [-4.0, 1.4], [-3.0, 1.8]], tmp_path)
    ctx = _make_ctx(img, prof=_make_profile(), wb_mode="off")
    stage = ExposureStage({})
    ev = stage._auto_ev(ctx)
    assert not ctx.state.get("ev_spike_lift"), "探针未饱和不应触发 lift"
    from pixo.render.modules.exposure import _load_cal_table, _cal_ev
    tbl = _load_cal_table()
    y = _probe_linear_srgb(ctx, img)
    med = float(np.median(np.log2(np.maximum(y, 1e-6))))
    base = _cal_ev(med, tbl, None)
    assert abs(ev - base) < 1e-6
