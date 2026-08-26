"""t11 —— 真美学评分器接入批量选片的接线单测。

覆盖：
  - make_default_scorer 在 torch 缺失环境回退 Mock 且不抛错；
  - 真评分器不可用(available=False)/构造异常时回退 Mock；
  - 可用时经 _PixoScorerAdapter 把 dict 输出转为 AestheticScore；
  - 注入 fake scorer 时 TopN 选择消费其分数排序。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

import numpy as np

from pixo.pipeline.batch import (
    AestheticScore,
    BatchInput,
    BatchPipeline,
    MockAestheticScorer,
    MockAgentSelector,
    _PixoScorerAdapter,
    make_default_scorer,
)


def _sharp_image(seed: int = 0) -> np.ndarray:
    """噪声图：细节丰富，能过硬过滤（锐度阈值）。"""
    rng = np.random.default_rng(seed)
    return rng.integers(70, 190, size=(64, 64, 3), dtype=np.uint8)


def _burst_meta(offset_sec: int, photo_id: str) -> dict:
    """相近 datetime 使多张并成一个连拍组（TopN 才有排序意义）。"""
    base = datetime(2026, 8, 1, 10, 0, 0)
    return {
        "photo_id": photo_id,
        "datetime": (base + timedelta(seconds=offset_sec)).isoformat(),
        "focal_length": 50.0,
        "aperture": 2.8,
        "shutter_speed": 0.001,
        "iso": 100,
    }


def _inputs(ids: list[str]) -> list[BatchInput]:
    return [
        BatchInput(
            photo_id=pid,
            image_rgb=_sharp_image(i),
            meta=_burst_meta(i, pid),
        )
        for i, pid in enumerate(ids)
    ]


class _FakeHealthScorer:
    """可编程 health_info 的假真评分器。"""

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.calls = 0

    def health_info(self) -> dict:
        return {"name": "AestheticScorer", "type": "real", "available": self._available}

    def score(self, image_rgb):
        self.calls += 1
        return {"overall": 4.2, "quality": 4.5, "color": 3.9}


def test_factory_returns_mock_without_torch(monkeypatch):
    """①无 torch 环境：工厂返回 Mock 兼容对象且不抛错。"""
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "transformers", None)
    scorer = make_default_scorer()
    assert isinstance(scorer, MockAestheticScorer)
    img = _sharp_image()
    result = scorer.score(img, {"photo_id": "x"})
    assert isinstance(result, AestheticScore)


def test_factory_falls_back_when_unavailable(monkeypatch):
    """②a 真评分器 available=False（权重缺失）→ Mock。"""
    monkeypatch.setattr(
        "pixo.vision.aesthetic.PixoAestheticScorer", _FakeHealthScorer(available=False)
    )
    assert isinstance(make_default_scorer(), MockAestheticScorer)


def test_factory_falls_back_on_constructor_error(monkeypatch):
    """②b 构造异常 → Mock，不向外抛错。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("pixo.vision.aesthetic.PixoAestheticScorer", _boom)
    assert isinstance(make_default_scorer(), MockAestheticScorer)


def test_factory_wraps_real_scorer_and_adapts_dict(monkeypatch):
    """③可用 → 适配器；dict 输出转 AestheticScore（overall 缺失取维度均值）。"""
    fake = _FakeHealthScorer(available=True)
    monkeypatch.setattr("pixo.vision.aesthetic.PixoAestheticScorer", lambda: fake)
    scorer = make_default_scorer()
    assert isinstance(scorer, _PixoScorerAdapter)

    result = scorer.score(_sharp_image(), {"photo_id": "p"})
    assert isinstance(result, AestheticScore)
    assert result.overall == 5.0      # t63 仿射后 4.2/4.5/3.9 均超上锚点→硬界
    assert result.dimensions == {"quality": 5.0, "color": 5.0}
    assert result.raw_overall == 4.2

    # overall 缺失 → 已标定维度均值兜底
    class _NoOverall(_FakeHealthScorer):
        def score(self, image_rgb):
            return {"quality": 4.0, "color": 2.0}

    adapter = _PixoScorerAdapter(_NoOverall())
    fallback = adapter.score(_sharp_image())
    assert fallback is not None and fallback.overall == 5.0  # 两维远超上锚点→均兜底5

    # 非法输出 → 永久降级为 Mock（t20③，暗路径不产生悬空 None）
    class _Junk(_FakeHealthScorer):
        def score(self, image_rgb):
            return "junk"

    adapter_junk = _PixoScorerAdapter(_Junk())
    junk_result = adapter_junk.score(_sharp_image())
    assert isinstance(junk_result, AestheticScore)
    assert junk_result.source == "mock"
    assert adapter_junk.degraded is True


def test_corrupt_weights_probe_rejects_and_factory_falls_back(tmp_path, monkeypatch):
    """损坏 .pt（>1MB 垃圾字节）→ 探针判不可用，工厂落 Mock 不崩。"""
    from pixo.vision.aesthetic import PixoAestheticScorer

    bad = tmp_path / "corrupt_aesthetic.pt"
    bad.write_bytes(b"garbage-not-a-torch-checkpoint" * 40000)
    assert bad.stat().st_size > 1024 * 1024

    scorer = PixoAestheticScorer(model_path=str(bad))
    info = scorer.health_info()
    assert info["available"] is False

    monkeypatch.setenv("PIXO_AESTHETIC_MODEL", str(bad))
    default = make_default_scorer()
    assert isinstance(default, MockAestheticScorer)


def test_adapter_affine_maps_and_caps_to_contract_domain():
    """t63 真模型带符号原始分 → 逐维仿射标定 + [0,5] 兜底，附追溯字段。"""
    class _Hi:
        def score(self, image_rgb):
            return {"overall": 7.2, "quality": 4.5, "color": -1.0}

    result = _PixoScorerAdapter(_Hi()).score(_sharp_image())
    assert result.overall == 5.0                       # 远超上锚点 → 硬界兜底
    assert result.dimensions == {"quality": 5.0, "color": 0.0}
    assert result.source == "pixo"
    assert result.raw_overall == 7.2                   # 原始分可追溯
    assert result.domain_hint == "synthetic_like"      # 超实拍域上尾(p75)


def test_adapter_permanent_degrade_on_inner_error():
    """③内层异常一次 → 永久降级走 Mock，不再重试内层。"""
    class _Boom:
        def __init__(self):
            self.calls = 0

        def score(self, image_rgb):
            self.calls += 1
            raise RuntimeError("boom")

    inner = _Boom()
    adapter = _PixoScorerAdapter(inner)
    first = adapter.score(_sharp_image())
    second = adapter.score(_sharp_image())
    assert adapter.degraded is True
    assert inner.calls == 1  # 只触达一次，后续全走 Mock
    assert isinstance(first, AestheticScore) and first.source == "mock"
    assert first.overall == second.overall


def test_adapter_permanent_degrade_on_empty_result():
    """③内层返回 None/空 dict → 永久降级走 Mock。"""
    class _Empty:
        def __init__(self):
            self.calls = 0

        def score(self, image_rgb):
            self.calls += 1
            return None

    inner = _Empty()
    adapter = _PixoScorerAdapter(inner)
    result = adapter.score(_sharp_image())
    assert adapter.degraded and inner.calls == 1
    assert isinstance(result, AestheticScore) and result.source == "mock"


def test_batch_skips_none_score_candidates(caplog):
    """⑤None 分候选跳过排序池+计数告警，其余照常 TopN。"""
    import logging

    scores = {"pa": 4.8, "pb": 3.6, "pc": None}

    class _FakeNone:
        def score(self, image_rgb, meta=None):
            pid = (meta or {}).get("photo_id")
            value = scores.get(pid)
            if value is None:
                return None
            return AestheticScore(overall=value, dimensions={"x": value})

    pipeline = BatchPipeline(aesthetic_scorer=_FakeNone(), top_n=2)
    import logging as _lg
    with caplog.at_level(_lg.WARNING, logger="pixo.pipeline.batch"):
        result = pipeline.process(_inputs(["pa", "pb", "pc"]))
    status = {
        p.photo_id: p.status
        for group in result.groups
        for p in group.photos
    }
    assert status["pa"] == "recommended"
    assert status["pb"] == "recommended"
    assert status["pc"] == "not_selected"      # 无分候选不崩批不入池
    assert pipeline._none_score_count == 1
    log_text = caplog.text
    assert "pc 美学分缺失(None)" in log_text and "跳出排序池" in log_text


def test_selector_filters_invalid_candidates_directly():
    """select() 兜底：混入 None 候选被过滤不抛错。"""
    selector = MockAgentSelector(top_n=2)
    items = _inputs(["pa", "pb"])
    verdicts = selector.select([
        (items[0], None),
        (items[1], AestheticScore(overall=3.9, dimensions={})),
    ])
    assert set(verdicts) == {"pb"}
    assert verdicts["pb"].recommended is True


def test_topn_consumes_injected_fake_scores():
    """④注入 fake scorer 时，TopN 选择按其 overall 排序消费。"""
    scores = {"pa": 4.8, "pb": 3.6, "pc": 2.9, "pd": 1.1}
    order_rank = {"pd": 0, "pc": 1, "pb": 2, "pa": 3}

    class _ByImageScorer:
        """按图片噪声强度返回不同分数，验证消费的是注入分数而非 Mock 分。"""

        def score(self, image_rgb, meta=None):
            pid = (meta or {}).get("photo_id")
            return AestheticScore(overall=scores[pid], dimensions={"x": scores[pid]})

    pipeline = BatchPipeline(
        aesthetic_scorer=_ByImageScorer(),
        top_n=2,
    )
    result = pipeline.process(_inputs(["pa", "pb", "pc", "pd"]))

    status = {
        p.photo_id: p.status
        for group in result.groups
        for p in group.photos
    }
    # Top2 = 分数最高的 pa/pb；其余 not_selected
    recommended = {pid for pid, st in status.items() if st == "recommended"}
    assert recommended == {"pa", "pb"}
    assert status["pc"] == "not_selected"
    assert status["pd"] == "not_selected"

    # confidence 与分数正相关且推荐者过阈值
    verdicts = {
        p.photo_id: p.agent
        for group in result.groups
        for p in group.photos
        if p.agent is not None
    }
    assert set(verdicts) == {"pa", "pb"}
    confs = [verdicts["pa"].confidence, verdicts["pb"].confidence]
    assert confs[0] > confs[1] > 0.6
    assert all(v.recommended and not v.manual_review for v in verdicts.values())

    # reason 中引用了 fake 分数，证明确实消费注入值
    assert "4.80" in verdicts["pa"].reason
    del order_rank


# --- t68：synthetic_like 域外隔离 ---------------------------------------------

class _DomainScorer:
    """按 photo_id 返回带 domain_hint 的固定分（pixo 适配器输出形态）。"""

    def __init__(self, table: dict) -> None:
        self.table = table          # pid -> (overall, domain_hint)

    def score(self, image_rgb, meta=None):
        pid = (meta or {}).get("photo_id", "unknown")
        overall, hint = self.table.get(pid, (3.0, None))
        return AestheticScore(
            overall=overall,
            dimensions={"mock": overall},
            source="pixo",
            raw_overall=overall,
            domain_hint=hint,
        )


def _domain_pipeline(table, top_n=2, **kw):
    photos = [
        BatchInput(photo_id=pid,
                   image_rgb=_sharp_image(seed=i),
                   meta=_burst_meta(0, pid))   # 同刻确保单组，TopN 才有意义
        for i, pid in enumerate(sorted(table))
    ]
    pipeline = BatchPipeline(
        aesthetic_scorer=_DomainScorer(table),
        top_n=top_n,
        **kw,
    )
    return pipeline.process(photos)


def test_synthetic_like_excluded_from_topn_default():
    result = _domain_pipeline(
        {"p0": (4.5, None), "p1": (3.9, None), "p2": (5.0, "synthetic_like")},
        top_n=2,
    )
    # 合成候选虽分最高，但默认隔离不占 TopN
    assert result.all_recommended == ["p0", "p1"]
    by_id = {p.photo_id: p for p in result.groups[0].photos}
    verdict = by_id["p2"].agent
    assert verdict.recommended is False
    assert "隔离" in verdict.reason


def test_include_synthetic_isolates_pool_not_mix():
    """t98：开关开启时合成候选进入「隔离合成池」可见，但不参与实拍 TopN、
    不推荐（t98 实测域内相对排名自洽性不足 ρ≈0.03，pooled rank 仅参考）。"""
    result = _domain_pipeline(
        {"p0": (4.5, None), "p1": (3.9, None), "p2": (5.0, "synthetic_like")},
        top_n=2,
        include_synthetic=True,
    )
    # 合成候选虽绝对分最高，仍不与实拍混排；实拍 TopN 不受影响
    assert sorted(result.all_recommended) == ["p0", "p1"]
    by_id = {p.photo_id: p for p in result.groups[0].photos}
    verdict = by_id["p2"].agent
    assert verdict is not None
    assert verdict.recommended is False
    assert verdict.synthetic_rank == 1
    assert verdict.synthetic_pool_size == 1
    assert "合成域" in verdict.reason and "ρ" in verdict.reason


def test_selector_level_domain_split_direct():
    """selector 直测：同输入下开关翻转不改变实拍 TopN；合成域池内可见但绝不推荐。"""
    from datetime import datetime

    base = datetime(2026, 8, 1, 10, 0, 0)
    items = []
    table = [("r0", 4.5, None), ("r1", 3.9, None), ("s0", 5.0, "synthetic_like")]
    for i, (pid, overall, hint) in enumerate(table):
        meta = {"photo_id": pid,
                "datetime": (base + __import__("datetime").timedelta(
                    seconds=i * 5)).isoformat()}
        item = BatchInput(photo_id=pid, image_rgb=_sharp_image(i), meta=meta)
        items.append((item, AestheticScore(
            overall=overall, dimensions={"m": overall},
            source="pixo", raw_overall=overall, domain_hint=hint)))

    excl = MockAgentSelector(top_n=2, include_synthetic=False).select(items)
    incl = MockAgentSelector(top_n=2, include_synthetic=True).select(items)
    assert "s0" not in excl or not excl["s0"].recommended
    # t98：开关开启=隔离池可见+池内排序，但绝不推荐
    assert not incl["s0"].recommended
    assert incl["s0"].synthetic_rank == 1
    assert incl["s0"].synthetic_pool_size == 1
    assert "池内" in incl["s0"].reason
    # 实拍域 r0（4.5）在两种开关下都进入 TopN 且不被打上合成域标记
    assert incl["r0"].recommended and incl["r0"].synthetic_rank is None


def test_synthetic_pool_internal_ordering_t98():
    """t98：多合成候选在隔离池内按标定分相对排序（rank 1=池内最高），全部不推荐。"""
    from datetime import datetime

    base = datetime(2026, 8, 1, 10, 0, 0)
    items = []
    table = [("s0", 2.0, "synthetic_like"), ("s1", 4.0, "synthetic_like"),
             ("s2", 3.0, "synthetic_like"), ("r0", 3.0, None)]
    for i, (pid, overall, hint) in enumerate(table):
        meta = {"photo_id": pid,
                "datetime": (base + __import__("datetime").timedelta(
                    seconds=i * 5)).isoformat()}
        item = BatchInput(photo_id=pid, image_rgb=_sharp_image(i), meta=meta)
        items.append((item, AestheticScore(
            overall=overall, dimensions={"m": overall},
            source="pixo", raw_overall=overall, domain_hint=hint)))
    sel = MockAgentSelector(top_n=2, include_synthetic=True)
    verdicts = sel.select(items)
    # 池内排序：s1(4.0) > s2(3.0) > s0(2.0)；rank 1/2/3；全部不推荐
    assert verdicts["s1"].synthetic_rank == 1
    assert verdicts["s2"].synthetic_rank == 2
    assert verdicts["s0"].synthetic_rank == 3
    assert verdicts["s1"].synthetic_pool_size == 3
    assert verdicts["s0"].synthetic_pool_size == 3
    assert all(not verdicts[p].recommended for p in ("s0", "s1", "s2"))
    # 实拍域不受合成池影响：r0 无合成域标记
    assert "r0" in verdicts
    assert verdicts["r0"].synthetic_rank is None
