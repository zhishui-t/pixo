"""pixo.vision.geometry —— 水平线检测/自动扶平。

迁移自 guanlan src/vision/horizon_det.py。输入统一为 Pixo 的 RGB 图，
使用 OpenCV Hough 直线投票估计水平线倾角并给出建议旋转角度。
该算法为纯 cv2/numpy，不依赖模型，模型缺失不影响导入。
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


def detect_horizon_angle(
    image_rgb: np.ndarray,
    sky_ratio: float | None = None,
    min_votes: int = 3,
) -> dict[str, Any]:
    """检测水平线倾角。

    Args:
        image_rgb: HxWx3 RGB 图像。
        sky_ratio: 可选天空占比；大于 0.4 时提高置信度。
        min_votes: 支持该角度的线数量阈值。

    Returns:
        {"angle": 度（逆时针为正）, "confidence": 0-1,
         "votes": 票数, "has_horizon": bool}
    """
    if image_rgb is None or image_rgb.size == 0:
        return {
            "angle": 0.0,
            "confidence": 0.0,
            "votes": 0,
            "has_horizon": False,
        }

    h, w = image_rgb.shape[:2]
    scale = min(1.0, 800.0 / max(h, w))
    if scale < 1.0:
        img = cv2.resize(
            image_rgb,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
    else:
        img = image_rgb
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blur, 50, 150)

    min_len = max(15, int(min(h, w) * 0.05))
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=40,
        minLineLength=min_len,
        maxLineGap=20,
    )
    if lines is None:
        return {
            "angle": 0.0,
            "confidence": 0.0,
            "votes": 0,
            "has_horizon": False,
        }

    angles: list[float] = []
    for line in lines:
        arr = np.asarray(line).reshape(-1, 4)
        for x1, y1, x2, y2 in arr:
            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) < 1e-6:
                continue
            angle_deg = math.degrees(math.atan2(dy, dx))
            if abs(angle_deg) <= 15:
                angles.append(angle_deg)
            elif abs(abs(angle_deg) - 180) <= 15:
                angles.append(angle_deg - 180 if angle_deg > 0 else angle_deg + 180)

    if len(angles) < min_votes:
        return {
            "angle": 0.0,
            "confidence": 0.0,
            "votes": len(angles),
            "has_horizon": False,
        }

    angles_np = np.array(angles, dtype=np.float64)
    hist, bin_edges = np.histogram(angles_np, bins=10, range=(-15, 15))
    peak_bin = int(np.argmax(hist))
    if hist[peak_bin] < min_votes:
        return {
            "angle": 0.0,
            "confidence": 0.0,
            "votes": len(angles),
            "has_horizon": False,
        }

    lo, hi = bin_edges[peak_bin], bin_edges[peak_bin + 1]
    mask = (angles_np >= lo) & (angles_np < hi)
    angle = float(np.mean(angles_np[mask]))
    confidence = min(1.0, float(hist[peak_bin]) / (min_votes * 3))
    if sky_ratio is not None and sky_ratio > 0.4:
        confidence = min(1.0, confidence + 0.2)

    return {
        "angle": round(angle, 2),
        "confidence": round(confidence, 2),
        "votes": int(hist[peak_bin]),
        "has_horizon": True,
    }


def angle_to_rotation_deg(angle: float) -> float:
    """水平线倾角 → 建议旋转扶正角度。

    与 guanlan 语义一致：crs:Angle 正值为顺时针，
    地平线逆时针倾斜 +θ 时需要顺时针旋转 θ 扶正。
    """
    return -float(angle)


class HorizonDetector:
    """水平线检测器门面（保留类式接口，便于注入/健康检查）。"""

    def __init__(self) -> None:
        self.available = True

    def detect(
        self,
        image_rgb: np.ndarray,
        sky_ratio: float | None = None,
        min_votes: int = 3,
    ) -> dict[str, Any]:
        """执行水平线检测。"""
        return detect_horizon_angle(image_rgb, sky_ratio=sky_ratio,
                                    min_votes=min_votes)

    def health_info(self) -> dict[str, Any]:
        """返回纯算法健康信息。"""
        return {
            "name": "HorizonDetector",
            "type": "algorithm",
            "provider": "opencv",
            "available": True,
            "ready": True,
            "loaded": True,
            "version": "0.1.0",
            "detail": "基于 OpenCV Hough 的水平线检测，无外部模型依赖。",
        }


def horizon_health_info() -> dict[str, Any]:
    """构造水平线检测器健康信息。"""
    return HorizonDetector().health_info()


__all__ = [
    "detect_horizon_angle",
    "angle_to_rotation_deg",
    "HorizonDetector",
    "horizon_health_info",
]
