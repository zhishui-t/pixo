"""pixo.render.raw_loader —— RAW 解码公开接入层。

re-export 现有 ``pixo.render.core.io`` 的 RAW 解码与白平衡读取函数。
"""
from __future__ import annotations

from .core.io import (
    camera_neutral_wb,
    camera_neutral_wb_cached,
    decode_cfa_half,
    decode_raw,
    decode_stage3_like,
)

# 规划中的便捷别名
load_raw = decode_raw

__all__ = [
    "decode_raw",
    "decode_cfa_half",
    "decode_stage3_like",
    "camera_neutral_wb",
    "camera_neutral_wb_cached",
    "load_raw",
]
