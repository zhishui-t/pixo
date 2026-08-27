"""pixo.vision.measure —— Pixo Vision 区域/全局测量。

本模块基于 cv2/numpy 实现图像测量统计，输出对齐 docs/架构设计文档.md §5.4：
  - global: mean_luminance、highlight_clip_ratio、shadow_clip_ratio、
            contrast、preview_highlight_clip_estimate。
  - region: mask_id、confidence、area_ratio、reliable、mean_lab、
            mean_luminance、highlight_clip_ratio。

设计说明：
  - 仅依赖 numpy 与 opencv-python，不引入 torch 等重依赖。
  - 输入统一按 RGB 展示空间处理；uint8 与 float32 均可，内部转为
    0-255 浮点亮度后测量。
  - 不符合真实分割/不可靠区域时按架构文档约定降级，不抛异常。
  - 算法口径参考 guanlan src/rules/color_stats.py、exposure.py、
    zone_exposure.py、sharpness.py、motion_blur.py、haze.py 的纯
    cv2/numpy 部分，仅做 Pixo schema 所需的轻适配。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import cv2
import numpy as np

# 测量器版本，供 Trace/评审记录。
MEASURE_VERSION = "0.1.0"

# mask/测量算法版本，用于 P0-4 完整评审追溯。
DEFAULT_MASK_VERSION = "mask_v0.1"

# 8-bit 展示空间高光/阴影裁切阈值（与 guanlan exposure.py RGB 回退口径一致）。
HIGHLIGHT_CLIP_THRESHOLD = 250.0
SHADOW_CLIP_THRESHOLD = 5.0

# 可靠性规则：置信度低于 0.6 或面积占比低于 0.5% 时标记不可靠。
CONFIDENCE_THRESHOLD = 0.6
MIN_AREA_RATIO = 0.005

# BT.709 亮度系数。
_LUM_R = 0.2126
_LUM_G = 0.7152
_LUM_B = 0.0722


def _validate_image(image_rgb: np.ndarray) -> None:
    """校验输入图像是否为合法的非空 HxWx3/HxWx4 RGB 数组。"""
    if image_rgb is None:
        raise TypeError("image_rgb 不能为 None")
    if not isinstance(image_rgb, np.ndarray):
        raise TypeError(f"image_rgb 必须是 numpy.ndarray，实际为 {type(image_rgb)}")
    if image_rgb.ndim != 3:
        raise ValueError(f"image_rgb 必须是 HxWx3 数组，实际维度为 {image_rgb.ndim}")
    if image_rgb.shape[2] not in (3, 4):
        raise ValueError(
            f"image_rgb 通道数只支持 3 或 4，实际为 {image_rgb.shape[2]}"
        )
    if image_rgb.shape[0] == 0 or image_rgb.shape[1] == 0:
        raise ValueError(f"输入图像不能为空，实际 shape 为 {image_rgb.shape}")


def _to_float_rgb(image_rgb: np.ndarray) -> np.ndarray:
    """把输入 RGB 转换为 0-255 浮点 RGB，统一测量口径。"""
    _validate_image(image_rgb)
    if image_rgb.dtype == np.uint8:
        rgb = image_rgb.astype(np.float32)
    elif np.issubdtype(image_rgb.dtype, np.floating):
        rgb = image_rgb.astype(np.float32)
        finite = rgb[np.isfinite(rgb)]
        if finite.size > 0 and float(finite.max()) <= 1.01:
            # 0~1 归一化输入，先转到 0~255，保证与 uint8 口径一致。
            rgb = rgb * 255.0
    else:
        rgb = image_rgb.astype(np.float32)

    # 防御 NaN/Inf：测量不应因坏像素抛异常。
    rgb = np.nan_to_num(rgb, nan=0.0, posinf=255.0, neginf=0.0)
    if rgb.shape[2] == 4:
        rgb = rgb[..., :3]
    return rgb


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """计算 BT.709 亮度，范围为 0-255。"""
    return (
        _LUM_R * rgb[..., 0]
        + _LUM_G * rgb[..., 1]
        + _LUM_B * rgb[..., 2]
    )


def _clip_ratio(lum: np.ndarray, threshold: float, *, high: bool) -> float:
    """计算高光或阴影裁切像素占比。"""
    if lum.size == 0:
        return 0.0
    if high:
        return float(np.count_nonzero(lum >= threshold)) / float(lum.size)
    return float(np.count_nonzero(lum <= threshold)) / float(lum.size)


def _contrast(lum: np.ndarray) -> float:
    """基于归一化亮度的标准差/均值计算对比度。"""
    norm = np.clip(lum, 0.0, 255.0) / 255.0
    mean = float(np.mean(norm))
    if mean < 1e-6:
        return 0.0
    return float(np.std(norm) / mean)


def _preview_highlight_estimate(lum: np.ndarray) -> float:
    """3x3 邻域最大值池化后的高光裁切估计，避免下采样低估极值。"""
    if lum.size == 0:
        return 0.0
    kernel = np.ones((3, 3), dtype=np.uint8)
    pooled = cv2.dilate(lum, kernel)
    return _clip_ratio(pooled, HIGHLIGHT_CLIP_THRESHOLD, high=True)


def compute_proxy_metrics(image_rgb: np.ndarray) -> dict[str, float]:
    """P2 前置三代理指标（纯 numpy，无新依赖）。

    输入契约：uint8 / 0-1 浮点 RGB；内部统一归一化到 [0,1] 后计算，
    与输入量纲无关（t41 统一域，修复 0-255 口径失配）。
    输出域：
    - haze_proxy ∈ [0,1]：1-(p95-p05)/p95_gray，灰度对比度衰减度，
      0=通透 1=浓雾（比值型，尺度不变）；p95≤ε 时记 1；
    - colorfulness_proxy ∈ [0,100]：简化 Hasler 式（rg=R-G,
      yb=0.5(R+G)-B），sqrt(std_rg^2+std_yb^2)+0.3*mean(|rg|,|yb|)，
      按 [0,1] 域理论最大值 √2+0.3 归一化；
    - tonal_range ∈ [0,1]：p95-p05（归一化灰度域）。

    输入 None / 非三通道 / 空图返回空 dict——调用方据此不写缺省键。
    """
    if image_rgb is None:
        return {}
    arr = np.asarray(image_rgb)
    if arr.ndim != 3 or arr.shape[2] < 3 or arr.size == 0:
        return {}
    # 统一域：_to_float_rgb 为 0-255 测量口径，此处归一到 [0,1]
    rgb = _to_float_rgb(arr) / 255.0
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    gray = 0.2126 * r + 0.7152 * g + 0.0722 * b
    p95 = float(np.percentile(gray, 95))
    p05 = float(np.percentile(gray, 5))
    tonal_range = max(p95 - p05, 0.0)
    if p95 <= 1e-6:
        haze_proxy = 1.0
    else:
        haze_proxy = min(1.0, max(0.0, 1.0 - tonal_range / p95))
    rg = r - g
    yb = 0.5 * (r + g) - b
    std_rg = float(np.std(rg))
    std_yb = float(np.std(yb))
    mean_term = 0.15 * (float(np.mean(np.abs(rg)))
                        + float(np.mean(np.abs(yb))))
    raw = float(np.sqrt(std_rg * std_rg + std_yb * std_yb)) + mean_term
    norm_max = float(np.sqrt(2.0)) + 0.3
    colorfulness_proxy = min(100.0, max(0.0, raw / norm_max * 100.0))
    return {
        "haze_proxy": round(haze_proxy, 4),
        "colorfulness_proxy": round(colorfulness_proxy, 4),
        "tonal_range": round(tonal_range, 4),
    }


def measure_global(image_rgb: np.ndarray) -> dict[str, float]:
    """计算全图测量指标。

    Args:
        image_rgb: HxWx3 RGB 图像（uint8 或 float，0-255 或 0-1）。

    Returns:
        包含 mean_luminance、highlight_clip_ratio、shadow_clip_ratio、
        contrast、preview_highlight_clip_estimate 的字典。
    """
    rgb = _to_float_rgb(image_rgb)
    lum = _luminance(rgb)
    return {
        "mean_luminance": round(float(np.mean(lum)), 2),
        "highlight_clip_ratio": round(
            _clip_ratio(lum, HIGHLIGHT_CLIP_THRESHOLD, high=True), 6
        ),
        "preview_highlight_clip_estimate": round(
            _preview_highlight_estimate(lum), 6
        ),
        "shadow_clip_ratio": round(
            _clip_ratio(lum, SHADOW_CLIP_THRESHOLD, high=False), 6
        ),
        "contrast": round(_contrast(lum), 4),
    }


def _gray_from_rgb(rgb: np.ndarray) -> np.ndarray:
    """把 0-255 浮点 RGB 转为 uint8 灰度图。"""
    rgb_u8 = np.clip(rgb, 0.0, 255.0).astype(np.uint8)
    return cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2GRAY)


def _roi_mean_luminance(rgb: np.ndarray, roi: tuple[int, int, int, int]) -> float:
    """计算矩形 ROI 的 BT.709 平均亮度。"""
    r0, r1, c0, c1 = roi
    r0 = max(0, r0)
    r1 = min(rgb.shape[0], r1)
    c0 = max(0, c0)
    c1 = min(rgb.shape[1], c1)
    if r1 <= r0 or c1 <= c0:
        return 0.0
    patch = rgb[r0:r1, c0:c1]
    return float(np.mean(_luminance(patch)))


def _center_roi(shape: tuple[int, int], ratio: float = 0.6) -> tuple[int, int, int, int]:
    """生成中央重点区域 ROI (r0, r1, c0, c1)。"""
    h, w = shape
    ch = int(h * ratio)
    cw = int(w * ratio)
    return ((h - ch) // 2, (h - ch) // 2 + ch,
            (w - cw) // 2, (w - cw) // 2 + cw)


def _grid_rois(
    shape: tuple[int, int], rows: int = 3, cols: int = 3
) -> list[tuple[tuple[int, int, int, int], str]]:
    """生成 rows x cols 等分网格 ROI，返回 [(roi, name), ...]。"""
    h, w = shape
    rois: list[tuple[tuple[int, int, int, int], str]] = []
    r_step = h // rows
    c_step = w // cols
    for i in range(rows):
        r0 = i * r_step
        r1 = (i + 1) * r_step if i < rows - 1 else h
        for j in range(cols):
            c0 = j * c_step
            c1 = (j + 1) * c_step if j < cols - 1 else w
            rois.append(((r0, r1, c0, c1), f"({i},{j})"))
    return rois


def measure_zone_exposure(image_rgb: np.ndarray) -> dict[str, Any]:
    """分区曝光测量（中央重点 + 九宫格）。

    参考 guanlan src/rules/zone_exposure.py 的纯 numpy/cv2 逻辑，
    输出 Pixo 展示空间（0-255）平均亮度。
    """
    rgb = _to_float_rgb(image_rgb)
    h, w = rgb.shape[:2]
    full = _roi_mean_luminance(rgb, (0, h, 0, w))
    center = _roi_mean_luminance(rgb, _center_roi((h, w), 0.6))

    grid_values: list[float] = []
    for roi, _ in _grid_rois((h, w), 3, 3):
        grid_values.append(_roi_mean_luminance(rgb, roi))

    grid_center = grid_values[4] if len(grid_values) > 4 else center
    top = float(np.mean(grid_values[0:3]))
    middle = float(np.mean(grid_values[3:6]))
    bottom = float(np.mean(grid_values[6:9]))

    return {
        "full": round(full, 2),
        "center": round(center, 2),
        "grid_center": round(grid_center, 2),
        "grid": [round(v, 2) for v in grid_values],
        "top_mid_bottom": [round(top, 2), round(middle, 2), round(bottom, 2)],
    }


def _fft_high_freq_ratio(gray: np.ndarray, radius: int = 40) -> float:
    """计算频域高频能量占比（越低越可能脱焦）。"""
    if gray.size == 0:
        return 0.0
    gray_f = gray.astype(np.float32)
    f = np.fft.fft2(gray_f)
    fshift = np.fft.fftshift(f)
    mag = np.abs(fshift)
    total = float(mag.sum()) or 1.0

    h, w = gray.shape
    cy, cx = h // 2, w // 2
    y, x = np.ogrid[:h, :w]
    low_mask = (y - cy) ** 2 + (x - cx) ** 2 <= radius ** 2
    low_energy = float(mag[low_mask].sum())
    return max(0.0, min(1.0, (total - low_energy) / total))


def measure_sharpness(image_rgb: np.ndarray) -> dict[str, float]:
    """锐度/脱焦测量（拉普拉斯方差 + 去噪 + FFT 高频占比）。

    参考 guanlan src/rules/sharpness.py 的纯 cv2/numpy 算法。
    """
    rgb = _to_float_rgb(image_rgb)
    gray = _gray_from_rgb(rgb)

    lap_raw = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    med = cv2.medianBlur(gray, 5)
    lap_denoised = float(cv2.Laplacian(med, cv2.CV_64F).var())
    noise_ratio = max(0.0, min(1.0, (lap_raw - lap_denoised) / max(lap_raw, 1e-6)))
    fft_high = _fft_high_freq_ratio(gray)

    return {
        "laplacian_raw": round(lap_raw, 2),
        "laplacian_denoised": round(lap_denoised, 2),
        "noise_ratio": round(noise_ratio, 4),
        "fft_high_ratio": round(fft_high, 4),
        "detail_score": round(lap_denoised, 2),
    }


def measure_motion_blur(image_rgb: np.ndarray) -> dict[str, Any]:
    """频域运动模糊检测（方向性幅值谱分析）。

    参考 guanlan src/rules/motion_blur.py 的纯 cv2/numpy 算法。
    小图或异常输入返回无运动模糊。
    """
    rgb = _to_float_rgb(image_rgb)
    gray = _gray_from_rgb(rgb)
    try:
        dft = cv2.dft(np.float32(gray), flags=cv2.DFT_COMPLEX_OUTPUT)
        dft_shift = np.fft.fftshift(dft)
        magnitude = cv2.magnitude(dft_shift[..., 0], dft_shift[..., 1])
        magnitude = np.log1p(magnitude)

        h, w = magnitude.shape
        cx, cy = w // 2, h // 2
        max_radius = min(cx, cy) - 5
        if max_radius <= 1:
            return {"has_motion_blur": False, "angle": 0.0, "strength": 0.0,
                    "error": None}

        angles = np.arange(0, 180, 5)
        radial_sums: list[float] = []
        for angle_deg in angles:
            angle_rad = float(np.deg2rad(angle_deg))
            line_sum = 0.0
            count = 0
            for r in range(5, max_radius, 2):
                x = int(cx + r * np.cos(angle_rad))
                y = int(cy + r * np.sin(angle_rad))
                if 0 <= x < w and 0 <= y < h:
                    line_sum += float(magnitude[y, x])
                    count += 1
                x2 = int(cx - r * np.cos(angle_rad))
                y2 = int(cy - r * np.sin(angle_rad))
                if 0 <= x2 < w and 0 <= y2 < h:
                    line_sum += float(magnitude[y2, x2])
                    count += 1
            radial_sums.append(line_sum / max(count, 1))

        radial = np.array(radial_sums, dtype=np.float64)
        mean_radial = float(np.mean(radial))
        if mean_radial < 1e-6:
            strength = 0.0
            angle = 0.0
        else:
            cv_val = float(np.std(radial) / mean_radial)
            strength = min(1.0, cv_val * 10.0)
            min_idx = int(np.argmin(radial))
            angle = float(angles[min_idx])

        return {
            "has_motion_blur": strength > 0.35,
            "angle": round(angle, 1),
            "strength": round(strength, 4),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - 测量降级
        return {"has_motion_blur": False, "angle": 0.0, "strength": 0.0,
                "error": str(exc)}


def measure_haze(image_rgb: np.ndarray) -> dict[str, float]:
    """雾密度估计（DCP 暗通道先验）。

    参考 guanlan src/rules/haze.py 的纯 cv2/numpy 算法。
    """
    rgb = _to_float_rgb(image_rgb)
    dark = np.min(rgb, axis=2).astype(np.float32) / 255.0
    h, w = dark.shape
    patch = 15
    if max(h, w) > 800:
        scale = 800.0 / float(max(h, w))
        dark = cv2.resize(dark, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_AREA)
        patch = max(7, int(patch * scale))

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch))
    dark_channel = cv2.erode(dark, kernel)
    bright_ratio = float(np.mean(dark > 0.9))
    haze = float(np.mean(dark_channel))
    saturated = float(np.mean(dark_channel > 0.9))
    if saturated > 0.3:
        haze *= 0.3

    return {
        "haze_density": round(max(0.0, min(1.0, haze)), 4),
        "dark_channel_mean": round(float(haze), 4),
        "sky_ratio": round(bright_ratio, 4),
    }


def _prepare_mask(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """把 mask 规范为 bool 数组；NaN/Inf 按 0 处理。"""
    if mask is None:
        return np.zeros(shape, dtype=bool)
    arr = np.asarray(mask)
    if arr.shape != shape:
        raise ValueError(
            f"mask shape {arr.shape} 与图像 shape {shape} 不一致"
        )
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr.astype(bool)


def _region_mean_lab(rgb: np.ndarray, mask: np.ndarray) -> dict[str, float] | None:
    """计算区域内真实 Lab 均值。

    按 guanlan 口径输出：L 为 0-100，a/b 为围绕 0 的有符号值。
    """
    pixels = rgb[mask]
    if pixels.size == 0:
        return None
    pixels_u8 = np.clip(pixels, 0.0, 255.0).astype(np.uint8).reshape(1, -1, 3)
    lab = cv2.cvtColor(pixels_u8, cv2.COLOR_RGB2LAB)
    return {
        "L": round(float(np.mean(lab[..., 0])) / 2.55, 1),
        "a": round(float(np.mean(lab[..., 1])) - 128.0, 1),
        "b": round(float(np.mean(lab[..., 2])) - 128.0, 1),
    }


def measure_region(
    image_rgb: np.ndarray,
    mask: np.ndarray,
    metrics: Sequence[str] | None = None,
    *,
    confidence: float = 1.0,
    mask_id: str | None = None,
) -> dict[str, Any]:
    """计算单个区域测量指标。

    Args:
        image_rgb: HxWx3 RGB 图像。
        mask: 与图像同尺寸的 mask（0/255、bool、float 均可）。
        metrics: 预留指标过滤参数；当前始终返回 §5.4 完整区域字段。
        confidence: 分割器输出的置信度，默认 1.0。
        mask_id: 区域 mask 标识，例如 face_0；缺省为 None。

    Returns:
        符合架构文档 §5.4 的区域测量字典。
    """
    rgb = _to_float_rgb(image_rgb)
    mask_bool = _prepare_mask(mask, rgb.shape[:2])

    total = rgb.shape[0] * rgb.shape[1]
    selected = int(np.count_nonzero(mask_bool))
    area_ratio = float(selected) / float(total) if total > 0 else 0.0

    if not np.isfinite(confidence):
        confidence = 0.0
    confidence = float(confidence)
    reliable = bool(
        confidence >= CONFIDENCE_THRESHOLD and area_ratio >= MIN_AREA_RATIO
    )

    if selected == 0:
        # 空 mask / 全零 / NaN 均不抛异常，返回不可靠的空区域结果。
        return {
            "mask_id": mask_id,
            "confidence": round(confidence, 4),
            "area_ratio": round(area_ratio, 6),
            "reliable": False,
            "mean_lab": None,
            "mean_luminance": None,
            "highlight_clip_ratio": 0.0,
        }

    lum = _luminance(rgb)
    region_lum = lum[mask_bool]
    mean_luminance = float(np.mean(region_lum))
    highlight_clip_ratio = float(
        np.count_nonzero(region_lum >= HIGHLIGHT_CLIP_THRESHOLD)
    ) / float(selected)

    return {
        "mask_id": mask_id,
        "confidence": round(confidence, 4),
        "area_ratio": round(area_ratio, 6),
        "reliable": reliable,
        "mean_lab": _region_mean_lab(rgb, mask_bool),
        "mean_luminance": round(mean_luminance, 2),
        "highlight_clip_ratio": round(highlight_clip_ratio, 6),
    }


class VisionMeasure:
    """Pixo Vision 测量器：提供全局与区域测量入口。"""

    def __init__(self, *, version: str = MEASURE_VERSION) -> None:
        self.version = version

    def measure_global(self, image_rgb: np.ndarray) -> dict[str, float]:
        """计算全图测量。"""
        return measure_global(image_rgb)

    def measure_region(
        self,
        image_rgb: np.ndarray,
        mask: np.ndarray,
        metrics: Sequence[str] | None = None,
        *,
        confidence: float = 1.0,
        mask_id: str | None = None,
    ) -> dict[str, Any]:
        """计算单个区域测量。"""
        return measure_region(
            image_rgb,
            mask,
            metrics,
            confidence=confidence,
            mask_id=mask_id,
        )

    def measure(
        self,
        image_rgb: np.ndarray,
        masks: Mapping[str, np.ndarray],
        *,
        confidences: Mapping[str, float] | None = None,
        image_id: str | None = None,
        render_version: str | None = None,
        detection_version: str | None = None,
        mask_version: str | None = None,
    ) -> dict[str, Any]:
        """计算全局与多个区域测量，并组装为 §5.4 结构。

        Args:
            image_rgb: HxWx3 RGB 图像。
            masks: prompt -> mask 字典，例如 {"face": mask, "sky": mask}。
            confidences: 可选 prompt -> 置信度；缺省按 1.0。
            image_id / render_version / detection_version / mask_version:
                可选溯源字段；mask_version 缺省使用 DEFAULT_MASK_VERSION。

        Returns:
            包含 global、regions 与版本字段的完整测量报告。
        """
        rgb = _to_float_rgb(image_rgb)
        global_result = measure_global(rgb)
        global_result["detail"] = {
            "zone_exposure": measure_zone_exposure(rgb),
            "sharpness": measure_sharpness(rgb),
            "motion_blur": measure_motion_blur(rgb),
            "haze": measure_haze(rgb),
            "thresholds": {
                "highlight_clip": HIGHLIGHT_CLIP_THRESHOLD,
                "shadow_clip": SHADOW_CLIP_THRESHOLD,
                "confidence": CONFIDENCE_THRESHOLD,
                "min_area_ratio": MIN_AREA_RATIO,
            },
        }

        regions: dict[str, Any] = {}
        for name, mask in masks.items():
            conf = 1.0
            if confidences is not None:
                conf = float(confidences.get(name, 1.0))
            regions[name] = self.measure_region(
                rgb,
                mask,
                confidence=conf,
                mask_id=f"{name}_0",
            )

        return {
            "image_id": image_id,
            "render_version": render_version,
            "detection_version": detection_version,
            "mask_version": mask_version or DEFAULT_MASK_VERSION,
            "regions": regions,
            "global": global_result,
        }


__all__ = [
    "VisionMeasure",
    "compute_proxy_metrics",
    "measure_global",
    "measure_region",
    "measure_zone_exposure",
    "measure_sharpness",
    "measure_motion_blur",
    "measure_haze",
    "MEASURE_VERSION",
    "DEFAULT_MASK_VERSION",
]
