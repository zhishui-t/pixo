"""F14 单元测试: decide region.* 点分键接线 (闭环: 规则 → region_adjust)。

覆盖 (设计 §2 F14 完成标准):
  - 键映射: region.<prompt>.<param> → region_adjust.regions[prompt][param]
    嵌套写入 + enabled=True 联动 (dehaze t108 同款); 越界值钳制到 stage
    schema 域 (exposure [-2,2] / saturation [-1,1]); 畸形键不吞 (informational
    顶层保留); 桶被占非 dict 退回扁平 (t51 同款); params 面 JSON 可序列化
    (掩码 ndarray 永不进 params —— F13 缓存指纹陷阱的 params 侧确认)
  - 指标键: SinglePhotoLoop 构造时把 <prompt>_{luminance,area_ratio,
    highlight_clip_ratio,reliable} 注册进 decide 键宇宙 (公式 lint 补缺)
  - 规则 YAML: region_rules.yaml 两条经 load_rules 严格 lint 加载并按指标
    触发 (天空过亮负补偿 / 植被过暗正提亮), 方向钳制生效
  - 合成 e2e 闭环: mock 掩码 → measure → decide 写 region 键 → 下轮渲染
    像素变化断言 (SinglePhotoLoop + SyntheticRenderBackend + MockSegmenter,
    掩码经 F13 通道注入, region_adjust 真实消费)

运行: python -m pytest tests/unit/test_decide_region_wiring.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pixo.decide.engine import (
    evaluate_rules,
    load_rules,
    registered_metric_keys,
    reset_metric_keys,
)
from pixo.decide.rules import RULES_DIR
from pixo.pipeline.loop import (
    SyntheticRenderBackend,
    SinglePhotoLoop,
    _apply_decide_params,
)
from pixo.render.pipeline.region_masks import adapt_region_masks
from pixo.vision import MockSegmenter

REGION_RULES_YAML = RULES_DIR / "region_rules.yaml"
CONFIGS_RULES_YAML = (Path(__file__).resolve().parents[2] / "configs"
                      / "rules" / "region_rules.yaml")


@pytest.fixture(autouse=True)
def _clean_registry():
    """指标键宇宙测试隔离: 前后清空 (注册是全局 set)。"""
    reset_metric_keys()
    yield
    reset_metric_keys()


# ---------------------------------------------------------------------------
# 键映射: region.<prompt>.<param> → region_adjust 嵌套 + enabled 联动
# ---------------------------------------------------------------------------

def test_region_exposure_key_maps_and_enables():
    out = _apply_decide_params({}, {"region.sky.exposure": -0.5})
    assert out["region_adjust"]["enabled"] is True          # 联动 (dehaze 模式)
    assert out["region_adjust"]["regions"]["sky"]["exposure"] == -0.5
    assert "region.sky.exposure" not in out                 # 不留悬空键


def test_region_saturation_key_maps():
    out = _apply_decide_params({}, {"region.plant.saturation": 0.3})
    assert out["region_adjust"]["enabled"] is True
    assert out["region_adjust"]["regions"]["plant"]["saturation"] == 0.3


def test_region_key_preserves_existing_bucket_and_multi_region():
    """既有 region_adjust 桶字段保留; 多区域/多参数并存。"""
    params = {"region_adjust": {"enabled": True,
                                "regions": {"ground": {"exposure": 0.2}}}}
    out = _apply_decide_params(params, {
        "region.sky.exposure": -0.4,
        "region.sky.saturation": -0.2,
    })
    ra = out["region_adjust"]
    assert ra["enabled"] is True
    assert ra["regions"]["ground"] == {"exposure": 0.2}     # 既有区域不被破坏
    assert ra["regions"]["sky"] == {"exposure": -0.4, "saturation": -0.2}


def test_region_key_out_of_range_clamped():
    """decide 写出越界值 → 映射侧钳制 (stage schema 域), 不炸渲染链。"""
    out = _apply_decide_params({}, {"region.sky.exposure": 5.0})
    assert out["region_adjust"]["regions"]["sky"]["exposure"] == 2.0
    out2 = _apply_decide_params({}, {"region.sky.saturation": -3.5})
    assert out2["region_adjust"]["regions"]["sky"]["saturation"] == -1.0


def test_region_malformed_keys_stay_informational(caplog):
    """非 (prompt,param) 双段形态 / 未知参数名 → 无执行位, 顶层保留+告警。"""
    import logging
    bad_keys = ["region.sky",                    # 少一段
                "region.a.b.exposure",           # 多一段
                "region.sky.hue",                # 未知参数名
                "region..exposure"]              # 空 prompt
    with caplog.at_level(logging.WARNING, logger="pixo.pipeline.loop"):
        out = _apply_decide_params({}, {k: 1.0 for k in bad_keys})
    for k in bad_keys:
        assert out[k] == 1.0                     # 不静默吞掉
    assert "region_adjust" not in out
    msgs = [r.message for r in caplog.records]
    assert sum("无执行位" in m for m in msgs) >= 1


def test_region_bucket_occupied_falls_back_flat():
    """region_adjust 桶被占成非 dict → 退回顶层扁平键 (不吞键, t51 同款)。"""
    out = _apply_decide_params({"region_adjust": "reserved"},
                               {"region.sky.exposure": -0.5})
    assert out["region.sky.exposure"] == -0.5
    assert out["region_adjust"] == "reserved"


def test_region_key_overwrites_same_region_param():
    """同区域同参数重复写入 → set 语义覆盖 (多轮迭代确定性)。"""
    out = _apply_decide_params(
        {"region_adjust": {"enabled": True,
                           "regions": {"sky": {"exposure": -0.9}}}},
        {"region.sky.exposure": -0.3})
    assert out["region_adjust"]["regions"]["sky"]["exposure"] == -0.3


def test_region_params_stay_json_serializable():
    """映射后的 params 面保持 JSON 可序列化 —— 掩码 ndarray 只走
    ctx.state["region_masks"] 通道, 永不进 params (F13 指纹陷阱 params 侧)。"""
    out = _apply_decide_params({}, {"region.sky.exposure": -0.5})
    json.dumps(out, allow_nan=False)             # 不抛即通过
    assert _apply_decide_params({}, {"region.sky.exposure": -0.5}) == \
        _apply_decide_params({}, {"region.sky.exposure": -0.5})


# ---------------------------------------------------------------------------
# 指标键注册 (公式 lint 键宇宙补缺)
# ---------------------------------------------------------------------------

def test_loop_construction_registers_region_metric_keys():
    SinglePhotoLoop(prompts=["sky", "plant"])
    registered = registered_metric_keys()
    for prompt in ("sky", "plant"):
        for suffix in ("luminance", "area_ratio",
                       "highlight_clip_ratio", "reliable"):
            assert f"{prompt}_{suffix}" in registered


def test_registered_keys_admit_rule_formula_reference():
    """注册后, 公式直接引用 <prompt>_luminance 通过加载期 lint (补缺前会
    DecideError)。"""
    SinglePhotoLoop(prompts=["sky"])
    rule = {
        "rule_id": "t",
        "condition": {"metric": "sky_luminance", "op": "gt", "value": 1},
        "action": {"param": "region.sky.exposure", "mode": "set",
                   "formula": "-0.5 * (sky_luminance / 150.0)"},
    }
    rules = load_rules(rule)                     # 不抛 DecideError 即通过
    assert len(rules) == 1


def test_default_rules_still_lint_after_loop_construction():
    """回归钉死: loop 构造注册键宇宙后 (进程内 strict 模式激活), 默认规则包
    必须仍能通过严格 lint —— 注册集必须是完整生产 flatten 宇宙, 只注册
    region 键会让 tone_clarity 的 condition.all (haze_proxy 等) 加载即炸。"""
    from pixo.decide.rules import DEFAULT_RULES
    SinglePhotoLoop(prompts=["sky", "plant"])    # 注册 → 全进程 strict
    for path in DEFAULT_RULES:
        rules = load_rules(str(path))            # 不抛 DecideError 即通过
        assert rules


# ---------------------------------------------------------------------------
# 规则 YAML: 加载 (严格 lint) + 触发 + 方向钳制
# ---------------------------------------------------------------------------

def _load_region_rules():
    assert CONFIGS_RULES_YAML.exists(), "configs/rules 镜像副本缺失"
    return load_rules(str(REGION_RULES_YAML))    # 注册表空 → 宽松模式可加载


def test_region_rules_yaml_loads_and_package_mirror_consistent():
    rules = _load_region_rules()
    assert [r["rule_id"] for r in rules] == [
        "region_sky_exposure_001", "region_plant_exposure_002"]
    # 两路来源逐字一致 (包内镜像 vs configs 源)
    assert REGION_RULES_YAML.read_bytes() == CONFIGS_RULES_YAML.read_bytes()


def test_sky_rule_fires_negative_compensation():
    SinglePhotoLoop(prompts=["sky"])             # 注册指标键
    rules = _load_region_rules()
    metrics = {"sky_luminance": 225.0}
    results = evaluate_rules(rules, metrics)
    sky = [r for r in results if r["param"] == "region.sky.exposure"]
    assert len(sky) == 1
    # 公式: -0.5 * 225/150 = -0.75; 方向钳制 ≤ 0
    assert sky[0]["value"] == pytest.approx(-0.75)
    assert sky[0]["value"] <= 0.0


def test_sky_rule_not_fires_below_threshold():
    rules = _load_region_rules()
    results = evaluate_rules(rules, {"sky_luminance": 100.0})
    assert all(r["param"] != "region.sky.exposure" for r in results)


def test_plant_rule_fires_positive_lift_and_direction_clamp():
    SinglePhotoLoop(prompts=["plant"])
    rules = _load_region_rules()
    results = evaluate_rules(rules, {"plant_luminance": 35.0})
    plant = [r for r in results if r["param"] == "region.plant.exposure"]
    assert len(plant) == 1
    # 公式: 0.4 * (70-35)/70 = 0.2; 方向钳制 ≥ 0 (只提亮不压暗)
    assert plant[0]["value"] == pytest.approx(0.2)
    assert plant[0]["value"] >= 0.0


# ---------------------------------------------------------------------------
# 合成 e2e 闭环: mock 掩码 → measure → decide 写 region 键 → 像素变化
# ---------------------------------------------------------------------------

def _sky_image(h=64, w=64):
    """上半亮天空 + 下半中性地面 (MockSegmenter sky = 顶部 40% 条带)。"""
    img = np.full((h, w, 3), 0.45, dtype=np.float32)
    img[: int(h * 0.4), :] = 0.9
    return img


class _SkyMeasurer:
    """在 sky 掩码区实测亮度 (0-255) —— 测量真实反映渲染像素变化。"""

    def measure(self, image, masks, **kw):
        arr = np.asarray(image, dtype=np.float32)
        lum = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])
        sky = masks.get("sky")
        if sky is not None and (sky > 0).any():
            sky_lum = float(lum[sky > 0].mean())
            ground_lum = float(lum[sky == 0].mean())
            area = float((sky > 0).mean())
        else:
            sky_lum = float(lum.mean())
            ground_lum = sky_lum
            area = 0.0
        return {
            "global": {
                "mean_luminance": float(lum.mean()),
                "highlight_clip_ratio": 0.0,
                "shadow_clip_ratio": 0.0,
                "contrast": 0.5,
            },
            "regions": {
                "sky": {"mean_luminance": sky_lum, "area_ratio": area,
                        "reliable": True},
                "ground": {"mean_luminance": ground_lum, "area_ratio": 1 - area,
                           "reliable": True},
            },
        }


def _make_region_loop(**kw):
    backend = SyntheticRenderBackend(
        _sky_image(), stages=("compose", "tone", "region_adjust"))
    return SinglePhotoLoop(
        render_backend=backend,
        segmenter=MockSegmenter(),
        measurer=_SkyMeasurer(),
        rules=load_rules(str(REGION_RULES_YAML)),
        prompts=["sky"],
        max_iterations=2,
        preview_long_edge=64,
        **kw,
    )


def test_e2e_region_rule_closed_loop():
    """闭环证明: 掩码 → measure(sky_luminance 超阈) → decide 写 region 键 →
    映射进 region_adjust (enabled 联动) → 下轮渲染天空区变暗 (测量回读)。"""
    result = _make_region_loop().run("region_e2e", image_rgb=_sky_image())

    # 1) decide 真实触发: region 规则进了决策
    decide_events = [e for e in result.trace_events
                     if e["event_type"] == "decide"]
    assert decide_events
    assert any("region_sky_exposure_001" in (e["value"].get("rule_ids") or [])
               for e in decide_events)

    # 2) region 键落位: 嵌套 regions + enabled 联动
    ra = result.params["region_adjust"]
    assert ra["enabled"] is True
    exposure = ra["regions"]["sky"]["exposure"]
    assert exposure < 0.0                        # 天空负补偿
    json.dumps(result.params, allow_nan=False)   # params 面无 ndarray

    # 3) 闭环回读: 施加区域调整后的测量 sky 亮度显著低于首轮 (像素真变了)
    assert len(result.measurements) == 2
    lum_first = result.measurements[0]["regions"]["sky"]["mean_luminance"]
    lum_last = result.measurements[-1]["regions"]["sky"]["mean_luminance"]
    assert lum_last < lum_first - 5.0, (
        f"区域调整未生效: sky 亮度 {lum_first:.1f} -> {lum_last:.1f}")


def test_e2e_region_effect_is_localized_pixel_change():
    """像素级局部性: 同一后端带掩码注入, region 参数只改变掩码区,
    远离掩码边界的地面像素逐位不变 (F12 羽化纪律 + 软混合 m=0 恒等)。"""
    img = _sky_image()
    backend = SyntheticRenderBackend(
        img, stages=("compose", "tone", "region_adjust"))
    masks = MockSegmenter().segment(img, ["sky"])
    backend.state_extras = {"region_masks": adapt_region_masks(masks)}

    before = backend.render_preview({}, long_edge=64)
    after = backend.render_preview(
        {"region_adjust": {"enabled": True,
                           "regions": {"sky": {"exposure": -0.8}}}},
        long_edge=64)

    sky_rows = slice(0, 20)                      # 掩码核心区 (顶部)
    deep_ground_rows = slice(40, 64)             # 远离掩码羽化带 (边界 row 25/26)
    assert float(after[sky_rows].mean()) < float(before[sky_rows].mean())
    assert np.array_equal(after[deep_ground_rows], before[deep_ground_rows])
