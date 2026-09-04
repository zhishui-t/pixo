"""t21 审核盲点 A1：oklch_demo 胶片卡（band schema v2）加载与 Stage 应用。

覆盖:
  - from_films_dir 加载两张 oklch_demo 卡，schema v2 自描述
    （hsl.color_domain + band 级 domain:"oklch" + OKLCh 感知角中心）;
  - 带中心与 core.hsl_oklch.DEFAULT_BANDS_OKLCH 一致（设计 §2.2 单一来源）;
  - HslStage / SplitToneStage 以卡参数实际应用：oklch 域出图有效、且与
    同数值 hsv 域出图不同（分派语义可见）;
  - 存量 24 卡零迁移不变量：无 color_domain 键、hsl bands 无 domain 键
    （盲点 A1 的"逐位不变"承诺在卡库层面的守卫）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pixo.know.cards import StyleCard
from pixo.render.core.hsl_oklch import DEFAULT_BANDS_OKLCH
from pixo.render.pipeline.graph import StageContext, DOMAIN_GAMMA_RGB
from pixo.render.modules.hsl import HslStage
from pixo.render.modules.split_tone import SplitToneStage

ROOT = Path(__file__).resolve().parents[2]
FILMS = ROOT / "configs" / "styles" / "films"
DEMO_IDS = ("oklch_demo_warm_portrait", "oklch_demo_cool_landscape")


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


def test_legacy_cards_untouched_no_domain_keys():
    """存量卡零迁移（A1）：无 color_domain 键、bands 无 domain 键。

    film_portra_400 为历史遗留双卡（见 docs/PROJECT_GRAPH_FRONTEND.md），
    本任务不触碰；此断言同时守护它不被误改。
    """
    for card in StyleCard.from_films_dir(FILMS):
        if card["style_id"] in DEMO_IDS:
            continue
        for stage_name, params in card["params"].items():
            assert "color_domain" not in params, (
                f"存量卡 {card['style_id']}.{stage_name} 出现 color_domain")
        hsl = card["params"].get("hsl")
        if hsl and hsl.get("bands"):
            bands = json.loads(hsl["bands"]) if isinstance(hsl["bands"], str) \
                else hsl["bands"]
            assert all("domain" not in b for b in bands), (
                f"存量卡 {card['style_id']} hsl bands 出现 domain 键")


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
