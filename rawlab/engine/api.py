"""rawlab.engine.api —— 兼容 shim（含 monkeypatch 友好的 Renderer 子类）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

import numpy as np

from rawlux import api as _impl
from rawlux.api import (  # noqa: F401
    RenderIntent, RawInput, RawMetadata, CameraCalibration,
)
from rawlux.core.calibration import DcpProfile, load_dcp
from rawlux.core.tone import srgb_decode
from rawlux.pipeline.base import find_camera_entry, load_camera_cache, render_dcp_linear
from rawlux.pipeline.presets import build_default_pipeline, pipeline_from_config


class Renderer(_impl.Renderer):
    """兼容 shim 子类：使用本模块可 monkeypatch 的函数，保持旧测试/调用可用。"""

    def __init__(self, dcp_path: Union[str, Path],
                 cache_path: Union[str, Path, None] = None):
        self.dcp_path = Path(dcp_path)
        self.profile = load_dcp(self.dcp_path)
        self.cache = load_camera_cache(cache_path)

    def calibrate(self, raw_path: Union[str, Path]) -> CameraCalibration:
        raw_path = Path(raw_path)
        entry = find_camera_entry(raw_path, self.cache)
        return CameraCalibration(profile=self.profile, camera_entry=entry,
                                 source=raw_path)

    def _params_from_intent(self, intent: RenderIntent) -> dict:
        params = {k: dict(v) for k, v in (intent.stages or {}).items()}
        if float(intent.exposure) != 0.0:
            params.setdefault("exposure", {})["mode"] = float(intent.exposure)
        return params

    def render_adjusted(self, raw_path, intent=None, half_size: bool = False):
        if intent is None:
            intent = RenderIntent()
        pipe = build_default_pipeline(prof=self.profile,
                                      params=self._params_from_intent(intent))
        return pipe.run_file(str(raw_path), half_size=half_size)

    def render(self, raw: RawInput, calib: CameraCalibration,
               intent: Optional[RenderIntent] = None) -> np.ndarray:
        if intent is None:
            intent = RenderIntent()
        if float(intent.exposure) == 0.0 and not (intent.stages or {}):
            return render_dcp_linear(raw.metadata.path, self.dcp_path,
                                     cache=self.cache)
        disp = self.render_adjusted(raw.metadata.path, intent, half_size=False)
        lin = srgb_decode(np.asarray(disp, dtype=np.float32) / 255.0)
        return np.clip(np.asarray(lin, dtype=np.float32), 0.0, None)

    def render_file(self, raw_path: Union[str, Path],
                    intent: Optional[RenderIntent] = None) -> np.ndarray:
        raw_path = Path(raw_path)
        calib = self.calibrate(raw_path)
        return self.render(
            RawInput(camera_rgb=np.zeros((1, 1, 3), np.float32),
                     metadata=RawMetadata(path=raw_path,
                                          camera_rgb_shape=(1, 1, 3),
                                          camera_key="")),
            calib, intent)

    def render_preview(self, raw_path, half_size: bool = True) -> np.ndarray:
        preset = Path(__file__).resolve().parents[2] / "rawlux" / "presets" / "preview_fast.json"
        cfg = json.loads(preset.read_text(encoding="utf-8"))
        pipe = pipeline_from_config(cfg, prof=self.profile)
        return pipe.run_file(str(raw_path), half_size=half_size)


__all__ = ["Renderer", "RenderIntent", "RawInput", "RawMetadata",
           "CameraCalibration", "DcpProfile", "load_dcp", "load_camera_cache",
           "render_dcp_linear", "build_default_pipeline", "pipeline_from_config",
           "find_camera_entry"]
