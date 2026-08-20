"""rawlux.core —— 核心引擎模块 (从 rawlab.engine 迁移, 兼容层阶段)。

目标结构 (迁移完成后的原生实现):
  io.py           原 engine/decode.py: decode_raw / stage3 输入
  color.py        原 engine/color.py: 色度学/矩阵
  calibration.py  原 rawlab/dcp.py + dng_camera_cache 合并入口
  curves.py       原 engine/curves.py
  tone.py         原 engine/dng_render.py (去 dng 命名)
  warp.py         原 engine/dng_warp.py (去 dng 命名)

当前阶段: 各子模块均为 rawlab.engine 的兼容回指针, old import 保持可用。
"""
from . import io, color, calibration, curves, tone, warp  # noqa: F401

__all__ = ["io", "color", "calibration", "curves", "tone", "warp"]
