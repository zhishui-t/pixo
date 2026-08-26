"""P2-2 单元测试：批量流程 + 连拍选帧三层过滤。

覆盖：
  - 连拍分组（有时间元数据自动成组，无时间元数据单张成组）
  - 硬过滤（运动模糊/锐度/曝光裁切淘汰）
  - 美学排序 + Top-N 推荐
  - 低置信度转人工
  - State/Trace 写入
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

import numpy as np
import pytest

from pixo.pipeline.batch import (
    AestheticScore,
    AgentVerdict,
    BatchInput,
    BatchPipeline,
    HardFilterConfig,
    MockAgentSelector,
)


def _sharp_image(seed: int = 0) -> np.ndarray:
    """带纹理的中亮度合成图，可通过硬过滤。"""
    rng = np.random.default_rng(seed)
    return rng.integers(70, 190, size=(64, 64, 3), dtype=np.uint8)


def _uniform_image(value: int = 128) -> np.ndarray:
    """纯色图，锐度低，硬过滤应淘汰。"""
    return np.full((64, 64, 3), value, dtype=np.uint8)


def _black_image() -> np.ndarray:
    """全黑图，阴影裁切，硬过滤应淘汰。"""
    return np.zeros((64, 64, 3), dtype=np.uint8)


def _burst_meta(offset_sec: int, photo_id: str) -> dict:
    """构造可被 detect_burst_groups 识别的连拍元数据。"""
    base = datetime(2026, 8, 1, 10, 0, 0)
    return {
        "photo_id": photo_id,
        "datetime": (base + timedelta(seconds=offset_sec)).isoformat(),
        "focal_length": 50.0,
        "aperture": 2.8,
        "shutter_speed": 0.001,
        "iso": 100,
    }


class FixedAestheticScorer:
    """按 photo_id 返回固定美学分的占位 scorer。"""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def score(
        self,
        image_rgb: np.ndarray,
        meta: dict | None = None,
    ) -> AestheticScore:
        del image_rgb
        photo_id = (meta or {}).get("photo_id", "unknown")
        return AestheticScore(
            overall=self.scores.get(photo_id, 3.0),
            dimensions={"mock": self.scores.get(photo_id, 3.0)},
        )


def _sharp_inputs(count: int, prefix: str = "p") -> list[BatchInput]:
    out: list[BatchInput] = []
    for i in range(count):
        photo_id = f"{prefix}{i}"
        out.append(BatchInput(
            photo_id=photo_id,
            image_rgb=_sharp_image(i),
            meta={"photo_id": photo_id},
        ))
    return out


def test_burst_grouping_with_datetime():
    """有时间元数据的相近照片应聚为同一个连拍组。"""
    photos = [
        BatchInput(
            photo_id=f"b{i}",
            image_rgb=_sharp_image(i),
            meta=_burst_meta(i, f"b{i}"),
        )
        for i in range(3)
    ]
    pipeline = BatchPipeline(top_n=10)
    result = pipeline.process(photos)

    assert len(result.groups) == 1
    assert len(result.groups[0].photos) == 3
    assert result.groups[0].group_id.startswith("burst_")


def test_burst_grouping_without_datetime_standalone():
    """无时间元数据时每张照片应成为独立组。"""
    photos = _sharp_inputs(3)
    pipeline = BatchPipeline(top_n=10)
    result = pipeline.process(photos)

    assert len(result.groups) == 3
    assert all(len(g.photos) == 1 for g in result.groups)


def test_hard_filter_rejects_uniform_and_black():
    """纯色/全黑图应被硬过滤淘汰。"""
    photos = [
        BatchInput(photo_id="sharp", image_rgb=_sharp_image()),
        BatchInput(photo_id="uniform", image_rgb=_uniform_image()),
        BatchInput(photo_id="black", image_rgb=_black_image()),
    ]
    pipeline = BatchPipeline(top_n=10)
    result = pipeline.process(photos)

    by_id = {p.photo_id: p for g in result.groups for p in g.photos}
    assert by_id["sharp"].hard_filter.passed is True
    assert by_id["uniform"].hard_filter.passed is False
    assert by_id["black"].hard_filter.passed is False
    assert "sharpness" in by_id["uniform"].hard_filter.reasons
    assert "shadow_clip" in by_id["black"].hard_filter.reasons
    assert by_id["uniform"].status == "hard_rejected"
    assert by_id["black"].status == "hard_rejected"


def test_aesthetic_sort_and_top_n_recommend():
    """通过硬过滤的照片应按美学分排序并推荐 Top N。"""
    scores = {"a": 4.8, "b": 4.5, "c": 4.2, "d": 3.9, "e": 3.6}
    photos = [
        BatchInput(
            photo_id=pid,
            image_rgb=_sharp_image(i),
            meta={**_burst_meta(i, pid), "photo_id": pid},
        )
        for i, pid in enumerate(["a", "b", "c", "d", "e"])
    ]

    pipeline = BatchPipeline(
        aesthetic_scorer=FixedAestheticScorer(scores),
        agent_selector=MockAgentSelector(top_n=3),
        top_n=3,
    )
    result = pipeline.process(photos)

    recommended = result.all_recommended
    assert len(recommended) == 3
    assert set(recommended) == {"a", "b", "c"}
    # 推荐顺序按美学分降序。
    assert recommended == ["a", "b", "c"]


def test_low_confidence_goes_to_manual_review():
    """低置信度不应直接推荐，应转人工复核。"""
    scores = {"a": 0.0, "b": 0.0, "c": 0.0}
    photos = [
        BatchInput(
            photo_id=pid,
            image_rgb=_sharp_image(i),
            meta={**_burst_meta(i, pid), "photo_id": pid},
        )
        for i, pid in enumerate(["a", "b", "c"])
    ]

    pipeline = BatchPipeline(
        aesthetic_scorer=FixedAestheticScorer(scores),
        agent_selector=MockAgentSelector(
            top_n=3, confidence_threshold=0.6, manual_threshold=0.75
        ),
        top_n=3,
    )
    result = pipeline.process(photos)

    assert result.all_manual_review == ["a", "b", "c"]
    assert result.all_recommended == []


def test_state_and_trace_written_for_batch():
    """批量筛选应写入 State/Trace 事件。"""
    photos = _sharp_inputs(2)
    pipeline = BatchPipeline(top_n=10)
    result = pipeline.process(photos)

    first = result.groups[0].photos[0]
    event_types = [e["event_type"] for e in first.trace_events]
    assert "STATE_CHANGE" in event_types
    assert "batch_hard_filter" in event_types
    # 至少有一张通过并记录 aesthetic/agent（top_n=10 会全部进入 agent）。
    assert any("aesthetic_score" in [e["event_type"] for e in p.trace_events]
               for p in result.groups[0].photos)


def test_single_photo_runner_invoked_for_recommended():
    """推荐照片可调用注入的单张闭环 runner。"""
    photos = _sharp_inputs(1)
    calls: list[str] = []

    def runner(photo_id: str, **kwargs) -> dict:
        del kwargs
        calls.append(photo_id)
        return {"photo_id": photo_id, "state": "ACCEPTED"}

    # 真评分器对噪声合成图打分偏低(标定待办)，推荐链路测试改注入
    # 确定性 scorer，避免依赖 333MB 模型与网络下载。
    pipeline = BatchPipeline(
        top_n=1,
        single_photo_runner=runner,
        aesthetic_scorer=FixedAestheticScorer({"p0": 4.8}),
    )
    result = pipeline.process(photos)

    assert calls == ["p0"]
    assert result.all_recommended == ["p0"]
    assert result.groups[0].photos[0].single_loop_result["state"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# RAW 通道：raw_path-only 输入解码预览图 + 分组键重复保留首个
# ---------------------------------------------------------------------------

class _FakeRawHandle:
    """rawpy.imread 句柄假件：postprocess 直接返回预置数组。"""

    def __init__(self, arr: np.ndarray) -> None:
        self._arr = arr

    def postprocess(self, **kw):
        return self._arr

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_rawpy(monkeypatch, arr_or_factory):
    """把假 rawpy 模块塞进 sys.modules（_image_for 函数内 import 生效）。"""
    def _imread(path):
        arr = arr_or_factory() if callable(arr_or_factory) else arr_or_factory
        return _FakeRawHandle(arr)

    fake = types.SimpleNamespace(imread=_imread)
    monkeypatch.setitem(sys.modules, "rawpy", fake)
    return fake


def test_raw_path_only_input_decodes_preview_not_no_image(monkeypatch):
    """image_rgb=None + raw_path：rawpy 半尺寸解码出预览图参与硬过滤，
    不再被 no_image 一律拒绝。"""
    _install_fake_rawpy(monkeypatch, _sharp_image(7))
    pipeline = BatchPipeline(
        top_n=1,
        aesthetic_scorer=FixedAestheticScorer({"r1": 4.5}),
    )
    item = BatchInput(photo_id="r1", raw_path="X:/fake/DSC_0001.NEF")

    image = pipeline._image_for(item)
    assert image is not None
    assert image.shape == (64, 64, 3)

    result = pipeline.process([item])
    photo = result.groups[0].photos[0]
    assert photo.hard_filter.passed is True
    assert "no_image" not in photo.hard_filter.reasons


def test_raw_decode_failure_warns_and_keeps_no_image(monkeypatch, caplog):
    """解码失败：记 warning 后走原拒绝路径（no_image），不崩批。"""

    class _BoomHandle:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def postprocess(self, **kw):
            raise RuntimeError("corrupt raw data")

    monkeypatch.setitem(
        sys.modules, "rawpy", types.SimpleNamespace(imread=lambda p: _BoomHandle()))
    pipeline = BatchPipeline(top_n=1)
    item = BatchInput(photo_id="bad", raw_path="X:/fake/bad.NEF")

    with caplog.at_level("WARNING", logger="pixo.pipeline.batch"):
        assert pipeline._image_for(item) is None
        result = pipeline.process([item])
    photo = result.groups[0].photos[0]
    assert photo.hard_filter.passed is False
    assert "no_image" in photo.hard_filter.reasons
    assert any("RAW 预览解码失败" in r.message for r in caplog.records)


def test_rawpy_missing_still_rejects_without_crash(monkeypatch):
    """未安装 rawpy（sys.modules[rawpy]=None 触发 ImportError）：拒绝路径
    不抛错。"""
    monkeypatch.setitem(sys.modules, "rawpy", None)
    pipeline = BatchPipeline(top_n=1)
    item = BatchInput(photo_id="nopy", raw_path="X:/fake/x.NEF")
    assert pipeline._image_for(item) is None


def test_duplicate_group_key_keeps_first_with_warning(caplog):
    """重复 file_path：保留首个输入并告警。

    原 dict 推导会让后者静默覆盖前者（连拍组凭空少一张照片）。
    """
    def _dup(photo_id: str) -> BatchInput:
        return BatchInput(
            photo_id=photo_id,
            image_rgb=_sharp_image(1),
            meta={**_burst_meta(0, photo_id), "file_path": "dup.NEF",
                  "photo_id": photo_id},
        )

    pipeline = BatchPipeline(top_n=10)
    with caplog.at_level("WARNING", logger="pixo.pipeline.batch"):
        groups = pipeline._group_inputs([_dup("first"), _dup("second")])

    ids = [p.photo_id for _, items in groups for p in items]
    assert "first" in ids
    assert "second" not in ids
    assert any("重复" in r.message for r in caplog.records)
