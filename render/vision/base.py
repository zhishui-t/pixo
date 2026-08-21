"""pixo.render.vision.base —— Segmenter 对外契约与基类。

P0-2 冻结的接口:
    segment(image_rgb: np.ndarray, prompts: list[str]) -> dict[str, np.ndarray]
返回每个 prompt 对应的 uint8 mask，形状与输入图像一致；模型不可用时抛
SegmenterUnavailable。

实现约定:
  - Mask 值为 0/255，shape 为 (H, W)。
  - 真实模型接入只应放在 segmenters/ 适配器内，本包不引入 torch/ultralytics。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import numpy as np

from .exceptions import (
    EmptyImageError,
    InvalidPromptsError,
    PromptNotSupportedError,
    SegmenterError,
    SegmenterUnavailable,
)


@runtime_checkable
class Segmenter(Protocol):
    """Pixo Vision 分割器协议（对外稳定契约）。"""

    def segment(
        self,
        image_rgb: np.ndarray,
        prompts: list[str],
    ) -> dict[str, np.ndarray]:
        """执行分割。

        Args:
            image_rgb: HxWx3 RGB 图像（uint8/float 均可，由适配器归一化）。
            prompts: 请求的目标类别列表，例如 ["face", "sky", "plant"]。

        Returns:
            dict[str, np.ndarray]: prompt -> uint8 mask（0/255），形状 (H, W)。

        Raises:
            SegmenterUnavailable: 模型未就绪/加载失败，上层应降级。
        """
        ...


class BaseSegmenter(Segmenter, ABC):
    """Segmenter 基类，固化输入校验，便于适配器统一实现。"""

    @abstractmethod
    def segment(
        self,
        image_rgb: np.ndarray,
        prompts: list[str],
    ) -> dict[str, np.ndarray]:
        """执行分割，子类必须实现。"""

    def validate_image(self, image_rgb: np.ndarray) -> None:
        """校验输入图像是否为非空 HxWx3 数组。"""
        if image_rgb is None:
            raise EmptyImageError("image_rgb 不能为 None")
        if not isinstance(image_rgb, np.ndarray):
            raise TypeError(f"image_rgb 必须是 numpy.ndarray，实际为 {type(image_rgb)}")
        if image_rgb.ndim != 3:
            raise ValueError(f"image_rgb 必须是 HxWx3 数组，实际维度为 {image_rgb.ndim}")
        if image_rgb.shape[2] not in (3, 4):
            raise ValueError(
                f"image_rgb 通道数只支持 3 或 4，实际为 {image_rgb.shape[2]}"
            )
        if image_rgb.shape[0] == 0 or image_rgb.shape[1] == 0:
            raise EmptyImageError(
                f"输入图像不能为空，实际 shape 为 {image_rgb.shape}"
            )

    def normalize_prompts(self, prompts: list[str]) -> list[str]:
        """校验并规范化 prompts。

        返回去除首尾空白的非空字符串列表；允许空列表（表示不请求任何分割）。
        """
        if prompts is None:
            raise InvalidPromptsError("prompts 不能为 None")
        if not isinstance(prompts, list):
            raise InvalidPromptsError(
                f"prompts 必须是 list[str]，实际为 {type(prompts)}"
            )
        normalized: list[str] = []
        for prompt in prompts:
            if not isinstance(prompt, str):
                raise InvalidPromptsError(
                    f"prompts 中每一项必须是 str，实际为 {type(prompt)}"
                )
            item = prompt.strip()
            if not item:
                raise InvalidPromptsError("prompts 中不能包含空字符串")
            normalized.append(item)
        return normalized


__all__ = [
    "Segmenter",
    "BaseSegmenter",
    "SegmenterError",
    "SegmenterUnavailable",
    "InvalidPromptsError",
    "PromptNotSupportedError",
    "EmptyImageError",
]
