"""rawlab.engine.calibration —— 兼容 shim（属性写透传到 rawlux.core.calibration）。"""
import sys
import types

import rawlux.core.calibration as _impl
from rawlux.core.calibration import (  # noqa: F401
    camera_look_curves,
    camera_neutral_trim,
)

_CAL_FILE = _impl._CAL_FILE
_cached = _impl._cached


class _CalModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name in ("_CAL_FILE", "_cached"):
            setattr(_impl, name, value)


sys.modules[__name__].__class__ = _CalModule

__all__ = ["camera_look_curves", "camera_neutral_trim", "_CAL_FILE", "_cached"]
