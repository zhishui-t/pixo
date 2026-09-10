"""R21 / F04 —— 评分器适配器可调用契约（``_PixoScorerAdapter.__call__``）定向单测。

覆盖 ``design-r21`` §2.4 与交付清单的**跨层注入**验收：

1. ``__call__`` 返回 **dict**（不是 ``AestheticScore`` 本体）——否则 loop 侧
   ``float(overall)``（在 try 之外）抛 ``TypeError``，静默跳过变 HTTP 500；
2. 注入 ``SinglePhotoLoop(...)`` → ``result.final_measurement["aesthetic"]`` 非空；
3. 同一个 adapter 传 ``suggest_crop(img, boxes, scorer=adapter)`` →
   ``parts.scorer is not None``。

> **断言口径警告**：这里断言 ``parts.scorer is not None``，**不写**「非
> fallback」——契约断裂时 ``suggest_crop`` 现状返回的 ``fallback=False`` 而
> ``parts.scorer=None``（静默降级），写「非 fallback」会误判通过。

> 不依赖 ``make_default_scorer()`` 的真假分支（真模型不可用时回退
> ``MockAestheticScorer``，它没有 ``__call__`` ⇒ 契约断裂被伪装成正常）。
> 内层评分器为固定假实现（对齐 ``tests/unit/test_scorer_calibration.py:17-27``）。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.pipeline.batch import AestheticScore, _PixoScorerAdapter
from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.render.geometry.smart_crop import suggest_crop
from pixo.vision import MockSegmenter


def _fixed_adapter(raw: float = -0.47) -> _PixoScorerAdapter:
    """固定假内层 scorer → 真 ``_PixoScorerAdapter``（跨层注入用真适配器）。"""

    class _Fixed:
        def score(self, image_rgb):
            return {"overall": raw, "quality": raw * 0.5}

    return _PixoScorerAdapter(_Fixed())


def _dark_image() -> np.ndarray:
    """低亮度合成图（对齐 tests/unit/test_loop_aesthetic.py），FINAL_QC 不溢出。"""
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.3
    return img


def _crop_image() -> np.ndarray:
    return np.full((100, 200, 3), 40, dtype=np.uint8)


def _crop_loop(scorer) -> SinglePhotoLoop:
    return SinglePhotoLoop(
        render_backend=SyntheticRenderBackend(_dark_image()),
        segmenter=MockSegmenter(),
        max_iterations=3,
        preview_long_edge=64,
        prompts=["face", "sky", "plant"],
        aesthetic_scorer=scorer,
    )


# ---------------------------------------------------------------- __call__ 契约本体


def test_call_returns_dict_not_dataclass_and_floats_cleanly():
    """__call__ 返回 dict；``float(out["overall"])`` 不抛 TypeError（原 500 根因）。"""
    adapter = _fixed_adapter()
    out = adapter(_dark_image())

    assert isinstance(out, dict)
    assert not isinstance(out, AestheticScore)          # 禁止返回 dataclass 本体
    assert isinstance(out["overall"], float)
    assert float(out["overall"]) == pytest.approx(2.915, abs=1e-3)  # 不再 TypeError
    # 标定维度 + 溯源字段一并保留（exploration §4.5 副作用项）
    assert out["quality"] == pytest.approx(3.309, abs=1e-3)
    assert out["source"] == "pixo"
    assert out["raw_overall"] == pytest.approx(-0.47, abs=1e-9)
    assert out["domain_hint"] is None


def test_call_accepts_masks_argument():
    """签名容忍 loop 侧 ``scorer(image, masks)`` 双参调用（masks 被忽略）。"""
    adapter = _fixed_adapter()
    masks = {"face": np.zeros((64, 64), dtype=np.uint8)}
    out = adapter(_dark_image(), masks)
    assert isinstance(out, dict)
    assert out["overall"] == pytest.approx(2.915, abs=1e-3)


def test_call_returns_none_when_inner_score_is_none():
    """防御分支：``.score()`` 返回 None → ``__call__`` 返回 None（契约完整）。"""
    adapter = _fixed_adapter()
    adapter.score = lambda image_rgb, meta=None: None  # type: ignore[assignment]
    assert adapter(_dark_image()) is None


def test_batch_contract_score_signature_unchanged():
    """批量线契约不动：``.score(image_rgb, meta)`` 仍返回 AestheticScore。"""
    adapter = _fixed_adapter()
    scored = adapter.score(_dark_image(), {"photo_id": "x"})
    assert isinstance(scored, AestheticScore)
    assert scored.source == "pixo"


# ---------------------------------------------------------------- 跨层注入（验收核心）


def test_same_adapter_serves_loop_and_suggest_crop():
    """同一 adapter 实例跨层注入：loop 出 aesthetic 分 + suggest_crop 出 scorer 维度。"""
    adapter = _fixed_adapter()

    # ① 注入闭环：final_measurement["aesthetic"] 非空
    result = _crop_loop(adapter).run("f04_cross", image_rgb=_dark_image())
    assert result.state == "ACCEPTED"
    assert result.final_measurement is not None
    aes = result.final_measurement.get("aesthetic")
    assert aes, (
        "F04 契约断裂：final_measurement 无 aesthetic"
        "（适配器不可调用 ⇒ loop 侧静默跳过计分）"
    )
    assert aes["overall"] == pytest.approx(2.915, abs=1e-3)
    assert aes["quality"] == pytest.approx(3.309, abs=1e-3)
    assert aes["source"] == "pixo"
    assert aes["raw_overall"] == pytest.approx(-0.47, abs=1e-9)
    # 每轮 preview 的 measurement 同样携带该维度
    assert result.measurements
    assert all("aesthetic" in m for m in result.measurements)

    # ② 同一 adapter 传 suggest_crop：parts.scorer 非 None
    _rect, cands = suggest_crop(
        _crop_image(), {}, ratios=("1:1",), scorer=adapter
    )
    assert cands
    assert cands[0]["parts"].get("scorer") is not None, (
        "F04 契约断裂：parts.scorer=None（静默降级；注意此时 fallback 仍为 False，"
        "所以不能用「非 fallback」判定）"
    )
    assert all(c["parts"].get("scorer") is not None for c in cands)


def test_callable_contract_is_load_bearing_for_loop():
    """反向护栏：去掉 __call__ 后 loop 会静默丢分（证明上面断言真的在守门）。"""
    adapter = _fixed_adapter()
    adapter_without_call = type("NoCall", (), {"score": adapter.score})()

    result = _crop_loop(adapter_without_call).run(
        "f04_no_call", image_rgb=_dark_image()
    )
    # 没有 __call__：loop 走 TypeError 回退 → 单参调用再失败 → 静默跳过
    assert result.state == "ACCEPTED"
    assert all("aesthetic" not in m for m in result.measurements)
    assert "aesthetic" not in (result.final_measurement or {})

    # suggest_crop 侧同样静默降级：parts.scorer=None 且 fallback 不为 True
    _rect, cands = suggest_crop(
        _crop_image(), {}, ratios=("1:1",), scorer=adapter_without_call
    )
    assert cands and cands[0].get("fallback") is not True
    assert cands[0]["parts"].get("scorer") is None
