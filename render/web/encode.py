"""pixo.render Web/自动化输出编码器（v1.5）。

提供 8-bit JPEG/WebP 与 16-bit PNG-16/TIFF-16/raw48 编码。
所有函数输入为 RGB 图像；8-bit 输入可为 float32 [0,1] 或 uint8，
16-bit 输入为 uint16 [0,65535] 或 float32 [0,1]（自动量化）。
"""
from __future__ import annotations

from typing import Union

import cv2
import numpy as np


def _to_uint8(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb)
    if arr.dtype == np.uint8:
        return np.ascontiguousarray(arr)
    if arr.dtype == np.uint16:
        return np.clip((arr.astype(np.float32) / 65535.0) * 255.0 + 0.5,
                       0, 255).astype(np.uint8)
    return np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _to_uint16(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb)
    if arr.dtype == np.uint16:
        return np.ascontiguousarray(arr)
    if arr.dtype == np.uint8:
        return (arr.astype(np.uint16) * 257).astype(np.uint16)
    return np.clip(arr * 65535.0 + 0.5, 0, 65535).astype(np.uint16)


def encode_jpeg(rgb: np.ndarray, quality: int = 88) -> bytes:
    """RGB -> JPEG bytes（默认 q=88，v1.5 预览档）。"""
    rgb8 = _to_uint8(rgb)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR),
                           [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("JPEG 编码失败")
    return buf.tobytes()


def encode_webp(rgb: np.ndarray, quality: int = 85) -> bytes:
    """RGB -> WebP bytes（默认 q=85，v1.5 预览档）。"""
    rgb8 = _to_uint8(rgb)
    ok, buf = cv2.imencode(".webp", cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR),
                           [cv2.IMWRITE_WEBP_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("WebP 编码失败")
    return buf.tobytes()


def encode_png16(rgb: np.ndarray) -> bytes:
    """RGB uint16 -> PNG-16 bytes。"""
    rgb16 = _to_uint16(rgb)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb16, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("PNG-16 编码失败")
    return buf.tobytes()


def encode_tiff16(rgb: np.ndarray) -> bytes:
    """RGB uint16 -> TIFF-16 bytes（cv2 16-bit TIFF 输出）。"""
    rgb16 = _to_uint16(rgb)
    ok, buf = cv2.imencode(".tiff", cv2.cvtColor(rgb16, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("TIFF-16 编码失败")
    return buf.tobytes()


def encode_raw48(rgb: np.ndarray) -> bytes:
    """RGB uint16 -> 48bpp raw，行主序，每通道 uint16 大端。"""
    rgb16 = _to_uint16(rgb)
    if rgb16.ndim != 3 or rgb16.shape[2] != 3:
        raise ValueError(f"raw48 需要 (H,W,3)，实际 {rgb16.shape}")
    # 大端 uint16 视图再 tobytes，保证每通道 2 字节大端。
    return np.ascontiguousarray(rgb16).astype(">u2", copy=False).tobytes()


def encode_image(rgb: np.ndarray, fmt: str,
                 quality: Union[int, None] = None) -> bytes:
    """按 fmt 分发：jpeg/webp/png16/tiff16/raw48。

    默认质量：JPEG 88，WebP 85（v1.5 预览档）。
    """
    fmt = fmt.lower()
    if quality is None:
        quality = 85 if fmt == "webp" else 88
    if fmt == "jpeg" or fmt == "jpg":
        return encode_jpeg(rgb, quality=quality)
    if fmt == "webp":
        return encode_webp(rgb, quality=quality)
    if fmt == "png16":
        return encode_png16(rgb)
    if fmt == "tiff16":
        return encode_tiff16(rgb)
    if fmt == "raw48":
        return encode_raw48(rgb)
    raise ValueError(f"不支持的编码格式: {fmt}")


__all__ = [
    "encode_jpeg", "encode_webp", "encode_png16", "encode_tiff16",
    "encode_raw48", "encode_image",
]
