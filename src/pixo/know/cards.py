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
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

_STYLE_CARD_PRIORITY = 6000.0

_LOGGER = logging.getLogger(__name__)

# 胶片卡目录（cwd 相对，与 registry 的 configs/knowledge 约定一致）。
FILMS_DIR = Path("configs") / "styles" / "films"

# metadata 字段缺省值：family 必有落点，前端分组永不悬空。
_FILM_METADATA_DEFAULTS: dict[str, Any] = {
    "family": "uncategorized",
    "label": "",
    "tags": [],
    "scenes": [],
    "character": "",
    "year": None,
}


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

    @classmethod
    def from_films_dir(cls, directory: str | Path | None = None) -> list[dict[str, Any]]:
        """扫描胶片卡目录（t86 LUT 库骨架），返回完整卡 dict 列表。

        卡 schema = 渲染卡 ``{stages,params,output}`` + 元数据节
        ``metadata:{family,label,tags,scenes,character,year}``；渲染管线
        ``pipeline_from_config`` 只读前三键，metadata 为未知键自然忽略。

        行为约定：
        - 目录不存在或为空 → 返回 ``[]``（不崩）；
        - 坏 JSON / 缺 ``stages`` 的文件跳过并 warning；
        - ``style_id`` 取文件名 stem；metadata 缺失字段补缺省
          （family 缺省 "uncategorized"，label 缺省文件名），前端分组
          永有落点。
        """
        d = Path(directory) if directory is not None else FILMS_DIR
        if not d.is_dir():
            return []
        cards: list[dict[str, Any]] = []
        for fp in sorted(d.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                _LOGGER.warning("[films] 跳过坏卡 %s: %s", fp.name, exc)
                continue
            if not isinstance(data, dict) or not data.get("stages"):
                _LOGGER.warning("[films] 跳过非卡文件 %s（缺 stages）", fp.name)
                continue
            meta = dict(_FILM_METADATA_DEFAULTS)
            meta.update(data.get("metadata") or {})
            meta["label"] = meta["label"] or fp.stem
            cards.append({"style_id": fp.stem, **data, "metadata": meta})
        return cards


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
    {
        # t89 LUT 卡：哈苏 XCD 自然色彩方案（NCS）——暖黄高光/冷蓝阴影
        # 的经典 split-tone，整体克制低饱和。
        "style_id": "hasselblad_ncs",
        "name": "Hasselblad NCS",
        "tags": {
            "scene": ["portrait", "landscape", "studio"],
            "light": ["soft_light", "studio", "window_light"],
            "skin_tone": ["natural_warm"],
        },
        "color_fingerprint": {
            "skin_lab_target": {"a": 16, "b": 18},
            "sky_lab_target": {"a": -5, "b": -12},
            "highlight_tint_lab": {"a": 4, "b": 14},
            "shadow_tint_lab": {"a": -3, "b": -14},
        },
        "tone_fingerprint": {
            "contrast_tendency": "low",
            "highlight_rolloff": "smooth",
            "shadow_depth": "cool_open",
        },
        "known_issues": ["混合光下黄蓝分离易过强，需降 split-tone 强度"],
        "recommended_adjustments": {
            "if_highlight_b_gt_20": "split_tone_yellow_-4",
            "if_shadow_b_lt_-18": "split_tone_blue_-3",
            "if_saturation_gt_0.45": "vibrance_-0.10",
        },
        "source": "builtin",
    },
    {
        # t89 LUT 卡：CineStill 800T——钨丝平衡片用于夜景霓虹，青蓝罩
        # 染 + 高光红色 halation（此处以高光染色代理，非光学仿真）。
        "style_id": "cinestill_800t",
        "name": "CineStill 800T",
        "tags": {
            "scene": ["night", "street", "neon"],
            "light": ["tungsten", "night_light", "mixed_light"],
            "mood": ["cinematic"],
        },
        "color_fingerprint": {
            "highlight_tint_lab": {"a": 8, "b": -16},
            "shadow_tint_lab": {"a": -2, "b": -8},
            "halation_proxy": {"hue_deg": 15, "strength_hint": 0.35},
        },
        "tone_fingerprint": {
            "contrast_tendency": "medium_high",
            "highlight_rolloff": "halation_soft",
            "shadow_depth": "deep_cool",
        },
        "known_issues": [
            "钨丝场景整体偏青需 WB 补偿",
            "halation 为代理近似非光学仿真，强逆光下慎加",
        ],
        "recommended_adjustments": {
            "if_night_neon": "temp_-200_tint_+6",
            "if_highlight_clip_ratio_gt_0.05": "halation_glow_+0.15",
            "if_skin_too_cyan": "temp_+150",
        },
        "source": "builtin",
    },
    {
        # t89 LUT 卡：Kodak TriX 400——经典黑白，粗颗粒、强反差、
        # 红镜滤镜天空压暗惯例。
        "style_id": "kodak_trix_400",
        "name": "Kodak TriX 400",
        "tags": {
            "scene": ["street", "documentary", "reportage"],
            "light": ["hard_light", "high_contrast"],
            "palette": ["monochrome"],
        },
        "color_fingerprint": {
            "monochrome": True,
            "grain_character": "coarse_400",
            "channel_mix_hint": "red_filter_sky_darken",
        },
        "tone_fingerprint": {
            "contrast_tendency": "strong",
            "highlight_rolloff": "bright",
            "shadow_depth": "deep",
        },
        "known_issues": [
            "高ISO 颗粒放大后需与降噪平衡",
            "彩转黑通道混合决定整体反差走向",
        ],
        "recommended_adjustments": {
            "if_monochrome": "bw_mix_red_filter_+0.3",
            "if_grain_visible_lt_0.2": "grain_+0.25",
            "if_sky_flat": "contrast_+0.15",
        },
        "source": "builtin",
    },
    {
        # t89 LUT 卡：Ilford HP5 Plus——黑白纪实高宽容，阴影开放不易
        # 死黑，中粒度，平淡光下需局部反差补救。
        "style_id": "ilford_hp5_plus",
        "name": "Ilford HP5 Plus",
        "tags": {
            "scene": ["documentary", "street", "photojournalism"],
            "light": ["available_light", "overcast", "flat_light"],
            "palette": ["monochrome"],
        },
        "color_fingerprint": {
            "monochrome": True,
            "grain_character": "moderate_400",
            "latitude_stops_hint": 6,
        },
        "tone_fingerprint": {
            "contrast_tendency": "medium",
            "highlight_rolloff": "long_linear",
            "shadow_depth": "open_forgiving",
        },
        "known_issues": [
            "宽容度大易出平淡灰调，需局部反差找回层次",
            "dmax 略低于 TriX，深黑密度不足时用曲线补",
        ],
        "recommended_adjustments": {
            "if_flat_light": "local_contrast_+0.20",
            "if_shadow_muddy": "shadow_lift_+0.10",
            "if_dmax_insufficient": "curve toe_-0.06",
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
