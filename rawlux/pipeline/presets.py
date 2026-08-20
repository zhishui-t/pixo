"""rawlux.pipeline.presets —— 默认管线组装 + 参数预设 (兼容层, 回指 rawlab.engine.pipeline)。

迁移目标: 原 engine/pipeline.py 的默认管线顺序与 JSON 配置驱动
(DEFAULT_STAGES / build_default_pipeline / pipeline_from_config / attach_prof)。
当前阶段保留旧模块, 本文件仅作兼容回指, 公共符号不变。
"""
from __future__ import annotations

from rawlab.engine.pipeline import (  # noqa: F401
    DEFAULT_STAGES,
    build_default_pipeline,
    pipeline_from_config,
    attach_prof,
)

__all__ = ["DEFAULT_STAGES", "build_default_pipeline", "pipeline_from_config",
           "attach_prof"]
