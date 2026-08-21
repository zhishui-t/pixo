"""pixo.vision.exceptions —— 分割模块异常与降级约定。

降级约定:
  - SegmenterUnavailable: 模型未就绪/加载失败/后端不可用时抛出，
    上层捕获后应走 manual_review / fallback，禁止把模型错误当作正常结果。
  - InvalidPromptsError / PromptNotSupportedError / EmptyImageError:
    属于调用方输入错误，应由调用方修正后重试。
"""
from __future__ import annotations


class SegmenterError(RuntimeError):
    """分割相关错误基类。"""


class SegmenterUnavailable(SegmenterError):
    """分割模型不可用或未就绪。

    上层应捕获此异常并降级到 manual_review / fallback 路径。
    """


class InvalidPromptsError(ValueError):
    """prompts 参数缺失或类型/格式非法。"""


class PromptNotSupportedError(ValueError):
    """请求的 prompt 不被当前 Segmenter 支持。"""


class EmptyImageError(ValueError):
    """输入图像为空（宽或高为 0）。"""


__all__ = [
    "SegmenterError",
    "SegmenterUnavailable",
    "InvalidPromptsError",
    "PromptNotSupportedError",
    "EmptyImageError",
]
