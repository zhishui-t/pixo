"""T1.3 手动白平衡 temp/tint (WhiteBalanceStage mode=manual) —— 物理接入测试。

覆盖: temp_tint_to_wb 往返、中性灰经 manual 矩阵仍中性、tint/temp 方向、
      等价回归 (默认/向量 mode)、参数序列化、warmth 跳过、缺 temp 报错。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.calibration import DcpProfile
from pixo.render.core.color import (cam_to_linear_srgb_matrix, temp_tint_to_wb,
                                 wb_to_temp_tint)
from pixo.render.pipeline.graph import StageContext, DOMAIN_LINEAR_CAM, DOMAIN_LINEAR_RGB
from pixo.render.modules.white_balance import WhiteBalanceStage, apply_warmth
from pathlib import Path


# 真实 Nikon Z 5 II Camera Standard 矩阵 (与 test_exposure / T2 一致, 确定性)
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


def _run_manual(temp, tint, warmth=1.0, prof=None, image=None):
    prof = prof if prof is not None else _profile()
    ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                       config={"stages": {"whitebalance": {
                           "mode": "manual", "temp": temp, "tint": tint,
                           "warmth": warmth}}})
    ctx.set_image(image.astype(np.float32) if image is not None
                  else np.full((8, 8, 3), 0.5, dtype=np.float32),
                  DOMAIN_LINEAR_CAM)
    WhiteBalanceStage().run(ctx)
    return ctx


def test_manual_wb_equals_temp_tint_to_wb():
    """manual: wb 恰为 temp_tint_to_wb(prof, temp, tint) 结果 (G=1), mode 正确写回。"""
    ctx = _run_manual(4500.0, 0.0)
    expected = temp_tint_to_wb(_profile(), 4500.0, 0.0)
    expected = expected / expected[1]
    assert ctx.state["wb_mode"] == "manual"
    assert np.allclose(ctx.state["wb"], expected, atol=1e-5)
    assert np.isclose(float(ctx.state["wb"][1]), 1.0, atol=1e-6)  # G=1 归一化
    assert ctx.state["cct_k"] > 0
    assert ctx.domain == DOMAIN_LINEAR_RGB
    assert np.allclose(ctx.results[-1].metrics["wb"], np.round(ctx.state["wb"], 4))


def test_roundtrip_temp_tint_small_error():
    """temp_tint_to_wb → (归一化 G=1) → wb_to_temp_tint 往返: temp 误差小 (色温可辨)。"""
    prof = _profile()
    # tint=0 处往返最稳 (dT≤~60K)
    for t in (3000.0, 4500.0, 6500.0):
        wb = temp_tint_to_wb(prof, t, 0.0)
        wb = wb / wb[1]
        t2, _ = wb_to_temp_tint(prof, wb)
        assert abs(t2 - t) < 200.0, f"temp 往返误差过大 t={t:.0f}->{t2:.0f}"
    # 非零 tint 往返: 色温仍可辨 (tint 求解分档较粗 ±25)
    wb = temp_tint_to_wb(prof, 4000.0, -15.0)
    t2, ti2 = wb_to_temp_tint(prof, wb)
    assert abs(t2 - 4000.0) < 300.0
    assert abs(abs(ti2) - abs(-15.0)) <= 25.0 + 1e-6


def test_manual_neutral_gray_stays_neutral():
    """WB 中性点 (相机信号 ∝ 1/wb, 经 WB 后均匀) 通过 manual 矩阵后仍中性。"""
    prof = _profile()
    for (t, ti) in [(4500.0, 0.0), (3000.0, 10.0), (6500.0, -10.0)]:
        wb = temp_tint_to_wb(prof, t, ti)
        wb = wb / wb[1]
        # 相机中性信号 = n / wb (逐通道), WB 后为均匀灰
        neut = np.zeros((16, 16, 3), dtype=np.float32)
        neut[..., 0] = 0.5 / wb[0]
        neut[..., 1] = 0.5 / wb[1]
        neut[..., 2] = 0.5 / wb[2]
        ctx = _run_manual(t, ti, image=neut)
        out = ctx.image
        spread = float(np.ptp(out, axis=2).max())
        assert spread < 1e-3, f"t={t} ti={ti} 中性输出不平衡 spread={spread}"


def test_tint_direction_rel_b_ratio():
    """tint 更正则 wb_B 相对 wb_R 更强 (r/b 比值下降), 方向符合实现。"""
    prof = _profile()
    wb_neg = temp_tint_to_wb(prof, 4500.0, -60.0)
    wb_zero = temp_tint_to_wb(prof, 4500.0, 0.0)
    wb_pos = temp_tint_to_wb(prof, 4500.0, 60.0)
    r_neg = wb_neg[0] / wb_neg[2]
    r_zero = wb_zero[0] / wb_zero[2]
    r_pos = wb_pos[0] / wb_pos[2]
    assert r_neg > r_zero > r_pos, "tint 越正 → r/b 应越低 (B 相对更强)"


def test_temp_lower_b_higher():
    """色温越低 → wb_B 越高、wb_R 越低 (本配置物理方向); 用 stage manual 输出验证。"""
    c_lo = _run_manual(3000.0, 0.0)
    c_hi = _run_manual(6500.0, 0.0)
    assert c_lo.state["wb"][2] > c_hi.state["wb"][2]       # B: 低温更高
    assert c_lo.state["wb"][0] < c_hi.state["wb"][0]       # R: 低温更低


def test_mode_vector_regression():
    """旧 mode=[r,g,b] 向量行为逐字不变 (wb=arr/arr[1], 且不套 warmth)。"""
    prof = _profile()
    vec = [1.3, 1.0, 2.2]
    ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                       config={"stages": {"whitebalance": {
                           "mode": vec, "warmth": 1.0}}})
    ctx.set_image(np.full((8, 8, 3), 0.5, dtype=np.float32), DOMAIN_LINEAR_CAM)
    WhiteBalanceStage().run(ctx)
    expected = np.array(vec, dtype=np.float32) / vec[1]
    # 向量 mode 不套 warmth: 输出 wb 恰为向量本身
    assert np.allclose(ctx.state["wb"], expected, atol=1e-6)
    assert isinstance(ctx.state["wb_mode"], list)


def test_default_params_unchanged_except_new_keys():
    """default_params 与旧版一致: mode=as_shot, 新增 temp/tint=None, 旧键值不变。"""
    d = WhiteBalanceStage().default_params()
    assert d["mode"] == "as_shot"
    assert d["temp"] is None and d["tint"] is None
    assert d["warmth"] == 0.9
    assert d["warmth_curve"] is None and d["trim"] is None
    assert set(d) >= {"mode", "warmth", "warmth_b0", "warmth_b1",
                      "warmth_r_slope", "warmth_g_slope", "warmth_b_slope",
                      "warmth_r_day", "warmth_curve", "trim", "temp", "tint"}


def test_default_output_bitwise_unchanged():
    """回退路径不变: warm_cal_file 置空时输出与既有 as_shot+warmth 路径一致。

    t14 后默认缺省加载 configs/calibration/warmth_curve.json (存在时);
    本测试显式关闭该开关, 验证 "文件缺失/关闭 -> 内置斜率模型" 的兼容行为。
    """
    prof = _profile()
    raw_wb = np.array([1.291, 1.0, 2.287], dtype=np.float32)
    ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                       config={"stages": {"whitebalance": {
                           "mode": "as_shot", "warm_cal_file": ""}}})
    ctx.set_image(np.full((8, 8, 3), 0.5, dtype=np.float32), DOMAIN_LINEAR_CAM)
    WhiteBalanceStage().run(ctx)
    # 旧路径: camera_neutral_wb 之后 apply_warmth(warmth 默认 0.9)
    expected = apply_warmth(np.asarray(raw_wb, dtype=np.float32), prof, 0.9, None)
    assert ctx.state["wb_mode"] == "as_shot"
    assert np.allclose(ctx.state["wb"], expected, atol=1e-5)


def test_warm_cal_file_loads_knots(tmp_path):
    """t14: warm_cal_file 指向合法标定文件 -> 其 knots 作为 warmth_curve 生效。"""
    import json
    knots = [[1.0, 1.0, 1.0, 1.0], [3.0, 1.2, 0.9, 0.8]]
    f = tmp_path / "warmth_curve.json"
    f.write_text(json.dumps({"version": 1, "type": "warmth_curve",
                             "knots": knots}), encoding="utf-8")
    prof = _profile()
    ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                       config={"stages": {"whitebalance": {
                           "mode": "as_shot", "warm_cal_file": str(f)}}})
    ctx.set_image(np.full((8, 8, 3), 0.5, dtype=np.float32), DOMAIN_LINEAR_CAM)
    WhiteBalanceStage().run(ctx)
    expected = apply_warmth(
        np.asarray(_FakeRaw().camera_whitebalance[:3], dtype=np.float32),
        prof, 0.9, {"curve": knots})
    assert np.allclose(ctx.state["wb"], expected, atol=1e-5)


def test_warm_cal_file_missing_or_invalid_falls_back(tmp_path):
    """t14: 标定文件缺失或结点非法 -> 静默回退内置斜率模型 (行为兼容)。"""
    bad = tmp_path / "bad.json"
    bad.write_text('{"knots": [[2.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]}',
                   encoding="utf-8")  # wb_B 递减 -> 非法
    prof = _profile()
    raw_wb = np.asarray([1.291, 1.0, 2.287], dtype=np.float32)
    expected = apply_warmth(raw_wb, prof, 0.9, None)
    for wcf in ("Z:/no/such/warmth.json", str(bad)):
        ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                           config={"stages": {"whitebalance": {
                               "mode": "as_shot", "warm_cal_file": wcf}}})
        ctx.set_image(np.full((8, 8, 3), 0.5, dtype=np.float32),
                      DOMAIN_LINEAR_CAM)
        WhiteBalanceStage().run(ctx)
        assert np.allclose(ctx.state["wb"], expected, atol=1e-5)


def test_warm_cal_domain_hint_and_fallback(tmp_path, capsys):
    """t22: 超出 _domain 打一次性提示; fallback_outside_domain=true 回退斜率模型。"""
    import json
    knots = [[2.4, 1.0, 1.0, 1.0], [3.0, 1.1, 1.0, 0.95]]  # 域 [2.4,3.0]
    f = tmp_path / "warmth_curve.json"
    f.write_text(json.dumps({"knots": knots,
                             "_domain": {"wb_B": [2.4, 3.0]}}),
                 encoding="utf-8")
    prof = _profile()
    raw_wb = np.asarray([1.291, 1.0, 2.287], dtype=np.float32)  # b=2.287 域外
    slope = apply_warmth(raw_wb, prof, 0.9, None)
    curved = apply_warmth(raw_wb, prof, 0.9, {"curve": knots})

    def run(extra):
        cfg = {"mode": "as_shot", "warm_cal_file": str(f)}
        cfg.update(extra)
        ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                           config={"stages": {"whitebalance": cfg}})
        ctx.set_image(np.full((8, 8, 3), 0.5, dtype=np.float32),
                      DOMAIN_LINEAR_CAM)
        WhiteBalanceStage().run(ctx)
        return ctx.state["wb"]

    # 默认 (fallback_outside_domain=False): 域外仍用曲线, 打一次性提示
    assert np.allclose(run({}), curved, atol=1e-5)
    assert "超出" in capsys.readouterr().out
    assert np.allclose(run({}), curved, atol=1e-5)   # 行为不变
    assert "超出" not in capsys.readouterr().out      # 提示仅一次
    # fallback_outside_domain=True: 回退内置斜率模型
    assert np.allclose(run({"fallback_outside_domain": True}), slope, atol=1e-5)


def test_explicit_warmth_curve_overrides_cal_file(tmp_path):
    """t14: 显式 warmth_curve 参数优先于 warm_cal_file 加载的标定。"""
    import json
    f = tmp_path / "warmth_curve.json"
    f.write_text(json.dumps({"knots": [[1.0, 1.0, 1.0, 1.0],
                                       [3.0, 1.2, 0.9, 0.8]]}),
                 encoding="utf-8")
    explicit = [[1.0, 1.0, 1.0, 1.0], [3.0, 0.9, 1.05, 1.1]]
    prof = _profile()
    ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                       config={"stages": {"whitebalance": {
                           "mode": "as_shot", "warm_cal_file": str(f),
                           "warmth_curve": explicit}}})
    ctx.set_image(np.full((8, 8, 3), 0.5, dtype=np.float32), DOMAIN_LINEAR_CAM)
    WhiteBalanceStage().run(ctx)
    expected = apply_warmth(
        np.asarray(_FakeRaw().camera_whitebalance[:3], dtype=np.float32),
        prof, 0.9, {"curve": explicit})
    assert np.allclose(ctx.state["wb"], expected, atol=1e-5)


def test_manual_requires_temp():
    """mode=manual 但 temp=None → ValueError。"""
    prof = _profile()
    ctx = StageContext("test.NEF", raw=_FakeRaw(), prof=prof,
                       config={"stages": {"whitebalance": {"mode": "manual"}}})
    ctx.set_image(np.full((8, 8, 3), 0.5, dtype=np.float32), DOMAIN_LINEAR_CAM)
    with pytest.raises(ValueError, match="temp"):
        WhiteBalanceStage().run(ctx)


def test_manual_skips_warmth():
    """manual 模式不套 warmth: 无论 warmth 何值, 输出 wb 均为 temp_tint_to_wb 结果。"""
    prof = _profile()
    expected = temp_tint_to_wb(prof, 4500.0, 10.0)
    expected = expected / expected[1]
    for warmth in (0.0, 1.0):
        ctx = _run_manual(4500.0, 10.0, warmth=warmth)
        assert np.allclose(ctx.state["wb"], expected, atol=1e-5)


def test_manual_metrics_and_state():
    """manual 结果写 state 与 metrics 保持既有结构 (wb/wb_cam/wb_mode/cct_k)。"""
    ctx = _run_manual(3000.0, 5.0)
    assert "wb_cam" in ctx.state and "wb" in ctx.state
    assert ctx.state["wb_mode"] == "manual"
    assert ctx.state["cct_k"] > 0
    m = ctx.results[-1].metrics
    assert set(["wb", "cct_k"]) <= set(m)
