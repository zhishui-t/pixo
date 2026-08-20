"""rawlab.engine.render_base —— 兼容 shim, 实现已迁至 rawlux.pipeline.base。"""
from rawlux.pipeline.base import (  # noqa: F401
    camera_key, load_camera_cache, find_camera_entry, render_dcp_linear,
)

__all__ = ["camera_key", "load_camera_cache", "find_camera_entry",
           "render_dcp_linear"]
