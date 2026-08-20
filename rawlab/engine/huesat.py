"""rawlab.engine.huesat —— 兼容 shim, 实现已迁至 rawlux.core.huesat。"""
from rawlux.core.huesat import (  # noqa: F401
    _hsv_to_rgb, _rgb_to_hsv, _srgb_encode_v, _srgb_decode_v, _sat_rolloff,
    decode_table, make_hue_sat_map, apply_table_to_hsv,
    get_hue_sat_table, get_look_table, apply_hue_sat_map,
    apply_hue_sat_map_prophoto, apply_look_table_prophoto, apply_look_table,
    apply_local_warm_sat,
)

__all__ = ["_hsv_to_rgb", "_rgb_to_hsv", "_srgb_encode_v", "_srgb_decode_v",
           "_sat_rolloff", "decode_table", "make_hue_sat_map", "apply_table_to_hsv",
           "get_hue_sat_table", "get_look_table", "apply_hue_sat_map",
           "apply_hue_sat_map_prophoto", "apply_look_table_prophoto", "apply_look_table",
           "apply_local_warm_sat"]
