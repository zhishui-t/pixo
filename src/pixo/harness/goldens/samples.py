"""pixo.harness.goldens.samples —— 合成金样本生成器与内置登记数据。

不依赖真实 RAW；真实路径缺失的条目通过 available=False + skip_reason 占位。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from pixo.vision import VisionMeasure

from .manifest import GOLDEN_MANIFEST_VERSION, GoldenSample

DEFAULT_SIZE = 96

_TYPE_ALIASES = {
    "曝光": "exposure",
    "肤色": "skin",
    "场景": "scene",
    "连拍": "burst",
}


def _normalize_type(sample_type: str) -> str:
    """把中文类型名归一化为英文内部类型。"""
    return _TYPE_ALIASES.get(sample_type, sample_type)


def _ellipse_mask(
    height: int,
    width: int,
    center_y: float,
    center_x: float,
    radius_y: float,
    radius_x: float,
) -> np.ndarray:
    """生成 0/255 椭圆 mask。"""
    yy, xx = np.ogrid[:height, :width]
    inside = (
        ((yy - center_y) / max(1.0, radius_y)) ** 2
        + ((xx - center_x) / max(1.0, radius_x)) ** 2
        <= 1.0
    )
    return inside.astype(np.uint8) * 255


def _top_band_mask(height: int, width: int, ratio: float) -> np.ndarray:
    """生成顶部条带 mask。"""
    mask = np.zeros((height, width), dtype=np.uint8)
    y1 = max(1, int(round(height * ratio)))
    mask[:y1, :] = 255
    return mask


def _bottom_band_mask(height: int, width: int, ratio: float) -> np.ndarray:
    """生成底部条带 mask。"""
    mask = np.zeros((height, width), dtype=np.uint8)
    y0 = max(0, int(round(height * ratio)))
    if y0 < height:
        mask[y0:, :] = 255
    else:
        mask[-1, :] = 255
    return mask


def generate_synthetic_sample(
    sample_type: str,
    seed: int = 0,
    size: tuple[int, int] = (DEFAULT_SIZE, DEFAULT_SIZE),
) -> dict[str, Any]:
    """生成一张合成 RGB 图像与对应 mask。

    Returns:
        {"image": uint8 HxWx3, "masks": {"face":..., "sky":..., "plant":...},
         "meta": {...}}
    """
    sample_type = _normalize_type(sample_type)
    height, width = int(size[0]), int(size[1])
    rng = np.random.default_rng(seed)
    if sample_type == "exposure":
        # 左暗右亮渐变 + 中央过曝块，模拟曝光金样本。
        x = np.linspace(0.0, 1.0, width, dtype=np.float32)
        y = np.linspace(0.0, 1.0, height, dtype=np.float32)
        img = (x[None, :] * 255.0 + y[:, None] * 30.0).astype(np.float32)
        img = np.repeat(img[:, :, None], 3, axis=2)
        img[height // 3 : 2 * height // 3, width // 3 : 2 * width // 3] = 250.0
        image = np.clip(img, 0, 255).astype(np.uint8)
    elif sample_type == "skin":
        # 灰背景 + 中央肤色椭圆，模拟肤色金样本。
        image = np.full((height, width, 3), 120, dtype=np.uint8)
        yy, xx = np.ogrid[:height, :width]
        inside = (
            ((yy - height * 0.5) / (height * 0.35)) ** 2
            + ((xx - width * 0.5) / (width * 0.30)) ** 2
            <= 1.0
        )
        image[inside] = (210, 155, 130)
    elif sample_type == "scene":
        # 天空蓝渐变 + 底部植物绿，模拟场景金样本。
        image = np.zeros((height, width, 3), dtype=np.uint8)
        sky_end = int(round(height * 0.40))
        for row in range(sky_end):
            t = row / max(1, sky_end - 1)
            image[row, :, 0] = int(180 - 60 * t)
            image[row, :, 1] = int(200 - 40 * t)
            image[row, :, 2] = int(240 - 20 * t)
        green_start = int(round(height * 0.60))
        for row in range(green_start, height):
            t = (row - green_start) / max(1, height - green_start)
            image[row, :, 1] = int(120 + 60 * t)
            image[row, :, 2] = int(40 + 30 * t)
            image[row, :, 0] = int(30 + 20 * t)
    elif sample_type == "burst":
        # 连拍样本复用场景结构并叠加确定性噪声，仅用于基础占位。
        base = generate_synthetic_sample("scene", seed=0, size=size)["image"]
        noise = rng.integers(0, 16, size=(height, width, 3), dtype=np.uint8)
        image = np.clip(base.astype(np.int16) + noise.astype(np.int16), 0, 255).astype(
            np.uint8
        )
    else:
        raise ValueError(f"未知金样本类型: {sample_type}")

    masks: dict[str, np.ndarray] = {
        "face": _ellipse_mask(height, width, height * 0.50, width * 0.50,
                              height * 0.30, width * 0.20),
        "sky": _top_band_mask(height, width, 0.40),
        "plant": _bottom_band_mask(height, width, 0.55),
    }
    return {
        "image": image,
        "masks": masks,
        "meta": {
            "sample_type": sample_type,
            "seed": int(seed),
            "size": [height, width],
            "generator": "pixo.harness.goldens.samples",
            "mask_ref": {
                "face": "synthetic:face_ellipse",
                "sky": "synthetic:sky_band",
                "plant": "synthetic:plant_band",
            },
        },
    }


def compute_expected_metrics(
    image: np.ndarray,
    masks: dict[str, np.ndarray],
) -> dict[str, float | None]:
    """用当前测量器为合成样本生成期望指标（v0 自动基线）。"""
    measurement = VisionMeasure().measure(
        image,
        masks,
        image_id="synthetic",
        render_version="golden_v0",
        detection_version="synthetic_v0",
        mask_version="mask_v0",
    )
    global_data = measurement.get("global") or {}
    regions = measurement.get("regions") or {}
    expected: dict[str, float | None] = {
        "global.mean_luminance": global_data.get("mean_luminance"),
        "global.highlight_clip_ratio": global_data.get("highlight_clip_ratio"),
        "global.shadow_clip_ratio": global_data.get("shadow_clip_ratio"),
        "global.contrast": global_data.get("contrast"),
    }
    for name in ("face", "sky", "plant"):
        region = regions.get(name) or {}
        expected[f"regions.{name}.mean_luminance"] = region.get("mean_luminance")
        expected[f"regions.{name}.area_ratio"] = region.get("area_ratio")
    return expected


def _make_synthetic_sample(
    photo_id: str,
    sample_type: str,
    seed: int,
) -> GoldenSample:
    """构造一条内置合成样本。"""
    generated = generate_synthetic_sample(sample_type, seed=seed)
    metrics = compute_expected_metrics(generated["image"], generated["masks"])
    return GoldenSample(
        photo_id=photo_id,
        type=sample_type,
        expected_metrics=metrics,
        synthetic=True,
        generator="pixo.harness.goldens.samples",
        seed=seed,
        mask_ref=dict(generated["meta"]["mask_ref"]),
        version=GOLDEN_MANIFEST_VERSION,
        available=True,
    )


def _make_real_placeholder(
    photo_id: str,
    sample_type: str,
    input_path: str,
) -> GoldenSample:
    """构造真实 RAW 占位条目（文件缺失时 skip）。"""
    return GoldenSample(
        photo_id=photo_id,
        type=sample_type,
        expected_metrics={},
        input_path=input_path,
        synthetic=False,
        available=False,
        skip_reason="raw_missing",
        version=GOLDEN_MANIFEST_VERSION,
    )


def build_builtin_samples() -> list[GoldenSample]:
    """返回内置金样本列表：少量合成 + 真实路径占位。"""
    samples: list[GoldenSample] = [
        _make_synthetic_sample("syn_exposure_001", "exposure", 1),
        _make_synthetic_sample("syn_skin_001", "skin", 2),
        _make_synthetic_sample("syn_scene_001", "scene", 3),
        _make_synthetic_sample("syn_burst_001", "burst", 4),
    ]
    placeholders = [
        ("raw_exposure_placeholder_001", "exposure",
         "K:/data/pixo/goldens/exposure_001.NEF"),
        ("raw_skin_placeholder_001", "skin",
         "K:/data/pixo/goldens/skin_001.NEF"),
        ("raw_scene_placeholder_001", "scene",
         "K:/data/pixo/goldens/scene_001.NEF"),
        ("raw_burst_placeholder_001", "burst",
         "K:/data/pixo/goldens/burst_001.NEF"),
    ]
    for photo_id, sample_type, path in placeholders:
        samples.append(_make_real_placeholder(photo_id, sample_type, path))
    return samples


def build_manifest_dict() -> dict[str, Any]:
    """构造可直接保存的 manifest 字典。"""
    samples = build_builtin_samples()
    return {
        "schema": "pixo-goldens-v0",
        "version": GOLDEN_MANIFEST_VERSION,
        "samples": [s.to_dict() for s in samples],
    }


__all__ = [
    "DEFAULT_SIZE",
    "generate_synthetic_sample",
    "compute_expected_metrics",
    "build_builtin_samples",
    "build_manifest_dict",
]
