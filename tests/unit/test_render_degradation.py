"""R22 F03: 关键路径静默降级可观测 (render 采集 + vision.health 暴露)。

覆盖 (设计 §1 F03 / §4 可观测靶子 / exploration §4.2 的 13 条关键路径承载点):

  ① 正向: 人为触发关键路径失败 (写坏标定表副本 / native 内核抛真异常)
     → ``render_degradation`` 结构化条目 + ``vision_health()["render_degraded"]``;
  ② **反向控制 (关键)**: 版本门合法拒绝 (DLL < 1.6.0 的 oklch 内核) **不得**
     记为 degraded, 且不产生 warning 日志 (否则每次渲染恒误告警);
  ③ 边界: 标定文件**缺失**是 calibration_store 明示的合法常态 → 不记 degraded;
  ④ 节流/去重: 同 (source, path, kind) 只告警一次, count 累加;
  ⑤ 回归守卫: health 增量键为纯附加, 不改既有 status/ready/available 语义。

仓库零改动: 损坏标定表用 tmp_path 副本 + monkeypatch, 不触碰 ``configs/**``。
"""
from __future__ import annotations

import logging

import numpy as np
import pytest

from pixo.render import _native as native
from pixo.render import degradation as deg
from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.modules.white_balance import (_load_warm_cal, _reset_caches,
                                               WhiteBalanceStage)
from pixo.render.pipeline.graph import (DOMAIN_GAMMA_RGB, DOMAIN_LINEAR_CAM,
                                        StageContext)
from pixo.vision.health import vision_health

_VERSION_GATE_MSG = (
    "native colorcal oklch F32 kernel unavailable (需 DLL >= 1.6.0, "
    "实际 (1, 5, 0))")


@pytest.fixture(autouse=True)
def _isolated_degradation_state():
    """每条用例前后清空降级登记表与 calibration_store (全局态隔离)。"""
    deg.clear_render_degradations()
    _reset_caches()
    yield
    deg.clear_render_degradations()
    _reset_caches()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

class MockProf:
    """最小 DcpProfile 替身 (恒等 ColorMatrix), 同 test_pipeline.MockProf。"""

    def __init__(self):
        self.color_matrix1 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.color_matrix2 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.forward_matrix1 = None
        self.forward_matrix2 = None
        self.camera_calibration1 = None
        self.camera_calibration2 = None
        self.calibration_illuminant1 = 17
        self.calibration_illuminant2 = 21
        self.baseline_exposure_offset = 0.0
        self.profile_tone_curve = None


class _FakeRawWB:
    """带 As Shot 白平衡的 raw 替身 (0376 暖锚点)。"""

    def __init__(self, wb=(1.291, 1.0, 2.287)):
        self.camera_whitebalance = [wb[0], wb[1], wb[2], 1.0]


def _broken_warmth_copy(tmp_path):
    """损坏的 warmth_curve.json 副本 (截断 JSON, 不触碰 configs/**)。"""
    p = tmp_path / "warmth_curve.json"
    p.write_text('{"knots": [[1.0, 1.0, 1.0, 1.0],', encoding="utf-8")
    return p


def _oklch_cfg():
    """oklch 域 colorcal 参数 (同 test_native_colorcal_oklch._oklch_cfg)。"""
    return {"stages": {"colorcal": {
        "color_domain": "oklch",
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 0.6, "neutral_b": -0.4, "neutral_sigma": 9.0,
        "neutral_mode": "static",
        "neutral_a_curve": [0.5, 1.0, 2.0, 1.5, 0.0, -1.0, -0.5],
        "neutral_b_curve": [1.0, 0.5, 0.0, -0.5, -1.0, -0.5, 0.5],
        "skin_protect": 0.7, "skin_trim": [-2.0, -4.0], "gamut_soft": 0.5,
    }}}


def _run_colorcal(img, cfg):
    ctx = StageContext("x.NEF", config=cfg)
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    return ctx.image


def _sources(entries):
    return [e["source"] for e in entries]


# ---------------------------------------------------------------------------
# ① 判定依据: 版本门 / 整库不可用 / 真异常 三类可区分
# ---------------------------------------------------------------------------

def test_classify_native_failure_markers():
    """分类器按 native 封装的**声明式**文本判别 (三类都是 RuntimeError)。"""
    assert deg.classify_native_failure(RuntimeError(_VERSION_GATE_MSG)) == "version_gate"
    assert deg.classify_native_failure(
        RuntimeError("native clarity kernel unavailable (DLL 未导出)")) == "version_gate"
    assert deg.classify_native_failure(
        RuntimeError("native DLL unavailable: native DLL not found: x.dll")
    ) == "native_unavailable"
    assert deg.classify_native_failure(ValueError("boom")) == "exception"
    assert deg.classify_native_failure(None) == "fallback"
    assert deg.is_expected_failure(RuntimeError(_VERSION_GATE_MSG)) is True
    assert deg.is_expected_failure(ValueError("boom")) is False


def test_native_unavailable_is_degraded_not_version_gate():
    """整库不可用 (DLL 缺失/加载失败) 算真降级 —— 与版本门区分开。"""
    deg.record_degradation("render.exposure.native",
                           RuntimeError("native DLL unavailable: not found"))
    entries = deg.render_degraded_entries()
    assert len(entries) == 1
    assert entries[0]["kind"] == "native_unavailable"
    assert entries[0]["expected"] is False
    assert deg.version_gate_rejections() == []


# ---------------------------------------------------------------------------
# ② 正向验收靶子: 写坏标定表副本 → degraded 条目 + health 暴露
# ---------------------------------------------------------------------------

def test_corrupt_warmth_curve_copy_records_degraded(tmp_path):
    """直接经 _load_warm_cal (exploration §4.4 靶子): 损坏副本 → None + 条目。"""
    broken = _broken_warmth_copy(tmp_path)
    assert _load_warm_cal(broken) is None
    entries = deg.render_degraded_entries()
    assert _sources(entries) == ["render.white_balance.warmth_curve"]
    e = entries[0]
    assert str(broken) == e["path"]
    assert e["reason"] == "calibration_unreadable"
    assert e["expected"] is False
    # 汇总须含来源/原因/时间戳
    for key in ("source", "reason", "detail", "timestamp", "first_seen",
                "last_seen", "count"):
        assert key in e, f"条目缺字段 {key}"
    assert e["timestamp"].startswith("20")  # ISO8601 UTC


def test_corrupt_warmth_curve_via_stage_then_health_exposes_degraded(tmp_path):
    """Stage 全链路 (whitebalance + warm_cal_file=损坏副本) → health 暴露。"""
    broken = _broken_warmth_copy(tmp_path)
    params = {"whitebalance": {"mode": "as_shot", "warmth": 1.0,
                               "warm_cal_file": str(broken)}}
    ctx = StageContext("x.NEF", raw=_FakeRawWB(), prof=MockProf(),
                       config={"stages": params})
    ctx.set_image(np.full((8, 8, 3), 0.3, dtype=np.float32), DOMAIN_LINEAR_CAM)
    WhiteBalanceStage().run(ctx)  # 不得抛错: 回退内置斜率模型

    health = vision_health()
    assert health["render_degraded_count"] == 1
    assert health["render_status"] == "degraded"
    entry = health["render_degraded"][0]
    assert entry["source"] == "render.white_balance.warmth_curve"
    assert str(broken) == entry["path"]
    assert health["render_version_gate_rejections"] == []
    # 既有 status/ready 语义不受 render 降级影响 (F03 为纯附加通道)
    assert health["status"] == ("ready" if health["segmenter"].get("ready")
                                else "not_ready")


def test_missing_warmth_curve_copy_not_degraded(tmp_path):
    """边界: 标定文件**缺失**是合法常态 (calibration_store 明示) → 不记。"""
    assert _load_warm_cal(tmp_path / "absent.json") is None
    assert deg.render_degraded_entries() == []


# ---------------------------------------------------------------------------
# ③ 反向控制 (关键): 版本门合法拒绝不产生 degraded / 不告警 / 回退等价
# ---------------------------------------------------------------------------

def test_version_gate_rejection_not_degraded(monkeypatch, caplog):
    """DLL < 1.6.0 的 oklch 内核 RuntimeError = 设计回退, 不是 degraded。"""
    def _raise_version_gate(*_a, **_kw):
        raise RuntimeError(_VERSION_GATE_MSG)

    monkeypatch.setattr(native, "available", lambda: True)
    monkeypatch.setattr(native, "colorcal_apply_lab_f32_oklch",
                        _raise_version_gate)
    img = np.random.default_rng(20260910).uniform(0.0, 1.0, (24, 24, 3)).astype(np.float32)

    with caplog.at_level(logging.DEBUG):
        gated = _run_colorcal(img, _oklch_cfg())

    assert deg.render_degraded_entries() == [], (
        "版本门合法拒绝被误记为 degraded (会每次渲染恒误告警)")
    assert vision_health()["render_status"] == "ok"
    gates = deg.version_gate_rejections()
    assert len(gates) == 1
    assert gates[0]["kind"] == "version_gate"
    assert gates[0]["expected"] is True
    assert gates[0]["source"] == "render.color_cal.native_f32"
    # 不产生 warning (只 debug)
    assert not [r for r in caplog.records
                if r.levelno >= logging.WARNING and "render-degraded" in r.getMessage()]

    # 回退路径未被破坏: 与「native 整体不可用」直跑逐位一致
    monkeypatch.setattr(native, "available", lambda: False)
    assert np.array_equal(gated, _run_colorcal(img, _oklch_cfg()))


# ---------------------------------------------------------------------------
# ④ 正向: native 真异常 → degraded + warning + 回退等价
# ---------------------------------------------------------------------------

def test_native_exception_records_degraded(monkeypatch, caplog):
    def _boom(*_a, **_kw):
        raise ValueError("simulated kernel crash")

    monkeypatch.setattr(native, "available", lambda: True)
    monkeypatch.setattr(native, "colorcal_apply_lab_f32_oklch", _boom)
    img = np.random.default_rng(20260911).uniform(0.0, 1.0, (16, 16, 3)).astype(np.float32)

    with caplog.at_level(logging.WARNING):
        out = _run_colorcal(img, _oklch_cfg())

    entries = deg.render_degraded_entries()
    assert _sources(entries) == ["render.color_cal.native_f32"]
    e = entries[0]
    assert e["kind"] == "exception" and e["expected"] is False
    assert e["exception"].startswith("ValueError: simulated kernel crash")
    assert deg.version_gate_rejections() == []
    assert [r for r in caplog.records
            if r.levelno == logging.WARNING and "render-degraded" in r.getMessage()], \
        "真异常必须留 warning 日志"
    assert vision_health()["render_degraded_count"] == 1

    monkeypatch.setattr(native, "available", lambda: False)
    assert np.array_equal(out, _run_colorcal(img, _oklch_cfg()))


# ---------------------------------------------------------------------------
# ⑤ 节流/去重 + 快照隔离
# ---------------------------------------------------------------------------

def test_dedup_and_warn_once(caplog):
    """同 (source, path, kind) 只告警一次, count 累加 (防 131 处变刷屏)。"""
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            deg.record_degradation("render.tone_map.lut1d_native",
                                   ValueError("x"), detail="d")
    entries = deg.render_degraded_entries()
    assert len(entries) == 1
    assert entries[0]["count"] == 3
    warns = [r for r in caplog.records
             if "render-degraded" in r.getMessage() and r.levelno == logging.WARNING]
    assert len(warns) == 1, f"warn-once 失效: {len(warns)} 条 warning"


def test_snapshot_returns_copies():
    deg.record_degradation("s", ValueError("x"))
    first = deg.render_degraded_entries()[0]
    first["source"] = "tampered"
    assert deg.render_degraded_entries()[0]["source"] == "s"
    report = deg.render_degradation_report()
    report["entries"][0]["source"] = "tampered-2"
    assert deg.render_degraded_entries()[0]["source"] == "s"


# ---------------------------------------------------------------------------
# ⑥ 回归守卫: 干净态下 health 增量键为纯附加
# ---------------------------------------------------------------------------

def test_health_render_keys_neutral_when_clean():
    health = vision_health()
    assert health["render_degraded"] == []
    assert health["render_degraded_count"] == 0
    assert health["render_status"] == "ok"
    assert health["render_version_gate_rejections"] == []
    assert health["render_version_gate_count"] == 0
    assert health["status"] == ("ready" if health["segmenter"].get("ready")
                                else "not_ready")
    assert health["ready"] == health["segmenter"].get("ready", False)
