"""rawlux.api —— RawLux 公共 API 兼容层。

当前迁移过渡期: 直接从 rawlab.engine.api / rawlab.engine 回指导出,
保持公共符号 (Renderer / RenderIntent / RawInput / RawMetadata /
CameraCalibration) 不变。迁移完成后改为本包 core 内的原生实现。
"""
from __future__ import annotations

# 兼容层: 公共 API 回指 rawlab.engine (迁移完成前不删除)
from rawlab.engine.api import (  # noqa: F401
    Renderer,
    RenderIntent,
    RawInput,
    RawMetadata,
    CameraCalibration,
)

# 管线框架符号 (同样回指, 保持 rawlab.engine 顶层导出一致)
try:
    from rawlab.engine import (  # noqa: F401
        Stage,
        StageContext,
        StageResult,
        StageParams,
        Pipeline,
        register_stage,
        available_stages,
        DOMAIN_LINEAR_CAM,
        DOMAIN_LINEAR_RGB,
        DOMAIN_GAMMA_RGB,
        DEFAULT_STAGES,
        build_default_pipeline,
        pipeline_from_config,
    )
except ImportError:  # pragma: no cover - 骨架阶段不强求全部就位
    Stage = StageContext = StageResult = StageParams = Pipeline = None
    register_stage = available_stages = None
    DOMAIN_LINEAR_CAM = DOMAIN_LINEAR_RGB = DOMAIN_GAMMA_RGB = None
    DEFAULT_STAGES = build_default_pipeline = pipeline_from_config = None

__all__ = [
    "Renderer", "RenderIntent", "RawInput", "RawMetadata", "CameraCalibration",
    "Stage", "StageContext", "StageResult", "StageParams", "Pipeline",
    "register_stage", "available_stages",
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
    "DEFAULT_STAGES", "build_default_pipeline", "pipeline_from_config",
]
