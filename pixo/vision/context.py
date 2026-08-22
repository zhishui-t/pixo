"""pixo.vision.context —— 轻量语义上下文（Chinese-CLIP 零样本）。

迁移/简化自 guanlan src/vision/clip_zeroshot.py 与 clip_hier.py 的可复用部分：
  - 输入 RGB 图像 + 中文 prompt，输出独立 sigmoid 相似度；
  - 仅用于 Meta/Agent 上下文与解释，不进入硬决策；
  - onnxruntime/tokenizers 懒加载，模型缺失时返回未就绪。

模型许可说明：
  - chinese-clip ONNX 来自社区转换，具体权重许可需在使用前核验并登记；
  - 本模块不引入 torch/transformers，只依赖 onnxruntime + tokenizers（可选）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import numpy as np

_IMG_SIZE = 224
_IMG_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_IMG_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
_MAX_TEXT_LEN = 52


def _default_vision_path() -> str:
    """解析默认 CLIP 视觉模型路径。"""
    env = os.environ.get("PIXO_CLIP_VISION_MODEL")
    if env:
        return env
    return str(Path(__file__).resolve().parents[2] / "models" /
               "chinese-clip-vision-q4f16.onnx")


def _default_tokenizer_path() -> str:
    """解析默认 CLIP tokenizer 路径。"""
    env = os.environ.get("PIXO_CLIP_TOKENIZER")
    if env:
        return env
    return str(Path(__file__).resolve().parents[2] / "models" /
               "chinese-clip" / "tokenizer.json")


def _has_optional_deps() -> bool:
    """检查 onnxruntime/tokenizers 是否可用。"""
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except Exception:
        return False
    return True


class PixoClipContext:
    """Chinese-CLIP 零样本语义上下文。"""

    def __init__(
        self,
        model_path: str | None = None,
        tokenizer_path: str | None = None,
    ) -> None:
        self.model_path = model_path or _default_vision_path()
        self.tokenizer_path = tokenizer_path or _default_tokenizer_path()
        self.session: Any = None
        self.tokenizer: Any = None
        self._ready = False
        self._error: str | None = None
        self._lock: Any = None

    @property
    def ready(self) -> bool:
        """模型是否就绪。"""
        return self._ready

    def _load(self) -> None:
        """懒加载 ONNX 会话与 tokenizer。"""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"CLIP 视觉模型不存在：{self.model_path}")
        if not os.path.exists(self.tokenizer_path):
            raise FileNotFoundError(f"CLIP tokenizer 不存在：{self.tokenizer_path}")

        import onnxruntime as ort
        from tokenizers import Tokenizer

        try:
            available = set(ort.get_available_providers())
            providers = []
            if "CUDAExecutionProvider" in available:
                providers.append("CUDAExecutionProvider")
            providers.append("CPUExecutionProvider")
        except Exception:
            providers = ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(self.model_path, providers=providers)
        self.tokenizer = Tokenizer.from_file(self.tokenizer_path)
        self._ready = True
        self._error = None

    def _ensure(self) -> bool:
        if self._ready:
            return True
        try:
            self._load()
            return True
        except Exception as exc:
            self._ready = False
            self._error = str(exc)
            return False

    def _preprocess_image(self, image_rgb: np.ndarray) -> np.ndarray:
        """RGB → 224x224 归一化 NCHW。"""
        import cv2

        rgb = cv2.resize(image_rgb, (_IMG_SIZE, _IMG_SIZE),
                         interpolation=cv2.INTER_AREA)
        pixel = rgb.astype(np.float32) / 255.0
        pixel = (pixel - _IMG_MEAN) / _IMG_STD
        return pixel.transpose(2, 0, 1)[np.newaxis, ...]

    def _preprocess_text(
        self,
        texts: Sequence[str],
    ) -> tuple[np.ndarray, np.ndarray]:
        """tokenize + pad 到固定长度。"""
        input_ids_list: list[list[int]] = []
        attention_list: list[list[int]] = []
        for text in texts:
            encoding = self.tokenizer.encode(text)
            ids = encoding.ids[:_MAX_TEXT_LEN]
            pad_len = _MAX_TEXT_LEN - len(ids)
            input_ids_list.append(ids + [0] * pad_len)
            attention_list.append([1] * len(ids) + [0] * pad_len)
        return (
            np.asarray(input_ids_list, dtype=np.int64),
            np.asarray(attention_list, dtype=np.int64),
        )

    def classify(
        self,
        image_rgb: np.ndarray,
        prompts: Sequence[str],
    ) -> list[tuple[str, float]]:
        """零样本分类，返回按相似度降序的 [(prompt, sigmoid score)]。"""
        if not self._ensure():
            return []
        try:
            pixel_values = self._preprocess_image(image_rgb)
            input_ids, attention_mask = self._preprocess_text(prompts)
            feeds = {
                "pixel_values": pixel_values,
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            }
            with self._lock or _NullLock():
                outputs = self.session.run(None, feeds)
            logits = outputs[0][0]
            mean = float(np.abs(logits).mean())
            temperature = max(1.0, mean / 5.0) if mean > 10.0 else 1.0
            probs = 1.0 / (1.0 + np.exp(-logits / temperature))
            results = [
                (str(prompts[i]), float(probs[i]))
                for i in range(len(prompts))
            ]
            results.sort(key=lambda x: -x[1])
            return results
        except Exception:
            return []

    def top_k(
        self,
        image_rgb: np.ndarray,
        prompts: Sequence[str],
        k: int = 3,
    ) -> list[tuple[str, float]]:
        """top-k 语义上下文。"""
        return self.classify(image_rgb, prompts)[:k]

    def health_info(self) -> dict[str, Any]:
        """返回健康信息。"""
        return {
            "name": "ChineseClipContext",
            "type": "real",
            "provider": "onnxruntime",
            "available": (
                _has_optional_deps()
                and os.path.exists(self.model_path)
                and os.path.exists(self.tokenizer_path)
            ),
            "ready": self._ready,
            "loaded": self._ready,
            "version": None,
            "model_path": self.model_path,
            "detail": (
                "Chinese-CLIP 语义上下文已就绪。"
                if self._ready
                else f"未就绪：{self._error or '缺少模型或依赖'}"
            ),
        }


class _NullLock:
    """无并发场景下的空锁。"""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: Any) -> None:
        return None


_clip: PixoClipContext | None = None


def get_clip_context() -> PixoClipContext | None:
    """进程级 CLIP 上下文单例；模型无法加载时返回 None。"""
    global _clip
    if _clip is None:
        candidate = PixoClipContext()
        if candidate._ensure():
            _clip = candidate
        else:
            _clip = None
    return _clip


def clip_health_info() -> dict[str, Any]:
    """构造 CLIP 语义上下文健康信息（不触发模型加载）。"""
    return PixoClipContext().health_info()


__all__ = [
    "PixoClipContext",
    "get_clip_context",
    "clip_health_info",
]
