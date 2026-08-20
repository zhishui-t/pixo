"""rawlux.pipeline.context —— 管线运行上下文 (StageContext/StageParams/StageResult)。

迁移目标: 原 engine/core.py 中的上下文与运行记录类型。
当前阶段: 兼容回指 rawlab.engine.core, 公共符号不变; 迁移完成后改为本包原生实现。
"""
from __future__ import annotations

from rawlab.engine.core import (  # noqa: F401
    StageParams,
    StageContext,
    StageResult,
)

__all__ = ["StageParams", "StageContext", "StageResult"]
