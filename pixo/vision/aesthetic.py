"""pixo.vision.aesthetic —— 7 维美学评分器。

迁移自 guanlan src/vision/aesthetic.py（rsinema/aesthetic-scorer），
适配 Pixo 契约：
  - 输入 RGB uint8/float，输出 7 维评分；
  - 模型懒加载；torch/transformers 或权重缺失时返回 None/未就绪，不阻断导入；
  - 维度名按 Pixo 架构文档统一为：
      overall / quality / composition / lighting / color /
      depth_of_field / content。

模型许可说明：
  - aesthetic_scorer.pt 来自 rsinema/aesthetic-scorer 项目头权重；
  - CLIP backbone 为 openai/clip-vit-base-patch32（MIT 类许可，需自行核验）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

PIXO_DIMENSIONS = (
    "overall",
    "quality",
    "composition",
    "lighting",
    "color",
    "depth_of_field",
    "content",
)

# 与 guanlan 模型 7 个 head 顺序对应的内部维度名。
_MODEL_DIMENSIONS = (
    "overall",
    "technical_quality",
    "composition",
    "lighting",
    "color_harmony",
    "depth_of_field",
    "content",
)

_DIMENSION_MAP = {
    "technical_quality": "quality",
    "color_harmony": "color",
}


def _default_model_path() -> str:
    """解析默认美学模型路径。"""
    env = os.environ.get("PIXO_AESTHETIC_MODEL")
    if env:
        return env
    return str(Path(__file__).resolve().parents[2] / "models" / "aesthetic_scorer.pt")


def _has_ml_deps() -> bool:
    """检查 torch/transformers 是否可用，不导入本模块时触发。"""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


class PixoAestheticScorer:
    """Pixo 7 维美学评分器（懒加载，模型缺失时 score 返回 None）。"""

    def __init__(
        self,
        model_path: str | None = None,
        device: str | None = None,
        backbone: str = "openai/clip-vit-base-patch32",
    ) -> None:
        self.model_path = model_path or _default_model_path()
        self.device = device
        self.backbone = backbone
        self._scorer: Any = None
        self._processor: Any = None
        self._ready = False
        self._error: str | None = None

    @property
    def ready(self) -> bool:
        """是否已成功加载模型。"""
        return self._ready

    def _load(self) -> None:
        """加载 CLIP backbone 与 7 个评分头。"""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"美学模型不存在：{self.model_path}")

        import torch
        import torch.nn as nn
        from transformers import CLIPModel, CLIPProcessor

        if self.device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"

        class _Scorer(nn.Module):
            """CLIP 视觉塔 + 7 个 Linear 评分头。"""

            def __init__(self, backbone_model: Any) -> None:
                super().__init__()
                self.backbone = backbone_model
                hidden_dim = 768
                self.aesthetic_head = nn.Sequential(nn.Linear(hidden_dim, 1))
                self.quality_head = nn.Sequential(nn.Linear(hidden_dim, 1))
                self.composition_head = nn.Sequential(nn.Linear(hidden_dim, 1))
                self.light_head = nn.Sequential(nn.Linear(hidden_dim, 1))
                self.color_head = nn.Sequential(nn.Linear(hidden_dim, 1))
                self.dof_head = nn.Sequential(nn.Linear(hidden_dim, 1))
                self.content_head = nn.Sequential(nn.Linear(hidden_dim, 1))

            def forward(self, pixel_values: Any) -> tuple[Any, ...]:
                features = self.backbone.vision_model(pixel_values).pooler_output
                return (
                    self.aesthetic_head(features),
                    self.quality_head(features),
                    self.composition_head(features),
                    self.light_head(features),
                    self.color_head(features),
                    self.dof_head(features),
                    self.content_head(features),
                )

        backbone_model = CLIPModel.from_pretrained(self.backbone)
        self._scorer = _Scorer(backbone_model).to(self.device)
        state = torch.load(self.model_path, map_location=self.device)
        self._scorer.load_state_dict(state, strict=False)
        self._scorer.eval()
        self._processor = CLIPProcessor.from_pretrained(self.backbone)
        self._ready = True
        self._error = None

    def _ensure(self) -> bool:
        """确保模型已加载；失败时降级并返回 False。"""
        if self._ready:
            return True
        try:
            self._load()
            return True
        except Exception as exc:
            self._ready = False
            self._error = str(exc)
            return False

    def score(self, image_rgb: np.ndarray) -> dict[str, float] | None:
        """对 RGB 图像打分，失败/未就绪返回 None。"""
        import torch

        if image_rgb is None or not isinstance(image_rgb, np.ndarray):
            return None
        if not self._ensure():
            return None
        try:
            arr = np.asarray(image_rgb)
            if arr.dtype == np.uint8:
                rgb = arr
            else:
                rgb = np.clip(arr, 0.0, 1.0)
                rgb = (rgb * 255.0 + 0.5).astype(np.uint8)
            if rgb.shape[2] == 4:
                rgb = rgb[..., :3]

            inputs = self._processor(
                images=rgb, return_tensors="pt"
            ).to(self.device)
            with torch.no_grad():
                outputs = self._scorer(**inputs)

            result: dict[str, float] = {}
            for model_name, tensor in zip(_MODEL_DIMENSIONS, outputs):
                name = _DIMENSION_MAP.get(model_name, model_name)
                result[name] = float(tensor[0][0])
            return result
        except Exception:
            return None

    def health_info(self) -> dict[str, Any]:
        """返回模型健康信息（不触发完整加载）。"""
        return {
            "name": "AestheticScorer",
            "type": "real",
            "provider": "torch+transformers",
            "available": _has_ml_deps() and os.path.exists(self.model_path),
            "ready": self._ready,
            "loaded": self._ready,
            "version": None,
            "model_path": self.model_path,
            "detail": (
                "7 维美学评分模型已就绪。"
                if self._ready
                else f"未加载：{self._error or '缺少模型或依赖'}"
            ),
        }


_aesthetic: PixoAestheticScorer | None = None


def get_aesthetic() -> PixoAestheticScorer | None:
    """进程级单例；模型无法加载时返回 None。"""
    global _aesthetic
    if _aesthetic is None:
        candidate = PixoAestheticScorer()
        if candidate._ensure():
            _aesthetic = candidate
        else:
            _aesthetic = None
    return _aesthetic


def aesthetic_health_info() -> dict[str, Any]:
    """构造当前美学模型的健康信息（不触发模型加载）。"""
    return PixoAestheticScorer().health_info()


__all__ = [
    "PixoAestheticScorer",
    "get_aesthetic",
    "aesthetic_health_info",
    "PIXO_DIMENSIONS",
]
