"""adjustments.hsl —— HSL 色彩调整公开接口。"""
from __future__ import annotations

from ..core.hsl import DEFAULT_BANDS, hsl_adjust_rgb
from ..modules.hsl import HslStage

__all__ = ["HslStage", "hsl_adjust_rgb", "DEFAULT_BANDS"]
