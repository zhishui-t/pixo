"""R21 / F03 —— 公共指标 API（``pixo.pipeline.metrics``）定向单测。

覆盖 ``design-r21`` §2.1 与交付清单的四条验收：

1. 公共 ``metrics_for_decide`` 与 loop 旧行为**逐键一致**（对冻结的期望
   dict 断言，而不是与已改成 wrapper 的 loop 函数自比）；
2. ``metric_universe(("face", "sky", "plant"))`` 覆盖 ``region_rules.yaml``
   的 condition 与 formula 引用的**全部**键；
3. **显式传** ``metric_keys=metric_universe(...)`` 后，7 个 ``DEFAULT_RULES``
   文件全部 ``load_rules`` 无 ``DecideError``（R22 F01 扩容：+noise_rules.yaml）；
4. ``merge_proxy_metrics`` 把 ``compute_proxy_metrics`` 三键合到 measurement
   **顶层**（非 ``global`` 下），且随后 ``metrics_for_decide`` 可见。

附：架构红线（``pipeline`` 不得 import ``pixo.service``）与
``compute_proxy_metrics`` 的导入来源（``pixo.vision.measure``）各一条守卫。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

import pixo.pipeline.metrics as metrics_mod
from pixo.decide.engine import (
    _FORMULA_FUNCS,
    _FORMULA_RUNTIME_VARS,
    load_rules,
)
from pixo.decide.rules import DEFAULT_RULES, RULES_DIR
from pixo.pipeline.loop import _metrics_for_decide
from pixo.pipeline.metrics import (
    METRIC_KEYS,
    merge_proxy_metrics,
    metric_universe,
    metrics_for_decide,
)
from pixo.vision.measure import compute_proxy_metrics


def _measurement() -> dict:
    """代表性测量报告：6 个 global 键 + 3 个顶层代理 + 2 个 region。"""
    return {
        "image_id": "img-1",
        "mask_version": "v1",
        "global": {
            "mean_luminance": 104.93,
            "highlight_clip_ratio": 0.012,
            "shadow_clip_ratio": 0.25,
            "contrast": 0.41,
            "preview_highlight_clip_estimate": 0.008,
            "not_exported_key": 123,
        },
        "regions": {
            "face": {
                "mean_luminance": 105.0,
                "area_ratio": 0.235,
                "highlight_clip_ratio": 0.01,
                "reliable": True,
            },
            "sky": {
                "mean_luminance": None,
                "area_ratio": 0.0,
                "highlight_clip_ratio": 0.0,
                "reliable": False,
            },
        },
        "haze_proxy": 0.1823,
        "colorfulness_proxy": 6.1888,
        "tonal_range": 0.4974,
    }


# 冻结的旧行为期望（= loop.py:527-551 的原实现产出）。
_EXPECTED_FLAT = {
    "mean_luminance": 104.93,
    "highlight_clip_ratio": 0.012,
    "shadow_clip_ratio": 0.25,
    "contrast": 0.41,
    "preview_highlight_clip_estimate": 0.008,
    "preview_overflow_ratio": 0.008,
    "haze_proxy": 0.1823,
    "colorfulness_proxy": 6.1888,
    "tonal_range": 0.4974,
    "face_luminance": 105.0,
    "face_area_ratio": 0.235,
    "face_highlight_clip_ratio": 0.01,
    "face_reliable": True,
    "sky_luminance": None,
    "sky_area_ratio": 0.0,
    "sky_highlight_clip_ratio": 0.0,
    "sky_reliable": False,
}


# ---------------------------------------------------------------- 验收 ① 逐键一致


def test_public_flatten_matches_frozen_legacy_expectation():
    """公共函数产出 == 冻结的旧 loop 实现期望（逐键、逐值）。"""
    measurement = _measurement()
    flat = metrics_for_decide(measurement)

    assert flat == _EXPECTED_FLAT
    # 关键负向：非 flatten 面键不得泄漏
    assert "not_exported_key" not in flat
    assert "mask_version" not in flat
    assert "global" not in flat and "regions" not in flat


def test_loop_alias_delegates_to_public_function():
    """loop 侧 wrapper 与公共函数同源（既有调用点 1393 行为不变）。"""
    measurement = _measurement()
    assert _metrics_for_decide(measurement) == metrics_for_decide(measurement)
    assert _metrics_for_decide(measurement) == _EXPECTED_FLAT


def test_proxy_keys_only_when_present_at_top_level():
    """代理键仅在 measurement **顶层**存在时产出（缺省不写空键）。"""
    measurement = _measurement()
    del measurement["haze_proxy"]
    del measurement["colorfulness_proxy"]
    del measurement["tonal_range"]

    flat = metrics_for_decide(measurement)
    assert "haze_proxy" not in flat
    assert "colorfulness_proxy" not in flat
    assert "tonal_range" not in flat
    # 嵌在 global 下的同名单不生效（口径要求顶层）
    measurement["global"]["haze_proxy"] = 0.9  # type: ignore[index]
    assert "haze_proxy" not in metrics_for_decide(measurement)


def test_region_reliable_is_coerced_to_bool():
    """region.reliable 恒为 bool（旧实现 bool(region.get("reliable", False))）。"""
    measurement = {
        "global": {},
        "regions": {
            "face": {"reliable": 1},
            "sky": {},
        },
    }
    flat = metrics_for_decide(measurement)
    assert flat["face_reliable"] is True
    assert flat["sky_reliable"] is False


def test_non_mapping_input_returns_empty():
    """非 Mapping 输入返回 {}（库层防御行为）。"""
    assert metrics_for_decide(None) == {}  # type: ignore[arg-type]
    assert metrics_for_decide([("global", {})]) == {}  # type: ignore[arg-type]
    assert metrics_for_decide("measurement") == {}  # type: ignore[arg-type]


def test_metric_keys_is_flatten_fixed_set_without_region_keys():
    """METRIC_KEYS = flatten 固定键（对齐 loop 注册面），**不含**区域键。"""
    assert METRIC_KEYS == frozenset({
        "mean_luminance",
        "highlight_clip_ratio",
        "shadow_clip_ratio",
        "contrast",
        "preview_highlight_clip_estimate",
        "preview_overflow_ratio",
        "haze_proxy",
        "colorfulness_proxy",
        "tonal_range",
        "crop_suggestion_applicable",
        # R22 F01 扩容（design §1/§2.1）：噪声/细节 4 层展平键入键宇宙
        # measurement["global"]["detail"]["sharpness"] → 精确集合 10→12 键
        "noise_ratio",
        "detail_score",
    })
    assert not any(k.startswith(("face_", "sky_", "plant_")) for k in METRIC_KEYS)


# ---------------------------------------------------------------- 验收 ② 覆盖区域键


def _region_rules_referenced_keys() -> set[str]:
    """region_rules.yaml 引用的指标名：condition.all[].metric ∪ formula 标识符。"""
    data = yaml.safe_load(
        (RULES_DIR / "region_rules.yaml").read_text(encoding="utf-8")
    )
    referenced: set[str] = set()
    for rule in data or []:
        cond = rule.get("condition") or {}
        for sub in cond.get("all") or []:
            if sub and sub.get("metric"):
                referenced.add(str(sub["metric"]))
        expr = (rule.get("action") or {}).get("formula")
        if isinstance(expr, str) and expr.strip():
            for node in ast.walk(ast.parse(expr, mode="eval")):
                if isinstance(node, ast.Name):
                    referenced.add(node.id)
    return referenced


def test_metric_universe_covers_region_rules_references():
    """metric_universe 覆盖 region_rules 引用的全部键（condition + formula）。"""
    referenced = _region_rules_referenced_keys()
    # 反向护栏：确保上面的解析真的取到了区域强引用键（测试非空转）
    assert {"sky_luminance", "sky_area_ratio", "sky_reliable",
            "plant_luminance", "plant_area_ratio", "plant_reliable",
            "preview_overflow_ratio"} <= referenced

    universe = metric_universe(("face", "sky", "plant"))
    allowed_non_metric = set(_FORMULA_FUNCS) | set(_FORMULA_RUNTIME_VARS)
    unknown = referenced - set(universe) - allowed_non_metric
    assert not unknown, f"metric_universe 缺键: {sorted(unknown)}"

    # METRIC_KEYS 是 universe 的真子集：区域键只能来自 prompts 参数
    assert set(METRIC_KEYS) < set(universe)
    assert "sky_luminance" not in METRIC_KEYS


def test_metric_universe_follows_prompts_argument():
    """区域键随 prompts 参数走（lint/装配按实际 prompts 传）。"""
    universe = metric_universe(("face", "sky", "plant"))
    assert len(universe) == len(METRIC_KEYS) + 3 * 4
    custom = metric_universe(("face",))
    assert "face_luminance" in custom
    assert "sky_luminance" not in custom
    assert METRIC_KEYS <= custom


# ---------------------------------------------------------------- 验收 ③ 规则全加载


def test_default_rules_load_with_explicit_metric_universe():
    """显式传键宇宙后，7 个 DEFAULT_RULES 文件全部 load_rules 无 DecideError。"""
    # R22 F01 扩容（design §1/§2.1）：新增 noise_rules.yaml（默认关）⇒ 6→7 文件
    assert len(DEFAULT_RULES) == 7
    universe = metric_universe(("face", "sky", "plant"))

    total = 0
    per_file: dict[str, int] = {}
    for path in DEFAULT_RULES:
        rules = load_rules(path, metric_keys=universe)  # 抛 DecideError 即失败
        assert rules, f"{Path(path).name} 未加载到任何规则"
        per_file[Path(path).name] = len(rules)
        total += len(rules)

    # R22 F01 扩容（design §1/§2.1）：noise_luminance_rule_040 计入 ⇒ 11→12 条
    assert total == 12, per_file  # 7 文件 / 12 条（R22 F01 增量后口径）
    assert per_file["region_rules.yaml"] == 2
    assert per_file["noise_rules.yaml"] == 1


# ---------------------------------------------------------------- 验收 ④ 顶层合并


def _rgb() -> np.ndarray:
    rng = np.random.default_rng(20260910)
    return rng.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)


def test_merge_proxy_metrics_lands_on_measurement_top_level():
    """proxies 合到 measurement 顶层，且 flatten 后可见（嵌套会取不到）。"""
    image = _rgb()
    expected = compute_proxy_metrics(image)
    assert set(expected) == {"haze_proxy", "colorfulness_proxy", "tonal_range"}

    measurement = {"global": {"mean_luminance": 100.0}, "regions": {}}
    out = merge_proxy_metrics(measurement, image)

    assert out is measurement  # 原地 + 返回同一对象
    for key, value in expected.items():
        assert measurement[key] == value          # 顶层落位
        assert key not in measurement["global"]   # 不是嵌进 global

    flat = metrics_for_decide(measurement)
    for key, value in expected.items():
        assert flat[key] == value                 # 展平后规则引擎可见


def test_merge_proxy_metrics_invalid_image_leaves_measurement_unchanged():
    """非法输入图 → compute_proxy_metrics 空 dict → measurement 不被改动。"""
    for bad in (None, np.zeros((16, 16), dtype=np.uint8)):
        measurement = {"global": {}, "regions": {}}
        out = merge_proxy_metrics(measurement, bad)
        assert out == {"global": {}, "regions": {}}


# ---------------------------------------------------------------- 架构 / 来源守卫


def test_metrics_module_does_not_import_service():
    """架构红线：pipeline 侧不得反向依赖 pixo.service（依赖方向 service→pipeline）。"""
    source = Path(metrics_mod.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+pixo\.service", source, re.M), (
        "pixo.pipeline.metrics 不得 import pixo.service"
    )
    assert not re.search(r"^\s*from\s+pixo\.service", source, re.M)


def test_proxy_metrics_imported_from_vision_measure():
    """compute_proxy_metrics 必须从 pixo.vision.measure 直接取（__init__ 未 re-export）。"""
    assert metrics_mod.compute_proxy_metrics is compute_proxy_metrics
    from pixo.vision import measure as vision_measure

    assert metrics_mod.compute_proxy_metrics is vision_measure.compute_proxy_metrics


def test_decide_photo_style_flatten_is_json_friendly():
    """扁平结果只含标量/None（规则 condition 比较面），无 numpy 容器。"""
    for value in metrics_for_decide(_measurement()).values():
        assert value is None or isinstance(value, (bool, int, float))
