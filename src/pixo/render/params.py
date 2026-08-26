"""pixo.render.params —— 集中导出 Stage 参数 schema 与常量。"""
from __future__ import annotations

from .modules.calibration import CalibrationStage
from .modules.clarity import ClarityStage
from .modules.color_cal import ColorCalStage
from .modules.compose import ComposeStage
from .modules.dehaze import DehazeStage
from .modules.denoise import DenoiseStage
from .modules.exposure import ExposureStage
from .modules.hsl import HslStage
from .modules.huesat import HueSatStage
from .modules.refine import RefineStage
from .modules.sharpen import SharpenStage
from .modules.skin import SkinStage
from .modules.split_tone import SplitToneStage
from .modules.style import StylizeStage
from .modules.tone_map import ToneStage
from .modules.reshape import VibranceStage
from .modules.white_balance import WhiteBalanceStage
from .pipeline.graph import (
    DOMAIN_GAMMA_RGB,
    DOMAIN_LINEAR_CAM,
    DOMAIN_LINEAR_RGB,
)
from .pipeline.presets import DEFAULT_STAGES

STAGE_CLASSES = {
    "exposure": ExposureStage,
    "whitebalance": WhiteBalanceStage,
    "compose": ComposeStage,
    "huesat": HueSatStage,
    "tone": ToneStage,
    "clarity": ClarityStage,
    "dehaze": DehazeStage,
    "denoise": DenoiseStage,
    "sharpen": SharpenStage,
    "vibrance": VibranceStage,
    "colorcal": ColorCalStage,
    "calibration": CalibrationStage,
    "hsl": HslStage,
    "split_tone": SplitToneStage,
    "skin": SkinStage,
    "stylize": StylizeStage,
    "refine": RefineStage,
}

PARAM_SCHEMAS = {
    name: cls.param_schema
    for name, cls in STAGE_CLASSES.items()
}
DEFAULT_PARAMS = {
    name: cls().default_params()
    for name, cls in STAGE_CLASSES.items()
}

# 常用兼容别名
STAGE_PARAM_SCHEMAS = PARAM_SCHEMAS
PARAM_SCHEMA = PARAM_SCHEMAS


def get_param_schema(stage: str) -> dict:
    """按 stage 名返回参数 schema。"""
    return dict(PARAM_SCHEMAS.get(stage, {}))


def get_default_params(stage: str) -> dict:
    """按 stage 名返回默认参数。"""
    return dict(DEFAULT_PARAMS.get(stage, {}))


__all__ = [
    "DEFAULT_STAGES",
    "DOMAIN_LINEAR_CAM",
    "DOMAIN_LINEAR_RGB",
    "DOMAIN_GAMMA_RGB",
    "STAGE_CLASSES",
    "PARAM_SCHEMAS",
    "STAGE_PARAM_SCHEMAS",
    "PARAM_SCHEMA",
    "DEFAULT_PARAMS",
    "get_param_schema",
    "get_default_params",
]
