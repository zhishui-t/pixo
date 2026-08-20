"""rawlab.engine.stages.tone —— 兼容 shim, 实现已迁至 rawlux.modules.tone_map。"""
from rawlux.modules.tone_map import (  # noqa: F401
    ToneStage,
    _check_highlight_compress_curve,
)
__all__ = ["ToneStage", "_check_highlight_compress_curve"]
