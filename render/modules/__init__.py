"""render.modules —— 可调参数渲染模块 (原生实现, 独立注册)。

目标结构 (迁移完成后原生实现):
  exposure.py / white_balance.py / huesat.py / tone_map.py / clarity.py
  dehaze.py / denoise.py / sharpen.py / vibrance.py / color_cal.py
  style.py / skin.py (外加 refine.py, 见该文件注释)

导入本包会触发全部 Stage 注册 (装饰器机制), 与引擎注册表一致。
保持原 Stage 名注册兼容: exposure / whitebalance / huesat / tone / clarity /
dehaze / denoise / sharpen / vibrance / colorcal / skin / stylize / refine。
"""
from . import exposure          # noqa: F401
from . import white_balance     # noqa: F401
from . import huesat            # noqa: F401
from . import tone_map          # noqa: F401
from . import clarity           # noqa: F401
from . import dehaze            # noqa: F401
from . import denoise           # noqa: F401
from . import sharpen           # noqa: F401
from . import vibrance          # noqa: F401
from . import color_cal         # noqa: F401
from . import skin              # noqa: F401
from . import style             # noqa: F401
from . import refine            # noqa: F401
from . import calibration      # noqa: F401
from . import hsl              # noqa: F401
from . import split_tone        # noqa: F401

from .exposure import ExposureStage
from .white_balance import WhiteBalanceStage
from .huesat import HueSatStage
from .tone_map import ToneStage
from .clarity import ClarityStage
from .dehaze import DehazeStage
from .denoise import DenoiseStage
from .sharpen import SharpenStage
from .vibrance import VibranceStage
from .color_cal import ColorCalStage
from .skin import SkinStage
from .style import StylizeStage
from .refine import RefineStage
from .calibration import CalibrationStage
from .hsl import HslStage
from .split_tone import SplitToneStage

__all__ = [
    "ExposureStage", "WhiteBalanceStage", "HueSatStage", "ToneStage",
    "ClarityStage", "DehazeStage", "DenoiseStage", "SharpenStage", "VibranceStage",
    "ColorCalStage", "CalibrationStage", "HslStage", "SkinStage", "StylizeStage",
    "RefineStage", "SplitToneStage",
]
