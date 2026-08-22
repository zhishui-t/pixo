"""pixo.harness.goldens.compare —— 金样本回归/对比接口。

支持：
  - 对一份测量报告与 manifest expected_metrics 做带容差比对；
  - 对合成样本直接运行测量并返回报告。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from pixo.vision import VisionMeasure

from .manifest import GoldenSample, is_sample_available
from .samples import generate_synthetic_sample

DEFAULT_TOLERANCE = 0.05


def _get_path(data: Any, path: str) -> Any:
    """按点分路径读取嵌套 dict；找不到返回 None。"""
    current = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _flatten_expected(
    expected: Mapping[str, Any],
    prefix: str = "",
) -> dict[str, Any]:
    """把嵌套期望指标展平为点分键。"""
    flat: dict[str, Any] = {}
    for key, value in expected.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            flat.update(_flatten_expected(value, full_key))
        else:
            flat[full_key] = value
    return flat


def compare_measurement(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    metrics: Sequence[str] | None = None,
) -> dict[str, Any]:
    """把实际测量值与期望指标逐项比对。

    Args:
        actual: 测量报告（含 global/regions）或扁平指标 dict。
        expected: manifest 中的扁平期望指标 dict。
        tolerance: 绝对容差。
        metrics: 可选过滤，只比较这些指标。

    Returns:
        包含 passed/matched/missing/failed/max_abs_diff/tolerance 的结果。
    """
    expected_flat = _flatten_expected(expected)
    keys = list(metrics) if metrics is not None else list(expected_flat.keys())
    matched: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    failed: list[dict[str, Any]] = []
    max_abs_diff = 0.0

    for key in keys:
        if key not in expected_flat:
            continue
        expected_value = expected_flat[key]
        if expected_value is None:
            continue
        actual_value = _get_path(actual, key)
        if actual_value is None and key in actual:
            actual_value = actual[key]
        if actual_value is None:
            missing.append(key)
            continue
        try:
            diff = abs(float(actual_value) - float(expected_value))
        except (TypeError, ValueError):
            missing.append(key)
            continue
        max_abs_diff = max(max_abs_diff, diff)
        if diff <= float(tolerance):
            matched[key] = {
                "expected": expected_value,
                "actual": actual_value,
                "abs_diff": round(diff, 6),
                "ok": True,
            }
        else:
            failed.append({
                "metric": key,
                "expected": expected_value,
                "actual": actual_value,
                "abs_diff": round(diff, 6),
                "ok": False,
            })

    return {
        "passed": not failed and not missing,
        "matched": matched,
        "missing": missing,
        "failed": failed,
        "max_abs_diff": round(max_abs_diff, 6),
        "tolerance": float(tolerance),
    }


def compare_sample(
    sample: GoldenSample | dict[str, Any],
    actual: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """按样本 expected_metrics 比对实际测量。"""
    if isinstance(sample, dict):
        sample = GoldenSample.from_dict(sample)
    return compare_measurement(
        actual,
        sample.expected_metrics,
        tolerance=tolerance,
    )


def run_synthetic_sample(
    sample: GoldenSample | dict[str, Any],
    size: tuple[int, int] = (96, 96),
) -> dict[str, Any]:
    """运行合成样本测量，返回测量报告。

    仅支持 synthetic=True 的样本；否则返回错误信息。
    """
    if isinstance(sample, dict):
        sample = GoldenSample.from_dict(sample)
    if not sample.synthetic:
        return {
            "photo_id": sample.photo_id,
            "error": "not_synthetic",
            "skip_reason": sample.skip_reason or "raw_missing",
            "measurement": None,
        }
    seed = int(sample.seed or 0)
    generated = generate_synthetic_sample(sample.type, seed=seed, size=size)
    measurement = VisionMeasure().measure(
        generated["image"],
        generated["masks"],
        image_id=sample.photo_id,
        render_version="golden_v0",
        detection_version="synthetic_v0",
        mask_version="mask_v0",
    )
    return {
        "photo_id": sample.photo_id,
        "type": sample.type,
        "available": True,
        "measurement": measurement,
    }


def compare_sample_with_run(
    sample: GoldenSample | dict[str, Any],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    size: tuple[int, int] = (96, 96),
) -> dict[str, Any]:
    """运行合成样本测量并直接与期望指标比对。"""
    if isinstance(sample, dict):
        sample = GoldenSample.from_dict(sample)
    if not is_sample_available(sample):
        return {
            "photo_id": sample.photo_id,
            "skipped": True,
            "skip_reason": sample.skip_reason or "raw_missing",
            "result": None,
        }
    run_result = run_synthetic_sample(sample, size=size)
    if run_result.get("measurement") is None:
        return {
            "photo_id": sample.photo_id,
            "skipped": True,
            "skip_reason": run_result.get("skip_reason") or "not_synthetic",
            "result": None,
        }
    result = compare_sample(
        sample, run_result["measurement"], tolerance=tolerance
    )
    return {
        "photo_id": sample.photo_id,
        "skipped": False,
        "result": result,
        "measurement": run_result["measurement"],
    }


__all__ = [
    "DEFAULT_TOLERANCE",
    "compare_measurement",
    "compare_sample",
    "run_synthetic_sample",
    "compare_sample_with_run",
]
