"""rawlab.engine —— 插件化渲染引擎 (2026-08 重构)。

六阶段管线 (用户定稿顺序):
  1. exposure     曝光矫正 (linear_cam, 场景参考自动曝光)
  2. whitebalance 色彩矫正/白平衡 (linear_cam → linear_rgb)
  3. tone         影调重塑 (linear_rgb → gamma_rgb, 单一亮度曲线)
  4. colorcal     色彩校准 (gamma_rgb, Lab 域)
  5. stylize      风格化 (gamma_rgb, 3D LUT)
  6. refine       精修 (gamma_rgb, 高光去色/锐化/降噪)

导出:
  - Stage / StageContext / Pipeline / register_stage / available_stages
  - build_default_pipeline / pipeline_from_config
  - 色彩域常量 DOMAIN_*
"""
from .core import (
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
)
from .pipeline import (
    DEFAULT_STAGES,
    build_default_pipeline,
    pipeline_from_config,
)

__all__ = [
    "Stage", "StageContext", "StageResult", "StageParams", "Pipeline",
    "register_stage", "available_stages",
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
    "DEFAULT_STAGES", "build_default_pipeline", "pipeline_from_config",
]
