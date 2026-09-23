"""R22 dev-3 探针：25 张卡 + 6 场景预设 params 键 vs 派生 schema 全量比对。

输出：逐卡违规清单（未知 stage / 未知键 / 越域数值）+ 汇总。
用途：确认「卡注入」不会被 F04 栅栏误拒（design §5 风险）。
"""
import json
from pathlib import Path

from pixo.know.cards import StyleCard
from pixo.render import modules as _stages  # noqa: F401  触发注册
from pixo.render.pipeline.graph import STAGE_REGISTRY
from pixo.render.params import PARAM_SCHEMAS
from pixo.render.pipeline.scene_apply import apply_scene_preset, load_scene_presets


def check_bucket(stage: str, key: str, value):
    """返回违规描述或 None。"""
    if stage not in PARAM_SCHEMAS:
        return f"未知 stage '{stage}'"
    schema = PARAM_SCHEMAS[stage].get(key)
    if schema is None:
        return f"未知键 {stage}.{key}={value!r}"
    typ = schema.get("type")
    if typ == "float" and not isinstance(value, (int, float)):
        return f"类型不符 {stage}.{key}={value!r} 期望 {typ}"
    if typ == "bool" and not isinstance(value, bool):
        return f"类型不符 {stage}.{key}={value!r} 期望 {typ}"
    if typ == "str" and not isinstance(value, str):
        return f"类型不符 {stage}.{key}={value!r} 期望 {typ}"
    if typ == "float_or_str" and not isinstance(value, (int, float, str, list, dict)):
        return f"类型不符 {stage}.{key}={value!r} 期望 {typ}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in schema and value < schema["min"]:
            return f"越域 {stage}.{key}={value} < min={schema['min']}"
        if "max" in schema and value > schema["max"]:
            return f"越域 {stage}.{key}={value} > max={schema['max']}"
    if "choices" in schema and value not in schema["choices"]:
        return f"越枚举 {stage}.{key}={value!r} 不在 {schema['choices']}"
    return None


violations = []
cards = StyleCard.from_films_dir()
for card in cards:
    sid = card["style_id"]
    for stage, bucket in (card.get("params") or {}).items():
        if not isinstance(bucket, dict):
            violations.append(f"{sid}: {stage} 非 dict")
            continue
        for key, value in bucket.items():
            bad = check_bucket(stage, key, value)
            if bad:
                violations.append(f"{sid}: {bad}")
    for stage in card.get("stages") or []:
        if stage not in STAGE_REGISTRY:
            violations.append(f"{sid}: stages 含未注册 stage '{stage}'")

print(f"卡数 = {len(cards)}")
print(f"卡违规数 = {len(violations)}")
for v in violations:
    print("  -", v)

# 场景预设
scenes = load_scene_presets()
print(f"\n场景数 = {len(scenes)} ids={sorted(scenes)}")
sviol = []
for scene_id in sorted(scenes):
    params, lut = apply_scene_preset(scene_id)
    if lut is not None:
        sviol.append(f"{scene_id}: lut={lut!r} 非 null")
    for stage, bucket in params.items():
        for key, value in bucket.items():
            bad = check_bucket(stage, key, value)
            if bad:
                sviol.append(f"{scene_id}: {bad}")
print(f"场景违规数 = {len(sviol)}")
for v in sviol:
    print("  -", v)

# 空 schema stage 清单（栅栏对它们任何键一律拒——需确认无人写）
empty = sorted(n for n, s in PARAM_SCHEMAS.items() if not s)
print(f"\n空 param_schema stage = {empty}")
print("路径类键（*_path/*_file）= ", sorted(
    f"{st}.{k}" for st, s in PARAM_SCHEMAS.items() for k in s
    if k.endswith("_path") or k.endswith("_file")))
