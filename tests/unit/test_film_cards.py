"""t86：胶片风格卡库骨架（films 目录 + from_films_dir）。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pixo.know.cards import StyleCard

ROOT = Path(__file__).resolve().parents[2]
FILMS = ROOT / "configs" / "styles" / "films"


def test_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert StyleCard.from_films_dir(tmp_path / "nope") == []


def test_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert StyleCard.from_films_dir(tmp_path) == []


def test_repo_sample_cards_load() -> None:
    cards = StyleCard.from_films_dir(FILMS)
    ids = {c["style_id"] for c in cards}
    assert {"film_portra_400", "film_pro_400h"} <= ids
    for c in cards:
        assert c["stages"], c["style_id"]
        assert isinstance(c["params"], dict)
        meta = c["metadata"]
        assert meta["family"] and meta["label"]
        assert isinstance(meta["tags"], list) and isinstance(meta["scenes"], list)
    families = {c["metadata"]["family"] for c in cards}
    assert {"Kodak", "Fuji"} <= families


def test_bad_json_and_non_card_skipped(tmp_path: Path, caplog) -> None:
    good = {"stages": ["tone"], "params": {}, "output": {},
            "metadata": {"family": "X", "label": "Good"}}
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")
    (tmp_path / "notacard.json").write_text(json.dumps({"foo": 1}), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="pixo.know.cards"):
        cards = StyleCard.from_films_dir(tmp_path)
    assert [c["style_id"] for c in cards] == ["good"]
    assert any("bad.json" in r.getMessage() for r in caplog.records)
    assert any("notacard.json" in r.getMessage() for r in caplog.records)


def test_metadata_defaults_fill(tmp_path: Path) -> None:
    (tmp_path / "bare.json").write_text(
        json.dumps({"stages": ["tone"], "params": {}}), encoding="utf-8")
    card = StyleCard.from_films_dir(tmp_path)[0]
    assert card["metadata"]["family"] == "uncategorized"
    assert card["metadata"]["label"] == "bare"
    assert card["metadata"]["tags"] == []


def test_render_pipeline_ignores_metadata() -> None:
    """metadata 为未知键：pipeline_from_config 只读三键，不阻塞。"""
    from pixo.render.pipeline import pipeline_from_config

    cfg = json.loads((FILMS / "film_portra_400.json").read_text(encoding="utf-8"))
    pipe = pipeline_from_config(cfg)
    assert pipe.output.get("quality") == 95
    assert "metadata" in cfg  # 键在文件里，但管线不消费
