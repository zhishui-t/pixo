"""rawlux.pipeline —— 管线框架 (惰性导出, 避免与 rawlab shim 循环 import)。"""
import importlib as _importlib

__all__ = [
    "context", "graph", "base", "presets",
    "StageContext", "StageParams", "StageResult",
    "Stage", "Pipeline", "register_stage", "available_stages", "STAGE_REGISTRY",
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
    "camera_key", "load_camera_cache", "find_camera_entry", "render_dcp_linear",
    "DEFAULT_STAGES", "build_default_pipeline", "pipeline_from_config", "attach_prof",
]

_SUBMODULES = {
    "context": ("StageContext", "StageParams", "StageResult"),
    "graph": ("Stage", "Pipeline", "register_stage", "available_stages",
              "STAGE_REGISTRY", "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB",
              "DOMAIN_GAMMA_RGB"),
    "base": ("camera_key", "load_camera_cache", "find_camera_entry",
             "render_dcp_linear"),
    "presets": ("DEFAULT_STAGES", "build_default_pipeline",
                "pipeline_from_config", "attach_prof"),
}


def __getattr__(name):
    if name in _SUBMODULES:
        return _importlib.import_module(f".{name}", __name__)
    for mod, names in _SUBMODULES.items():
        if name in names:
            module = _importlib.import_module(f".{mod}", __name__)
            return getattr(module, name)
    raise AttributeError(f"module 'rawlux.pipeline' has no attribute {name!r}")
