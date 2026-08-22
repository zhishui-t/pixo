"""pixo.vision.mock —— MockSegmenter 合成 mask，用于测量/闭环测试。

本实现仅依赖 NumPy，不引入 torch/ultralytics，不接真实语义模型。
MockSegmenter 按 prompt 生成确定性的几何 mask，shape 与输入图像一致。
"""
from __future__ import annotations

import numpy as np

from .base import BaseSegmenter
from .exceptions import (
    EmptyImageError,
    InvalidPromptsError,
    SegmenterUnavailable,
)


def _ellipse_mask(
    height: int,
    width: int,
    center_y: float,
    center_x: float,
    radius_y: float,
    radius_x: float,
    value: int = 255,
) -> np.ndarray:
    """生成一张 0/255 的椭圆 mask。"""
    yy, xx = np.ogrid[:height, :width]
    cy = float(np.clip(center_y, 0, max(0, height - 1)))
    cx = float(np.clip(center_x, 0, max(0, width - 1)))
    ry = max(1.0, float(radius_y))
    rx = max(1.0, float(radius_x))
    inside = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 <= 1.0
    return inside.astype(np.uint8) * value


def _bottom_band_mask(
    height: int, width: int, start_ratio: float, value: int = 255
) -> np.ndarray:
    """生成底部横向条带 mask。"""
    mask = np.zeros((height, width), dtype=np.uint8)
    y0 = max(0, int(round(height * start_ratio)))
    if y0 < height:
        mask[y0:, :] = value
    elif height > 0:
        mask[height - 1, :] = value
    return mask


class MockSegmenter(BaseSegmenter):
    """确定性合成分割器。

    支持 face/sky/plant/person/ground 等常见类别；未知 prompt 回退为中央
    椭圆区域，确保调用方总能拿到 `prompt -> mask` 的完整结果。
    """

    def __init__(
        self,
        available: bool = True,
        *,
        name: str = "MockSegmenter",
        version: str = "0.1.0",
        strict: bool = False,
    ) -> None:
        self.available = available
        self.name = name
        self.version = version
        self.strict = strict

    def segment(
        self,
        image_rgb: np.ndarray,
        prompts: list[str],
    ) -> dict[str, np.ndarray]:
        """合成 mask；available=False 时抛 SegmenterUnavailable。

        默认对空图/缺失 prompts 采取优雅降级（返回空 dict），
        可通过 strict=True 切换为抛 EmptyImageError / InvalidPromptsError。
        """
        # 空图/None 图：默认视为无掩码请求
        if image_rgb is None:
            if self.strict:
                raise EmptyImageError("image_rgb 不能为 None")
            return {}
        if not isinstance(image_rgb, np.ndarray):
            raise TypeError(f"image_rgb 必须是 numpy.ndarray，实际为 {type(image_rgb)}")
        if image_rgb.ndim != 3:
            raise ValueError(f"image_rgb 必须是 HxWx3 数组，实际维度为 {image_rgb.ndim}")
        if image_rgb.shape[2] not in (3, 4):
            raise ValueError(
                f"image_rgb 通道数只支持 3 或 4，实际为 {image_rgb.shape[2]}"
            )
        if image_rgb.shape[0] == 0 or image_rgb.shape[1] == 0:
            if self.strict:
                raise EmptyImageError(
                    f"输入图像不能为空，实际 shape 为 {image_rgb.shape}"
                )
            return {}

        # 缺失 prompts：默认视为空请求
        if prompts is None:
            if self.strict:
                raise InvalidPromptsError("prompts 不能为 None")
            return {}

        normalized = self.normalize_prompts(prompts)
        if not self.available:
            raise SegmenterUnavailable(
                f"{self.name} 未就绪（模拟模型不可用，上层应降级）"
            )

        height, width = image_rgb.shape[:2]
        masks: dict[str, np.ndarray] = {}
        for prompt in normalized:
            masks[prompt] = self._synthesize(height, width, prompt)
        return masks

    def _synthesize(self, height: int, width: int, prompt: str) -> np.ndarray:
        """按 prompt 生成一张 0/255 mask。"""
        key = prompt.strip().lower()

        # 人脸/人物：中央偏上椭圆
        if any(word in key for word in ("face", "portrait", "person", "human",
                                        "body", "head", "脸", "人脸", "人",
                                        "人体", "头")):
            if "face" in key or "脸" in key or "portrait" in key:
                return _ellipse_mask(height, width, height * 0.38,
                                     width * 0.50, height * 0.20,
                                     width * 0.15)
            return _ellipse_mask(height, width, height * 0.52,
                                 width * 0.50, height * 0.42,
                                 width * 0.18)

        # 天空：顶部条带
        if any(word in key for word in ("sky", "天空", "天", "背景")):
            mask = np.zeros((height, width), dtype=np.uint8)
            y1 = max(1, int(round(height * 0.40)))
            mask[:y1, :] = 255
            return mask

        # 植物/树/花：底部区域
        if any(word in key for word in ("plant", "tree", "flower", "grass",
                                        "植物", "树", "花", "草")):
            return _bottom_band_mask(height, width, 0.55)

        # 地面/道路/水：底部条带
        if any(word in key for word in ("ground", "road", "water", "floor",
                                        "地面", "道路", "路", "水", "水面")):
            return _bottom_band_mask(height, width, 0.65)

        # 建筑：中上偏右矩形
        if any(word in key for word in ("building", "house", "建筑", "楼", "房子")):
            mask = np.zeros((height, width), dtype=np.uint8)
            y0 = int(round(height * 0.15))
            y1 = int(round(height * 0.70))
            x0 = int(round(width * 0.55))
            x1 = int(round(width * 0.95))
            if y0 < y1 and x0 < x1:
                mask[y0:y1, x0:x1] = 255
            return mask

        # 文字/标志：中部水平条
        if any(word in key for word in ("text", "logo", "sign", "文字",
                                        "标志", "标牌")):
            mask = np.zeros((height, width), dtype=np.uint8)
            y0 = int(round(height * 0.42))
            y1 = int(round(height * 0.58))
            x0 = int(round(width * 0.20))
            x1 = int(round(width * 0.80))
            if y0 < y1 and x0 < x1:
                mask[y0:y1, x0:x1] = 255
            return mask

        # 未知类别：中央椭圆，保证调用方拿到可用 mask
        return _ellipse_mask(height, width, height * 0.50,
                             width * 0.50, height * 0.30,
                             width * 0.25)


__all__ = ["MockSegmenter"]
