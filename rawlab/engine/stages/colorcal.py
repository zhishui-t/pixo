"""rawlab.engine.stages.colorcal —— 兼容 shim, 实现已迁至 rawlux.modules.color_cal。"""
from rawlux.modules.color_cal import (  # noqa: F401
    ColorCalStage,
    _NEUTRAL_CENTERS, _SCENE_TRIM_BOUND, _check_scene_trim,
    _check_scene_skin_trim, _scene_skin_trim_for_wb, _check_scene_hue,
    _scene_hue_for_wb, _scene_trim_for_wb,
)
__all__ = ["ColorCalStage", "_NEUTRAL_CENTERS", "_SCENE_TRIM_BOUND",
           "_check_scene_trim", "_check_scene_skin_trim", "_scene_skin_trim_for_wb",
           "_check_scene_hue", "_scene_hue_for_wb", "_scene_trim_for_wb"]
