"""segmenters/common —— 多模型适配器共享助手（无第三方重依赖）。"""
from __future__ import annotations

import importlib
import logging
import os

import cv2
import numpy as np

from ..exceptions import SegmenterUnavailable

_LOGGER = logging.getLogger(__name__)


def warmup_enabled(env_key: str = "PIXO_SEGMENTER_WARMUP") -> bool:
    """PIXO_SEGMENTER_WARMUP=0/false/off/no 时跳过预热，默认启用。"""
    return os.environ.get(env_key, "1").strip().lower() not in (
        {"0", "false", "off", "no"}
    )


def zeros_mask(h: int, w: int) -> np.ndarray:
    """契约内合法的“未检出”降级掩码（全零二值）。"""
    return np.zeros((max(int(h), 1), max(int(w), 1)), dtype=np.uint8)


def to_binary_mask(raw: np.ndarray, h: int, w: int) -> np.ndarray:
    """任意掩码/概率图 -> 与输入对齐的 0/255 uint8 二值掩码。"""
    arr = np.asarray(raw)
    if arr.ndim == 3:
        arr = arr[..., 0]
    if arr.shape[:2] != (h, w):
        arr = cv2.resize(arr, (w, h), interpolation=cv2.INTER_NEAREST)
    return ((np.asarray(arr, dtype=np.float32) > 0) * 255).astype(np.uint8)


class LazyBackendMixin:
    """权重懒加载 + 永久降级 + 常驻预热（t67 模式复用）。

    子类实现 _load()；首次 segment/warmup 触发 _ensure_loaded()。
    加载失败置 _degraded=True 不再重试；后续调用抛 SegmenterUnavailable。
    """

    _loaded: bool = False
    _degraded: bool = False
    _error: str | None = None
    _warned: bool = False
    _warmup_info: dict | None = None
    # 轻量探测所需的顶层依赖模块名（子类按适配器声明，如
    # ("torch", "transformers") / ("rfdetr",)）；仅做 import 检查，
    # 禁止触发 from_pretrained / 完整权重加载。
    _PROBE_IMPORTS: tuple[str, ...] = ()

    def _load(self) -> None:  # pragma: no cover - 由子类覆盖
        raise NotImplementedError

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        if self._degraded:
            raise SegmenterUnavailable(
                f"{type(self).__name__} 已永久降级: {self._error}"
            )
        try:
            self._load()
            self._loaded = True
            return True
        except SegmenterUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._degraded = True
            self._error = f"{type(exc).__name__}: {exc}"
            _LOGGER.warning(
                "[pixo.vision.segmenters] %s 加载失败，永久降级: %s",
                type(self).__name__, self._error)
            raise SegmenterUnavailable(self._error) from exc

    def available(self) -> bool:
        """轻量探测可用性：已加载标记 + 依赖可 import。

        不触发 from_pretrained / 完整加载（_probe 仅 import 声明的
        顶层依赖模块）；永久降级实例恒 False。
        """
        if self._loaded:
            return True
        if self._degraded:
            return False
        try:
            self._probe()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _probe(self) -> None:
        """默认轻量探针：仅 import 子类声明的依赖模块名。"""
        for module_name in self._PROBE_IMPORTS:
            importlib.import_module(module_name)

    def warmup(self, image: np.ndarray | None = None) -> dict:
        """预加载并跑一次 dummy 推理；返回状态字典并入健康信息。"""
        if not warmup_enabled():
            self._warmup_info = {"warmed": False, "skipped": True,
                                 "warmup_ms": None}
            return dict(self._warmup_info)
        import time

        dummy = (np.zeros((16, 16, 3), dtype=np.uint8)
                 if image is None else image)
        t0 = time.perf_counter()
        err = None
        warmed = False
        try:
            self._ensure_loaded()
            self._dummy_infer(dummy)
            warmed = True
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
        ms = round((time.perf_counter() - t0) * 1000.0, 1)
        self._warmup_info = {"warmed": warmed, "skipped": False,
                             "warmup_ms": ms,
                             "error": err}
        return dict(self._warmup_info)

    def _dummy_infer(self, image: np.ndarray) -> None:  # pragma: no cover
        self.segment(image, list(getattr(self, "PROMPT_KEYS", [])[:1]))

    def warmup_health(self) -> dict:
        if self._warmup_info is None:
            return {"warmed": False, "warmup_ms": None}
        out = dict(self._warmup_info)
        out.pop("skipped", None)
        return out
