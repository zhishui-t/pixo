"""rawlux.core.tone —— 影调重塑数值函数 (兼容层, 回指 rawlab.engine.dng_render)。

迁移目标: 原 engine/dng_render.py (去掉 dng 文件名), 公共函数名去 dng 前缀
后仍须可用; 当前阶段保留旧模块 (rawlab.engine 旧名继续可用)。
公开面已剔除全部 dng_ 符号: dng 名以私有导入绑定, 对外只暴露 clean 名。
"""
from __future__ import annotations

# dng 底层以私有名导入, 不进入模块公开命名空间
from rawlab.engine.dng_render import (  # noqa: F401
    dng_exposure_ramp as _dng_exposure_ramp,
    dng_srgb_encode as _dng_srgb_encode,
    dng_srgb_decode as _dng_srgb_decode,
    dng_table_interp as _dng_table_interp,
    dng_build_tonetable as _dng_build_tonetable,
    apply_dng_rgb_tone as _apply_dng_rgb_tone,
    load_dng_tone_table as _load_dng_tone_table,
    apply_dng_hue_sat_map as _apply_dng_hue_sat_map,
    tone_table_interp,
)

# 去 dng_ 前缀别名 (迁移规范: 禁止 dng_ 公开符号)
exposure_ramp = _dng_exposure_ramp
srgb_encode = _dng_srgb_encode
srgb_decode = _dng_srgb_decode
table_interp = _dng_table_interp
build_tonetable = _dng_build_tonetable
apply_rgb_tone = _apply_dng_rgb_tone
load_tone_table = _load_dng_tone_table
apply_hue_sat_map = _apply_dng_hue_sat_map

__all__ = [
    "tone_table_interp",
    # 去 dng 前缀的 clean 别名
    "exposure_ramp", "srgb_encode", "srgb_decode", "table_interp",
    "build_tonetable", "apply_rgb_tone", "load_tone_table",
    "apply_hue_sat_map",
]
