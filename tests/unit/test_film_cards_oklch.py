"""t21 审核盲点 A1：oklch_demo 胶片卡（band schema v2）加载与 Stage 应用。

覆盖:
  - from_films_dir 加载两张 oklch_demo 卡，schema v2 自描述
    （hsl.color_domain + band 级 domain:"oklch" + OKLCh 感知角中心）;
  - 带中心与 core.hsl_oklch.DEFAULT_BANDS_OKLCH 一致（设计 §2.2 单一来源）;
  - HslStage / SplitToneStage 以卡参数实际应用：oklch 域出图有效、且与
    同数值 hsv 域出图不同（分派语义可见）;
  - 存量 23 卡 A1 不变量（F07 钉域）：凡带涉域 stage（hsl/split_tone/skin/
    colorcal）键的卡一律显式钉 `color_domain:"hsv"`（qa 修订口径 =「凡带键
    即钉」，不区分 enabled）；hsl bands 无 band 级 domain 键。oklch 切默认
    （F10 只翻 hsl+split_tone 的 Stage 缺省）后存量卡语义由卡级锚定保护，
    不再依赖 Stage 缺省（t61 清理历史双卡 film_portra_400 后 24→23）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pixo.know.cards import StyleCard
from pixo.render.core.hsl_oklch import DEFAULT_BANDS_OKLCH
from pixo.render.pipeline.graph import (StageContext, DOMAIN_GAMMA_RGB,
                                        STAGE_REGISTRY)
from pixo.render.modules.hsl import HslStage
from pixo.render.modules.split_tone import SplitToneStage

ROOT = Path(__file__).resolve().parents[2]
FILMS = ROOT / "configs" / "styles" / "films"
DEMO_IDS = ("oklch_demo_warm_portrait", "oklch_demo_cool_landscape")
# 涉域 stage（color_domain 参数面四枚举, t52 §2）：卡级钉域的作用面
DOMAIN_STAGES = ("hsl", "split_tone", "skin", "colorcal")


def _demo_cards() -> dict[str, dict]:
    cards = {c["style_id"]: c for c in StyleCard.from_films_dir(FILMS)}
    missing = [sid for sid in DEMO_IDS if sid not in cards]
    assert not missing, f"oklch_demo 卡未加载: {missing}"
    return cards


def _hue_spectrum_img(h: int = 64, w: int = 64) -> np.ndarray:
    """彩色渐变测试图（gamma [0,1]），覆盖多色相扇区。"""
    y, x = np.mgrid[0:h, 0:w]
    t = x / max(w - 1, 1)
    r = 0.15 + 0.7 * t
    g = 0.15 + 0.7 * (1.0 - t)
    b = 0.15 + 0.6 * np.abs(0.5 - t) * 2
    img = np.stack([r, g, b], axis=-1).astype(np.float32)
    return np.clip(img + 0.05 * np.sin(y / 4.0)[..., None], 0.0, 1.0)


def _run_stage(stage, img: np.ndarray) -> np.ndarray:
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    stage.run(ctx)
    return np.clip(ctx.image, 0.0, 1.0)


# ---------------------------------------------------------------------------
# 加载与 schema v2
# ---------------------------------------------------------------------------

def test_demo_cards_load_with_schema_v2():
    cards = _demo_cards()
    for sid in DEMO_IDS:
        card = cards[sid]
        hsl = card["params"]["hsl"]
        assert hsl["enabled"] is True
        assert hsl["color_domain"] == "oklch"
        bands = json.loads(hsl["bands"])
        assert len(bands) == 8
        assert all(b["domain"] == "oklch" for b in bands)
        # 演示卡必须带非零参数（否则验证不了应用路径）
        assert any(float(b.get("hue_shift", 0)) or float(b.get("saturation", 0))
                   or float(b.get("luminance", 0)) for b in bands)
        st = card["params"]["split_tone"]
        assert st["color_domain"] == "oklch"
        assert st["enabled"] is True and st["highlights_sat"] > 0 and st["shadows_sat"] > 0
        meta = card["metadata"]
        assert meta["family"] and meta["label"]


def test_demo_band_centers_match_default_bands_oklch():
    """带中心单一来源：新卡的 OKLCh 感知角中心必须取自 DEFAULT_BANDS_OKLCH。"""
    ref = {b["name"]: b["hue_center"] for b in DEFAULT_BANDS_OKLCH}
    cards = _demo_cards()
    for sid in DEMO_IDS:
        for band in json.loads(cards[sid]["params"]["hsl"]["bands"]):
            assert band["name"] in ref
            assert band["hue_center"] == ref[band["name"]], (
                f"{sid} band {band['name']} 中心 {band['hue_center']} 偏离 "
                f"DEFAULT_BANDS_OKLCH {ref[band['name']]}")


def test_legacy_cards_pin_hsv_domain_explicitly():
    """存量卡 A1 不变量（F07）：凡带涉域 stage 键即显式钉 color_domain:"hsv"。

    qa 修订口径 =「凡带键即钉」——不区分 enabled（未启用的 stage 未来启用
    时已被保护，不变量无特例）。四 stage 的 Stage 级缺省 color_domain 均为
    "hsv"（hsl.py:34 / split_tone.py:43 / color_cal.py:218 / skin.py:67），
    卡级显式钉 hsv 后，切默认（F10 翻 hsl+split_tone 缺省）不再改变存量卡
    语义 —— A1「存量卡零迁移、逐位不变」由卡级锚定兑现，不再依赖 Stage 缺省。
    计数为 qa 2026-09-07 实测：hsl 12 / split_tone 12 / skin 22（enabled=true
    17）/ colorcal 23（新增卡应自觉带钉并同步此处计数）。
    """
    counts = {s: 0 for s in DOMAIN_STAGES}
    for card in StyleCard.from_films_dir(FILMS):
        if card["style_id"] in DEMO_IDS:
            continue
        for stage_name in DOMAIN_STAGES:
            params = card["params"].get(stage_name)
            if params is None:
                continue
            assert params.get("color_domain") == "hsv", (
                f"存量卡 {card['style_id']}.{stage_name} 未显式钉 "
                f'color_domain:"hsv" (实际 {params.get("color_domain")!r})')
            counts[stage_name] += 1
        # 涉域四枚举之外禁止出现 color_domain（旧「零迁移」不变量的全覆盖
        # 守卫保留——如 huesat 也有 color_domain 参数面（t64 接线），存量卡
        # 在其上钉域属新的语义变更，须显式扩枚举而非静默漂移）
        for stage_name, params in card["params"].items():
            if stage_name not in DOMAIN_STAGES and isinstance(params, dict):
                assert "color_domain" not in params, (
                    f"存量卡 {card['style_id']}.{stage_name} 出现 "
                    f"color_domain（涉域枚举外，钉域须显式扩 DOMAIN_STAGES）")
        # band 级 domain 键仍禁止（schema v2 是 oklch_demo 专用形态；
        # 存量卡域语义单点在 Stage 级 color_domain，禁止双源）
        hsl = card["params"].get("hsl")
        if hsl and hsl.get("bands"):
            bands = json.loads(hsl["bands"]) if isinstance(hsl["bands"], str) \
                else hsl["bands"]
            assert all("domain" not in b for b in bands), (
                f"存量卡 {card['style_id']} hsl bands 出现 domain 键")
    assert counts == {"hsl": 12, "split_tone": 12, "skin": 22, "colorcal": 23}


def test_legacy_domain_pin_merge_equivalent_to_defaults():
    """graph.py 参数合并层证明卡级钉域覆盖缺省（F07 锚定 × F10 翻缺省）。

    Stage.__init__ 以 {**default_params(), **卡参数} 合并（graph.py:46-48）。
    F10 前（缺省 hsv）：钉域为语义 no-op（合并结果与钉前逐键相等）。
    F10 起（hsl/split_tone 缺省 oklch）：钉域转为**实义覆盖**——本测试
    翻转为该语义：卡参数显式 "hsv" 恒覆盖新缺省（运行时
    `p(ctx, "color_domain", ...)` 取值由卡锚定为 hsv），除 color_domain
    外其余键合并结果逐键相等（钉域不引入任何其他参数面变化）。
    """
    for card in StyleCard.from_films_dir(FILMS):
        if card["style_id"] in DEMO_IDS:
            continue
        for stage_name in DOMAIN_STAGES:
            params = card["params"].get(stage_name)
            if params is None:
                continue
            cls = STAGE_REGISTRY[stage_name]
            merged_pinned = dict(cls(dict(params)).params.values)
            unpinned = {k: v for k, v in params.items()
                        if k != "color_domain"}
            merged_baseline = dict(cls(unpinned).params.values)
            # 钉域是唯一差异点：其余键合并逐键相等
            diff_keys = {k for k in set(merged_pinned) | set(merged_baseline)
                         if merged_pinned.get(k) != merged_baseline.get(k)}
            assert diff_keys <= {"color_domain"}, (
                f"{card['style_id']}.{stage_name} 钉域引入意外参数差异: "
                f"{diff_keys}")
            # 卡级锚定：显式 "hsv" 恒覆盖 Stage 缺省（F10 翻缺省后即实义）
            assert merged_pinned["color_domain"] == "hsv"
            # 基线（无钉）随缺省同源变化（读同源, 不钉字面量）
            assert (merged_baseline["color_domain"]
                    == cls().default_params()["color_domain"])


# ---------------------------------------------------------------------------
# Stage 应用（卡参数 → Stage 分派）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sid", DEMO_IDS)
def test_demo_card_hsl_stage_applies_oklch(sid):
    cards = _demo_cards()
    hsl_params = dict(cards[sid]["params"]["hsl"])
    bands = json.loads(hsl_params["bands"])
    img = _hue_spectrum_img()

    out_oklch = _run_stage(HslStage(hsl_params), img)

    # 对照：同数值若按 hsv 语义路由（剥 band 级 domain 戳 + Stage hsv），
    # 出图必须不同 —— band 级 domain 戳确实是语义分派的决定项。
    hsv_bands = [{k: v for k, v in b.items() if k != "domain"} for b in bands]
    hsv_params = dict(hsl_params, color_domain="hsv",
                      bands=json.dumps(hsv_bands))
    out_hsv = _run_stage(HslStage(hsv_params), img)
    assert not np.array_equal(out_oklch, out_hsv)
    # 仅翻转 Stage 级 color_domain 不改变路径：band 级戳逐段覆盖（schema v2）
    out_stage_flipped = _run_stage(
        HslStage(dict(hsl_params, color_domain="hsv")), img)
    assert np.array_equal(out_oklch, out_stage_flipped)
    # oklch 域实际改动像素
    assert np.abs(out_oklch - img).max() > 1e-4


@pytest.mark.parametrize("sid", DEMO_IDS)
def test_demo_card_split_tone_stage_applies_oklch(sid):
    cards = _demo_cards()
    st_params = dict(cards[sid]["params"]["split_tone"])
    img = _hue_spectrum_img()

    out_oklch = _run_stage(SplitToneStage(st_params), img)
    assert np.abs(out_oklch - img).max() > 1e-4

    out_hsv = _run_stage(SplitToneStage(dict(st_params, color_domain="hsv")), img)
    assert not np.array_equal(out_oklch, out_hsv)
