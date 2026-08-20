"""rawlab.engine.pipeline —— 兼容 shim, 实现已迁至 rawlux.pipeline.presets。"""
from rawlux.pipeline.graph import Pipeline  # noqa: F401
from rawlux.pipeline.presets import (  # noqa: F401
    DEFAULT_STAGES, build_default_pipeline, pipeline_from_config, attach_prof,
)

__all__ = ["Pipeline", "DEFAULT_STAGES", "build_default_pipeline",
           "pipeline_from_config", "attach_prof"]
