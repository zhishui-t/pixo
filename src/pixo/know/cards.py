"""pixo.know.cards —— 风格卡片 schema 与 Decide 建议规则。

风格卡片结构对齐 docs/架构设计文档.md §10.2：
  style_id / tags / color_fingerprint / tone_fingerprint /
  known_issues / recommended_adjustments。

与 Decide 的优先级约定：
  - 风格卡片生成规则使用 level="style_card"（权重 6000）；
  - 用户锁定（10000）与用户软偏好（9000）始终高于风格卡片；
  - 硬规则/系统默认（3000）低于风格卡片。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

_STYLE_CARD_PRIORITY = 6000.0


@dataclass
class StyleCard:
    """一张风格卡片。"""

    style_id: str
    name: str = ""
    tags: dict[str, list[str]] = field(default_factory=dict)
    color_fingerprint: dict[str, Any] = field(default_factory=dict)
    tone_fingerprint: dict[str, Any] = field(default_factory=dict)
    known_issues: list[str] = field(default_factory=list)
    recommended_adjustments: dict[str, Any] = field(default_factory=dict)
    source: str = "builtin"

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 友好 dict。"""
        return {
            "style_id": self.style_id,
            "name": self.name,
            "tags": dict(self.tags),
            "color_fingerprint": dict(self.color_fingerprint),
            "tone_fingerprint": dict(self.tone_fingerprint),
            "known_issues": list(self.known_issues),
            "recommended_adjustments": dict(self.recommended_adjustments),
            "source": self.source,
        }

    def __getitem__(self, key: str) -> Any:
        """支持 card["style_id"] 式访问。"""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """dict 风格 get。"""
        return getattr(self, key, default)


def style_card_from_dict(data: Mapping[str, Any]) -> StyleCard:
    """从 dict 构造 StyleCard。"""
    return StyleCard(
        style_id=str(data.get("style_id", "")),
        name=str(data.get("name", "")),
        tags=dict(data.get("tags") or {}),
        color_fingerprint=dict(data.get("color_fingerprint") or {}),
        tone_fingerprint=dict(data.get("tone_fingerprint") or {}),
        known_issues=list(data.get("known_issues") or []),
        recommended_adjustments=dict(data.get("recommended_adjustments") or {}),
        source=str(data.get("source", "builtin")),
    )


def style_card_to_dict(card: StyleCard | Mapping[str, Any]) -> dict[str, Any]:
    """把 StyleCard 或 dict 统一转为标准 dict。"""
    if isinstance(card, StyleCard):
        return card.to_dict()
    return dict(card)


# 默认风格卡片，先按文档示例落地一张柯达 Portra，并补一张富士 Pro 系。
DEFAULT_STYLE_CARDS: list[dict[str, Any]] = [
    {
        "style_id": "kodak_portra_400",
        "name": "Kodak Portra 400",
        "tags": {
            "scene": ["outdoor", "portrait", "wedding"],
            "light": ["golden_hour", "soft_light"],
            "skin_tone": ["warm_pink"],
        },
        "color_fingerprint": {
            "skin_lab_target": {"a": 18, "b": 20},
            "sky_lab_target": {"a": -2, "b": -8},
        },
        "tone_fingerprint": {
            "contrast_tendency": "low",
            "highlight_rolloff": "soft",
            "shadow_depth": "open",
        },
        "known_issues": ["逆光下肤色容易偏黄"],
        "recommended_adjustments": {
            "if_skin_b_gt_22": "hue_orange_shift_-3",
            "if_highlight_clip_ratio_gt_0.03": "exposure_-0.15",
        },
        "source": "builtin",
    },
    {
        "style_id": "fuji_pro_400h",
        "name": "Fuji Pro 400H",
        "tags": {
            "scene": ["outdoor", "portrait", "landscape"],
            "light": ["soft_light", "overcast"],
            "skin_tone": ["neutral_clean"],
        },
        "color_fingerprint": {
            "skin_lab_target": {"a": 14, "b": 16},
            "sky_lab_target": {"a": -4, "b": -10},
        },
        "tone_fingerprint": {
            "contrast_tendency": "medium",
            "highlight_rolloff": "soft",
            "shadow_depth": "airy",
        },
        "known_issues": ["阴天画面容易偏灰"],
        "recommended_adjustments": {
            "if_contrast_lt_0.15": "contrast_0.05",
        },
        "source": "builtin",
    },
]


def _parse_if_condition(key: str) -> dict[str, Any] | None:
    """解析 ``if_皮肤b_gt_22`` 形式的条件键。"""
    match = re.match(
        r"^if_(.+?)_(gt|ge|lt|le|eq)_(-?\d+(?:\.\d+)?)$", key
    )
    if not match:
        return None
    metric = match.group(1)
    op = {
        "gt": ">",
        "ge": ">=",
        "lt": "<",
        "le": "<=",
        "eq": "==",
    }[match.group(2)]
    value = float(match.group(3))
    # 将下划线指标转为 Decide 可读 metric（保留下划线）。
    return {"metric": metric, "op": op, "value": value}


def _parse_action(value: Any) -> dict[str, Any]:
    """把建议值转换为 {param, value}。"""
    if isinstance(value, dict):
        param = value.get("param")
        val = value.get("value", value.get("amount", 0))
        return {"param": str(param or "value"), "value": float(val)}
    text = str(value)
    match = re.match(r"^(.+?)_(-?\d+(?:\.\d+)?)$", text)
    if match:
        return {"param": match.group(1), "value": float(match.group(2))}
    return {"param": text, "value": 1.0}


def style_card_to_decide_rules(card: StyleCard | Mapping[str, Any]) -> list[dict[str, Any]]:
    """把风格卡片建议转换为 Decide 规则。

    生成规则带 ``level="style_card"`` / ``priority=6000``，
    因此不会覆盖用户锁定（10000）与用户软偏好（9000）。
    """
    data = style_card_to_dict(card)
    style_id = str(data.get("style_id", "style"))
    recommended = data.get("recommended_adjustments") or {}
    rules: list[dict[str, Any]] = []
    if not isinstance(recommended, dict):
        return rules

    for key, raw_action in recommended.items():
        rule: dict[str, Any] = {
            "rule_id": f"{style_id}_{key}",
            "priority": _STYLE_CARD_PRIORITY,
            "level": "style_card",
            "source": "style_card",
            "reason": f"风格卡片 {style_id} 建议：{key}",
            "action": _parse_action(raw_action),
        }
        condition = _parse_if_condition(str(key))
        if condition is not None:
            rule["condition"] = condition
        rules.append(rule)
    return rules


def load_style_cards(source: Any | None = None) -> list[StyleCard]:
    """加载风格卡片。

    source 为 None 时加载内置卡片；为路径时加载 JSON；
    否则按 dict/list 解析。
    """
    if source is None:
        raw_items = DEFAULT_STYLE_CARDS
    elif isinstance(source, (str, Path)):
        path = Path(source)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            raw_items = data.get("style_cards") or data.get("cards")
            if raw_items is None and "style_id" in data:
                raw_items = [data]
            else:
                raw_items = raw_items or []
        else:
            raw_items = data
    elif isinstance(source, (dict, StyleCard)):
        raw_items = [source]
    else:
        raw_items = source

    cards: list[StyleCard] = []
    for item in raw_items or []:
        if isinstance(item, StyleCard):
            item = item.to_dict()
        if not isinstance(item, dict):
            continue
        cards.append(style_card_from_dict(item))
    return cards


def load_style_card_dicts(source: Any | None = None) -> list[dict[str, Any]]:
    """直接返回 dict 风格卡片列表（兼容 JSON 消费方）。"""
    return [c.to_dict() for c in load_style_cards(source)]


def build_style_card_rules(
    cards: StyleCard | Mapping[str, Any] | Iterable[StyleCard | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """合并多张风格卡片为 Decide 规则列表。"""
    if isinstance(cards, (StyleCard, dict)):
        cards = [cards]
    rules: list[dict[str, Any]] = []
    for card in cards:
        rules.extend(style_card_to_decide_rules(card))
    return rules


__all__ = [
    "StyleCard",
    "DEFAULT_STYLE_CARDS",
    "style_card_from_dict",
    "style_card_to_dict",
    "style_card_to_decide_rules",
    "load_style_cards",
    "load_style_card_dicts",
    "build_style_card_rules",
]
