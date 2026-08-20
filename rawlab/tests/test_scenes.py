"""T3 单元测试: 场景分类器 (rawlab/engine/scenes.py)。

覆盖 (验收: 6 类合成图分类正确; 置信度 0..1; 纯函数无 I/O):
  - portrait : 肤色块 + persons>0 → portrait; 无 persons → 非 portrait
  - night    : 暗图 / 全黑图 → night
  - landscape: 天空+绿植 / 纯绿植 → landscape
  - food     : 暖色块 + 主体框 20~60% → food; 主体占比越界 → 非 food
  - mono     : 灰度渐变 → mono
  - street   : 中性多彩混合, 无规则命中 → street (兜底)
  - 置信度: 6 类全部落在 [0, 1]
  - 确定性: 同图两次分类结果一致 (纯函数)
  - 输入宽容: float 0..1 图 / vision_report 供 persons / 缺图回退 ('street', 0.0)
  - 特征 sanity: 暗图 brightness<60 且 dark_ratio>0.3; 灰度图 color_ratio=0

运行: python -m pytest rawlab/tests/test_scenes.py -q
"""
from __future__ import annotations

import numpy as np

from rawlab.engine.scenes import (
    classify_scene,
    _extract_features,
)

# 合成图尺寸 (小图足够, 特征为全局统计)
_H = _W = 64


def _solid(h, w, rgb):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = rgb
    return img


def _put_block(img, rgb, x0, y0, x1, y1):
    """归一化坐标块填充 (x0,y0,x1,y1 ∈ [0,1])。"""
    h, w = img.shape[:2]
    img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = rgb
    return img


# ---------------------------------------------------------------------------
# 合成特征图
# ---------------------------------------------------------------------------

def _portrait_image():
    """灰背景 + 中央肤色块 (~30% 面积, Lab 椭圆内: (210,155,130)→(145,149))。"""
    img = _solid(_H, _W, (128, 128, 128))
    _put_block(img, (210, 155, 130), 0.2, 0.2, 0.8, 0.8)
    return img


def _night_image():
    """全图近黑 (亮度 18 + 微噪), 暗区 100%。"""
    rng = np.random.default_rng(0)
    img = np.full((_H, _W, 3), 18, dtype=np.uint8)
    img += rng.integers(0, 9, size=(_H, _W, 1), dtype=np.uint8)
    return img


def _landscape_image():
    """上半天空 (蓝主导) + 下半绿植。"""
    img = _solid(_H, _W, (60, 160, 80))          # 绿
    img[:_H // 2, :] = (90, 140, 220)            # 天空蓝
    return img


def _food_image():
    """灰背景 + 中央橙色暖块 (占 ~30% 面积)。"""
    img = _solid(_H, _W, (128, 128, 128))
    _put_block(img, (230, 120, 40), 0.2, 0.25, 0.8, 0.75)
    return img


def _mono_image():
    """灰度竖直渐变 100..220 (零饱和, 非暗图)。"""
    ramp = np.linspace(100, 220, _W, dtype=np.uint8)
    img = np.repeat(ramp[None, :, None], _H, axis=0)
    return np.repeat(img, 3, axis=2)


def _street_image():
    """灰背景 + 红色块 (~25%) + 深灰块: 有彩但无绿/蓝/人/暖主体规则命中。"""
    img = _solid(_H, _W, (128, 128, 128))
    _put_block(img, (180, 60, 60), 0.05, 0.1, 0.55, 0.6)   # 红色建筑块
    _put_block(img, (70, 68, 66), 0.6, 0.65, 0.95, 0.95)   # 深灰块
    return img


# ---------------------------------------------------------------------------
# 6 类合成图分类
# ---------------------------------------------------------------------------

def test_portrait_skin_with_person():
    scene, conf = classify_scene(_portrait_image(), subjects={"persons": 1})
    assert scene == "portrait"
    assert 0.0 < conf <= 1.0


def test_portrait_requires_person():
    """有肤色但无 persons 信息 → 非 portrait (主体框列表不带人物语义)。"""
    box = [0.2, 0.2, 0.8, 0.8]
    scene, _ = classify_scene(_portrait_image(), subjects=[box])
    assert scene != "portrait"


def test_portrait_persons_from_vision_report():
    """vision_report['subject']['persons'] 作为 persons 权威来源。"""
    report = {"subject": {"persons": 2, "count": 2, "items": []}}
    scene, conf = classify_scene(_portrait_image(), vision_report=report)
    assert scene == "portrait"
    assert 0.0 < conf <= 1.0


def test_night_dark_image():
    scene, conf = classify_scene(_night_image())
    assert scene == "night"
    assert 0.0 < conf <= 1.0


def test_night_black_image():
    scene, _ = classify_scene(_solid(_H, _W, (0, 0, 0)))
    assert scene == "night"


def test_landscape_sky_and_green():
    scene, conf = classify_scene(_landscape_image())
    assert scene == "landscape"
    assert 0.0 < conf <= 1.0


def test_landscape_green_only():
    scene, _ = classify_scene(_solid(_H, _W, (60, 160, 80)))
    assert scene == "landscape"


def test_food_warm_block_with_subject():
    box = [0.2, 0.25, 0.8, 0.75]  # 面积 30%, 落在 20~60%
    scene, conf = classify_scene(_food_image(), subjects=[box])
    assert scene == "food"
    assert 0.0 < conf <= 1.0


def test_food_subject_ratio_out_of_range():
    """主体占比 <20% (或 >60%) → 非 food。"""
    tiny = [0.45, 0.45, 0.55, 0.55]   # 1%
    scene, _ = classify_scene(_food_image(), subjects=[tiny])
    assert scene != "food"
    huge = [0.0, 0.0, 1.0, 1.0]       # 100%
    scene, _ = classify_scene(_food_image(), subjects=[huge])
    assert scene != "food"


def test_food_without_subjects_not_food():
    scene, _ = classify_scene(_food_image())
    assert scene != "food"


def test_mono_gray_gradient():
    scene, conf = classify_scene(_mono_image())
    assert scene == "mono"
    assert 0.0 < conf <= 1.0


def test_street_neutral_fallback():
    scene, conf = classify_scene(_street_image())
    assert scene == "street"
    assert 0.0 < conf <= 1.0


# ---------------------------------------------------------------------------
# 置信度 / 确定性 / 输入宽容
# ---------------------------------------------------------------------------

def test_confidence_in_range_all_classes():
    cases = [
        (_portrait_image(), {"subjects": {"persons": 1}}),
        (_night_image(), {}),
        (_landscape_image(), {}),
        (_food_image(), {"subjects": [[0.2, 0.25, 0.8, 0.75]]}),
        (_mono_image(), {}),
        (_street_image(), {}),
    ]
    for img, kw in cases:
        scene, conf = classify_scene(img, **kw)
        assert 0.0 <= conf <= 1.0, f"{scene}: conf={conf} 越界"
        assert scene in {"portrait", "night", "landscape", "food", "mono", "street"}


def test_deterministic_pure_function():
    img = _landscape_image()
    a = classify_scene(img)
    b = classify_scene(img)
    assert a == b


def test_float_input_same_as_uint8():
    u8 = _portrait_image()
    flt = u8.astype(np.float32) / 255.0
    s1, c1 = classify_scene(u8, subjects={"persons": 1})
    s2, c2 = classify_scene(flt, subjects={"persons": 1})
    assert (s1, c1) == (s2, c2)


def test_missing_image_fallback():
    assert classify_scene(None) == ("street", 0.0)
    assert classify_scene(np.zeros((0, 0, 3), np.uint8)) == ("street", 0.0)


# ---------------------------------------------------------------------------
# 特征 sanity
# ---------------------------------------------------------------------------

def test_feature_extraction_night():
    feats = _extract_features(_night_image())
    assert feats["brightness"] < 60
    assert feats["dark_ratio"] > 0.3


def test_feature_extraction_mono():
    feats = _extract_features(_mono_image())
    assert feats["color_ratio"] == 0.0
    assert feats["skin_ratio"] == 0.0


def test_feature_extraction_landscape():
    feats = _extract_features(_landscape_image())
    assert feats["sky_ratio"] > 0.2
    assert feats["green_ratio"] > 0.2
