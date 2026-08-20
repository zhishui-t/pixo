"""rawlux.core.curves —— 影调曲线原语 (兼容层, 回指 rawlab.engine.curves)。

迁移目标: 原 engine/curves.py 的查表曲线原语。
当前阶段保留旧模块, 本文件仅作兼容回指, 公共符号不变。
"""
from __future__ import annotations

from rawlab.engine.curves import *  # noqa: F401,F403

__all__ = [n for n in dir() if not n.startswith("_")]
