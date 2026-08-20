"""rawlab.engine.core —— 兼容 shim, 真实实现已迁至 rawlux.pipeline。"""
from rawlux.pipeline.graph import (  # noqa: F401
    DOMAIN_LINEAR_CAM, DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB,
    StageParams, StageContext, StageResult, Stage,
    register_stage, STAGE_REGISTRY, available_stages, Pipeline,
)

__all__ = [
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
    "StageParams", "StageContext", "StageResult", "Stage",
    "register_stage", "STAGE_REGISTRY", "available_stages", "Pipeline",
]
