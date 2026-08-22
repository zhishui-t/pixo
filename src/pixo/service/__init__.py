"""pixo.service —— Pixo 本地 FastAPI 服务。

一期提供照片导入/预览会话/参数 patch/generation/测量/决策/导出/健康接口。
"""
from __future__ import annotations

from .app import create_app
from .runtime import PhotoRecord, PixoServiceRuntime, SUPPORTED_EXTENSIONS

__all__ = [
    "create_app",
    "PixoServiceRuntime",
    "PhotoRecord",
    "SUPPORTED_EXTENSIONS",
]
