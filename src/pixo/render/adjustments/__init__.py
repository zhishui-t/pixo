"""pixo.render.adjustments —— Phase C 规划的调整模块公开目录。

各子模块 re-export 现有 ``pixo.render.modules`` / ``pixo.render.core``
实现，旧路径继续可用。
"""
from __future__ import annotations

__all__ = [
    "exposure",
    "white_balance",
    "tone_curve",
    "highlights_shadows",
    "hsl",
    "color_calibration",
    "split_toning",
    "clarity_dehaze",
    "noise_reduction",
    "sharpening",
]
