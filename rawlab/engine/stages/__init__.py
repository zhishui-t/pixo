"""engine.stages —— 六阶段插件集合。

导入本包即完成全部插件注册 (装饰器机制), 无需手动列名。
"""
from . import exposure      # noqa: F401
from . import whitebalance  # noqa: F401
from . import tone          # noqa: F401
from . import colorcal      # noqa: F401
from . import stylize       # noqa: F401
from . import refine        # noqa: F401

from .exposure import ExposureStage
from .whitebalance import WhiteBalanceStage
from .tone import ToneStage
from .colorcal import ColorCalStage
from .stylize import StylizeStage
from .refine import RefineStage

__all__ = ["ExposureStage", "WhiteBalanceStage", "ToneStage",
           "ColorCalStage", "StylizeStage", "RefineStage"]
