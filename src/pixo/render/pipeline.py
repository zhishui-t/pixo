"""pixo.render.pipeline —— Phase C 规划公开入口。

当前实际实现仍保留在 ``pixo.render.pipeline`` 包内；本文件是规划中的
顶层模块结构占位，旧包路径继续可用。
"""
from __future__ import annotations

from .pipeline import (  # noqa: F401
    DEFAULT_STAGES,
    DOMAIN_GAMMA_RGB,
    DOMAIN_LINEAR_CAM,
    DOMAIN_LINEAR_RGB,
    STAGE_REGISTRY,
    Pipeline,
    Stage,
    StageContext,
    StageParams,
    StageResult,
    attach_prof,
    available_stages,
    build_default_pipeline,
    camera_key,
    find_camera_entry,
    load_camera_cache,
    pipeline_from_config,
    register_stage,
    render_dcp_linear,
)

__all__ = [
    "Pipeline",
    "Stage",
    "StageContext",
    "StageParams",
    "StageResult",
    "register_stage",
    "available_stages",
    "STAGE_REGISTRY",
    "DOMAIN_LINEAR_CAM",
    "DOMAIN_LINEAR_RGB",
    "DOMAIN_GAMMA_RGB",
    "DEFAULT_STAGES",
    "build_default_pipeline",
    "pipeline_from_config",
    "attach_prof",
    "camera_key",
    "load_camera_cache",
    "find_camera_entry",
    "render_dcp_linear",
]
