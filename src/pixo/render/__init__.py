"""pixo.render —— Pixo 渲染引擎独立包。

包内按 core / modules / pipeline 等组织。顶层公共 API 惰性加载,
独立引擎包。
"""
import importlib as _importlib

__version__ = "0.1.0"

__all__ = [
    "api",
    "Renderer", "RenderIntent", "RawInput", "RawMetadata", "CameraCalibration",
]


def __getattr__(name):
    if name == "api":
        return _importlib.import_module(".api", __name__)
    if name in ("Renderer", "RenderIntent", "RawInput", "RawMetadata",
                "CameraCalibration"):
        api = _importlib.import_module(".api", __name__)
        return getattr(api, name)
    raise AttributeError(f"module 'pixo.render' has no attribute {name!r}")
