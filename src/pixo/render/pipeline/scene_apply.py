"""engine.scene_apply —— 场景→风格预设注册表与应用 (阶段2, T4)。

职责 (软件设计 §2 / 规格 §1):
  - load_scene_presets() -> dict: 读 configs/styles/scenes.json (进程内缓存)。
  - apply_scene_preset(scene_id) -> (params, lut): 场景参数覆盖 + 可选 LUT id;
    未知场景 → ({}, None) 并告警。

预设格式 (scenes.json):
  {"<scene_id>": {"params": {"<stage>": {...}}, "lut": "<style_id>" | null}}
params 是引擎 Stage 参数覆盖 (三层覆盖的最外层), 经 param_schema 校验;
lut 指向 render.core.lut 注册的 LUT id (null = 不套 LUT)。

场景 id: portrait / landscape / night / street / food / mono (engine.scenes)。
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

_SCENES_FILE = (Path(__file__).resolve().parents[4] / "configs" / "styles"
                     / "scenes.json")
_cache: Optional[dict] = None


def load_scene_presets() -> dict:
    """读场景预设注册表 (进程内缓存; 文件缺失/非法 → 空表)。"""
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_SCENES_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
        if not isinstance(_cache, dict):
            _cache = {}
    return _cache


def _reset_caches() -> None:
    """测试隔离钩子: 还原模块级场景预设缓存初始态 (与 exposure/
    white_balance/tone_map 的同名钩子配套, 供测试 fixture 使用)。"""
    global _cache
    _cache = None


def apply_scene_preset(scene_id: str) -> Tuple[Dict[str, dict], Optional[str]]:
    """场景 id → (params 覆盖, LUT id)。

    - 已知场景: params = 该场景的 stage 参数覆盖 (dict 拷贝), lut = LUT id 或 None。
    - 未知场景: ({}, None) 并告警 (回退基座默认)。
    """
    presets = load_scene_presets()
    entry = presets.get(scene_id) if scene_id else None
    if not isinstance(entry, dict):
        warnings.warn(
            f"未知场景 '{scene_id}', 回退基座默认 (可用: {sorted(presets)})",
            stacklevel=2)
        return {}, None
    params = entry.get("params")
    if not isinstance(params, dict):
        params = {}
    lut = entry.get("lut")
    return {k: dict(v) for k, v in params.items() if isinstance(v, dict)}, \
        (str(lut) if lut else None)

__all__ = ["load_scene_presets", "apply_scene_preset"]
