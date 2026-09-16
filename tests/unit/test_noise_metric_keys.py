"""R22 / F01（CR-06）—— 噪声/细节指标入决策键宇宙 定向单测。

覆盖 design-r22 §1 F01 的四条验收（dev-1 文件域，tests/unit 新增文件）：

1. **展平键存在且层级正确**：``noise_ratio`` / ``detail_score`` 来自
   **4 层**路径 ``measurement["global"]["detail"]["sharpness"][*]``
   （3 层/顶层同名键不得被误取）；
2. **键宇宙 lint 放行**（**显式传** ``metric_keys=metric_universe(...)``）：
   新规则 YAML 可加载；缺 ``noise_ratio`` 时同一份 YAML 必须被 lint 拦下
   （反证 lint 真生效，不是空转）；
3. **规则默认关**：``enabled: false``；未开启时对既有判定**零影响**
   （同一 metrics 快照下，注册表 ± 该规则，``evaluate_rules`` 输出逐条相同）；
4. **口径留证**：规则头注写明「全幅标定 + 闭环只吃 preview ⇒ 不生效」
   与 512 tier 排序非单调证据（ISO12800 0.2837 < ISO1600 0.6680）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pixo.decide.engine import (
    DecideError,
    evaluate_rules,
    load_rules,
    register_metric_keys,
    registered_metric_keys,
    reset_metric_keys,
)
from pixo.decide.rules import DEFAULT_RULES, RULES_DIR
from pixo.pipeline.metrics import (
    METRIC_KEYS,
    SHARPNESS_METRIC_KEYS,
    metric_universe,
    metrics_for_decide,
)

NOISE_RULE_ID = "noise_luminance_rule_040"
NOISE_YAML = RULES_DIR / "noise_rules.yaml"
PROMPTS = ("face", "sky", "plant")


def _measurement(sharpness: dict | None, *, top_level_noise: float | None = None) -> dict:
    global_metrics: dict = {
        "mean_luminance": 100.0,
        "highlight_clip_ratio": 0.004,
        "shadow_clip_ratio": 0.0,
        "contrast": 0.4,
        "preview_highlight_clip_estimate": 0.002,
    }
    if sharpness is not None:
        global_metrics["detail"] = {"sharpness": dict(sharpness)}
    measurement: dict = {"global": global_metrics, "regions": {}}
    if top_level_noise is not None:
        measurement["noise_ratio"] = top_level_noise   # 顶层同名键（干扰项）
    return measurement


# ---------------------------------------------------------------- 验收 ① 层级正确


def test_sharpness_metric_keys_are_the_two_designed_names():
    assert SHARPNESS_METRIC_KEYS == ("noise_ratio", "detail_score")


def test_flatten_reads_four_layer_path_global_detail_sharpness():
    measurement = _measurement({
        "laplacian_raw": 1840.85,
        "laplacian_denoised": 2063.98,
        "noise_ratio": 0.5123,
        "fft_high_ratio": 0.0014,
        "detail_score": 2063.98,
    })
    flat = metrics_for_decide(measurement)

    assert flat["noise_ratio"] == pytest.approx(0.5123)
    assert flat["detail_score"] == pytest.approx(2063.98)
    # 非目标键不泄漏（只展平设计指定的两键）
    assert "fft_high_ratio" not in flat
    assert "laplacian_raw" not in flat


def test_flatten_requires_the_full_four_layer_path():
    """3 层（global.noise_ratio）与顶层同名键都不得被误取。"""
    three_layer = _measurement(None)
    three_layer["global"]["noise_ratio"] = 0.9
    three_layer["global"]["detail"] = {"noise_ratio": 0.8}   # detail 下但不在 sharpness
    flat = metrics_for_decide(three_layer)
    assert "noise_ratio" not in flat
    assert "detail_score" not in flat

    top_level = _measurement(None, top_level_noise=0.7)
    flat_top = metrics_for_decide(top_level)
    assert "noise_ratio" not in flat_top


def test_flatten_emits_no_empty_keys_when_detail_absent():
    """detail 缺席 → 不写空键（与代理键同款「缺省不写」语义）。"""
    flat = metrics_for_decide(_measurement(None))
    assert "noise_ratio" not in flat and "detail_score" not in flat
    # 既有固定键语义未变（仍恒写）
    assert flat["mean_luminance"] == pytest.approx(100.0)
    assert flat["preview_overflow_ratio"] == pytest.approx(0.002)


def test_flatten_tolerates_malformed_detail_layers():
    """detail / sharpness 非法形态（list/str）不得抛异常。"""
    for bad_detail in ([1, 2], "sharpness", 3):
        measurement = _measurement(None)
        measurement["global"]["detail"] = bad_detail
        flat = metrics_for_decide(measurement)
        assert "noise_ratio" not in flat and "detail_score" not in flat


# ---------------------------------------------------------------- 键宇宙同步


def test_metric_keys_and_universe_include_noise_keys():
    assert {"noise_ratio", "detail_score"} <= set(METRIC_KEYS)
    universe = metric_universe(PROMPTS)
    assert {"noise_ratio", "detail_score"} <= set(universe)
    # 区域键仍只来自 prompts 参数（口径未变）
    assert len(universe) == len(METRIC_KEYS) + len(PROMPTS) * 4


# ---------------------------------------------------------------- 验收 ② lint 放行


def test_noise_rule_loads_with_explicit_metric_universe():
    """显式传键宇宙 → 新规则 YAML 加载成功（lint 放行）。"""
    rules = load_rules(NOISE_YAML, metric_keys=metric_universe(PROMPTS))
    assert len(rules) == 1
    rule = rules[0]
    assert rule["rule_id"] == NOISE_RULE_ID
    assert rule["condition"]["metric"] == "noise_ratio"
    assert rule["condition"]["op"] in ("gte", "ge", ">=")
    assert "noise_ratio" in rule["action"]["formula"]        # 公式直引指标键
    assert rule["enabled"] is False                          # 验收 ③ 默认关


def test_lint_rejects_rule_when_noise_ratio_key_is_missing():
    """反证 lint 真生效：键宇宙缺 noise_ratio → 加载期 DecideError。

    ``register_metric_keys`` 是进程级全局副作用，故先快照 + 清空，结束后
    原样恢复（否则会污染同进程后续用例的 lint 松紧）。
    """
    saved = registered_metric_keys()
    reset_metric_keys()
    try:
        partial = frozenset(
            set(metric_universe(PROMPTS)) - {"noise_ratio"}
        )
        with pytest.raises(DecideError):
            load_rules(NOISE_YAML, metric_keys=partial)
    finally:
        reset_metric_keys()
        register_metric_keys(saved)


def test_noise_rule_registered_in_default_rules():
    assert NOISE_YAML in [Path(p) for p in DEFAULT_RULES]
    assert NOISE_YAML.name in [Path(p).name for p in DEFAULT_RULES]


# ---------------------------------------------------------------- A10 双镜像

ROOT = Path(__file__).resolve().parents[2]
CONFIG_YAML = ROOT / "configs" / "rules" / "noise_rules.yaml"


def test_configs_mirror_exists_and_is_byte_identical():
    """A10（design §7）：``configs/rules/`` 是镜像目录，新规则文件必须同步。

    约定同 ``test_color_rules.py:77-81`` / ``test_decide_region_wiring.py:205``：
    镜像缺失即失败，且与包内副本**逐字节一致**（不得手抄漂移）。
    """
    assert CONFIG_YAML.exists(), "configs/rules/noise_rules.yaml 镜像缺失"
    assert CONFIG_YAML.read_bytes() == NOISE_YAML.read_bytes()


# ---------------------------------------------------------------- 验收 ③ 默认关零影响


def _noisy_metrics() -> dict:
    """会命中噪声规则阈值的指标快照（noise_ratio 远高于阈值）。

    额外注入 ``haze_proxy`` / ``shadow_clip_ratio`` 两个既有规则驱动量，
    使「既有判定」非空（否则零影响断言会空转）。
    """
    flat = metrics_for_decide(_measurement({
        "noise_ratio": 0.99,
        "detail_score": 1.0,
    }))
    flat["haze_proxy"] = 0.30          # 驱动既有 dehaze_rule_030 (>=0.22)
    flat["shadow_clip_ratio"] = 0.5    # 驱动既有 shadow_open_rule_032 (>=0.18)
    return flat


def _load_default_rules(with_noise: bool) -> list[dict]:
    universe = metric_universe(PROMPTS)
    paths = [p for p in DEFAULT_RULES if Path(p).name != NOISE_YAML.name]
    if with_noise:
        paths = list(paths) + [NOISE_YAML]
    out: list[dict] = []
    for path in paths:
        out.extend(load_rules(path, metric_keys=universe))
    assert out, "默认规则包加载为空"
    return out


def test_noise_rule_disabled_never_fires():
    rules = [r for r in _load_default_rules(True)
             if r["rule_id"] == NOISE_RULE_ID]
    assert len(rules) == 1 and rules[0]["enabled"] is False
    assert evaluate_rules(rules, _noisy_metrics(), params={}) == []


def test_disabled_noise_rule_does_not_change_any_existing_decision():
    """未开启时**不影响任何既有判定**：± 该规则，求值输出逐条相同。"""
    metrics = _noisy_metrics()
    without = evaluate_rules(_load_default_rules(False), metrics, params={})
    with_noise = evaluate_rules(_load_default_rules(True), metrics, params={})

    def _shape(results):
        return [(r["rule_id"], r["param"], r["value"]) for r in results]

    assert _shape(with_noise) == _shape(without)
    assert NOISE_RULE_ID not in [r["rule_id"] for r in with_noise]
    # 反向护栏：该快照下确有既有规则命中（证明上面的相等不是「双空」）
    assert without, "快照未命中任何既有规则，零影响断言会空转"


def test_noise_rule_fires_only_when_explicitly_enabled():
    """显式开启（enabled=True 覆盖）后规则可命中 —— 证明阈值/条件可判。"""
    rule = dict(_load_default_rules(True)[-1])
    assert rule["rule_id"] == NOISE_RULE_ID
    rule["enabled"] = True
    hits = evaluate_rules([rule], _noisy_metrics(), params={})
    assert [h["rule_id"] for h in hits] == [NOISE_RULE_ID]
    assert hits[0]["param"] == "denoise.luminance_strength"
    assert hits[0]["value"] >= 0.0


# ---------------------------------------------------------------- 验收 ④ 口径留证


def test_noise_rule_documents_full_frame_tier_and_preview_caveat():
    """规则头注必须留证：全幅标定 + 闭环只吃 preview ⇒ 本规则不生效。"""
    text = NOISE_YAML.read_text(encoding="utf-8")
    assert "enabled: false" in text
    assert "全幅" in text
    assert "preview" in text
    assert "1024" in text                       # 生产 preview_long_edge 缺省
    assert "0.2837" in text and "0.6680" in text  # 512 tier 排序非单调实测
    data = yaml.safe_load(text)
    rule = data[0] if isinstance(data, list) else data
    assert rule["enabled"] is False
    assert rule["condition"]["metric"] == "noise_ratio"
