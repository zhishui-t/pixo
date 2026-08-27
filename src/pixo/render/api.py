"""pixo.render 渲染引擎统一 API (v0.1)。

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


def _apply_orientation(img: np.ndarray, orientation) -> np.ndarray:
    """按 EXIF orientation (1/3/6/8) 旋转图像; 其它值原样返回 (L11 去重)。"""
    import cv2
    o = int(orientation)
    if o == 3:
        return cv2.rotate(img, cv2.ROTATE_180)
    if o == 6:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if o == 8:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _orientation_from_exif(raw_path: Union[str, Path]) -> int:
    """读 EXIF orientation; 缺失/异常回退 1 (不转)。"""
    try:
        from pixo.meta import extract as _extract
        return int((_extract(raw_path)["capture"].get("orientation") or 1))
    except Exception:
        return 1


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
    """pixo.render 渲染器。"""

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
        """低分辨率快速预览: 轻量链 (Path(__file__).resolve().parents[0] / "presets" / "preview_fast.json"), 默认 half_size。

        预览目标"看得见、快": 只跑 [exposure, whitebalance, huesat, tone];
        由预设驱动 (pipeline_from_config), prof 用本 Renderer 的已加载 profile。
        """
        preset = (Path(__file__).resolve().parents[3] / "configs" / "styles"
                     / "preview_fast.json")
        cfg = json.loads(preset.read_text(encoding="utf-8"))
        pipe = pipeline_from_config(cfg, prof=self.profile)
        return pipe.run_file(str(raw_path), half_size=half_size)

    def render_preview_full(self, raw_path: Union[str, Path], long_edge: int = 1024,
                            params: Optional[dict] = None, output_bps: int = 8,
                            decode_mode: str = "cfa_half_native") -> np.ndarray:
        """P1 全链路预览：完整 12 stage，长边 1024/2048，支持 8/16-bit 输出。

        decode_mode:
          - "cfa_half_native": 优先 C++ CFA 2×2 分箱；失败回退 rawpy AHD half。
          - 其它值: 直接走 rawpy AHD half 回退路径。

        样板 (ctx 构建/注入/终检/量化) 收敛在 pipeline.runner (三入口共用)。
        """
        import cv2
        import rawpy

        from .core.io import decode_cfa_half
        from .pipeline.runner import run_full_pipeline

        raw_path = Path(raw_path)
        params = dict(params or {})
        if output_bps not in (8, 16):
            raise ValueError("output_bps 只支持 8 或 16")

        raw = rawpy.imread(str(raw_path))
        try:
            img = None
            if decode_mode == "cfa_half_native":
                try:
                    img = decode_cfa_half(raw, raw_path=raw_path)
                except Exception:
                    img = None
            if img is None:
                rgb16 = raw.postprocess(
                    use_camera_wb=False,
                    output_bps=16,
                    output_color=rawpy.ColorSpace.raw,
                    no_auto_bright=True,
                    half_size=True,
                    user_wb=[1.0, 1.0, 1.0, 1.0],
                    demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                )
                img = rgb16.astype(np.float32) / 65535.0

            h, w = img.shape[:2]
            scale = float(long_edge) / max(h, w)
            if abs(scale - 1.0) > 1e-6:
                new_w = max(1, int(round(w * scale)))
                new_h = max(1, int(round(h * scale)))
                img = cv2.resize(img, (new_w, new_h),
                                 interpolation=cv2.INTER_AREA)

            pipe = build_default_pipeline(prof=self.profile, params=params)
            state_inject = {}
            try:
                from .core.io import camera_neutral_wb_cached
                state_inject["camera_wb"] = camera_neutral_wb_cached(raw, raw_path)
            except Exception:
                pass
            return run_full_pipeline(
                img, self.profile, params,
                config={"stages": dict(params), "half_size": True,
                        "decode_mode": decode_mode, "long_edge": int(long_edge),
                        "preview": True},
                output_bps=output_bps, mode="preview",
                raw_path=raw_path, raw=raw, state_inject=state_inject,
                pipe=pipe, label="预览管线")
        finally:
            try:
                raw.close()
            except Exception:
                pass

    def render_preview_degraded(self, raw_path: Union[str, Path],
                                half_size: bool = True) -> np.ndarray:
        """旧 preview_fast 轻量链，仅作 P-degraded 紧急兜底，不参与 P1 验收。"""
        return self.render_preview(raw_path, half_size=half_size)

    def render(self, raw: RawInput, calib: CameraCalibration,
               intent: Optional[RenderIntent] = None) -> np.ndarray:
        """渲染为线性 sRGB float32 (H,W,3), 可 >1 (高光余量)。

        - 默认 intent (无调整): render_dcp_linear 底座, 天然线性直出;
        - 带 intent: 全链渲染到 gamma float 后 srgb_decode 回线性 (L9 修复:
          旧实现经 render_adjusted 的 uint8 量化往返, 线性输出精度受损;
          gamma encode→decode 的 float 往返本身近无损, 损失全在 8bit 量化,
          现直接取管线 float 输出解码, 免除量化损失)。
        """
        if intent is None:
            intent = RenderIntent()
        if float(intent.exposure) == 0.0 and not (intent.stages or {}):
            return render_dcp_linear(
                raw.metadata.path, self.dcp_path, cache=self.cache)
        gamma = self._render_adjusted_gamma_float(raw.metadata.path, intent)
        lin = srgb_decode(np.asarray(gamma, dtype=np.float32))
        return np.clip(np.asarray(lin, dtype=np.float32), 0.0, None)

    def _render_adjusted_gamma_float(self, raw_path, intent: RenderIntent) -> np.ndarray:
        """调整路径: 全链渲染, 返回 gamma 域 float32 (不量化)。

        状态语义与 render_adjusted→run_file 一致 (half_size=False,
        config 只带 stages; 不注入 camera_wb state), 仅免去 8bit 量化。
        """
        from .core.io import decode_raw
        from .pipeline.runner import run_pipeline_float

        raw_path = Path(raw_path)
        params = self._params_from_intent(intent)
        img, raw = decode_raw(str(raw_path), half_size=False)
        try:
            return run_pipeline_float(
                img, self.profile, params,
                config={"stages": dict(params), "half_size": False},
                mode="export", raw_path=raw_path, raw=raw,
                pipe=build_default_pipeline(prof=self.profile, params=params))
        finally:
            try:
                raw.close()
            except Exception:
                pass

    def render_camera_matched(self, raw_path: Union[str, Path], long_edge: int = 1024,
                               params: Optional[dict] = None, output_bps: int = 8,
                               iters: int = 8) -> np.ndarray:
        """渲染并自动用 RAW 内嵌相机预览做色彩/亮度校准。

        当 DCP 色彩矩阵不够准或出现绿偏时，用相机原图作为基准，
        迭代求解曝光偏移 + 白平衡 trim，使输出贴近相机原图。
        返回 RGB uint8/uint16（方向按 EXIF 转正）。
        """
        import cv2
        import numpy as np
        import rawpy

        raw_path = Path(raw_path)
        base = self.render_preview_full(
            raw_path, long_edge=512, output_bps=8,
            params={"exposure": {"mode": 0.0},
                    "whitebalance": {"trim": [1.0, 1.0, 1.0]}})
        with rawpy.imread(str(raw_path)) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                cam = cv2.imdecode(np.frombuffer(thumb.data, np.uint8), cv2.IMREAD_COLOR)
            else:
                cam = thumb.data
        cam_rgb = cv2.cvtColor(cam, cv2.COLOR_BGR2RGB)
        cam_rgb = _apply_orientation(cam_rgb, _orientation_from_exif(raw_path))

        target = cam_rgb.astype(np.float32).mean(axis=(0, 1))
        base_mean = base.astype(np.float32).mean(axis=(0, 1))
        ev = float(np.log2(target.mean() / max(base_mean.mean(), 1e-6)))
        trim = np.array([1.0, 1.0, 1.0], dtype=np.float64)
        for _ in range(int(iters)):
            img = self.render_preview_full(
                raw_path, long_edge=512, output_bps=8,
                params={"exposure": {"mode": ev},
                        "whitebalance": {"trim": trim.tolist()}})
            cur = img.astype(np.float32).mean(axis=(0, 1))
            ev += float(np.log2(target.mean() / max(cur.mean(), 1e-6)))
            trim = trim * (target / np.maximum(cur, 1e-6))
            trim = np.clip(trim, 0.3, 3.0)
            ev = float(np.clip(ev, -1.5, 1.5))

        final_params = dict(params or {})
        exp = final_params.setdefault("exposure", {})
        exp["mode"] = ev
        wb = final_params.setdefault("whitebalance", {})
        wb["trim"] = trim.tolist()
        final = self.render_preview_full(
            raw_path, long_edge=long_edge, params=final_params, output_bps=output_bps)
        final = _apply_orientation(final, _orientation_from_exif(raw_path))
        return final

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
