"""P1b 单元测试：闭环美学维度接入与终止条件。

覆盖：
  - fake scorer 高分 + 验收阈值 -> 首轮 preview 提前终止并 ACCEPTED；
  - 美分连续两轮改善 < eps -> 按停滞规则终止（区别于 max_iterations）；
  - 默认无 scorer：不计分、不注入 aesthetic 字段，行为与 P1 完全一致；
  - FINAL_QC 全分辨率测量在有 scorer 时携带 aesthetic 字段。
"""
from __future__ import annotations

import numpy as np

from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.vision import MockSegmenter


def _dark_image() -> np.ndarray:
    """低亮度合成图，FINAL_QC 不会高光溢出。"""
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.3
    return img


def _make_loop(scorer=None, *, accept_threshold=None, stagnation_eps=None):
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
        aesthetic_scorer=scorer,
        aesthetic_accept_threshold=accept_threshold,
        aesthetic_stagnation_eps=stagnation_eps,
    )


def _decide_events(result):
    return [e for e in result.trace_events if e["event_type"] == "decide"]


def test_high_score_stops_first_iteration():
    """fake scorer 高于验收阈值 -> 首轮即停，最终 ACCEPTED。"""

    def scorer(image_rgb, masks=None):
        return 0.95

    loop = _make_loop(scorer, accept_threshold=0.9)
    result = loop.run("aes_high", image_rgb=_dark_image())

    assert result.state == "ACCEPTED"
    assert len(result.measurements) == 1
    assert result.measurements[0]["aesthetic"]["overall"] == 0.95

    events = _decide_events(result)
    assert len(events) == 1
    assert events[0]["value"]["decision"] == "stopped"
    assert any("美学总分" in r for r in events[0]["value"]["reasons"])

    # FINAL_QC 测量同样携带 aesthetic 字段
    assert result.final_measurement is not None
    assert result.final_measurement["aesthetic"]["overall"] == 0.95


def test_score_stagnation_stops_by_rule():
    """美分连续两轮改善 < eps -> 停滞规则终止，而非 max_iterations。"""
    # FINAL_QC 还会评分一次，序列取尽后保持末值，避免 StopIteration。
    seq = [0.50, 0.505, 0.508]
    state = {"i": 0}

    def scorer(image_rgb, masks=None):
        value = seq[min(state["i"], len(seq) - 1)]
        state["i"] += 1
        return value

    loop = _make_loop(scorer, stagnation_eps=0.01)
    result = loop.run("aes_stag", image_rgb=_dark_image())

    assert result.state == "ACCEPTED"
    assert len(result.measurements) == 3

    events = _decide_events(result)
    last_reasons = events[-1]["value"]["reasons"]
    assert any("停滞" in r for r in last_reasons), last_reasons
    assert not any("最大迭代" in r for r in last_reasons), last_reasons


def test_no_scorer_keeps_legacy_behavior():
    """默认无 scorer：不注分、measurement 无 aesthetic 键，跑满 3 轮。"""
    loop = _make_loop(None)
    result = loop.run("aes_none", image_rgb=_dark_image())

    assert result.state == "ACCEPTED"
    assert result.iteration == 3
    assert len(result.measurements) == 3
    assert all("aesthetic" not in m for m in result.measurements)
    assert "aesthetic" not in (result.final_measurement or {})


def test_scorer_runtime_error_skips_scoring_and_loop_completes(caplog):
    """scorer 抛 RuntimeError：记 warning 后按本轮无分跳过，闭环正常走完。"""
    calls = {"n": 0}

    def bad_scorer(image_rgb, masks=None):
        calls["n"] += 1
        raise RuntimeError("aesthetic model weights corrupted")

    loop = _make_loop(bad_scorer)
    with caplog.at_level("WARNING"):
        result = loop.run("aes_err", image_rgb=_dark_image())

    # 闭环不炸：正常走完 3 轮 preview + FINAL_QC 并 ACCEPTED
    assert result.state == "ACCEPTED"
    assert len(result.measurements) == 3
    # 所有测量均无 aesthetic 字段（按本轮无美学分处理）
    assert all("aesthetic" not in m for m in result.measurements)
    assert "aesthetic" not in (result.final_measurement or {})
    # scorer 每轮仍被调用（3 preview + FINAL_QC），异常未中断调用链
    assert calls["n"] == 4
    # 记录了 warning 日志
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings and any("美学评分异常" in r.getMessage() for r in warnings)


def test_dict_scorer_overall_and_extra_fields_preserved():
    """scorer 返回 dict：取 overall 计分并保留附加字段到测量。"""
    captured = {}

    def scorer(image_rgb, masks=None):
        captured["mask_keys"] = sorted(masks or {})
        return {"overall": 0.97, "composition": 0.9}

    loop = _make_loop(scorer, accept_threshold=0.95)
    result = loop.run("aes_dict", image_rgb=_dark_image())

    assert result.state == "ACCEPTED"
    assert len(result.measurements) == 1
    aes = result.measurements[0]["aesthetic"]
    assert aes["overall"] == 0.97
    assert aes["composition"] == 0.9
    # scorer 收到的 masks 是 dict（MockSegmenter 输出）
    assert isinstance(captured["mask_keys"], list)
