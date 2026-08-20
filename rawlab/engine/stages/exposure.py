"""rawlab.engine.stages.exposure —— 兼容 shim（含 monkeypatch 友好的缓存加载器）。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from rawlux.modules import exposure as _impl  # noqa: F401
from rawlux.modules.exposure import (  # noqa: F401
    LOG2_GRAY, soft_highlight_rolloff, ExposureStage,
    _luma_proxy, _vignette_lift_linear, _BASELINE_EV_BOUND,
    _check_baseline_ev_curve, _baseline_curve_ev,
    _check_baseline_scene_ev, _baseline_scene_ev, _probe_linear_srgb,
)

# 兼容测试对 shim 模块 monkeypatch 的需求：本地缓存变量与加载函数。
_CAL_FILE = _impl._CAL_FILE
_cached_offset = _impl._cached_offset
_cached_table = _impl._cached_table


def _load_target_offset() -> float:
    global _cached_offset
    if _cached_offset is None:
        try:
            if _CAL_FILE.exists():
                _cached_offset = float(json.loads(
                    _CAL_FILE.read_text(encoding="utf-8")).get("target_offset", 0.0))
            else:
                _cached_offset = 0.0
        except Exception:
            _cached_offset = 0.0
    return _cached_offset


def _load_cal_table():
    global _cached_table
    if _cached_table is None:
        _cached_table = False
        try:
            if _CAL_FILE.exists():
                tbl = json.loads(_CAL_FILE.read_text(encoding="utf-8")).get("cal_table")
                if tbl and len(tbl) >= 3:
                    xs = np.array([t[0] for t in tbl], dtype=np.float64)
                    ys = np.array([t[1] for t in tbl], dtype=np.float64)
                    if np.all(np.diff(xs) > 0):
                        _cached_table = (xs, ys)
        except Exception:
            _cached_table = False
    return _cached_table if _cached_table else None


class ExposureStage(_impl.ExposureStage):
    """兼容 shim 子类：default_params 的 target_offset 走本 shim 的 loader，支持 monkeypatch。"""

    def default_params(self):
        params = super().default_params()
        params["target_offset"] = _load_target_offset()
        return params


__all__ = ["LOG2_GRAY", "soft_highlight_rolloff", "ExposureStage", "_CAL_FILE",
           "_load_target_offset", "_load_cal_table", "_luma_proxy",
           "_vignette_lift_linear", "_BASELINE_EV_BOUND", "_check_baseline_ev_curve",
           "_baseline_curve_ev", "_check_baseline_scene_ev", "_baseline_scene_ev",
           "_probe_linear_srgb", "_cached_offset", "_cached_table"]
