"""pixo.manifests —— Pixo Vision 模型与数据集清单读取/校验。

只登记元数据，不复制模型或数据集大文件。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MODELS_PATH = Path(__file__).with_name("vision_models.json")
DEFAULT_DATASETS_PATH = Path(__file__).with_name("vision_datasets.json")

MODEL_REQUIRED_FIELDS = (
    "id",
    "purpose",
    "path_or_source",
    "license",
    "publishable",
    "pixo_status",
)

DATASET_REQUIRED_FIELDS = (
    "id",
    "purpose",
    "path_or_source",
    "license",
    "publishable",
    "pixo_status",
)


def _validate_items(
    data: dict[str, Any],
    key: str,
    required: tuple[str, ...],
) -> list[str]:
    """校验条目列表字段完整性。"""
    errors: list[str] = []
    items = data.get(key)
    if not isinstance(items, list) or not items:
        errors.append(f"{key} 必须是非空列表")
        return errors
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{key}[{index}] 必须是对象")
            continue
        for field in required:
            if field not in item:
                errors.append(f"{key}[{index}] 缺少字段 {field}")
        if "publishable" in item and not isinstance(item["publishable"], bool):
            errors.append(f"{key}[{index}].publishable 必须是布尔值")
    return errors


def validate_vision_models(data: dict[str, Any]) -> list[str]:
    """校验 vision_models.json 字典。"""
    errors: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("schema_version 必须为 1.0")
    errors.extend(_validate_items(data, "models", MODEL_REQUIRED_FIELDS))
    return errors


def validate_vision_datasets(data: dict[str, Any]) -> list[str]:
    """校验 vision_datasets.json 字典。"""
    errors: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("schema_version 必须为 1.0")
    errors.extend(_validate_items(data, "datasets", DATASET_REQUIRED_FIELDS))
    return errors


def _load_json(path: str | Path) -> dict[str, Any]:
    """读取 JSON 文件。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"清单不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_vision_models(path: str | Path | None = None) -> dict[str, Any]:
    """加载并校验 vision_models.json。"""
    data = _load_json(path or DEFAULT_MODELS_PATH)
    errors = validate_vision_models(data)
    if errors:
        raise ValueError("; ".join(errors))
    return data


def load_vision_datasets(path: str | Path | None = None) -> dict[str, Any]:
    """加载并校验 vision_datasets.json。"""
    data = _load_json(path or DEFAULT_DATASETS_PATH)
    errors = validate_vision_datasets(data)
    if errors:
        raise ValueError("; ".join(errors))
    return data


def load_all_manifests() -> dict[str, dict[str, Any]]:
    """加载两个 Vision 清单。"""
    return {
        "vision_models": load_vision_models(),
        "vision_datasets": load_vision_datasets(),
    }


__all__ = [
    "DEFAULT_MODELS_PATH",
    "DEFAULT_DATASETS_PATH",
    "MODEL_REQUIRED_FIELDS",
    "DATASET_REQUIRED_FIELDS",
    "validate_vision_models",
    "validate_vision_datasets",
    "load_vision_models",
    "load_vision_datasets",
    "load_all_manifests",
]
