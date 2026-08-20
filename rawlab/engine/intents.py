"""rawlab.engine.intents —— 兼容 shim, 实现已迁至 rawlux.pipeline.intents。"""
from rawlux.pipeline.intents import (  # noqa: F401
    UnknownOp, ValueOutOfRange, UnknownFragment, EditIntent,
    apply_intents, parse_feedback, DAMPING,
)

__all__ = ["UnknownOp", "ValueOutOfRange", "UnknownFragment", "EditIntent",
           "apply_intents", "parse_feedback", "DAMPING"]
