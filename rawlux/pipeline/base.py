"""rawlux.pipeline.base —— DCP 底座渲染 (兼容层, 回指 rawlab.engine.render_base)。

迁移目标: 原 engine/render_base.py 的 NEF/DNG + DCP -> 线性 sRGB 底座渲染
(camera_key / load_camera_cache / find_camera_entry / render_dcp_linear)。
当前阶段保留旧模块, 本文件仅作兼容回指, 公共符号不变。
"""
from __future__ import annotations

from rawlab.engine.render_base import (  # noqa: F401
    camera_key,
    load_camera_cache,
    find_camera_entry,
    render_dcp_linear,
)

__all__ = ["camera_key", "load_camera_cache", "find_camera_entry",
           "render_dcp_linear"]
