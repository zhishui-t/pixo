"""rawlab.engine —— 插件化渲染引擎 (2026-08 重构)。

七阶段管线 (用户定稿顺序, order 值见 @register_stage):
  1. exposure     (order=10) 曝光矫正 (linear_cam, 场景参考自动曝光)
  2. whitebalance (order=20) 色彩矫正/白平衡 (linear_cam → linear_rgb)
  3. huesat       (order=25) DCP HueSatMap/LookTable 观感 (linear_rgb,
                             线性 ProPhoto 域查表、影调曲线之前, 默认关)
  4. tone         (order=30) 影调重塑 (linear_rgb → gamma_rgb, 单一亮度曲线)
  5. colorcal     (order=50) 色彩校准 (gamma_rgb, Lab 域)
  6. stylize      (order=60) 风格化 (gamma_rgb, 3D LUT)
  7. refine       (order=70) 精修 (gamma_rgb, 高光去色/锐化/降噪)

另: stages/reshape.py 预留 Phase 1.5 影调重塑层空壳 Stage
(dehaze/clarity/denoise/sharpen/vibrance, order 45..49, 默认不启用)。

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
