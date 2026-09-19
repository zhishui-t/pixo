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
from pixo.decide.rules import DEFAULT_RULES, RULES_DIR
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


def test_region_warmth_key_maps_and_enables():
    """R13: region.<prompt>.warmth 新键映射 + enabled 联动 (与 exposure/
    saturation 同款); 规则 YAML 可引用该键 (映射侧准入即规则可用性确认)。"""
    out = _apply_decide_params({}, {"region.sky.warmth": 0.5})
    assert out["region_adjust"]["enabled"] is True
    assert out["region_adjust"]["regions"]["sky"]["warmth"] == 0.5
    assert "region.sky.warmth" not in out


def test_region_warmth_key_clamped_and_sign_preserved():
    """warmth 越界钳制到 [-1,1] 且符号保留 (负=冷, 正=暖)。"""
    out = _apply_decide_params({}, {"region.sky.warmth": 5.0})
    assert out["region_adjust"]["regions"]["sky"]["warmth"] == 1.0
    out2 = _apply_decide_params({}, {"region.sky.warmth": -5.0})
    assert out2["region_adjust"]["regions"]["sky"]["warmth"] == -1.0


def test_region_warmth_admitted_by_mapping_for_rules():
    """规则可用性确认 (不写真规则): decide 动作 param="region.<p>.warmth"
    经 _apply_decide_params 准入并落 region_adjust 嵌套参数面 —— 即
    region_rules.yaml 的 action.param 引用该键的通路已通。"""
    rule_action_param = "region.sky.warmth"
    out = _apply_decide_params({}, {rule_action_param: 0.4})
    assert out["region_adjust"]["regions"]["sky"]["warmth"] == 0.4


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
    SinglePhotoLoop()        # 默认 prompts 注册键宇宙 (strict lint 需覆盖两规则指标)
    rules = _load_region_rules()
    metrics = {"sky_luminance": 225.0, "sky_reliable": True,
               "sky_area_ratio": 0.4}   # 面积护栏 <0.7 (R13)
    results = evaluate_rules(rules, metrics)
    sky = [r for r in results if r["param"] == "region.sky.exposure"]
    assert len(sky) == 1
    # 公式 (R15 分层复权: sky 全量): -0.5 * 225/150 = -0.75; 钳制 ≤ 0
    assert sky[0]["value"] == pytest.approx(-0.75)
    assert sky[0]["value"] <= 0.0


def test_sky_rule_not_fires_below_threshold():
    rules = _load_region_rules()
    results = evaluate_rules(rules, {"sky_luminance": 100.0,
                                     "sky_reliable": True,
                                     "sky_area_ratio": 0.4})
    assert all(r["param"] != "region.sky.exposure" for r in results)


def test_unreliable_region_blocks_rule():
    """S-5 (M1 评审): 区域不可靠 (*_reliable != true) 时规则不得触发 ——
    小面积/低置信区域的区域亮度不可信, 不做区域补偿。
    (metrics 补 area_ratio: 保证拦截因素是 reliable 闸, 而非 R13 覆盖率
    护栏条件缺指标导致的同形失败。)"""
    rules = _load_region_rules()
    # 亮度超阈但 reliable 缺失/False → 不触发
    for reliable in (False, None):
        metrics = {"sky_luminance": 225.0, "sky_area_ratio": 0.4}
        if reliable is not None:
            metrics["sky_reliable"] = reliable
        results = evaluate_rules(rules, metrics)
        assert all(r["param"] != "region.sky.exposure" for r in results), (
            f"reliable={reliable!r} 时规则不应触发")
    plant_metrics_variants = [
        {"plant_luminance": 35.0, "plant_area_ratio": 0.4,
         "preview_overflow_ratio": 0.0},
        {"plant_luminance": 35.0, "plant_area_ratio": 0.4,
         "preview_overflow_ratio": 0.0, "plant_reliable": False}]
    for metrics in plant_metrics_variants:
        results = evaluate_rules(rules, metrics)
        assert all(r["param"] != "region.plant.exposure" for r in results)


def test_region_rules_activation_guard_and_trial_coefficients():
    """R15 分层复权 + R16 溢出负联动钉死: 覆盖率护栏 (area_ratio < 0.70)、
    sky 全量系数 (-0.5, 54 张零回退+救回主驱)、plant 试水系数 (0.2, 回退与
    S-4 共现续观察)、plant 溢出负联动 (preview_overflow_ratio < 1% 才提亮,
    sky 豁免 —— 压暗方向与溢出无关) 在位; region_rules.yaml 已入
    DEFAULT_RULES (M1 决策闭环激活)。复权/调参/回退须显式修改本断言
    (防静默变更)。依据: .artifacts/region_trial_54.md +
    .artifacts/region_rules_activation_eval.md。"""
    from pixo.decide.rules import DEFAULT_RULES

    rules = _load_region_rules()
    by_id = {r["rule_id"]: r for r in rules}
    for rid, area_key, coef, ovf_gate in (
            ("region_sky_exposure_001", "sky_area_ratio", "-0.5 *", False),
            ("region_plant_exposure_002", "plant_area_ratio", "0.2 *", True)):
        cond = by_id[rid]["condition"]["all"]
        area_conds = [c for c in cond if c.get("metric") == area_key]
        assert len(area_conds) == 1, f"{rid} 缺覆盖率护栏条件"
        assert area_conds[0]["op"] == "lt", rid
        assert area_conds[0]["value"] == pytest.approx(0.70), rid
        assert coef in by_id[rid]["action"]["formula"], (
            f"{rid} 系数漂移: {by_id[rid]['action']['formula']!r}")
        ovf_conds = [c for c in cond
                     if c.get("metric") == "preview_overflow_ratio"]
        if ovf_gate:
            assert len(ovf_conds) == 1 and ovf_conds[0]["op"] == "lt" \
                and ovf_conds[0]["value"] == pytest.approx(0.01), (
                f"{rid} 溢出负联动门控漂移")
        else:
            assert not ovf_conds, f"{rid} 不应有溢出门控 (sky 豁免)"
    assert any(Path(p).name == "region_rules.yaml" for p in DEFAULT_RULES), (
        "region_rules.yaml 未入 DEFAULT_RULES —— M1 决策闭环未激活")


def test_plant_rule_fires_positive_lift_and_direction_clamp():
    SinglePhotoLoop()        # 默认 prompts 注册键宇宙
    rules = _load_region_rules()
    results = evaluate_rules(rules, {"plant_luminance": 35.0,
                                     "plant_reliable": True,
                                     "plant_area_ratio": 0.4,
                                     "preview_overflow_ratio": 0.0})
    plant = [r for r in results if r["param"] == "region.plant.exposure"]
    assert len(plant) == 1
    # 公式 (R15 分层复权维持试水): 0.2 * (70-35)/70 = 0.1; 钳制 ≥ 0
    assert plant[0]["value"] == pytest.approx(0.1)
    assert plant[0]["value"] >= 0.0


def test_plant_rule_blocked_by_high_overflow():
    """R16 溢出负联动: preview_overflow_ratio >= 1% 时 plant 提亮不触发
    (事前门控, R15 回退 DSC_5276/5277 清偿 —— 决定轮溢出地板 1.35% 以上
    不做提亮决定); 低于阈值正常触发; sky 规则无此门控 (压暗方向与溢出
    无关, 高溢出下 sky 压暗照常触发)。"""
    SinglePhotoLoop()
    rules = _load_region_rules()
    base = {"plant_luminance": 35.0, "plant_area_ratio": 0.4,
            "plant_reliable": True, "sky_luminance": 225.0,
            "sky_area_ratio": 0.4, "sky_reliable": True}
    high = evaluate_rules(rules, {**base, "preview_overflow_ratio": 0.02})
    assert all(r["param"] != "region.plant.exposure" for r in high), (
        "溢出 >=1% 时 plant 提亮不应触发")
    sky_high = [r for r in high if r["param"] == "region.sky.exposure"]
    assert len(sky_high) == 1 and sky_high[0]["value"] < 0.0, (
        "溢出门控不得波及 sky 压暗规则")
    low = evaluate_rules(rules, {**base, "preview_overflow_ratio": 0.005})
    assert any(r["param"] == "region.plant.exposure" for r in low), (
        "溢出 <1% 时 plant 提亮应正常触发")


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
    kw.setdefault("max_iterations", 2)
    return SinglePhotoLoop(
        render_backend=backend,
        segmenter=MockSegmenter(),
        measurer=_SkyMeasurer(),
        rules=load_rules(str(REGION_RULES_YAML)),
        prompts=["sky"],
        preview_long_edge=64,
        **kw,
    )


def _make_default_rules_region_loop(**kw):
    """真 DEFAULT_RULES 包 (含 region_rules) 的闭环工厂 —— 守护「入包」:
    region 规则不靠注入、随默认包参与决策 (R13 激活)。
    先构造 priming loop 注册键宇宙 (镜像生产 strict 次序), 再装载默认包。"""
    SinglePhotoLoop(prompts=["sky", "plant"])   # 注册 → 全进程 strict lint
    default_rules: list[dict] = []
    for path in DEFAULT_RULES:
        default_rules.extend(load_rules(str(path)))
    backend = SyntheticRenderBackend(
        _sky_image(), stages=("compose", "tone", "region_adjust"))
    kw.setdefault("max_iterations", 2)
    return SinglePhotoLoop(
        render_backend=backend,
        segmenter=MockSegmenter(),
        measurer=_SkyMeasurer(),
        rules=default_rules,
        prompts=["sky", "plant"],
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


def test_e2e_region_rule_participates_under_default_rules_package():
    """R13 激活闭环 (真 DEFAULT_RULES 包, 非注入): region 规则随默认包参与
    决策 —— rule_ids 含 region_sky_exposure_001 且 region_adjust 落位
    (enabled 联动 + 天空负补偿)。与注入版 e2e 互补, 本用例守护「入包」本身:
    region_rules 被移出默认包即翻红。"""
    result = _make_default_rules_region_loop().run(
        "region_e2e_default", image_rgb=_sky_image())

    decide_events = [e for e in result.trace_events
                     if e["event_type"] == "decide"]
    assert decide_events
    assert any("region_sky_exposure_001" in (e["value"].get("rule_ids") or [])
               for e in decide_events), (
        "默认规则包下 region 规则未参与决策 —— 激活回退或护栏误拦")

    ra = result.params["region_adjust"]
    assert ra["enabled"] is True
    assert ra["regions"]["sky"]["exposure"] < 0.0
    json.dumps(result.params, allow_nan=False)   # params 面无 ndarray


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


# ---------------------------------------------------------------------------
# I-1 (M1 评审): compose 参数变化 → region 掩码缓存失效 (不作为优于错作为)
# ---------------------------------------------------------------------------

def test_compose_fingerprint_basics():
    from pixo.pipeline.loop import _compose_fingerprint
    assert _compose_fingerprint({}) == ""                  # 无 compose
    assert _compose_fingerprint({"compose": {}}) == ""
    assert _compose_fingerprint({"compose": None}) == ""
    a = _compose_fingerprint({"compose": {"mode": "free", "x": 10, "y": 0,
                                          "width": 40, "height": 40}})
    b = _compose_fingerprint({"compose": {"y": 0, "width": 40, "height": 40,
                                          "x": 10, "mode": "free"}})
    assert a == b                                          # 键序无关
    assert a != _compose_fingerprint({"compose": {"mode": "ratio",
                                                  "ratio": "3:2"}})


def test_sync_region_masks_invalidates_on_compose_change(caplog):
    """compose 指纹变化 (含 adopt_crop 改写) → 软掩码清空 + warn-once;
    未变化时原对象返回 (F13 缓存指纹纪律)。"""
    import logging

    from pixo.pipeline.loop import _compose_fingerprint
    loop = _make_region_loop(max_iterations=1)
    masks = {"sky": np.full((64, 64), 1.0, dtype=np.float32)}
    loop._region_masks_soft = masks
    with caplog.at_level(logging.WARNING, logger="pixo.pipeline.loop"):
        # 首轮同步 (无 compose): 建立基线指纹, 不清掩码、不告警
        assert loop._sync_region_masks({}) is masks
        assert loop._region_masks_soft is masks
        assert not [r for r in caplog.records if "掩码缓存已失效" in r.message]
        # 未变化: 幂等, 原对象返回
        assert loop._sync_region_masks({}) is masks
        # compose 变化 (模拟 adopt_crop 改写): 清空 + warn 一次
        cropped = {"compose": {"mode": "free", "x": 8, "y": 8,
                               "width": 48, "height": 48}}
        assert loop._sync_region_masks(cropped) is None
        assert loop._region_masks_soft is None
        assert any("掩码缓存已失效" in r.message for r in caplog.records)
        n_warn = sum(1 for r in caplog.records if "掩码缓存已失效" in r.message)
        # 再次变化: 掩码本已空, 不再重复告警 (warn-once)
        loop._sync_region_masks({"compose": {"mode": "ratio", "ratio": "3:2"}})
        assert sum(1 for r in caplog.records
                   if "掩码缓存已失效" in r.message) == n_warn
    # 掩码清空后指纹跟随最新 compose (region_adjust wants 静默直通)
    latest = {"compose": {"mode": "ratio", "ratio": "3:2"}}
    loop._sync_region_masks(latest)
    assert _compose_fingerprint(latest) == loop._compose_fp


class _RecordingBackend(SyntheticRenderBackend):
    """记录每次渲染入口的 state_extras (验证 loop 实际注入面)。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rendered_extras: list = []

    def _render(self, params, long_edge):
        self.rendered_extras.append(
            dict(getattr(self, "state_extras", None) or {}))
        return super()._render(params, long_edge)


def test_e2e_crop_adoption_drops_region_masks(monkeypatch, caplog):
    """I-1 闭环: crop 建议被采纳 (compose 变化) 后, 后续渲染与导出线不再
    注入 region_masks —— 区域效果消失, 而非作用到错误区域。"""
    import logging

    import pixo.pipeline.loop as loop_mod

    def fake_suggest_crop(img, boxes, **kw):
        rect = [0.1, 0.1, 0.9, 0.9]            # 归一化 [x0,y0,x1,y1]
        return rect, [{"rect": rect, "ratio": "original", "score": 0.9}]

    monkeypatch.setattr(loop_mod, "suggest_crop", fake_suggest_crop)
    backend = _RecordingBackend(
        _sky_image(), stages=("compose", "tone", "region_adjust"))
    loop = SinglePhotoLoop(
        render_backend=backend,
        segmenter=MockSegmenter(),
        measurer=_SkyMeasurer(),
        rules=[
            # region 规则 (首轮即触发, 建立掩码注入)
            {"rule_id": "r", "condition": {"metric": "sky_luminance",
                                           "op": "gt", "value": 150},
             "action": {"param": "region.sky.exposure", "mode": "set",
                        "value": -0.5}},
            # crop 采纳规则: 首轮即写 compose.apply_suggestion=1
            {"rule_id": "c", "condition": {"metric": "mean_luminance",
                                           "op": "gt", "value": 0.0},
             "action": {"param": "compose.apply_suggestion", "mode": "set",
                        "value": 1}},
        ],
        prompts=["sky"],
        max_iterations=2,
        preview_long_edge=64,
        crop_suggest=True,
        jnd_threshold=None,
    )
    with caplog.at_level(logging.WARNING, logger="pixo.pipeline.loop"):
        result = loop.run("crop_region", image_rgb=_sky_image())

    # crop 确实被采纳 (compose 变化的前提成立)
    assert result.params.get("compose", {}).get("mode") == "free"
    # R22 F09 / R23 补盲区: 采纳后写回的矩形必须在**几何上真的生效**。
    # 原用例只断言 mode, 因此 "写回 px 值 + coord 缺省 norm" 的取景退化
    # （输出 1×1, 见 .artifacts/_r23_adopt_crop_probe.py）长期不可见。
    from pixo.render.modules.compose import compute_crop_rect

    cp = result.params["compose"]
    assert cp.get("coord") == "norm", "采纳后必须显式声明 norm 语义"
    h, w = _sky_image().shape[:2]
    rect = compute_crop_rect(h, w, "free", x=cp["x"], y=cp["y"],
                             width=cp["width"], height=cp["height"],
                             coord=cp["coord"])
    # 建议 [0.1, 0.1, 0.9, 0.9] → 64×64 上的中 80% 区域
    assert rect == (6, 6, 51, 51), f"裁剪矩形退化: {rect}"
    # 渲染序列: 首轮 (分割前, 无掩码) → 次轮 (旧构图掩码本应注入)
    assert len(backend.rendered_extras) >= 2
    assert "region_masks" not in backend.rendered_extras[0]
    # 关键断言: 采纳后区域效果消失 (掩码被失效, 而非携带旧几何继续作用)
    assert "region_masks" not in backend.rendered_extras[1]
    assert any("掩码缓存已失效" in r.message for r in caplog.records)
