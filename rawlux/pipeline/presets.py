"""rawlux.pipeline.presets —— 默认管线组装 + JSON 配置驱动 (原生实现)。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .graph import Pipeline

# 默认管线顺序: 曝光 → 白平衡 → HueSatMap(默认关, 线性域、tone 前) → 影调
# → 清晰度(质感, 基座开) → 色彩校准(肤色保护) → 用户校准 → HSL → 分离色调
# → 磨皮(仅人像, wants 门控) → 风格化(LUT) → 精修
DEFAULT_STAGES = ["exposure", "whitebalance", "huesat", "tone", "clarity",
                  "colorcal", "calibration", "hsl", "split_tone",
                  "skin", "stylize", "refine"]


def build_default_pipeline(prof=None, style_lut=None,
                           params: Optional[Dict[str, Dict[str, Any]]] = None) -> Pipeline:
    """默认管线: 全链, 参数可覆盖。style_lut 非空时注入 stylize Stage。"""
    # 触发注册: 导入 rawlux.modules (装饰器注册所有插件)
    from rawlux import modules as _  # noqa: F401
    p = dict(params or {})
    if style_lut is not None:
        p.setdefault("stylize", {})["lut"] = style_lut
    pipe = Pipeline(stages=DEFAULT_STAGES, params=p)
    pipe.prof = prof
    return pipe


def pipeline_from_config(cfg: Dict[str, Any], prof=None) -> Pipeline:
    """从 JSON 配置构建管线。"""
    from rawlux import modules as _  # noqa: F401
    stages = cfg.get("stages") or DEFAULT_STAGES
    params = cfg.get("params") or {}
    pipe = Pipeline(stages=stages, params=params)
    pipe.prof = prof
    pipe.output = cfg.get("output") or {}
    return pipe


def attach_prof(pipe: Pipeline, prof):
    """管线绑定 DCP (run_file 时写入 ctx.prof)。"""
    pipe.prof = prof
    return pipe


__all__ = ["DEFAULT_STAGES", "build_default_pipeline", "pipeline_from_config",
           "attach_prof"]
