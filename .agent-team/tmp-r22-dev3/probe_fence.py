"""R22 dev-3 探针：参数栅栏行为快速自检（正/反向）。"""
from pixo.render.web.session import (ParamValidationError,
                                     RawPreviewSession,
                                     validate_param_patch)

POSITIVE = [
    {"exposure": {"mode": 0.5}},
    {"whitebalance": {"temp": 5200.0, "tint": -10.0}},
    {"tone": {"highlights": -0.2, "shadows": 0.1, "contrast": 0.3}},
    {"clarity": {"strength": 0.5, "enabled": True}},
    {"colorcal": {"saturation": 0.2, "color_domain": "oklch"}},
    {"hsl": {"enabled": True, "color_domain": "oklch",
             "bands": [{"name": "red", "hue_center": 20, "hue_shift": 3.0}]}},
    {"calibration": {"red_hue": -30.0, "red_sat": 12.0}},
    {"split_tone": {"highlights_sat": 40.0, "shadows_hue": 200.0}},
    {"compose": {"mode": "ratio", "ratio": "16:9", "center": [0.5, 0.5]}},
    {"region_adjust": {"enabled": True,
                       "regions": {"sky": {"exposure": -0.5}}}},
    {"refine": {"sharpen": 0.2, "chroma_denoise": 0.8}},
    {"stylize": {}},
    {"dehaze": {"enabled": False, "strength": 0.0}},
    {"exposure": {}},
    {"tone": {"highlights": None}},
]
NEGATIVE = [
    ({"s1": {"x": 1}}, "未知 stage"),
    ({"tone": {"nope": 1}}, "未知键"),
    ({"tone": {"contrast": 5}}, "越域高"),
    ({"tone": {"highlights": -20}}, "越域低"),
    ({"stylize": {"lut_path": "C:/x.cube"}}, "lut_path 路径键"),
    ({"whitebalance": {"warm_cal_file": "/tmp/x.json"}}, "路径键"),
    ({"huesat": {"oklch_points_file": "..\\x.json"}}, "路径键2"),
    ({"compose": {"ratio": "..\\..\\x"}}, "路径形态值"),
    ({"stylize": {"lut": "velvia"}}, "LUT 激活"),
    ({"colorcal": {"neutral_mode": "bogus"}}, "越枚举"),
    ({"compose": {"rotation": float("nan")}}, "NaN"),
    ({"compose": {"rotation": float("inf")}}, "Inf"),
    ({"tone": 5}, "非 dict 桶"),
    ({"__meta__": {"scene": "x"}}, "控制键/未知 stage"),
    ([1, 2], "非 dict patch"),
]

bad = 0
for patch in POSITIVE:
    try:
        validate_param_patch(patch, strict=True)
    except ParamValidationError as exc:
        bad += 1
        print(f"[FAIL 正向被拒] {patch} -> {exc}")
print(f"正向 strict 通过 = {len(POSITIVE) - bad}/{len(POSITIVE)}")

for patch, why in NEGATIVE:
    try:
        validate_param_patch(patch, strict=True)
        bad += 1
        print(f"[FAIL 反向被放行] {why}: {patch}")
    except ParamValidationError as exc:
        print(f"[OK 反向拒绝] {why}: {exc}")

# 非 strict（缺省会话）：敏感面恒检，合成 stage 放行
for patch in ({"s1": {"x": 1}}, {"s2": {"value": 0.75}}, {"wb": {"gain": 0.5}}):
    validate_param_patch(patch, strict=False)
print("非 strict 合成 stage 放行 = OK")
for patch in ({"stylize": {"lut_path": "/x.cube"}}, {"tone": {"user_curve": "../x"}}):
    try:
        validate_param_patch(patch, strict=False)
        bad += 1
        print(f"[FAIL 非 strict 敏感面漏检] {patch}")
    except ParamValidationError as exc:
        print(f"[OK 非 strict 拒绝敏感面] {exc}")

sess = RawPreviewSession("x.nef", prof=object())
sess.update_params({"s1": {"x": 1}})
print("缺省会话合成 stage =", sess.params, "gen =", sess.generation)
try:
    sess.update_params({"stylize": {"lut_path": "/x.cube"}})
    bad += 1
    print("[FAIL] 缺省会话漏检 lut_path")
except ParamValidationError as exc:
    print("[OK 缺省会话拒 lut_path]", exc)

print("=== 失败项 =", bad)
