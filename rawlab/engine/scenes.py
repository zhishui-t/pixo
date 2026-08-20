"""engine.scenes —— 场景分类器 (阶段2, T3)。

职责 (软件设计 §2 / 规格 §1):
  - 纯函数 (无 I/O, 无全局状态): classify_scene(rgb8, vision_report=None,
    subjects=None) -> (scene_id, confidence)。
  - 特征 = 确定性 CV 统计 (亮度中位/对比度 std/直方形态/天空/绿植/肤色/
    主体占比/彩色占比/暖色相占比), 全部由 rgb8 直接计算;
    vision_report / subjects 只补充深度学习侧信息 (persons 数、主体框)。
  - 分类 = 固定优先级规则链 (阈值模块级常量, 可调):
        portrait → night → landscape → food → mono → street
  - confidence = 命中规则的命中度 (0..1); 无规则命中 → street。

输入约定:
  - rgb8: 8bit RGB (uint8, HxWx3)。float 输入会被钳位量化到 0..255。
  - vision_report: build_vision_report 的输出 dict (可选, 取 subject.persons)。
  - subjects: 归一化 [l, t, r, b] 框列表, 或含 items/persons 的 dict (可选)。

引用: rawlab/vision_report.py 的 skin/sky/green 掩码写法 (此处由 BGR 域改为
RGB 域并核对 Lab 椭圆参数)。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# 可调阈值 (规则门限; 比例为 0..1, 亮度为 0..255)
# ═══════════════════════════════════════════════════════════════════════════
SKIN_RATIO_MIN = 0.03      # portrait: 肤色占比下限 (>3%)
NIGHT_BRIGHT_MAX = 60.0    # night: 亮度中位上限 (<60)
NIGHT_DARK_MIN = 0.30      # night: 暗区占比下限 (>30%)
LANDSCAPE_MIN = 0.20       # landscape: 绿植或天空占比下限 (>20%)
FOOD_SUBJ_MIN = 0.20       # food: 主体占比下限 (≥20%)
FOOD_SUBJ_MAX = 0.60       # food: 主体占比上限 (≤60%)
FOOD_WARM_MIN = 0.25       # food: 暖色相占比下限
MONO_COLOR_MAX = 0.10      # mono: 彩色占比上限 (≤10%)
MONO_COLOR_REF = 0.20      # mono: 置信度标尺 (彩色占比 ≥20% → 置信度 0)

# 暗区/亮区直方形态阈值 (亮度 0..255)
DARK_LEVEL = 60            # 暗区: gray < 60
BRIGHT_LEVEL = 200         # 亮区: gray > 200

# 掩码判据 (与 vision_report.py 同风格, RGB 域)
SKY_MIN_BLUE = 80          # 天空: 蓝色通道下限
GREEN_MIN = 45             # 绿植: 绿色通道下限
SAT_COLOR_MIN = 30         # 彩色: HSV 饱和度下限 (0..255)
WARM_HUE_MAX = 40          # 暖色相: HSV 色相 (0..180) ≤40 (红~黄)
WARM_HUE_MIN = 150         # 暖色相: ≥150 (品红~红)
WARM_VAL_MIN = 40          # 暖色: HSV 明度下限 (排除近黑)

# 肤色椭圆 (规格 §2.2): Lab 中心 (a=140, b=150), 主轴 22, 副轴 14, 倾角 0.65 rad
SKIN_LAB_A, SKIN_LAB_B = 140.0, 150.0
SKIN_MAJOR, SKIN_MINOR = 22.0, 14.0
SKIN_ANGLE = 0.65

# 规则优先级 (首个命中者胜; 顺序不可随意调换, 见模块 docstring)
_RULE_ORDER: Tuple[str, ...] = ("portrait", "night", "landscape", "food", "mono")

# 置信度标尺: 特征超阈值多少 → 命中度 1.0 (2× 门限 / 固定跨度)
_SCORE_SAT_FACTOR = 2.0          # 比例类: 2× 门限 → 1.0
_NIGHT_BRIGHT_SPAN = 30.0        # night: 亮度低于门限 30 → 该分量 1.0
_NIGHT_DARK_SPAN = 0.40          # night: 暗区超门限 0.40 → 该分量 1.0
_FOOD_SUBJ_SPAN = 0.20           # food: 主体占比越过下门限 0.20 → 该分量 1.0


def _clamp01(x: float) -> float:
    return float(min(max(x, 0.0), 1.0))


# ────────────────────────────────────────────────────────────────────────────
# 掩码 (确定性 CV, RGB 域; 参考 vision_report.py 写法)
# ────────────────────────────────────────────────────────────────────────────

def _sky_mask(rgb8: np.ndarray) -> np.ndarray:
    """天空掩码: 上半区蓝色主导 (蓝 > 红+8 且 蓝 > 绿+8 且 蓝 > 80)。"""
    h = rgb8.shape[0]
    r = rgb8[:, :, 0].astype(np.int16)
    g = rgb8[:, :, 1].astype(np.int16)
    b = rgb8[:, :, 2].astype(np.int16)
    upper = np.arange(h)[:, None] < h * 0.5
    return (b > r + 8) & (b > g + 8) & (b > SKY_MIN_BLUE) & upper


def _green_mask(rgb8: np.ndarray) -> np.ndarray:
    """绿植掩码: 绿色主导 (绿 > 红+6 且 绿 > 蓝+6 且 绿 > 45)。"""
    r = rgb8[:, :, 0].astype(np.int16)
    g = rgb8[:, :, 1].astype(np.int16)
    b = rgb8[:, :, 2].astype(np.int16)
    return (g > r + 6) & (g > b + 6) & (g > GREEN_MIN)


def _skin_mask_ellipse(lab: np.ndarray) -> np.ndarray:
    """Lab 椭圆肤色掩码 (简化二值版, 内部实现; T5 engine.skin 提供软掩码)。

    规格 §2.2: 中心 (a=140, b=150), 主轴 22, 副轴 14, 倾角 0.65 rad。
    将 (a, b) 旋转变换到椭圆主轴系后判马氏距离 ≤1。
    """
    a = lab[:, :, 1].astype(np.float32)
    b = lab[:, :, 2].astype(np.float32)
    da = a - SKIN_LAB_A
    db = b - SKIN_LAB_B
    cos_a, sin_a = np.cos(SKIN_ANGLE), np.sin(SKIN_ANGLE)
    u = da * cos_a + db * sin_a   # 沿主轴
    v = -da * sin_a + db * cos_a  # 沿副轴
    d2 = (u / SKIN_MAJOR) ** 2 + (v / SKIN_MINOR) ** 2
    return d2 <= 1.0


# ────────────────────────────────────────────────────────────────────────────
# 特征提取
# ────────────────────────────────────────────────────────────────────────────

def _as_uint8_rgb(rgb8) -> np.ndarray:
    """入参清洗 → uint8 RGB HxWx3 (float 图按 0..1 量化; 灰度图扩 3 通道)。"""
    arr = np.asarray(rgb8)
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 1.0)
        arr = (arr * 255.0 + 0.5).astype(np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb8 需为 HxWx3 图, 实际 {arr.shape}")
    return arr


def _extract_features(rgb8: np.ndarray) -> Dict[str, float]:
    """确定性 CV 特征 (全部由 rgb8 计算, 无 I/O)。

    Returns:
        brightness  : 亮度中位 (0..255)
        contrast    : 亮度标准差
        dark_ratio  : 暗区占比 (gray < DARK_LEVEL)
        bright_ratio: 亮区占比 (gray > BRIGHT_LEVEL)
        sky_ratio   : 天空占比
        green_ratio : 绿植占比
        skin_ratio  : 肤色占比 (Lab 椭圆)
        color_ratio : 彩色占比 (HSV 饱和度 ≥ SAT_COLOR_MIN)
        warm_ratio  : 暖色相占比 (饱和且色相红~黄 / 品红~红)
    """
    import cv2  # 函数内导入: 保持模块导入无重依赖 (纯函数仍无 I/O)

    img = _as_uint8_rgb(rgb8)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)

    sat = hsv[:, :, 1].astype(np.float32)
    val = hsv[:, :, 2].astype(np.float32)
    hue = hsv[:, :, 0].astype(np.float32)
    colorful = sat >= SAT_COLOR_MIN
    warm = colorful & (val >= WARM_VAL_MIN) & ((hue <= WARM_HUE_MAX) | (hue >= WARM_HUE_MIN))

    feats = {
        "brightness": float(np.median(gray)),
        "contrast": float(gray.std()),
        "dark_ratio": float((gray < DARK_LEVEL).mean()),
        "bright_ratio": float((gray > BRIGHT_LEVEL).mean()),
        "sky_ratio": float(_sky_mask(img).mean()),
        "green_ratio": float(_green_mask(img).mean()),
        "skin_ratio": float(_skin_mask_ellipse(lab).mean()),
        "color_ratio": float(colorful.mean()),
        "warm_ratio": float(warm.mean()),
    }
    feats["size"] = (h, w)
    return feats


def _persons_and_boxes(vision_report, subjects) -> Tuple[int, List[List[float]]]:
    """persons 数 + 归一化主体框列表 (vision_report / subjects 双源融合)。"""
    persons = 0
    boxes: List[List[float]] = []

    # subjects: 归一化框列表 或 dict {persons/count/items}
    if isinstance(subjects, dict):
        persons = int(subjects.get("persons", 0) or 0)
        items = subjects.get("items") or []
        for it in items:
            box = it.get("box") if isinstance(it, dict) else None
            if box:
                boxes.append([float(x) for x in box])
    elif subjects:
        for b in subjects:
            try:
                v = [float(x) for x in b]
            except (TypeError, ValueError):
                continue
            if len(v) == 4:
                boxes.append(v)

    # vision_report 优先补充 persons (深度学习侧权威)
    if vision_report is not None:
        subj = (vision_report.get("subject") or {}) if isinstance(vision_report, dict) else {}
        if subj.get("persons") is not None:
            persons = int(subj["persons"])
        if not boxes:
            items = subj.get("items") or []
            boxes = [it["box"] for it in items
                     if isinstance(it, dict) and it.get("box")]
    return persons, boxes


def _subject_ratio(boxes: List[List[float]], h: int, w: int) -> float:
    """主体占比 = 归一化框并集面积 / 帧面积 (无框 → 0.0)。"""
    if not boxes:
        return 0.0
    mask = np.zeros((h, w), dtype=bool)
    for b in boxes:
        l, t, r, bb = b
        x0 = max(0, int(round(l * w)))
        x1 = min(w, int(round(r * w)))
        y0 = max(0, int(round(t * h)))
        y1 = min(h, int(round(bb * h)))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return float(mask.mean())


# ────────────────────────────────────────────────────────────────────────────
# 规则评分 (命中度 0..1; 前置条件不满足 → 0, 即不命中)
# ────────────────────────────────────────────────────────────────────────────

def _score_portrait(feats: Dict[str, float], persons: int) -> float:
    """portrait: persons>0 且肤色占比 >3%。命中度 = 肤色占比相对 2×门限。"""
    if persons <= 0 or feats["skin_ratio"] <= SKIN_RATIO_MIN:
        return 0.0
    return _clamp01(feats["skin_ratio"] / (_SCORE_SAT_FACTOR * SKIN_RATIO_MIN))


def _score_night(feats: Dict[str, float]) -> float:
    """night: 亮度<60 且暗区>30%。命中度 = 亮度/暗区两个分量的均值。"""
    if feats["brightness"] >= NIGHT_BRIGHT_MAX or feats["dark_ratio"] <= NIGHT_DARK_MIN:
        return 0.0
    b_comp = _clamp01((NIGHT_BRIGHT_MAX - feats["brightness"]) / _NIGHT_BRIGHT_SPAN)
    d_comp = _clamp01((feats["dark_ratio"] - NIGHT_DARK_MIN) / _NIGHT_DARK_SPAN)
    return 0.5 * b_comp + 0.5 * d_comp


def _score_landscape(feats: Dict[str, float]) -> float:
    """landscape: 绿植或天空 >20%。命中度 = 最大占比相对 2×门限。"""
    dom = max(feats["green_ratio"], feats["sky_ratio"])
    if dom <= LANDSCAPE_MIN:
        return 0.0
    return _clamp01(dom / (_SCORE_SAT_FACTOR * LANDSCAPE_MIN))


def _score_food(feats: Dict[str, float], subj_ratio: float) -> float:
    """food: 主体占比 20~60% 且暖色相占比高。命中度 = 暖色占比/主体占比均值。"""
    if not (FOOD_SUBJ_MIN <= subj_ratio <= FOOD_SUBJ_MAX):
        return 0.0
    if feats["warm_ratio"] <= FOOD_WARM_MIN:
        return 0.0
    s_comp = _clamp01((subj_ratio - FOOD_SUBJ_MIN) / _FOOD_SUBJ_SPAN)
    w_comp = _clamp01(feats["warm_ratio"] / (_SCORE_SAT_FACTOR * FOOD_WARM_MIN))
    return 0.5 * s_comp + 0.5 * w_comp


def _score_mono(feats: Dict[str, float]) -> float:
    """mono: 彩色占比低 (≤10%)。命中度 = 随彩色占比线性衰减。"""
    if feats["color_ratio"] > MONO_COLOR_MAX:
        return 0.0
    return _clamp01(1.0 - feats["color_ratio"] / MONO_COLOR_REF)


def _score_rules(feats: Dict[str, float], persons: int,
                 subj_ratio: float) -> Dict[str, float]:
    return {
        "portrait": _score_portrait(feats, persons),
        "night": _score_night(feats),
        "landscape": _score_landscape(feats),
        "food": _score_food(feats, subj_ratio),
        "mono": _score_mono(feats),
    }


# ────────────────────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────────────────────

def classify_scene(rgb8, vision_report=None, subjects=None) -> Tuple[str, float]:
    """场景分类 (纯函数, 无 I/O)。

    Args:
        rgb8: 8bit RGB 图 (uint8 HxWx3; float 0..1 亦可)。
        vision_report: build_vision_report 输出 (可选; 取 subject.persons)。
        subjects: 归一化 [l,t,r,b] 框列表, 或 dict {persons, items} (可选)。

    Returns:
        (scene_id, confidence): scene_id ∈ {portrait, night, landscape, food,
        mono, street}; confidence ∈ [0, 1] (规则命中度, 3 位小数)。

    规则链 (首个命中胜, 阈值见模块常量):
        portrait: persons>0 且肤色占比>3%
        night   : 亮度<60 且暗区>30%
        landscape: 绿植或天空>20%
        food    : 主体占比 20~60% 且暖色相占比高
        mono    : 彩色占比≤10%
        street  : 以上皆不命中 (兜底)
    """
    if rgb8 is None or getattr(rgb8, "size", 0) == 0:
        return ("street", 0.0)  # 特征缺失回退 (规格 §1 错误码)

    feats = _extract_features(rgb8)
    persons, boxes = _persons_and_boxes(vision_report, subjects)
    h, w = feats["size"]
    subj_ratio = _subject_ratio(boxes, h, w)
    feats["subject_ratio"] = subj_ratio
    feats["persons"] = persons

    scores = _score_rules(feats, persons, subj_ratio)

    # 优先级序取首个命中 (score>0 即前置条件满足且超门限)
    for scene_id in _RULE_ORDER:
        if scores[scene_id] > 0.0:
            return (scene_id, round(scores[scene_id], 3))

    # 兜底 street: 命中度 = 0.5 + 0.5×(1 - 最强未命中规则的接近度)
    best_other = max(scores.values())
    conf = 0.5 + 0.5 * (1.0 - best_other)
    return ("street", round(min(conf, 1.0), 3))
