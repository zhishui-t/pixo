"""Pixo Vision 模型与数据集清单测试。

验证 vision_models.json / vision_datasets.json 可加载、字段完整。
"""
from __future__ import annotations

from pixo.manifests import (
    load_vision_datasets,
    load_vision_models,
    validate_vision_datasets,
    validate_vision_models,
)


def test_vision_models_manifest_loads():
    """模型清单可加载，且包含核心模型。"""
    data = load_vision_models()
    ids = {item["id"] for item in data["models"]}
    assert "yoloe-26l-seg" in ids
    assert "mobileclip2-b" in ids
    assert "aesthetic-scorer" in ids
    assert "openai-clip-vit-base-patch32" in ids
    assert "fairface-onnx" in ids


def test_vision_models_fields_complete():
    """每个模型条目包含用途/路径/许可/可发布/集成状态。"""
    data = load_vision_models()
    for item in data["models"]:
        assert item["id"]
        assert item["purpose"]
        assert item["path_or_source"]
        assert item["license"]
        assert isinstance(item["publishable"], bool)
        assert item["pixo_status"]


def test_vision_datasets_manifest_loads():
    """数据集清单可加载，包含金样本与 guanlan 参考数据。"""
    data = load_vision_datasets()
    ids = {item["id"] for item in data["datasets"]}
    assert "guanlan-calibration-synthetic" in ids
    assert "guanlan-landscape-yolo96" in ids
    assert "pixo-golden-samples-v0" in ids
    assert "pixo-raw-golden-placeholders" in ids


def test_vision_datasets_fields_complete():
    """每个数据集条目包含用途/来源/许可/可发布/集成状态。"""
    data = load_vision_datasets()
    for item in data["datasets"]:
        assert item["id"]
        assert item["purpose"]
        assert item["path_or_source"]
        assert item["license"]
        assert isinstance(item["publishable"], bool)
        assert item["pixo_status"]


def test_missing_field_detected():
    """缺失字段时校验返回错误。"""
    invalid_models = {
        "schema_version": "1.0",
        "models": [
            {
                "id": "missing-fields",
                "purpose": "test",
            }
        ],
    }
    model_errors = validate_vision_models(invalid_models)
    assert any("path_or_source" in e for e in model_errors)

    invalid_datasets = {
        "schema_version": "1.0",
        "datasets": [
            {
                "id": "missing-fields",
                "purpose": "test",
            }
        ],
    }
    dataset_errors = validate_vision_datasets(invalid_datasets)
    assert any("license" in e for e in dataset_errors)


def test_publishable_boolean_must_be_bool():
    """publishable 非布尔时校验失败。"""
    invalid = {
        "schema_version": "1.0",
        "models": [
            {
                "id": "x",
                "purpose": "p",
                "path_or_source": "s",
                "license": "MIT",
                "publishable": "yes",
                "pixo_status": "planned",
            }
        ],
    }
    errors = validate_vision_models(invalid)
    assert any("publishable" in e for e in errors)
