"""rawlab/engine/dng_render.py —— 兼容 shim, 真实实现已迁至 rawlux。保留旧 import 路径。"""
from rawlux.core.tone import (  # noqa: F401
    exposure_ramp,
    table_interp,
    srgb_encode,
    srgb_decode,
    tone_table_interp,
    apply_rgb_tone,
    load_tone_table,
    build_tonetable,
    apply_hue_sat_map,
)

dng_exposure_ramp = exposure_ramp
dng_table_interp = table_interp
dng_srgb_encode = srgb_encode
dng_srgb_decode = srgb_decode
apply_dng_rgb_tone = apply_rgb_tone
load_dng_tone_table = load_tone_table
dng_build_tonetable = build_tonetable
apply_dng_hue_sat_map = apply_hue_sat_map

__all__ = ["dng_exposure_ramp", "dng_table_interp", "dng_srgb_encode", "dng_srgb_decode", "tone_table_interp", "apply_dng_rgb_tone", "load_dng_tone_table", "dng_build_tonetable", "apply_dng_hue_sat_map"]
