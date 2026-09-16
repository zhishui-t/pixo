"""R22 / F06（CR-11）—— 多轴 QC 软告警 定向单测。

覆盖 design-r22 §1 F06 + §4 QC 判据（dev-1 文件域，tests/unit 新增文件）：

1. **软告警出现在返回与 payload**：``qc_rollback`` 返回 dict 的
   ``soft_warnings``；``LoopResult.metadata``；service auto-loop 任务视图；
2. **既有判定不变**：构造「不触发软告警」与「触发软告警」两例，
   ACCEPT/REJECT（decision/params/reasons/state）逐字段一致；
   并把 loop 的软告警组装函数强关为 ``[]`` 再跑同一输入，判定仍一致；
3. **硬门禁仍只一条**：``engine._QC_OVERFLOW_THRESHOLD``（0.03）。

所有软告警断言都只用模块常量 ``_QC_SOFT_*`` 相对取值 —— 阈值重标定后
测试无需改写（但阈值本身必须在全幅口径留证，见 loop.py 常量注释）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pixo.decide.engine import qc_rollback
from pixo.pipeline import loop as loop_mod
from pixo.pipeline.loop import (
    SinglePhotoLoop,
    SyntheticRenderBackend,
    _QC_SOFT_COLORFULNESS_HIGH,
    _QC_SOFT_COLORFULNESS_LOW,
    _QC_SOFT_DETAIL_SCORE,
    _QC_SOFT_NOISE_RATIO,
    _qc_soft_warnings,
)
from pixo.service import PixoServiceRuntime
from pixo.service import runtime as runtime_mod
from pixo.vision import MockSegmenter


# ---------------------------------------------------------------- 造数工具

def _measurement(*, noise=None, detail=None, colorful=None,
                 overflow: float = 0.004) -> dict:
    global_metrics: dict = {
        "mean_luminance": 96.0,
        "highlight_clip_ratio": overflow,
        "shadow_clip_ratio": 0.0,
        "contrast": 0.4,
        "preview_highlight_clip_estimate": 0.002,
    }
    if noise is not None or detail is not None:
        sharpness: dict = {}
        if noise is not None:
            sharpness["noise_ratio"] = noise
        if detail is not None:
            sharpness["detail_score"] = detail
        global_metrics["detail"] = {"sharpness": sharpness}
    out: dict = {"global": global_metrics, "regions": {}}
    if colorful is not None:
        out["colorfulness_proxy"] = colorful
    return out


def _clean_measurement() -> dict:
    """不触发任何软告警：三轴都取阈值内侧。"""
    return _measurement(
        noise=_QC_SOFT_NOISE_RATIO - 0.2,
        detail=_QC_SOFT_DETAIL_SCORE + 5.0,
        colorful=(_QC_SOFT_COLORFULNESS_LOW + _QC_SOFT_COLORFULNESS_HIGH) / 2.0,
    )


def _noisy_measurement() -> dict:
    """三轴同时触发：噪声偏高 + 细节偏低 + 色彩偏淡。"""
    return _measurement(
        noise=_QC_SOFT_NOISE_RATIO + 0.2,
        detail=_QC_SOFT_DETAIL_SCORE - 0.5,
        colorful=_QC_SOFT_COLORFULNESS_LOW - 0.5,
    )


def _axes(warnings: list[dict]) -> list[str]:
    return [w["axis"] for w in warnings]


def _without_soft_warnings(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "soft_warnings"}


# ---------------------------------------------------------------- ① 组装面


def test_no_warning_for_clean_measurement():
    assert _qc_soft_warnings(_clean_measurement()) == []


def test_warnings_cover_axes_and_schema():
    warnings = _qc_soft_warnings(_noisy_measurement())
    assert _axes(warnings) == ["noise", "sharpness", "color"]
    for item in warnings:
        assert set(item) >= {"axis", "metric", "op", "value", "threshold",
                             "tier", "gate", "message"}
        assert item["tier"] == "full_export"    # design §2.1 裁决③ 全幅口径
        assert item["gate"] == "soft"           # 非门禁
        assert isinstance(item["threshold"], float)
        assert item["message"]
    json.dumps(warnings)                        # payload 必须可 JSON 序列化


def test_color_axis_high_branch():
    warnings = _qc_soft_warnings(_measurement(
        noise=_QC_SOFT_NOISE_RATIO - 0.2,
        detail=_QC_SOFT_DETAIL_SCORE + 5.0,
        colorful=_QC_SOFT_COLORFULNESS_HIGH + 1.0,
    ))
    assert _axes(warnings) == ["color"]
    assert warnings[0]["op"] == ">="
    assert warnings[0]["value"] >= _QC_SOFT_COLORFULNESS_HIGH


def test_motion_blur_axis_when_flagged():
    measurement = _noisy_measurement()
    measurement["global"]["detail"]["motion_blur"] = {
        "has_motion_blur": True, "strength": 0.9, "angle": 12.0, "error": None,
    }
    axes = _axes(_qc_soft_warnings(measurement))
    assert axes.count("sharpness") == 2         # detail_score + motion_blur
    assert any(w["metric"] == "motion_blur.strength"
               for w in _qc_soft_warnings(measurement))


def test_no_warning_on_missing_or_malformed_measurement():
    assert _qc_soft_warnings(None) == []
    assert _qc_soft_warnings({}) == []
    assert _qc_soft_warnings({"global": {"detail": "oops"}}) == []
    assert _qc_soft_warnings({"global": {"detail": {"sharpness": [1, 2]}}}) == []
    # 值非法（None / NaN / 布尔）不产生告警，也不抛异常
    assert _qc_soft_warnings({"global": {"detail": {"sharpness": {
        "noise_ratio": None, "detail_score": float("nan"),
    }}}}) == []
    assert _qc_soft_warnings(_measurement(noise=bool(True))) == []


# ---------------------------------------------------------------- ② 引擎返回


def test_qc_rollback_echoes_soft_warnings_in_both_designed_branches():
    warnings = _qc_soft_warnings(_noisy_measurement())
    assert warnings  # 造数自检：确有告警

    pass_case = qc_rollback({
        "params": {}, "qc_overflow_ratio": 0.001, "soft_warnings": warnings,
    })
    assert pass_case["decision"] == "adjust_and_continue"
    assert pass_case["soft_warnings"] == warnings

    rollback_case = qc_rollback({
        "params": {"Exposure": 0.3}, "qc_overflow_ratio": 0.04,
        "soft_warnings": warnings,
    })
    assert rollback_case["decision"] == "rollback"
    assert rollback_case["soft_warnings"] == warnings
    assert rollback_case["params"]["Exposure"] == pytest.approx(0.15)


def test_qc_rollback_soft_warnings_default_empty_when_absent():
    out = qc_rollback({"params": {}, "qc_overflow_ratio": 0.001})
    assert out["soft_warnings"] == []


# ---------------------------------------------------------------- ③ 判定不变


@pytest.mark.parametrize("context", [
    {"params": {"Exposure": 0.3}, "qc_overflow_ratio": 0.001},   # 达标
    {"params": {"Exposure": 0.3}, "qc_overflow_ratio": 0.04},    # 一次回退
    {"params": {"Exposure": 0.3}, "qc_overflow_ratio": 0.04,
     "qc_rollback_count": 1},                                    # 二次超标
    {"params": {"Exposure": 0.3}, "qc_overflow_ratio": 0.04,
     "locked_params": ["Exposure"]},                             # 锁定
])
def test_engine_decision_unchanged_by_soft_warnings(context):
    """带/不带软告警：除新键外返回 dict 逐字段相同（既有判定零变化）。"""
    warnings = _qc_soft_warnings(_noisy_measurement())
    baseline = qc_rollback(dict(context))
    with_warnings = qc_rollback({**context, "soft_warnings": warnings})
    assert _without_soft_warnings(with_warnings) \
        == _without_soft_warnings(baseline)
    assert with_warnings["decision"] == baseline["decision"]


# ---------------------------------------------------------------- ④ loop 接线


def _dark_image() -> np.ndarray:
    image = np.full((64, 64, 3), 0.08, dtype=np.float32)
    image[16:48, 16:48] = 0.3
    return image


def _build_loop() -> SinglePhotoLoop:
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        max_iterations=2,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
        manual_on_unreliable=False,
    )


def test_loop_result_metadata_carries_soft_warnings():
    loop = _build_loop()
    result = loop.run("pic_soft", image_rgb=_dark_image())

    assert "soft_warnings" in result.metadata
    assert isinstance(result.metadata["soft_warnings"], list)
    # 与同一最终测量的独立组装结果一致（同源，不是随手写的空表）
    assert result.metadata["soft_warnings"] \
        == _qc_soft_warnings(result.final_measurement)
    assert result.metadata["soft_warnings"], "合成暗图应触发至少一轴软告警"


def test_loop_decision_identical_when_soft_warnings_disabled(monkeypatch):
    """把软告警组装强关为空表 → 判定/参数/原因逐字段一致（ACCEPT/REJECT 不变）。"""
    result_with = _build_loop().run("pic_with", image_rgb=_dark_image())
    monkeypatch.setattr(loop_mod, "_qc_soft_warnings", lambda _m: [])
    result_off = _build_loop().run("pic_off", image_rgb=_dark_image())

    assert result_with.state == result_off.state
    assert result_with.decision == result_off.decision
    assert result_with.reason == result_off.reason
    assert result_with.params == result_off.params
    assert result_with.qc_rollback_count == result_off.qc_rollback_count
    assert result_with.metadata["soft_warnings"] != \
        result_off.metadata["soft_warnings"]           # 仅软告警字段不同
    assert result_off.metadata["soft_warnings"] == []


def test_loop_hard_gate_is_still_only_overflow_threshold():
    """硬门禁输入面唯一：qc_context 只喂 highlight_clip_ratio（软告警不改判定）。"""
    from pixo.decide.engine import _QC_OVERFLOW_THRESHOLD

    assert _QC_OVERFLOW_THRESHOLD == 0.03
    loop = _build_loop()
    loop.run("pic_gate", image_rgb=_dark_image())
    captured: dict = {}
    original = loop_mod.qc_rollback

    def _spy(context):
        captured.update(context)
        return original(context)

    loop_mod.qc_rollback = _spy
    try:
        loop.run("pic_gate2", image_rgb=_dark_image())
    finally:
        loop_mod.qc_rollback = original

    assert set(captured) >= {"qc_overflow_ratio", "soft_warnings"}
    ratio = captured["qc_overflow_ratio"]
    assert isinstance(ratio, float) and 0.0 <= ratio <= 1.0


# ---------------------------------------------------------------- ⑤ service payload


class _FakeSession:
    """runtime 装配替身（同 test_auto_loop_api.py:36-61 风格）。"""

    def __init__(self, photo, session_id: str) -> None:
        self.photo_id = photo.photo_id
        self.raw_path = Path(photo.path)
        self.session_id = session_id
        self.params: dict = {}
        self.generation = 0

    def update_params(self, patch: dict) -> int:
        self.params.update(dict(patch or {}))
        self.generation += 1
        return self.generation

    def canonical_params(self) -> dict:
        return dict(self.params)

    def render(self, long_edge: int = 1024) -> np.ndarray:
        del long_edge
        return np.zeros((16, 16, 3), dtype=np.uint8)


def test_service_payload_exposes_soft_warnings(tmp_path, monkeypatch):
    """auto-loop 任务视图透出 soft_warnings，且既有键一个不少。"""
    monkeypatch.delenv("PIXO_DATA_ROOT", raising=False)
    monkeypatch.setattr(
        runtime_mod, "RawRenderBackend",
        lambda raw_path, prof: SyntheticRenderBackend(_dark_image()),
    )
    # 空规则包：让闭环确定性走到 FINAL_QC（软告警与规则无关）
    monkeypatch.setattr(runtime_mod, "_load_auto_loop_rules",
                        lambda prompts=None: [])

    raw = tmp_path / "DSC_9001.nef"
    raw.write_bytes(b"fake-raw")
    runtime = PixoServiceRuntime(
        profile=object(),
        work_dir=tmp_path / "exports",
        session_factory=lambda photo, sid: _FakeSession(photo, sid),
    )
    photo = runtime.create_photo(raw)
    result = runtime.run_auto_loop(
        photo.photo_id, max_iterations=2, preview_long_edge=64, sync=True,
    )

    assert result["status"] == "done", result.get("error")
    assert "soft_warnings" in result
    assert isinstance(result["soft_warnings"], list)
    assert result["soft_warnings"], "payload 软告警为空（合成暗图应触发）"
    for item in result["soft_warnings"]:
        assert item["gate"] == "soft" and item["tier"] == "full_export"
    # 既有键一个不少（追加语义，不改名/不删除）
    assert {"task_id", "status", "photo_id", "segmenter_type", "state",
            "iteration", "params", "rule_ids", "rule_ids_by_iteration",
            "trace_event_count", "error", "duration"} <= set(result)
