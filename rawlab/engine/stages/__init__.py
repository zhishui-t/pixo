"""engine.stages —— 插件集合。

导入本包即完成全部插件注册 (装饰器机制), 无需手动列名。
"""
from . import exposure      # noqa: F401
from . import whitebalance  # noqa: F401
from . import tone          # noqa: F401
from . import huesat        # noqa: F401  (DCP HueSatMap/LookTable)
from . import reshape       # noqa: F401  (Phase 1.5 影调重塑层空壳)
from . import colorcal      # noqa: F401
from . import skin          # noqa: F401  (人像磨皮, order=55)
from . import stylize       # noqa: F401
from . import refine        # noqa: F401
from . import hsl           # noqa: F401  (人工 HSL 八色段, order=52)
from . import split_tone    # noqa: F401  (分离色调, order=54)

from .exposure import ExposureStage
from .whitebalance import WhiteBalanceStage
from .tone import ToneStage
from .huesat import HueSatStage
from .reshape import DehazeStage, ClarityStage, DenoiseStage, SharpenStage, VibranceStage
from .colorcal import ColorCalStage
from .skin import SkinStage
from .stylize import StylizeStage
from .refine import RefineStage
from .hsl import HslStage
from .split_tone import SplitToneStage
from .calibration import CalibrationStage

__all__ = ["ExposureStage", "WhiteBalanceStage", "ToneStage", "HueSatStage",
           "DehazeStage", "ClarityStage", "DenoiseStage", "SharpenStage", "VibranceStage",
           "ColorCalStage", "SkinStage", "StylizeStage", "RefineStage", "HslStage",
           "SplitToneStage",
           "CalibrationStage"]
