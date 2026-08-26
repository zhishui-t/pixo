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

# 兼容旧名：语义映射到 abs_tol（绝对容差下限）。
DEFAULT_TOLERANCE = 0.05
# 相对容差通道：0-1 量纲（比例/分数）指标按 rel_tol 缩放。
DEFAULT_REL_TOL = 0.03
# 0-255 量纲阈值：|expected| 超过该值视为大尺度指标（亮度/RGB 均值等）。
# 1.5 之上只可能是 0-255 量纲（0-1 比例不可能超过 1）。
LARGE_SCALE_THRESHOLD = 1.5
# 大尺度（0-255）指标的相对容差上限：0.002*|expected| ≈ 绝对 0.3-0.4。
# 依据：比纯 abs_tol=0.05 宽 ~7 倍，可容忍跨平台浮点求和重排误差；
# 但远小于 1 个亮度级（旧 rel_tol=0.03 会放宽到 4.6-6.3，约 5 个亮度级）。
LARGE_SCALE_REL_TOL = 0.002


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


def _effective_rel_tol(rel_tol: float, expected_abs: float) -> float:
    """按期望值量纲取相对容差系数。

    |expected| > LARGE_SCALE_THRESHOLD 视为 0-255 量纲指标（亮度/RGB
    均值等），rel 系数收紧到不超过 LARGE_SCALE_REL_TOL（min 保证调用方
    显式传更紧的 rel_tol 时仍尊重更紧值）；0-1 量纲保持传入的 rel_tol。
    """
    if expected_abs > LARGE_SCALE_THRESHOLD:
        return min(float(rel_tol), LARGE_SCALE_REL_TOL)
    return float(rel_tol)


def compare_measurement(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    tolerance: float | None = None,
    abs_tol: float = DEFAULT_TOLERANCE,
    rel_tol: float = DEFAULT_REL_TOL,
    metrics: Sequence[str] | None = None,
) -> dict[str, Any]:
    """把实际测量值与期望指标逐项比对（abs_tol + rel_tol 双通道）。

    Args:
        actual: 测量报告（含 global/regions）或扁平指标 dict。
        expected: manifest 中的扁平期望指标 dict。
        tolerance: 兼容旧调用，等价于 abs_tol。
        abs_tol: 绝对容差下限（diff <= abs_tol + rel*|expected| 判通过）。
        rel_tol: 相对容差系数，按期望值量纲缩放；0-255 量纲
            （|expected| > 1.5）自动收紧为不超过 LARGE_SCALE_REL_TOL。
        metrics: 可选过滤，只比较这些指标；含 expected 中不存在的键时抛
            ValueError（避免调用方拼错指标名被静默忽略）。

    Returns:
        包含 passed/matched/missing/failed/max_abs_diff/abs_tol/rel_tol 的结果。
        matched/failed 条目里的 effective_tol 已体现量纲收紧后的实际判定容差。

    Raises:
        ValueError: metrics 中出现了 expected 里不存在的指标名。
    """
    if tolerance is not None:
        # 旧参数兼容：旧 DEFAULT_TOLERANCE 语义即绝对容差。
        abs_tol = float(tolerance)
    expected_flat = _flatten_expected(expected)
    keys = list(metrics) if metrics is not None else list(expected_flat.keys())
    unknown = [key for key in keys if key not in expected_flat]
    if unknown:
        raise ValueError(
            f"metrics 中存在 expected 未定义的指标: {unknown}；"
            f"合法键: {sorted(expected_flat.keys())}"
        )
    matched: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    failed: list[dict[str, Any]] = []
    max_abs_diff = 0.0

    for key in keys:
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
        expected_abs = abs(float(expected_value))
        # 分量纲：0-255 量纲指标收紧 rel 系数（见 LARGE_SCALE_REL_TOL）。
        effective_rel = _effective_rel_tol(rel_tol, expected_abs)
        effective_tol = float(abs_tol) + effective_rel * expected_abs
        max_abs_diff = max(max_abs_diff, diff)
        if diff <= effective_tol:
            matched[key] = {
                "expected": expected_value,
                "actual": actual_value,
                "abs_diff": round(diff, 6),
                "effective_tol": round(effective_tol, 6),
                "ok": True,
            }
        else:
            failed.append({
                "metric": key,
                "expected": expected_value,
                "actual": actual_value,
                "abs_diff": round(diff, 6),
                "effective_tol": round(effective_tol, 6),
                "ok": False,
            })

    return {
        "passed": not failed and not missing,
        "matched": matched,
        "missing": missing,
        "failed": failed,
        "max_abs_diff": round(max_abs_diff, 6),
        # tolerance 字段保留旧语义（= abs_tol）以兼容既有调用方。
        "tolerance": float(abs_tol),
        "abs_tol": float(abs_tol),
        # rel_tol 保留调用方传入值（兼容旧字段）；0-255 量纲实际生效值
        # 见各条目的 effective_tol 与 LARGE_SCALE_REL_TOL。
        "rel_tol": float(rel_tol),
        "large_scale_rel_tol": float(LARGE_SCALE_REL_TOL),
    }


def compare_sample(
    sample: GoldenSample | dict[str, Any],
    actual: Mapping[str, Any],
    *,
    tolerance: float | None = None,
    abs_tol: float = DEFAULT_TOLERANCE,
    rel_tol: float = DEFAULT_REL_TOL,
) -> dict[str, Any]:
    """按样本 expected_metrics 比对实际测量（双通道容差）。"""
    if isinstance(sample, dict):
        sample = GoldenSample.from_dict(sample)
    return compare_measurement(
        actual,
        sample.expected_metrics,
        tolerance=tolerance,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
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
    tolerance: float | None = None,
    abs_tol: float = DEFAULT_TOLERANCE,
    rel_tol: float = DEFAULT_REL_TOL,
    size: tuple[int, int] = (96, 96),
) -> dict[str, Any]:
    """运行合成样本测量并直接与期望指标比对（双通道容差）。"""
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
        sample, run_result["measurement"],
        tolerance=tolerance, abs_tol=abs_tol, rel_tol=rel_tol,
    )
    return {
        "photo_id": sample.photo_id,
        "skipped": False,
        "result": result,
        "measurement": run_result["measurement"],
    }


__all__ = [
    "DEFAULT_TOLERANCE",
    "DEFAULT_REL_TOL",
    "LARGE_SCALE_THRESHOLD",
    "LARGE_SCALE_REL_TOL",
    "compare_measurement",
    "compare_sample",
    "run_synthetic_sample",
    "compare_sample_with_run",
]
