"""pixo.render 预览会话与缓存增量（v1.5）。

提供 RawPreviewSession：
- RAW 解码只做一次（L1 decode 缓存）
- 各 long_edge 等比缩放缓存（L2）
- 按 stage 参数指纹 + 输入指纹缓存中间输出（L3，LRU）
- generation 令牌：参数每次更新 +1，编码缓存按 generation 失效
- 8-bit/16-bit 编码复用 render.web.encode
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
import rawpy

from pixo.render.core.io import decode_cfa_half
from pixo.render.pipeline.context import (DOMAIN_GAMMA_RGB, DOMAIN_LINEAR_CAM,
                                     StageContext)
from pixo.render.pipeline.presets import build_default_pipeline

from .encode import encode_image


def _param_fingerprint(params: Any) -> str:
    text = json.dumps(params, sort_keys=True, default=str,
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def _array_fingerprint(arr: np.ndarray) -> str:
    a = np.ascontiguousarray(arr)
    h = hashlib.sha256(a.tobytes()).hexdigest()
    return f"{h}:{a.shape}:{a.dtype.str}"


def _state_fingerprint(state: dict) -> str:
    """对 ctx.state 做规范化指纹，包含 ndarray 内容。

    用于 stage 缓存 key：即使输入图像与 stage 参数相同，若 wb/ev/cct/
    scene_trim 等 state 变化，也必须让缓存失效。
    """
    def _norm(value):
        if isinstance(value, np.ndarray):
            arr = np.ascontiguousarray(value)
            digest = hashlib.sha256(arr.tobytes()).hexdigest()
            return {"__ndarray__": True, "shape": list(arr.shape),
                    "dtype": arr.dtype.str, "sha256": digest}
        if isinstance(value, dict):
            return {str(k): _norm(v) for k, v in sorted(value.items(),
                                                        key=lambda kv: str(kv[0]))}
        if isinstance(value, (list, tuple)):
            return [_norm(v) for v in value]
        if isinstance(value, (np.floating, np.integer)):
            return value.item()
        return value

    text = json.dumps(_norm(state), sort_keys=True, default=str,
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(text).hexdigest()


class StaleGenerationError(RuntimeError):
    """异步任务完成时 generation 已过期，结果应被丢弃。"""


def _deep_merge(base: dict, update: dict) -> None:
    """递归合并 stage 参数：部分更新不覆盖同 stage 的其它参数。"""
    for key, value in update.items():
        if (key in base and isinstance(base[key], dict)
                and isinstance(value, dict)):
            _deep_merge(base[key], value)
        else:
            base[key] = value


class RawPreviewSession:
    """单张 RAW 的预览会话缓存。"""

    def __init__(self, raw_path, prof, params: Optional[dict] = None,
                 session_id: Optional[str] = None,
                 max_stage_entries: int = 64,
                 max_encoding_entries: int = 32,
                 max_stage_bytes: int = 512 * 1024 * 1024):
        self.raw_path = Path(raw_path)
        self.prof = prof
        self.params = dict(params or {})
        self.generation = 0
        self.session_id = session_id or uuid.uuid4().hex
        self.max_stage_entries = max_stage_entries
        self.max_encoding_entries = max_encoding_entries
        self.max_stage_bytes = max_stage_bytes

        self._decode_cache: dict[str, np.ndarray] = {}
        self._decode_wb: dict[str, np.ndarray | None] = {}
        self._tier_cache: dict[tuple, np.ndarray] = {}
        self._stage_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
        self._encoding_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._async_lock = threading.Lock()
        self._latest_result: dict[int, np.ndarray] = {}
        self._closed = False

    def close(self) -> None:
        """关闭后台线程池；不再接受新的异步任务。"""
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    # ---- 参数 / generation ----
    def update_params(self, new_params: dict) -> int:
        """递归合并更新参数并递增 generation，返回新 generation。"""
        _deep_merge(self.params, dict(new_params or {}))
        self.generation += 1
        return self.generation

    def _raw_version(self) -> tuple[int, int]:
        """RAW 文件版本指纹：同路径文件被替换时缓存自动失效。"""
        try:
            st = self.raw_path.stat()
            return (int(st.st_mtime_ns), st.st_size)
        except OSError:
            return (0, 0)

    # ---- 缓存 ----
    def _get_decode(self, decode_mode: str) -> np.ndarray:
        version = self._raw_version()
        key = (decode_mode, version)
        if key in self._decode_cache:
            return self._decode_cache[key]

        raw = rawpy.imread(str(self.raw_path))
        try:
            img = None
            if decode_mode == "cfa_half_native":
                try:
                    img = decode_cfa_half(raw, raw_path=self.raw_path)
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
            try:
                from pixo.render.core.io import camera_neutral_wb_cached
                wb = camera_neutral_wb_cached(raw, self.raw_path)
            except Exception:
                wb = None
        finally:
            try:
                raw.close()
            except Exception:
                pass
        self._decode_cache[key] = img
        self._decode_wb[key] = wb
        return img

    def _get_tier(self, long_edge: int, decode_mode: str) -> np.ndarray:
        key = (int(long_edge), decode_mode, self._raw_version())
        if key in self._tier_cache:
            return self._tier_cache[key]

        img = self._get_decode(decode_mode)
        h, w = img.shape[:2]
        scale = float(long_edge) / max(h, w)
        if abs(scale - 1.0) > 1e-6:
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        self._tier_cache[key] = img
        return img

    def _evict_stage_cache(self):
        """按条数与估算字节数做 LRU 淘汰。"""
        while len(self._stage_cache) > self.max_stage_entries:
            self._stage_cache.popitem(last=False)
        if self.max_stage_bytes > 0:
            while self._stage_cache:
                total = sum(
                    entry[0].nbytes + sum(v.nbytes for v in entry[2].values()
                                          if isinstance(v, np.ndarray))
                    for entry in self._stage_cache.values())
                if total <= self.max_stage_bytes:
                    break
                self._stage_cache.popitem(last=False)

    # ---- 渲染 ----
    def render(self, long_edge: int = 1024, output_bps: int = 8,
               decode_mode: str = "cfa_half_native",
               state_extras: Optional[dict] = None) -> np.ndarray:
        """渲染当前参数快照；返回 uint8 或 uint16 RGB。

        state_extras: 额外 state 注入（如归一化 face_boxes/subject_boxes），
        供 exposure 测光 subject_mode=box 消费（t92 原生框链路的 raw 侧缺口）。
        与原 state 键同名时以本参数为准；None/空 dict 不注入，行为与旧版一致。
        """
        return self._render_with_params(
            copy.deepcopy(self.params), long_edge, output_bps, decode_mode,
            state_extras=state_extras)

    def _render_with_params(self, params: dict, long_edge: int,
                            output_bps: int,
                            decode_mode: str,
                            state_extras: Optional[dict] = None) -> np.ndarray:
        """使用指定参数快照渲染（供异步任务调用，避免读到最新 params）。

        state_extras: 与 render() 同语义；注入发生在 stage 循环之前，并计入
        每级 stage 缓存的状态指纹，框变化会自然使 stage 缓存失效。
        """
        if output_bps not in (8, 16):
            raise ValueError("output_bps 只支持 8 或 16")
        img = self._get_tier(long_edge, decode_mode)

        pipe = build_default_pipeline(prof=self.prof, params=params)
        ctx = StageContext(
            self.raw_path, prof=self.prof,
            config={"stages": dict(params), "half_size": True,
                    "decode_mode": decode_mode, "long_edge": int(long_edge)})
        ctx.set_image(img.copy(), DOMAIN_LINEAR_CAM)
        ctx.state["half_size"] = True
        wb = self._decode_wb.get((decode_mode, self._raw_version()))
        if wb is not None:
            ctx.state["camera_wb"] = wb
        # t92 遗留闭合：归一化框（face_boxes/subject_boxes）注入 state，
        # exposure 测光 subject_mode=box 在 raw 会话同样生效
        # （与 SyntheticRenderBackend._render 的注入语义一致）。
        if isinstance(state_extras, dict) and state_extras:
            ctx.state.update(state_extras)

        for stage in pipe.stages:
            if not stage.wants(ctx):
                continue
            param_fp = _param_fingerprint(params.get(stage.name, {}))
            input_fp = _array_fingerprint(ctx.image)
            state_fp = _state_fingerprint(ctx.state)
            key = (stage.name, param_fp, input_fp, state_fp)
            if key in self._stage_cache:
                out, domain, state = self._stage_cache[key]
                ctx.image = out.copy()
                ctx.domain = domain
                ctx.state = copy.deepcopy(state)
                self._stage_cache.move_to_end(key)
            else:
                stage.run(ctx)
                self._stage_cache[key] = (
                    ctx.image.copy(), ctx.domain, copy.deepcopy(ctx.state))
                self._stage_cache.move_to_end(key)
                self._evict_stage_cache()

        if ctx.domain != DOMAIN_GAMMA_RGB:
            raise RuntimeError(
                f"预览管线最终域不是 {DOMAIN_GAMMA_RGB} 而是 {ctx.domain}")
        if output_bps == 16:
            return (np.clip(ctx.image, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
        return (np.clip(ctx.image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    # ---- 异步 generation 防御 ----
    def _accept_async_result(self, generation: int, result: np.ndarray) -> bool:
        """只有当前 generation 才接受异步结果；旧 generation 直接丢弃。"""
        if self._closed or generation != self.generation:
            return False
        with self._async_lock:
            self._latest_result = {generation: result}
        return True

    def submit_render(self, long_edge: int = 1024, output_bps: int = 8,
                      decode_mode: str = "cfa_half_native"):
        """提交异步渲染任务；返回 Future，结果可能为 None（已过期丢弃）。

        捕获提交时的 generation 与参数快照；任务完成时若 generation 已过期，
        不会覆盖最新结果，也不会写入 latest_result。
        """
        if self._closed:
            raise RuntimeError("RawPreviewSession has been closed")
        generation = self.generation
        params_snapshot = copy.deepcopy(self.params)
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"render-{self.session_id}")
        return self._executor.submit(
            self._render_snapshot, generation, params_snapshot,
            int(long_edge), int(output_bps), decode_mode)

    def _render_snapshot(self, generation: int, params_snapshot: dict,
                         long_edge: int, output_bps: int,
                         decode_mode: str):
        if self._closed or generation != self.generation:
            return None
        result = self._render_with_params(
            params_snapshot, long_edge, output_bps, decode_mode)
        if self._closed or generation != self.generation:
            return None
        self._accept_async_result(generation, result)
        return result

    @property
    def latest_result(self) -> Optional[np.ndarray]:
        """当前 generation 的最新异步渲染结果；无或已过期返回 None。"""
        return self._latest_result.get(self.generation)

    def canonical_params(self) -> dict:
        """把当前 session 参数与默认值合并为完整 canonical params。

        供最终全质量渲染复用：每个 stage 输出“默认值 + 用户覆盖”后的
        完整参数 dict，可直接传给 build_default_pipeline(params=...)。
        """
        pipe = build_default_pipeline(prof=self.prof, params=self.params)
        canonical: dict[str, Any] = {}
        for stage in pipe.stages:
            merged: dict[str, Any] = {}
            try:
                merged.update(copy.deepcopy(stage.default_params()))
            except Exception:
                pass
            merged.update(copy.deepcopy(self.params.get(stage.name, {})))
            canonical[stage.name] = merged
        return canonical

    # ---- 编码 ----
    def encode(self, long_edge: int = 1024, fmt: str = "jpeg",
               quality: int = 88, output_bps: int = 8,
               decode_mode: str = "cfa_half_native") -> bytes:
        """渲染并编码为字节；编码缓存按 generation 失效。

        16-bit 格式 (png16/tiff16/raw48) 强制以 16-bit 精度渲染，
        8-bit 格式 (jpeg/webp) 强制以 8-bit 精度渲染，避免先量化到
        8-bit 再上采样造成精度损失。
        """
        fmt_l = fmt.lower()
        if fmt_l in ("png16", "tiff16", "raw48"):
            render_bps = 16
        elif fmt_l in ("jpeg", "jpg", "webp"):
            render_bps = 8
        else:
            raise ValueError(f"不支持的编码格式: {fmt}")
        key = (int(long_edge), fmt_l, int(quality),
               int(render_bps), self.generation, decode_mode,
               self._raw_version())
        if key in self._encoding_cache:
            return self._encoding_cache[key]
        img = self.render(long_edge, output_bps=render_bps,
                          decode_mode=decode_mode)
        data = encode_image(img, fmt_l, quality=quality)
        self._encoding_cache[key] = data
        self._encoding_cache.move_to_end(key)
        while len(self._encoding_cache) > self.max_encoding_entries:
            self._encoding_cache.popitem(last=False)
        return data

    def save_encoded(self, out_dir, long_edge: int = 1024, fmt: str = "jpeg",
                     quality: int = 88, output_bps: int = 8,
                     decode_mode: str = "cfa_half_native") -> Path:
        """渲染编码并写入文件；raw48 额外写 JSON sidecar。"""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        data = self.encode(long_edge, fmt=fmt, quality=quality,
                           output_bps=output_bps, decode_mode=decode_mode)
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp",
               "png16": ".png", "tiff16": ".tiff", "raw48": ".raw48"}[fmt.lower()]
        path = out_dir / f"{self.session_id}_{long_edge}_{self.generation}{ext}"
        path.write_bytes(data)
        if fmt.lower() == "raw48":
            img = self.render(long_edge, output_bps=16,
                              decode_mode=decode_mode)
            profile_path = str(getattr(self.prof, "path", "")
                               or getattr(self.prof, "source", "") or "")
            sidecar = {
                "session_id": self.session_id,
                "raw_path": str(self.raw_path),
                "profile_path": profile_path,
                "long_edge": int(long_edge),
                "width": int(img.shape[1]),
                "height": int(img.shape[0]),
                "generation": self.generation,
                "params": self.params,
                "format": "raw48",
                "channels": "RGB",
                "channel_order": "RGB",
                "endian": "big",
                "bits_per_channel": 16,
                "value_range": [0, 65535],
            }
            side_path = path.with_suffix(".json")
            side_path.write_text(
                json.dumps(sidecar, ensure_ascii=False, indent=2),
                encoding="utf-8")
        return path


__all__ = ["RawPreviewSession", "_param_fingerprint", "_array_fingerprint"]
