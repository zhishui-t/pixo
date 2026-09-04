"""model_licenses.json 轻量 schema 守卫（t57）+ 许可白名单门（阶段三治理）。

锁定：必填字段齐全、usage 词表不漂移、status 与 usage 一致、文件末尾换行；
许可白名单硬拒（OWN_PIPELINE_STAGE3_DESIGN §1）：license 不在
ALLOWED_LICENSES（MIT/Apache only）的条目（需审核家族）publishable
必须为 false——非白名单且 publishable=true 即硬拒。
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

# 阶段三门禁：可分发许可白名单（精确匹配）。复合 license 文案（如
# "code MIT / weights CC BY-NC-SA"）按整体字符串比对——权重许可非白名单
# 即视为需审核家族，publishable 必须显式 false（缺省视为 false 不可发布）。
ALLOWED_LICENSES = {"MIT", "Apache-2.0"}


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


# ---------------------------------------------------------------------------
# 许可白名单门（OWN_PIPELINE_STAGE3_DESIGN §1 固化）
# ---------------------------------------------------------------------------

def _license_gate_errors(models: list[dict]) -> list[str]:
    """白名单门检查 → 违规理由列表（空 = 通过）。

    规则：publishable 必须为显式布尔（缺省视为未声明，一并报缺）；
    license ∉ ALLOWED_LICENSES 且 publishable=true → 硬拒。
    """
    errors: list[str] = []
    for model in models:
        name = model.get("name", "?")
        pub = model.get("publishable")
        if not isinstance(pub, bool):
            errors.append(f"{name!r} 缺显式 publishable 布尔字段（缺省按 false 治理）")
            continue
        if model.get("license") not in ALLOWED_LICENSES and pub:
            errors.append(
                f"{name!r} license={model.get('license')!r} 不在白名单 "
                f"{sorted(ALLOWED_LICENSES)} 且 publishable=true —— 硬拒"
                f"（需审核/替换许可后才能转可发布）")
    return errors


def test_license_gate_real_manifest_clean():
    """真实 manifest 全量过白名单门（现存需审核条目均 publishable=false）。"""
    assert _license_gate_errors(_load()["models"]) == []


def test_license_gate_hard_rejects_nonwhitelist_publishable():
    """非白名单 license + publishable=true → 硬拒；false 豁免；缺字段报缺。"""
    models = [
        {"name": "mit-model", "license": "MIT", "publishable": True},
        {"name": "nc-model", "license": "CC-BY-NC-4.0", "publishable": True},
        {"name": "nc-suppressed", "license": "CC-BY-NC-4.0", "publishable": False},
        {"name": "compound", "license": "code MIT / weights CC BY-NC-SA",
         "publishable": True},
        {"name": "no-field", "license": "Apache-2.0"},
    ]
    errors = _license_gate_errors(models)
    assert any("nc-model" in e and "硬拒" in e for e in errors)
    assert any("compound" in e and "硬拒" in e for e in errors), (
        "复合 license 文案按整体比对，不得因含 'MIT' 字样漏放")
    assert not any("nc-suppressed" in e for e in errors)
    assert not any("mit-model" in e for e in errors)
    assert any("no-field" in e and "publishable" in e for e in errors)


def test_publishable_implies_redistributable_usage():
    """publishable=true 的条目 usage 必须是可再分发档（口径自洽）。"""
    for model in _load()["models"]:
        if model.get("publishable") is True:
            assert model["usage"] == "redistribution_allowed_with_license_notice", (
                f"{model['name']!r} publishable=true 但 usage={model['usage']!r} "
                f"非可再分发档，两字段口径冲突")
