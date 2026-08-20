"""rawlab.engine.decode —— 兼容 shim（属性写透传到 rawlux.core.io）。"""
import sys
import types

import rawlux.core.io as _impl
from rawlux.core.io import (  # noqa: F401
    decode_raw,
    decode_stage3_like,
    camera_neutral_wb,
    _read_opcode_list,
    _apply_vignette,
)


class _DecodeModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name in ("decode_raw", "decode_stage3_like", "camera_neutral_wb",
                    "_read_opcode_list", "_apply_vignette"):
            setattr(_impl, name, value)


sys.modules[__name__].__class__ = _DecodeModule

decode_dng_stage3_like = decode_stage3_like
_read_dng_opcode_list = _read_opcode_list
_apply_dng_vignette = _apply_vignette

__all__ = ["decode_raw", "decode_dng_stage3_like", "camera_neutral_wb",
           "_read_dng_opcode_list", "_apply_dng_vignette", "decode_stage3_like",
           "_read_opcode_list", "_apply_vignette"]
