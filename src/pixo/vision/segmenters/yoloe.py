"""pixo.vision.segmenters.yoloe —— YOLOE-26L-seg 实例分割适配器。

本文件是 Pixo 仓库中唯一允许直接 import torch / ultralytics 的模块（AGPL 隔离）。

设计目标（P0-3）：
  - 遵守 P0-2 冻结的 Segmenter 契约：segment(image_rgb, prompts) -> dict[str, np.ndarray]。
  - 参考 guanlan src/vision/yoloe_det.py 的加载与 prompt-free 94 词方案。
  - 读取 results[0].masks 并输出 0/255 uint8 mask。
  - 输入统一：外部传入 RGB（uint8/float32），适配器内部转 BGR uint8 后推理。
  - 模型未就绪时抛 SegmenterUnavailable，由上层降级到 manual_review/fallback。

AGPL 说明：
  - YOLOE-26L-seg 为 AGPL-3.0 许可，仅限内部研发；产品化前需替换或购买授权。
  - 所有 ultralytics/torch import 均在本文件内，其它模块不得直接依赖。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

from ..base import BaseSegmenter
from ..exceptions import SegmenterUnavailable

# ── 默认模型文件名与路径解析 ────────────────────────────────────
DEFAULT_MODEL_NAME = "yoloe-26l-seg.pt"
YOLOE_SEGMENTER_VERSION = "0.1.0"

# ── prompt-free 固化的英文开放词汇表（与 guanlan 对齐）────────────
# YOLOE 内部 mobileclip2 是英文 CLIP，中文提示词无法检出；词表必须无空格。
YOLOE_QUERIES: list[str] = [
    "person", "face", "crowd", "people",
    "sky", "sea", "water", "mountain", "tree", "flower", "grass",
    "cloud", "building", "house", "road", "beach", "forest", "river",
    "lake", "snow", "field", "shore", "horizon", "mountainpeak",
    "car", "bus", "truck", "airplane", "train", "boat",
    "bicycle", "motorcycle", "trafficlight", "stopsign", "parkingmeter",
    "cat", "dog", "bird", "horse", "cow", "sheep", "elephant",
    "bear", "zebra", "giraffe",
    "chair", "table", "cup", "bottle", "plant", "couch", "tv",
    "laptop", "cellphone", "book", "bench", "umbrella", "backpack",
    "suitcase",
    "bowl", "banana", "apple", "sandwich", "pizza", "cake", "donut",
    "hotdog", "broccoli", "carrot", "wineglass", "diningtable",
    "sink", "oven", "refrigerator", "microwave", "toilet", "bed",
    "pottedplant", "lamp", "light", "window", "wall", "indoor",
    "street",
    "sportsball", "skis", "snowboard", "skateboard", "surfboard",
    "frisbee", "kite", "tennisracket",
    "overcast", "skyline",
]
YOLOE_QUERIES = list(dict.fromkeys(YOLOE_QUERIES))

# 背景追加词表：文本模式兜底用，仅保留 guanlan 中核心映射。
YOLOE_BACKGROUND_QUERIES: dict[str, list[str]] = {
    "人物": ["crowd", "street", "indoor", "wall", "people"],
    "自然": ["mountain", "river", "forest", "snow", "lake", "field",
             "overcast", "mountainpeak"],
    "建筑": ["building", "tower", "window", "street", "roof", "bridge",
             "skyline"],
    "植物": ["leaf", "petal", "field", "bush", "garden"],
    "天空": ["cloud", "overcast", "skyline", "horizon", "mountainpeak"],
    "水域": ["mountain", "shore", "building", "forest", "beach", "water"],
}
YOLOE_BACKGROUND_FALLBACK: list[str] = [
    "crowd", "street", "indoor", "mountain", "river", "forest",
    "snow", "field", "beach", "light", "window", "wall",
]

# 像素证据 → 必补实体词（保留 guanlan 思路，未在本适配器中强制使用）。
YOLOE_PIXEL_QUERIES: list[tuple[str, float, list[str]]] = [
    ("sky_top", 0.25, ["sky", "cloud", "overcast"]),
    ("blue", 0.30, ["water", "sea", "building", "skyline"]),
    ("green", 0.20, ["tree", "field", "flower"]),
    ("skin", 0.20, ["face", "person"]),
]


def _default_model_path() -> str:
    """解析默认 YOLOE 权重路径。

    优先级：显式 model_path > 环境变量 > 仓库根/models/ 下的默认文件名。
    找不到不会在这里报错，交给 _load() 时抛出 SegmenterUnavailable。
    """
    env_path = os.environ.get("PIXO_YOLOE_MODEL") or os.environ.get(
        "PIXO_YOLOE_MODEL_PATH"
    )
    if env_path:
        return env_path
    candidates = [
        Path.cwd() / "models" / DEFAULT_MODEL_NAME,
        Path(__file__).resolve().parents[3] / "models" / DEFAULT_MODEL_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


class YoloeSegmenter(BaseSegmenter):
    """YOLOE-26L-seg 适配器。

    实现 Pixo Segmenter 契约；模型采用惰性加载，未就绪时 segment() 抛
    SegmenterUnavailable。prompt-free 主模型负责 94 词零提示快扫，
    缺失类别再走文本模式实例做兜底。
    """

    def __init__(
        self,
        model_path: str | None = None,
        conf_threshold: float = 0.25,
        device: str | None = None,
        prompt_free: bool = True,
    ) -> None:
        self.model_path = model_path or _default_model_path()
        self.conf_threshold = float(conf_threshold)
        self.device = device
        self.prompt_free = bool(prompt_free)
        self.model: Any = None
        self._text_model: Any = None
        self.names: dict[int, str] = {}
        self.version: str | None = None
        self._ready = False
        self._load_error: str | None = None

    # ── 状态与健康信息 ────────────────────────────────────────
    @property
    def ready(self) -> bool:
        """模型是否已成功加载并可以推理。"""
        return self._ready

    def health_info(self) -> dict[str, Any]:
        """返回本适配器的模型健康信息，供 vision_health / UI 展示。"""
        detail = (
            "YOLOE-26L-seg 已就绪。"
            if self._ready
            else f"YOLOE-26L-seg 未就绪：{self._load_error or '尚未加载'}"
        )
        return {
            "name": "YOLOE-26L-seg",
            "type": "real",
            "provider": "ultralytics",
            "available": self._ready,
            "ready": self._ready,
            "loaded": self._ready,
            "version": self.version or YOLOE_SEGMENTER_VERSION,
            "model_path": self.model_path,
            "detail": detail,
        }

    # ── 对外接口 ──────────────────────────────────────────────
    def segment(
        self,
        image_rgb: np.ndarray,
        prompts: list[str],
    ) -> dict[str, np.ndarray]:
        """执行分割并返回 prompt -> uint8 mask（0/255，HxW）。

        Args:
            image_rgb: RGB 图像，HxWx3 或 HxWx4；uint8 或 float [0,1]/[0,255]。
            prompts: 英文类别列表，例如 ["face", "sky", "plant"]。

        Returns:
            dict[str, np.ndarray]: 每个 prompt 一张 0/255 mask；无检测时返回全零。
        """
        self.validate_image(image_rgb)
        normalized = self.normalize_prompts(prompts)
        if not normalized:
            return {}
        self._ensure_model()
        bgr = self._to_bgr_uint8(image_rgb)
        masks = self._segment_prompt_free(bgr, normalized)
        missing = [p for p in normalized if not bool(masks[p].any())]
        if missing:
            masks = self._text_fallback(bgr, masks, missing)
        return masks

    # ── 加载与初始化 ──────────────────────────────────────────
    def _ensure_model(self) -> None:
        """确保主模型已加载；失败时抛 SegmenterUnavailable。"""
        if self._ready:
            return
        self._load()

    def _load(self) -> None:
        """加载 YOLOE 模型并按需做 prompt-free 固化。

        本方法是全仓库唯一触达 torch/ultralytics 的地方。
        """
        try:
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(
                    f"模型文件不存在：{self.model_path}"
                )
            import torch
            from ultralytics import YOLOE

            self.model = YOLOE(self.model_path)
            if self.device is None:
                self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
            self.model = self.model.to(self.device)
            self.version = getattr(
                __import__("ultralytics"), "__version__", None
            )
            if self.prompt_free:
                try:
                    self._prompt_free(self.model, YOLOE_QUERIES)
                except Exception:
                    # prompt-free 与当前 ultralytics 版本不兼容时，
                    # 回退为普通文本模式：重新加载未固化实例。
                    self.prompt_free = False
                    self.model = YOLOE(self.model_path).to(self.device)
                    self.names = dict(getattr(self.model, "names", {}))
            else:
                self.names = dict(getattr(self.model, "names", {}))
            self._ready = True
            self._load_error = None
        except Exception as exc:
            self._ready = False
            self._load_error = str(exc)
            raise SegmenterUnavailable(
                f"YOLOE-26L-seg 加载失败：{exc}"
            ) from exc

    def _prompt_free(self, model: Any, names: list[str]) -> None:
        """复刻 guanlan 的 prompt-free 固化流程，把 94 词融合进分类头。

        固化后主模型推理零提示开销；该流程依赖 ultralytics 内部结构，
        若版本不兼容则由 _load() 捕获并回退为文本模式。
        """
        import torch
        from ultralytics.nn.modules import head as head_module

        vocab = model.get_vocab(names)
        head = model.model.model[-1]
        assert isinstance(head, head_module.YOLOEDetect)
        cv3 = getattr(head, "one2one_cv3", head.cv3)
        cv2 = getattr(head, "one2one_cv2", head.cv2)
        head.lrpc = torch.nn.ModuleList(
            head_module.LRPCHead(
                cls, pf[-1], loc[-1], enabled=i != 2
            )
            for i, (cls, pf, loc) in enumerate(zip(vocab, cv3, cv2))
        )
        for loc_head, cls_head in zip(cv2, cv3):
            assert isinstance(loc_head, torch.nn.Sequential)
            assert isinstance(cls_head, torch.nn.Sequential)
            del loc_head[-1]
            del cls_head[-1]
        head.nc = len(names)
        model.model.names = {i: n for i, n in enumerate(names)}
        self.names = dict(model.model.names)

    def _ensure_text_model(self) -> Any:
        """懒加载独立的文本模式 YOLOE 实例。

        主模型 prompt-free 固化后不能再次 set_classes，因此动态词表
        必须由独立实例承担。
        """
        if self._text_model is None:
            try:
                if not os.path.exists(self.model_path):
                    raise FileNotFoundError(
                        f"模型文件不存在：{self.model_path}"
                    )
                import torch
                from ultralytics import YOLOE

                text_model = YOLOE(self.model_path)
                if self.device is None:
                    self.device = (
                        "cuda:0" if torch.cuda.is_available() else "cpu"
                    )
                self._text_model = text_model.to(self.device)
            except Exception as exc:
                raise SegmenterUnavailable(
                    f"YOLOE 文本实例加载失败：{exc}"
                ) from exc
        return self._text_model

    # ── 输入转换 ──────────────────────────────────────────────
    def _to_bgr_uint8(self, image_rgb: np.ndarray) -> np.ndarray:
        """把 Pixo RGB 图像转为 ultralytics 期望的 BGR uint8。

        支持 float32 [0,1] / [0,255] 与 uint8；RGBA 会自动丢弃 alpha。
        """
        arr = np.asarray(image_rgb)
        if arr.ndim != 3 or arr.shape[2] not in (3, 4):
            raise ValueError(
                f"输入必须是 HxWx3/4，实际 shape={arr.shape}"
            )
        if arr.shape[2] == 4:
            arr = arr[..., :3]
        if np.issubdtype(arr.dtype, np.floating):
            if arr.size and float(arr.max()) <= 1.0 + 1e-6:
                arr = arr * 255.0
            arr = np.clip(arr, 0.0, 255.0)
        arr = np.round(arr).astype(np.uint8)
        # RGB -> BGR
        return arr[..., ::-1].copy()

    # ── 推理与 mask 收集 ──────────────────────────────────────
    def _segment_prompt_free(
        self,
        bgr: np.ndarray,
        prompts: list[str],
    ) -> dict[str, np.ndarray]:
        """用主模型（prompt-free 固化词表）推理并收集 prompt mask。"""
        try:
            results = self.model.predict(
                bgr, conf=self.conf_threshold, verbose=False
            )
        except Exception as exc:
            raise SegmenterUnavailable(
                f"YOLOE prompt-free 推理失败：{exc}"
            ) from exc
        combined = self._collect_masks(results, bgr.shape[:2])
        return {
            p: combined.get(
                p, np.zeros(bgr.shape[:2], dtype=np.uint8)
            )
            for p in prompts
        }

    def _text_fallback(
        self,
        bgr: np.ndarray,
        masks: dict[str, np.ndarray],
        missing: list[str],
    ) -> dict[str, np.ndarray]:
        """对 prompt-free 未检出的类别，用文本模式实例追加一次推理。"""
        try:
            text_model = self._ensure_text_model()
            text_model.set_classes(missing)
            fallback = self._segment_with_model(text_model, bgr, missing)
        except Exception:
            # 兜底失败不抛给上层，保留已有 mask（缺失项为全零）由测量层降级。
            return masks
        for prompt in missing:
            if fallback.get(prompt) is not None and fallback[prompt].any():
                masks[prompt] = fallback[prompt]
        return masks

    def _segment_with_model(
        self,
        model: Any,
        bgr: np.ndarray,
        prompts: list[str],
    ) -> dict[str, np.ndarray]:
        """用指定 model 推理并收集 prompt mask。"""
        results = model.predict(
            bgr, conf=self.conf_threshold, verbose=False
        )
        combined = self._collect_masks(results, bgr.shape[:2])
        return {
            p: combined.get(
                p, np.zeros(bgr.shape[:2], dtype=np.uint8)
            )
            for p in prompts
        }

    def _collect_masks(
        self,
        results: list[Any],
        image_shape: tuple[int, int],
    ) -> dict[str, np.ndarray]:
        """从 ultralytics Results 中提取实例 mask 并按 label 合并。

        多个同 label 实例通过 OR 合并为一张 mask，符合 Segmenter 契约。
        """
        height, width = image_shape
        combined: dict[str, np.ndarray] = {}
        for result in results:
            masks = getattr(result, "masks", None)
            if masks is None:
                continue
            raw = getattr(masks, "data", None)
            if raw is None:
                continue
            if hasattr(raw, "cpu"):
                raw = raw.cpu().numpy()
            elif hasattr(raw, "numpy"):
                raw = raw.numpy()
            raw = np.asarray(raw, dtype=np.float32)
            if raw.ndim == 2:
                raw = raw[None, ...]
            if raw.shape[0] == 0:
                continue

            boxes = getattr(result, "boxes", None)
            names = getattr(result, "names", None) or {}
            cls_array = self._boxes_cls_array(boxes)
            for index in range(raw.shape[0]):
                label = self._label_for_index(
                    names, cls_array, index
                )
                if label is None:
                    continue
                mask = raw[index]
                if mask.shape != (height, width):
                    mask = self._resize_mask(mask, width, height)
                combined[label] = np.maximum(
                    combined.get(
                        label,
                        np.zeros((height, width), dtype=np.uint8),
                    ),
                    self._to_binary_mask(mask),
                )
        return combined

    @staticmethod
    def _boxes_cls_array(boxes: Any) -> np.ndarray | None:
        """取 boxes.cls 并统一转成 numpy 1D 数组。"""
        if boxes is None:
            return None
        cls = getattr(boxes, "cls", None)
        if cls is None:
            return None
        if hasattr(cls, "cpu"):
            cls = cls.cpu().numpy()
        elif hasattr(cls, "numpy"):
            cls = cls.numpy()
        return np.asarray(cls)

    @staticmethod
    def _label_for_index(
        names: Any,
        cls_array: np.ndarray | None,
        index: int,
    ) -> str | None:
        """根据 result.names 和 boxes.cls 取第 index 个实例的 label。"""
        if cls_array is None or index >= len(cls_array):
            return None
        cls_id = int(cls_array[index])
        if isinstance(names, dict):
            return names.get(cls_id, str(cls_id))
        try:
            return str(names[cls_id])
        except Exception:
            return str(cls_id)

    @staticmethod
    def _to_binary_mask(mask: np.ndarray) -> np.ndarray:
        """把 ultralytics mask 统一为 0/255 uint8。"""
        if mask.dtype.kind == "f":
            binary = (mask > 0.5).astype(np.uint8) * 255
        else:
            threshold = 127 if float(mask.max()) > 1 else 0
            binary = (mask > threshold).astype(np.uint8) * 255
        return binary

    @staticmethod
    def _resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
        """mask 与输入尺寸不一致时用最近邻调整（保持二值性质）。"""
        import cv2
        resized = cv2.resize(
            mask.astype(np.uint8),
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        )
        return resized


__all__ = ["YoloeSegmenter", "YOLOE_QUERIES"]
