"""rawlab.engine.hsl —— 兼容 shim, 实现已迁至 rawlux.core.hsl。"""
from rawlux.core.hsl import (  # noqa: F401
    H_MAX, DEFAULT_BANDS, hsl_adjust_rgb, _ring_mask,
)

__all__ = ["H_MAX", "DEFAULT_BANDS", "hsl_adjust_rgb", "_ring_mask"]
