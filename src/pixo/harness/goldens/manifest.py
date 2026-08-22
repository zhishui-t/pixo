"""pixo.harness.goldens.manifest —— 金样本 manifest 数据结构与校验。

Schema 版本: pixo-goldens-v0
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GOLDEN_SCHEMA = "pixo-goldens-v0"
GOLDEN_MANIFEST_VERSION = "0.1.0"

SAMPLE_TYPES = (
    "exposure",
    "skin",
    "scene",
    "burst",
    "曝光",
    "肤色",
    "场景",
    "连拍",
)

REQUIRED_SAMPLE_KEYS = (
    "photo_id",
    "type",
    "input",
    "expected_metrics",
    "version",
    "available",
)


@dataclass
class GoldenSample:
    """一条金样本登记。

    Args:
        photo_id: 样本唯一 ID。
        type: exposure / skin / scene / burst。
        input_path: 真实文件路径；合成样本可为 None。
        input_hash: 真实输入文件的 SHA-256；合成样本可为 None。
        synthetic: 是否为合成样本。
        generator: 合成样本的生成器名称。
        seed: 合成样本随机种子。
        mask_ref: mask 标注引用，例如 {"face": "synthetic:face_ellipse"}。
        expected_metrics: 期望指标扁平字典，如 {"global.mean_luminance": 120.0}。
        version: 样本/算法版本。
        available: 是否可运行（真实文件存在）。
        skip_reason: 不可运行时的原因。
        frames: 连拍样本的 frame id 列表。
    """

    photo_id: str
    type: str
    expected_metrics: dict[str, Any]
    input_path: str | None = None
    input_hash: str | None = None
    synthetic: bool = False
    generator: str | None = None
    seed: int | None = None
    mask_ref: dict[str, str] = field(default_factory=dict)
    version: str = GOLDEN_MANIFEST_VERSION
    available: bool = False
    skip_reason: str | None = None
    frames: list[str] = field(default_factory=list)

    @property
    def input(self) -> dict[str, Any]:
        """input 字段的 dict 视图，兼容 JSON 结构。"""
        return {
            "path": self.input_path,
            "hash": self.input_hash,
            "synthetic": self.synthetic,
            "generator": self.generator,
            "seed": self.seed,
            "frames": list(self.frames),
        }

    def to_dict(self) -> dict[str, Any]:
        """转 JSON 字典。"""
        return {
            "photo_id": self.photo_id,
            "type": self.type,
            "input": self.input,
            "mask_ref": dict(self.mask_ref),
            "expected_metrics": dict(self.expected_metrics),
            "version": self.version,
            "available": bool(self.available),
            "skip_reason": self.skip_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenSample":
        """从 JSON 字典构建。"""
        input_data = data.get("input") or {}
        return cls(
            photo_id=str(data["photo_id"]),
            type=str(data["type"]),
            input_path=input_data.get("path"),
            input_hash=input_data.get("hash"),
            synthetic=bool(input_data.get("synthetic", False)),
            generator=input_data.get("generator"),
            seed=input_data.get("seed"),
            frames=list(input_data.get("frames") or []),
            mask_ref=dict(data.get("mask_ref") or {}),
            expected_metrics=dict(data.get("expected_metrics") or {}),
            version=str(data.get("version", GOLDEN_MANIFEST_VERSION)),
            available=bool(data.get("available", False)),
            skip_reason=data.get("skip_reason"),
        )


@dataclass
class GoldenManifest:
    """金样本 manifest 容器。"""

    schema: str = GOLDEN_SCHEMA
    version: str = GOLDEN_MANIFEST_VERSION
    samples: list[GoldenSample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转 JSON 字典。"""
        return {
            "schema": self.schema,
            "version": self.version,
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenManifest":
        """从 JSON 字典构建。"""
        return cls(
            schema=str(data.get("schema", GOLDEN_SCHEMA)),
            version=str(data.get("version", GOLDEN_MANIFEST_VERSION)),
            samples=[
                GoldenSample.from_dict(item)
                for item in (data.get("samples") or [])
                if isinstance(item, dict)
            ],
        )


def validate_manifest(
    manifest: GoldenManifest | dict[str, Any],
) -> list[str]:
    """校验 manifest 字典，返回错误列表；空列表表示合法。"""
    if isinstance(manifest, GoldenManifest):
        manifest = manifest.to_dict()
    if not isinstance(manifest, dict):
        return ["manifest 必须是对象"]
    errors: list[str] = []
    if manifest.get("schema") != GOLDEN_SCHEMA:
        errors.append(f"schema 必须为 {GOLDEN_SCHEMA}")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        errors.append("samples 必须是非空列表")
        return errors

    for index, sample in enumerate(samples):
        prefix = f"samples[{index}]"
        if not isinstance(sample, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        for key in REQUIRED_SAMPLE_KEYS:
            if key not in sample:
                errors.append(f"{prefix} 缺少字段 {key}")
        sample_type = sample.get("type")
        if sample_type not in SAMPLE_TYPES:
            errors.append(f"{prefix}.type 非法: {sample_type!r}")
        input_data = sample.get("input")
        if not isinstance(input_data, dict):
            errors.append(f"{prefix}.input 必须是对象")
        else:
            if "synthetic" not in input_data:
                errors.append(f"{prefix}.input 缺少 synthetic")
            if input_data.get("synthetic") is False and not input_data.get("path"):
                errors.append(f"{prefix}.input.path 在非合成样本中不能为空")
        if not isinstance(sample.get("expected_metrics"), dict):
            errors.append(f"{prefix}.expected_metrics 必须是对象")
        if "available" not in sample:
            errors.append(f"{prefix} 缺少 available")
    return errors


def is_valid_manifest(manifest: GoldenManifest | dict[str, Any]) -> bool:
    """校验是否合法（无错误）。"""
    return not validate_manifest(manifest)


def load_manifest(path: str | Path) -> GoldenManifest:
    """读取并解析 golden_manifest.json。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"manifest 不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_manifest(data)
    if errors:
        raise ValueError("; ".join(errors))
    return GoldenManifest.from_dict(data)


def save_manifest(
    manifest: GoldenManifest | dict[str, Any],
    path: str | Path,
) -> Path:
    """保存 manifest 到 JSON 文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(manifest, GoldenManifest):
        data = manifest.to_dict()
    else:
        data = manifest
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def hash_file(path: str | Path) -> str:
    """计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sample_available(sample: GoldenSample | dict[str, Any]) -> bool:
    """判断样本是否可运行：合成样本始终可用；真实样本需文件存在。"""
    if isinstance(sample, dict):
        sample = GoldenSample.from_dict(sample)
    if sample.synthetic:
        return bool(sample.available)
    if not sample.available or not sample.input_path:
        return False
    return Path(sample.input_path).is_file()


def verify_input_hash(
    sample: GoldenSample | dict[str, Any],
    path: str | Path | None = None,
) -> bool:
    """校验真实样本输入哈希；合成/无哈希样本视为通过。"""
    if isinstance(sample, dict):
        sample = GoldenSample.from_dict(sample)
    if sample.synthetic or not sample.input_hash:
        return True
    file_path = Path(path or sample.input_path or "")
    if not file_path.is_file():
        return False
    return hash_file(file_path) == sample.input_hash


__all__ = [
    "GOLDEN_SCHEMA",
    "GOLDEN_MANIFEST_VERSION",
    "SAMPLE_TYPES",
    "GoldenSample",
    "GoldenManifest",
    "validate_manifest",
    "is_valid_manifest",
    "load_manifest",
    "save_manifest",
    "hash_file",
    "is_sample_available",
    "verify_input_hash",
]
