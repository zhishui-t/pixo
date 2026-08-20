"""RawLux 渲染引擎统一 API (v0.1)。

当前底座阶段: Renderer.render 走 DNG 对齐 base 渲染;
RenderIntent.stages 为后续调色/风格化扩展占位, 现阶段不执行。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import numpy as np

from .pipeline.base import find_camera_entry, load_camera_cache, render_dcp_linear
from .pipeline.presets import build_default_pipeline, pipeline_from_config
from .core.tone import srgb_decode
from .core.calibration import DcpProfile, load_dcp


@dataclass
class RawMetadata:
    path: Path
    camera_rgb_shape: tuple[int, int, int]
    camera_key: str
    wb: Optional[np.ndarray] = None
    white_level: Optional[int] = None
    opcodes: Optional[dict] = None
    extras: dict = field(default_factory=dict)


@dataclass
class RawInput:
    """解码后的相机 RGB + 元数据。引擎内部统一入口。"""
    camera_rgb: np.ndarray
    metadata: RawMetadata


@dataclass
class CameraCalibration:
    """DCP profile + camera/lens 标定缓存。"""
    profile: DcpProfile
    camera_entry: dict
    source: Optional[Path] = None


@dataclass
class RenderIntent:
    """渲染意图: base 现在只支持 as_shot; stages 为后续风格化参数。"""
    base: str = "as_shot"
    exposure: float = 0.0
    stages: dict = field(default_factory=dict)


class Renderer:
    """RawLux 渲染器。"""

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
        """RenderIntent -> Pipeline stage 参数 dict (不修改原 intent)。"""
        params = {k: dict(v) for k, v in (intent.stages or {}).items()}
        if float(intent.exposure) != 0.0:
            params.setdefault("exposure", {})["mode"] = float(intent.exposure)
        return params

    def render_adjusted(self, raw_path, intent=None, half_size: bool = False):
        """走 Pipeline 默认链 + 调整参数, 返回 gamma uint8 (H,W,3)。"""
        if intent is None:
            intent = RenderIntent()
        pipe = build_default_pipeline(prof=self.profile,
                                      params=self._params_from_intent(intent))
        return pipe.run_file(str(raw_path), half_size=half_size)

    def render_preview(self, raw_path, half_size: bool = True) -> np.ndarray:
        """低分辨率快速预览: 轻量链 (Path(__file__).resolve().parents[1] / "presets" / "preview_fast.json"), 默认 half_size。

        预览目标"看得见、快": 只跑 [exposure, whitebalance, huesat, tone];
        由预设驱动 (pipeline_from_config), prof 用本 Renderer 的已加载 profile。
        """
        preset = (Path(__file__).resolve().parents[1] / "presets" / "preview_fast.json")
        cfg = json.loads(preset.read_text(encoding="utf-8"))
        pipe = pipeline_from_config(cfg, prof=self.profile)
        return pipe.run_file(str(raw_path), half_size=half_size)

    def render(self, raw: RawInput, calib: CameraCalibration,
               intent: Optional[RenderIntent] = None) -> np.ndarray:
        if intent is None:
            intent = RenderIntent()
        if float(intent.exposure) == 0.0 and not (intent.stages or {}):
            return render_dcp_linear(
                raw.metadata.path, self.dcp_path, cache=self.cache)
        disp = self.render_adjusted(raw.metadata.path, intent, half_size=False)
        lin = srgb_decode(np.asarray(disp, dtype=np.float32) / 255.0)
        return np.clip(np.asarray(lin, dtype=np.float32), 0.0, None)

    def render_file(self, raw_path: Union[str, Path],
                    intent: Optional[RenderIntent] = None) -> np.ndarray:
        """便捷入口: RAW 文件 -> 线性 sRGB float32。"""
        raw_path = Path(raw_path)
        calib = self.calibrate(raw_path)
        # 生产入口仍由 render_base 负责解码; RawInput 结构用于未来
        # 外部注入解码结果 (例如 C++ backend)。
        return self.render(
            RawInput(camera_rgb=np.zeros((1, 1, 3), np.float32),
                     metadata=RawMetadata(path=raw_path,
                                          camera_rgb_shape=(1, 1, 3),
                                          camera_key="")),
            calib, intent)


__all__ = ["Renderer", "RenderIntent", "RawInput", "RawMetadata",
           "CameraCalibration"]
