"""rawlab/engine/decode.py —— 兼容 shim, 真实实现已迁至 rawlux。保留旧 import 路径。"""
from rawlux.core.io import (  # noqa: F401
    decode_raw,
    decode_stage3_like,
    camera_neutral_wb,
    _read_opcode_list,
    _apply_vignette,
)

decode_dng_stage3_like = decode_stage3_like
_read_dng_opcode_list = _read_opcode_list
_apply_dng_vignette = _apply_vignette

__all__ = ["decode_raw", "decode_dng_stage3_like", "camera_neutral_wb", "_read_dng_opcode_list", "_apply_dng_vignette"]
