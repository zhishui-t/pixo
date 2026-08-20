"""rawlux.core.warp —— 几何校正 (兼容层, 回指 rawlab.engine.dng_warp)。

迁移目标: 原 engine/dng_warp.py (去掉 dng 文件名), WarpRectilinear 实现。
当前阶段保留旧模块, 本文件仅作兼容回指 (rawlab.engine 旧名继续可用)。
公开面已剔除 dng_ 符号: dng 名以私有导入绑定, 对外只暴露 clean 名。
"""
from __future__ import annotations

from rawlab.engine.dng_warp import dng_warp_rectilinear as _dng_warp_rectilinear  # noqa: F401

# 去 dng_ 前缀别名 (迁移规范: 禁止 dng_ 公开符号)
warp_rectilinear = _dng_warp_rectilinear

__all__ = ["warp_rectilinear"]
