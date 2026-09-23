"""R22 dev-3 探针：导出全部 Stage param_schema（栅栏派生依据）。"""
import json
import sys

from pixo.render import modules as _stages  # noqa: F401  触发 Stage 注册
from pixo.render.pipeline.graph import STAGE_REGISTRY
from pixo.render.pipeline.presets import DEFAULT_STAGES

rows = {}
for name, cls in sorted(STAGE_REGISTRY.items()):
    schema = getattr(cls, "param_schema", None) or {}
    rows[name] = {k: dict(v) for k, v in schema.items()}

print("DEFAULT_STAGES =", DEFAULT_STAGES)
print("REGISTERED =", sorted(STAGE_REGISTRY))
print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
