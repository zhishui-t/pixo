"""render.core —— 核心引擎模块 (原生引擎核心)。

目标结构 (迁移完成后的原生实现):
  io.py           原 engine/decode.py: decode_raw / stage3 输入
  color.py        原 engine/color.py: 色度学/矩阵
  calibration.py  DCP 解析与相机缓存
  curves.py       原 engine/curves.py
  tone.py         原 engine/dng_render.py (去 dng 命名)
  warp.py         原 engine/dng_warp.py (去 dng 命名)

当前阶段: 各子模块为 render 原生实现。
"""
from . import io, color, calibration, curves, tone, warp, calibration_store  # noqa: F401

__all__ = ["io", "color", "calibration", "curves", "tone", "warp",
           "calibration_store"]
