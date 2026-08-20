"""rawlux —— RawLux 渲染引擎独立包。

包内按 core / modules / pipeline 组织。顶层公共 API 惰性加载,
避免迁移期 rawlab shim 的循环 import。rawlab 旧 import 继续可用。
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
    raise AttributeError(f"module 'rawlux' has no attribute {name!r}")
