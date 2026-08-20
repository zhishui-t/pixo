"""engine.intents —— EditIntent 编辑模型 + 修图意见解析 (阶段3, T1+T2)。

职责 (软件设计 §2 / 规格 §1):
  - EditIntent dataclass: op/value/scope/semantic (结构化编辑)。
  - apply_intents(params, intents) -> params: 编辑 → 引擎参数覆盖
    (绝对语义直接设值; 相对语义按 步长×值×阻尼(0.7) 在累计值上增减并钳位)。
  - parse_feedback(text) -> list[EditIntent]: 中文修图意见 → 编辑列表
    (规则表驱动, 确定性; 未识别片段抛 UnknownFragment)。

设计约束:
  - 纯函数、无 I/O、无随机 —— 意见序列可位精确回放 (ADR-13/14/16)。
  - 白名单外 op 抛 UnknownOp; 值越界抛 ValueOutOfRange。
  - 本层是结构化中间层: 未来 LLM 调度只需产出 EditIntent 结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

# ────────────────────────────────────────────────────────────────────────────
# 异常
# ────────────────────────────────────────────────────────────────────────────

class UnknownOp(ValueError):
    """白名单外编辑操作。"""


class ValueOutOfRange(ValueError):
    """编辑值越界。"""


class UnknownFragment(ValueError):
    """意见文本含未识别片段 (其余片段照常解析)。"""


# ────────────────────────────────────────────────────────────────────────────
# 白名单与映射
# ────────────────────────────────────────────────────────────────────────────

DAMPING = 0.7  # 相对编辑阻尼 (ADR-14, 防震荡)

# op → (stage, param, 类型, 步长, 值域 (min, max), 说明)
# 类型: "float" 数值参数; "str" 字符串参数 (style/scene 特殊处理)
_OP_TABLE: Dict[str, Tuple[str, str, str, float, Tuple[Optional[float], Optional[float]]]] = {
    "ev":            ("exposure",     "mode",            "float", 0.3,  (-2.5, 2.5)),
    "brightness":    ("tone",         "brightness",      "float", 0.3,  (-2.0, 2.0)),
    "contrast":      ("tone",         "contrast",        "float", 0.05, (0.0, 1.0)),
    "saturation":    ("colorcal",     "saturation",      "float", 0.05, (-1.0, 1.0)),
    "vibrance":      ("colorcal",     "vibrance",        "float", 0.1,  (-1.0, 1.0)),
    "sharpen":       ("refine",       "sharpen",         "float", 0.05, (0.0, 1.0)),
    "skin_strength": ("skin",         "strength",        "float", 0.1,  (0.0, 1.0)),
    "denoise":       ("refine",       "chroma_denoise",  "float", 0.2,  (0.0, 5.0)),
    "highlight":     ("refine",       "highlight_desat", "float", 0.1,  (0.0, 1.0)),
    # Phase 1 新增 (T2.3/T1.5): tone 四键
    "shadows":       ("tone",         "shadows",         "float", 0.1,  (-1.0, 1.0)),
    "highlights":    ("tone",         "highlights",      "float", 0.1,  (-1.0, 1.0)),
    "whites":        ("tone",         "whites",          "float", 0.1,  (-1.0, 1.0)),
    "blacks":        ("tone",         "blacks",          "float", 0.1,  (-1.0, 1.0)),
}

# 字符串类 op (style/scene/wb_temp/tint 特殊映射, 不走 _OP_TABLE)
_STR_OPS = ("style", "scene")

# 色温步长与范围 (wb_temp: rel ±500K/单位; tint: 手动 b 系数微调)
WB_TEMP_STEP = 500.0
WB_TEMP_RANGE = (2500.0, 10000.0)


def _lookup_op(op: str) -> Optional[Tuple[str, str, str, float, Tuple[Optional[float], Optional[float]]]]:
    return _OP_TABLE.get(op)


@dataclass
class EditIntent:
    """结构化修图编辑。

    op       : 白名单操作 (见 _OP_TABLE / style / scene / wb_temp / tint)。
    value    : 数值 (float) 或字符串 (style/scene 的 id)。
    scope    : "global"(默认) | "subject" (主体区; 当前引擎参数为全局, 保留语义)。
    semantic : "rel"(默认, 相对步长×阻尼) | "abs"(绝对设值)。
    """
    op: str
    value: float | str
    scope: str = "global"
    semantic: str = "rel"
    _PHASE1_OPS = ("clarity", "dehaze", "calibration", "hsl", "split_tone", "user_curve")
    _STRUCT_OPS = ("hsl", "split_tone", "calibration", "user_curve")

    def __post_init__(self):
        if self.op not in _OP_TABLE and self.op not in _STR_OPS \
                and self.op not in ("wb_temp", "tint")                 and self.op not in self._PHASE1_OPS:
            raise UnknownOp(f"未知编辑操作: {self.op!r} (可用: "
                            f"{sorted(list(_OP_TABLE) + list(_STR_OPS) + ['wb_temp', 'tint'] + list(self._PHASE1_OPS))})")
        if self.op in _STR_OPS and not isinstance(self.value, str):
            raise ValueOutOfRange(f"{self.op} 需要字符串值, 实得 {self.value!r}")
        if self.op in self._STRUCT_OPS:
            if not isinstance(self.value, (dict, list, tuple)):
                raise ValueOutOfRange(f"{self.op} 需要 dict/list 结构值, 实得 {self.value!r}")
        elif self.op not in _STR_OPS and not isinstance(self.value, (int, float)):
            raise ValueOutOfRange(f"{self.op} 需要数值, 实得 {self.value!r}")
        if self.scope not in ("global", "subject"):
            raise ValueOutOfRange(f"scope 非法: {self.scope!r}")
        if self.semantic not in ("rel", "abs"):
            raise ValueOutOfRange(f"semantic 非法: {self.semantic!r}")


def _clamp(v: float, rng: Tuple[Optional[float], Optional[float]]) -> float:
    lo, hi = rng
    if lo is not None and v < lo:
        return float(lo)
    if hi is not None and v > hi:
        return float(hi)
    return float(v)


def _current_float(params: Dict[str, dict], stage: str, param: str, default: float) -> float:
    """取当前累计参数值 (缺省用 default)。"""
    v = params.get(stage, {}).get(param, default)
    return float(v)


def _wb_from_temp(temp_k: float) -> List[float]:
    """色温 K → 近似相机 WB 系数 [r, g, b] (线性近似, 用于 whitebalance 手动 mode)。

    采用 Tanner Helland 式反演的标准近似 (系数针对 gamma 域标定, 此处仅作
    手动微调的工程近似, 误差在观感步长内); 保证单调、端点合理。
    """
    t = _clamp(temp_k, WB_TEMP_RANGE) / 100.0
    if t <= 66:
        r = 255.0
    else:
        r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
    r = _clamp(r, (0.0, 255.0))
    if t <= 66:
        g = 99.4708025861 * np_log(t) - 161.1195681661 if t > 0 else 0.0
    else:
        g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
    g = _clamp(g, (0.0, 255.0))
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * np_log(t - 10.0) - 305.0447927307
    b = _clamp(b, (0.0, 255.0))
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    g = max(g, 1e-6)
    return [float(r / g), 1.0, float(b / g)]


def np_log(x: float) -> float:
    import math
    return math.log(max(x, 1e-9))


def _apply_wb_temp(params: Dict[str, dict], value: float, semantic: str) -> Dict[str, dict]:
    """wb_temp 映射: 设置 WhiteBalanceStage mode=manual + temp (abs 或 rel 步长)。"""
    cur = _current_float(params, "whitebalance", "_temp", 6500.0)
    if semantic == "abs":
        temp = float(value)
    else:
        temp = cur + value * WB_TEMP_STEP
    temp = _clamp(temp, WB_TEMP_RANGE)
    wb = params.setdefault("whitebalance", {})
    wb["mode"] = "manual"
    wb["temp"] = temp
    wb["_temp"] = temp  # 会话内部累计值 (非引擎参数)
    return params


def _apply_tint(params: Dict[str, dict], value: float, semantic: str) -> Dict[str, dict]:
    """tint 映射: 设置 WhiteBalanceStage mode=manual + tint (abs 或 rel 步长 5)。"""
    cur = _current_float(params, "whitebalance", "_tint", 0.0)
    if semantic == "abs":
        tint = float(value)
    else:
        tint = cur + value * 5.0  # 步长 5 (tint 单位)
    tint = _clamp(tint, (-150.0, 150.0))
    wb = params.setdefault("whitebalance", {})
    wb["mode"] = "manual"
    wb["tint"] = tint
    wb["_tint"] = tint
    return params


def apply_intents(params: Dict[str, dict], intents: List[EditIntent]) -> Dict[str, dict]:
    """把编辑列表合并进引擎参数 (返回新 dict, 不改入参)。

    - abs: 直接设值 (数值类钳位到值域; str 类直接设)。
    - rel: 在累计值上按 步长 × value × DAMPING 增减并钳位。
    """
    out: Dict[str, dict] = {k: dict(v) for k, v in (params or {}).items()}
    for it in intents:
        # Phase 1 特判: 需 enabled=True + 多参的 Stage (数值/JSON dict / list)
        if it.op == "user_curve":
            out.setdefault("tone", {})["user_curve"] = (
                it.value if isinstance(it.value, (list, tuple, dict))
                else str(it.value))
            continue
        if it.op == "clarity":
            st = out.setdefault("clarity", {}); st["enabled"] = True
            st["strength"] = _clamp(float(it.value), (0.0, 1.0)); continue
        if it.op == "dehaze":
            st = out.setdefault("dehaze", {}); st["enabled"] = True
            st["strength"] = _clamp(float(it.value), (0.0, 1.0)); continue
        if it.op == "calibration":
            st = out.setdefault("calibration", {}); st["enabled"] = True
            if isinstance(it.value, dict):
                for k, v in it.value.items():
                    if k in ("shadow_tint", "red_hue", "red_sat", "green_hue",
                             "green_sat", "blue_hue", "blue_sat"):
                        st[k] = float(v)
            else:
                st["shadow_tint"] = _clamp(float(it.value), (-1.0, 1.0))
            continue
        if it.op == "hsl":
            st = out.setdefault("hsl", {}); st["enabled"] = True
            if isinstance(it.value, dict):
                st["bands"] = it.value
            continue
        if it.op == "split_tone":
            st = out.setdefault("split_tone", {}); st["enabled"] = True
            if isinstance(it.value, dict):
                for k in ("shadows_hue", "shadows_sat", "highlights_hue",
                          "highlights_sat", "balance", "strength"):
                    if k in it.value:
                        st[k] = float(it.value[k])
            continue
        if it.op == "wb_temp":
            out = _apply_wb_temp(out, float(it.value), it.semantic)
            continue
        if it.op == "tint":
            out = _apply_tint(out, float(it.value), it.semantic)
            continue
        if it.op == "style":
            out.setdefault("stylize", {})["lut_path"] = str(it.value)
            continue
        if it.op == "scene":
            from .scene_apply import apply_scene_preset
            sp, lut = apply_scene_preset(str(it.value))
            for st, kv in sp.items():
                out.setdefault(st, {}).update(kv)
            if lut:
                out.setdefault("stylize", {})["lut_path"] = lut
            out.setdefault("__meta__", {})["scene"] = str(it.value)
            continue

        stage, param, typ, step, rng = _lookup_op(it.op)
        if it.semantic == "abs":
            v = float(it.value)
        else:
            cur = _current_float(out, stage, param, 0.0)
            v = cur + float(it.value) * step * DAMPING
        out.setdefault(stage, {})[param] = _clamp(v, rng)
    return out


# ────────────────────────────────────────────────────────────────────────────
# 修图意见解析 (规则表驱动, 确定性)
# ────────────────────────────────────────────────────────────────────────────

_DEGREES = [("很", 2.0), ("非常", 2.0), ("特别", 2.0), ("太", 2.0), ("过于", 2.0),
            ("再多", 1.5), ("多点", 1.5), ("再", 1.5),
            ("一点", 1.0), ("稍微", 1.0), ("稍稍", 1.0), ("些", 1.0)]

# 意见规则: (关键词正则, op, 方向符号或 scene/style id, 是否需要程度词匹配)
# 正则用 finditer 顺序匹配; 方向 +1 = 增大 (更亮/更饱和/更锐/更暖=色温低) 等。
_RULES: List[Tuple[str, str, float | str]] = [
    # 曝光/亮度
    (r"更亮|亮一点|亮些|提亮", "ev", +1.0),
    (r"暗一点|暗些|压暗|更暗", "ev", -1.0),
    (r"曝光加|曝光\+", "ev", +1.0),
    (r"曝光减|曝光\-", "ev", -1.0),
    # 色温/色调
    (r"暖一点|更暖|暖些", "wb_temp", -1.0),   # 暖 = 降低色温 K
    (r"冷一点|更冷|冷些", "wb_temp", +1.0),   # 冷 = 升高色温 K
    (r"色温低|色温降", "wb_temp", -1.0),
    (r"色温高|色温升", "wb_temp", +1.0),
    (r"偏绿", "tint", -1.0),
    (r"偏品|偏紫|偏洋红", "tint", +1.0),
    # 色彩
    (r"饱和一点|更饱和|饱和些|鲜艳一点", "saturation", +1.0),
    (r"清淡一点|更清淡|去饱和|饱和度低", "saturation", -1.0),
    (r"自然饱和|通透一点|鲜活", "vibrance", +1.0),
    # 细节
    (r"锐一点|更锐|锐化", "sharpen", +1.0),
    (r"柔一点|更柔|柔和一点", "sharpen", -1.0),
    (r"磨皮|皮肤光滑|美颜", "skin_strength", +1.0),
    (r"降噪|去噪|噪点少", "denoise", +1.0),
    # 影调
    (r"对比高|对比强|对比大", "contrast", +1.0),
    (r"提亮暗部|阴影提亮|暗部提亮", "shadows", +1.0),
    (r"压暗暗部|阴影压暗", "shadows", -1.0),
    (r"提亮高光", "highlights", +1.0),
    (r"压暗高光|高光回收", "highlights", -1.0),
    (r"提白|白色提升", "whites", +1.0),
    (r"加黑|黑色加深", "blacks", -1.0),
    (r"清晰度|更清晰", "clarity", +1.0),
    (r"去雾|除雾|更通透", "dehaze", +1.0),
    (r"对比低|对比弱|柔和对比", "contrast", -1.0),
    (r"高光压|高光降|高光回收", "highlight", +1.0),
    # 场景 / 风格
    (r"人像|肖像", "scene", "portrait"),
    (r"风光|风景|户外", "scene", "landscape"),
    (r"夜景|夜晚", "scene", "night"),
    (r"街拍|街头|人文", "scene", "street"),
    (r"美食|食物", "scene", "food"),
    (r"黑白|单色", "scene", "mono"),
    (r"velvia|维尔维亚", "style", "velvia"),
    (r"classic[_ ]?neg|经典负片", "style", "classic_neg"),
    (r"astia|阿斯蒂亚", "style", "astia"),
    # 兜底裸词 (须排在具体规则之后; 注意排除误匹配)
    (r"(?<!漂)亮", "ev", +1.0),
    (r"暗", "ev", -1.0),
    (r"暖", "wb_temp", -1.0),
    (r"冷", "wb_temp", +1.0),
    (r"饱和", "saturation", +1.0),
    (r"清淡", "saturation", -1.0),
    (r"锐", "sharpen", +1.0),
    (r"柔", "sharpen", -1.0),
    (r"对比", "contrast", +1.0),
    (r"磨皮|美颜", "skin_strength", +1.0),
    (r"降噪|去噪", "denoise", +1.0),
]

_STYLE_OPS = {"style", "scene"}


def _split_sentences(text: str) -> List[str]:
    """按中文逗号/分号/句号切分意见片段 (保留原文位置用于报错)。"""
    return [s.strip() for s in re.split(r"[，,;；。.!！\n]", text) if s.strip()]


def _degree_for(seg: str) -> float:
    """片段内程度词 → 倍率 (乘法合成: "再亮一点" = 1.5×1.0; 上限 3.0)。"""
    deg = 1.0
    for kw, d in sorted(_DEGREES, key=lambda kv: -len(kv[0])):
        if kw in seg:
            deg *= d
    return min(deg, 3.0)


def parse_feedback(text: str) -> List[EditIntent]:
    """中文修图意见 → EditIntent 列表 (规则表驱动, 确定性)。

    支持同句多条 (逗号/句号分隔)。未识别片段抛 UnknownFragment (已识别
    片段照常返回, 由调用方决定是否继续)。
    """
    intents: List[EditIntent] = []
    unknown: List[str] = []
    for seg in _split_sentences(text):
        matched = False
        for pattern, op, sign in _RULES:
            if re.search(pattern, seg):
                deg = _degree_for(seg)
                if op in _STYLE_OPS:
                    intents.append(EditIntent(op=op, value=sign, semantic="abs"))
                else:
                    intents.append(EditIntent(op=op, value=float(sign) * deg,
                                              semantic="rel"))
                matched = True
                break
        if not matched:
            unknown.append(seg)
    if unknown:
        raise UnknownFragment(f"未识别的修图意见片段: {unknown}")
    return intents

__all__ = ["UnknownOp", "ValueOutOfRange", "UnknownFragment", "EditIntent",
           "apply_intents", "parse_feedback", "DAMPING"]
