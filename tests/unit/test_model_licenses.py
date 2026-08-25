"""model_licenses.json 轻量 schema 守卫（t57）。

锁定：必填字段齐全、usage 词表不漂移、status 与 usage 一致、文件末尾换行。
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LICENSE_PATH = REPO_ROOT / "model_licenses.json"

USAGE_VOCAB = {
    "internal_development_only",
    "redistribution_allowed_with_license_notice",
}
REQUIRED_FIELDS = ("name", "provider", "license", "files", "usage", "status")


def _load_raw() -> bytes:
    return LICENSE_PATH.read_bytes()


def _load() -> dict:
    return json.loads(_load_raw().decode("utf-8"))


def test_file_ends_with_trailing_newline():
    """①文件末尾必须有换行符（POSIX 友好 diff）。"""
    assert _load_raw().endswith(b"\n")


def test_schema_version_and_models_shape():
    data = _load()
    assert data.get("schema_version") == "1.0"
    assert isinstance(data.get("models"), list) and data["models"]


def test_every_entry_has_required_fields():
    for model in _load()["models"]:
        for key in REQUIRED_FIELDS:
            assert key in model, f"{model.get('name')!r} 缺字段 {key}"
            assert model[key] not in ("", None), f"{model.get('name')!r} 字段 {key} 为空"


def test_usage_locked_to_vocabulary():
    """usage 词表锁定，防口径漂移。"""
    for model in _load()["models"]:
        assert model["usage"] in USAGE_VOCAB, (
            f"{model['name']!r} usage={model['usage']!r} 不在受控词表 {sorted(USAGE_VOCAB)}"
        )


def test_status_mirrors_usage():
    for model in _load()["models"]:
        assert model["status"] == model["usage"]


def test_files_is_list_of_str():
    for model in _load()["models"]:
        assert isinstance(model["files"], list)
        assert all(isinstance(f, str) for f in model["files"])
