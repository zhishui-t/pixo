"""rawlux.pipeline.graph —— Stage/Pipeline 插件框架 (兼容层, 回指 rawlab.engine.core)。

迁移目标: 原 engine/core.py 中的插件框架 (Stage 基类 / Pipeline 调度 /
register_stage 注册表 / 色彩域常量)。
当前阶段保留旧模块, 本文件仅作兼容回指, 公共符号不变。
"""
from __future__ import annotations

from rawlab.engine.core import (  # noqa: F401
    Stage,
    Pipeline,
    register_stage,
    available_stages,
    STAGE_REGISTRY,
    DOMAIN_LINEAR_CAM,
    DOMAIN_LINEAR_RGB,
    DOMAIN_GAMMA_RGB,
)

__all__ = [
    "Stage", "Pipeline", "register_stage", "available_stages", "STAGE_REGISTRY",
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
]
