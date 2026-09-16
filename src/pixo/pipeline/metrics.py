"""pixo.pipeline.metrics —— 规则引擎指标口径公共 API（F03, R21；R22/F01 扩键）。

本模块是「完整测量报告 → 规则引擎可引用的扁平指标」的**单一来源**：
loop 侧（``_metrics_for_decide``）与 service 侧装配共用同一实现，消除
「指标嵌在 measurement 的 ``global`` / ``regions`` 下、规则 condition /
formula 取不到」这一 decide 零触发成因（task-brief 成因①）。

R22/F01（CR-06）增量：把 4 层路径
``measurement["global"]["detail"]["sharpness"][noise_ratio|detail_score]``
展平为扁平键并加入 :data:`METRIC_KEYS`（口径见 :data:`SHARPNESS_METRIC_KEYS`
注释：噪声/细节类指标只用导出全幅标定）。

架构约束（task-brief 架构红线；exploration-r21 §6.5）：
本模块属 ``pixo.pipeline`` 库层，**不得** import ``pixo.service``——依赖方向
恒为 service → pipeline。本模块只依赖 ``pixo.vision.measure``（纯 numpy 代理
指标），不引入 torch 级重依赖。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# 与 loop 侧同源：compute_proxy_metrics 未在 pixo.vision.__init__ re-export，
# 只能从 pixo.vision.measure 直接导入（measure.py __all__ 内含）。
from pixo.vision.measure import compute_proxy_metrics

# 顶层代理指标键（measurement 直出，落在 measurement 顶层而非 global 下）。
PROXY_METRIC_KEYS: tuple[str, str, str] = (
    "haze_proxy",
    "colorfulness_proxy",
    "tonal_range",
)

# 区域 flatten 键后缀：<prompt>_{suffix}。
REGION_METRIC_SUFFIXES: tuple[str, str, str, str] = (
    "luminance",
    "area_ratio",
    "highlight_clip_ratio",
    "reliable",
)

# R22/F01（CR-06）锐度/噪声展平键 —— 来源层级固定为 **4 层**：
# ``measurement["global"]["detail"]["sharpness"][<key>]``
# （``vision/measure.py:549-553`` 由 ``VisionMeasure.measure`` 组装；
# ``measure_sharpness`` 产出 noise_ratio/detail_score/...）。
# **口径**（design-r22 §2.1 裁决③）：噪声/细节类指标强分辨率依赖
# （512 tier 下 noise_ratio 排序非单调：ISO12800 0.2837 < ISO1600 0.6680）
# ⇒ 阈值类消费一律只用导出全幅（``final_measurement``）。
SHARPNESS_METRIC_KEYS: tuple[str, str] = ("noise_ratio", "detail_score")

# flatten **固定键**（对齐 loop.py:761-770 注册面）：6 个 global 键 +
# 3 个顶层代理键 + "crop_suggestion_applicable" + R22/F01 的 2 个锐度键。
# **不含区域键**。
METRIC_KEYS: frozenset[str] = frozenset(
    {
        # measurement["global"] / 顶层测量键（metrics_for_decide 固定键）
        "mean_luminance",
        "highlight_clip_ratio",
        "shadow_clip_ratio",
        "contrast",
        "preview_highlight_clip_estimate",
        "preview_overflow_ratio",
        # 顶层代理指标（measurement 直出）
        "haze_proxy",
        "colorfulness_proxy",
        "tonal_range",
        # loop 上下文指标（crop 建议链）
        "crop_suggestion_applicable",
        # R22/F01：global.detail.sharpness 4 层展平（噪声/细节）
        "noise_ratio",
        "detail_score",
    }
)


def metrics_for_decide(measurement: Mapping[str, Any]) -> dict[str, Any]:
    """完整测量报告 → 规则引擎可引用的扁平指标 dict。

    产出键 = 原 ``loop._metrics_for_decide``（loop.py:521-551）全部键：

    - ``measurement["global"]`` 的 6 键：``mean_luminance`` /
      ``highlight_clip_ratio`` / ``shadow_clip_ratio`` / ``contrast`` /
      ``preview_highlight_clip_estimate`` / ``preview_overflow_ratio``
      （末两键同源 preview_highlight_clip_estimate）；
    - 顶层代理键 ``haze_proxy`` / ``colorfulness_proxy`` / ``tonal_range``
      —— **仅当 measurement 顶层存在时**才产出（缺省不写空键）；
    - R22/F01 锐度/噪声键 ``noise_ratio`` / ``detail_score`` —— 取自
      **4 层路径** ``measurement["global"]["detail"]["sharpness"]``，
      **仅当该层存在（且含对应键）时才产出**（与代理键同款「缺省不写空键」
      语义：规则侧「键缺席」与「值为 None」都走引擎的静默不触发，
      exploration-r22 §2.2 #1 的缺失语义二选一取此支）；
    - 各 region 的 ``{name}_{luminance,area_ratio,highlight_clip_ratio,reliable}``
      （``reliable`` 恒为 ``bool``）。

    非 Mapping 输入返回 ``{}``（与库层旧行为一致，防御非法调用）。
    """
    if not isinstance(measurement, Mapping):
        return {}
    global_metrics = measurement.get("global") or {}
    regions = measurement.get("regions") or {}
    metrics: dict[str, Any] = {
        "mean_luminance": global_metrics.get("mean_luminance"),
        "highlight_clip_ratio": global_metrics.get("highlight_clip_ratio"),
        "shadow_clip_ratio": global_metrics.get("shadow_clip_ratio"),
        "contrast": global_metrics.get("contrast"),
        "preview_highlight_clip_estimate": global_metrics.get(
            "preview_highlight_clip_estimate"
        ),
        "preview_overflow_ratio": global_metrics.get(
            "preview_highlight_clip_estimate"
        ),
    }
    detail = global_metrics.get("detail")
    sharpness = detail.get("sharpness") if isinstance(detail, Mapping) else None
    if isinstance(sharpness, Mapping):
        for key in SHARPNESS_METRIC_KEYS:
            if key in sharpness:
                metrics[key] = sharpness[key]
    for key in PROXY_METRIC_KEYS:
        if key in measurement:
            metrics[key] = measurement[key]
    for name, region in regions.items():
        if not isinstance(region, Mapping):
            continue
        metrics[f"{name}_luminance"] = region.get("mean_luminance")
        metrics[f"{name}_area_ratio"] = region.get("area_ratio")
        metrics[f"{name}_highlight_clip_ratio"] = region.get(
            "highlight_clip_ratio"
        )
        metrics[f"{name}_reliable"] = bool(region.get("reliable", False))
    return metrics


def metric_universe(
    prompts: Sequence[str] = ("face", "sky", "plant"),
) -> frozenset[str]:
    """lint / 装配专用完整键宇宙 = ``METRIC_KEYS`` ∪ 区域 flatten 键。

    区域键（``{p}_{luminance,area_ratio,highlight_clip_ratio,reliable}``）被
    ``src/pixo/decide/rules/region_rules.yaml`` 的 condition 与 formula
    **同时引用**（``sky_luminance`` / ``plant_luminance`` 等）——只传
    ``METRIC_KEYS`` 会让 ``load_rules`` 抛 ``DecideError``。

    必须**显式传**给 ``load_rules(..., metric_keys=metric_universe(...))``：
    ``register_metric_keys`` 是 loop 构造期的全局 set 副作用（loop.py:783），
    lint 松紧取决于 load_rules 与 loop 构造的先后（exploration-r21 §6.8）。
    """
    universe = set(METRIC_KEYS)
    for prompt in prompts:
        for suffix in REGION_METRIC_SUFFIXES:
            universe.add(f"{prompt}_{suffix}")
    return frozenset(universe)


def merge_proxy_metrics(
    measurement: dict[str, Any],
    image_rgb: Any,
) -> dict[str, Any]:
    """把 ``compute_proxy_metrics(image_rgb)`` 的顶层键合并进 measurement。

    合并层级必须是 measurement **顶层**（与 loop.py:1352-1354 /
    :1730-1732 同层）：``metrics_for_decide`` 用 ``if key in measurement``
    读代理键，嵌进 ``measurement["global"]`` 取不到（exploration-r21 §0.1
    分离证明：展平但无 proxies ⇒ 规则零触发）。

    原地 + 返回同一对象；``image_rgb`` 非法（None / 非三通道 / 空图）时
    ``compute_proxy_metrics`` 返回空 dict，此处不改动 measurement。
    """
    proxies = compute_proxy_metrics(image_rgb)
    if proxies and isinstance(measurement, dict):
        measurement.update(proxies)
    return measurement


__all__ = [
    "METRIC_KEYS",
    "PROXY_METRIC_KEYS",
    "REGION_METRIC_SUFFIXES",
    "SHARPNESS_METRIC_KEYS",
    "metrics_for_decide",
    "metric_universe",
    "merge_proxy_metrics",
]
