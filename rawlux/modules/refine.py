"""rawlux.modules.refine —— 精修 Stage (兼容层, 回指 rawlab.engine.stages.refine)。

注: refactor 文档 modules/ 目标结构未单列 refine.py, 但 refine 是 engine
七阶段管线的第 7 阶段 (order=70), 不能丢失, 故保留为一个兼容 shim 模块。
"""
from __future__ import annotations

from rawlab.engine.stages.refine import RefineStage  # noqa: F401
from rawlab.engine.stages.refine import apply_warm_sat_gamma  # noqa: F401

__all__ = ["RefineStage", "apply_warm_sat_gamma"]
