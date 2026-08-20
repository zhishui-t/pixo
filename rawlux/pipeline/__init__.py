"""rawlux.pipeline —— 管线框架 (兼容层)。

目标结构 (迁移完成后的原生实现):
  context.py  StageContext / StageParams / StageResult
  graph.py    Stage / Pipeline / register_stage / available_stages / DOMAIN_*
  base.py     render_base.py (DCP 底座渲染)
  presets.py  参数 Schema/预设 (DEFAULT_STAGES / build_default_pipeline / ...)

当前阶段: 各子模块均为 rawlab.engine 的兼容回指针, old import 保持可用。
"""
from . import context, graph, base, presets  # noqa: F401
from .context import StageContext, StageParams, StageResult  # noqa: F401
from .graph import (  # noqa: F401
    Stage,
    Pipeline,
    register_stage,
    available_stages,
    STAGE_REGISTRY,
    DOMAIN_LINEAR_CAM,
    DOMAIN_LINEAR_RGB,
    DOMAIN_GAMMA_RGB,
)
from .base import (  # noqa: F401
    camera_key,
    load_camera_cache,
    find_camera_entry,
    render_dcp_linear,
)
from .presets import (  # noqa: F401
    DEFAULT_STAGES,
    build_default_pipeline,
    pipeline_from_config,
    attach_prof,
)

__all__ = [
    "context", "graph", "base", "presets",
    "StageContext", "StageParams", "StageResult",
    "Stage", "Pipeline", "register_stage", "available_stages", "STAGE_REGISTRY",
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
    "camera_key", "load_camera_cache", "find_camera_entry", "render_dcp_linear",
    "DEFAULT_STAGES", "build_default_pipeline", "pipeline_from_config", "attach_prof",
]
