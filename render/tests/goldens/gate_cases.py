"""gate golden 用例定义：生成器与校验测试共享，保证输入与计算口径一致。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from render.core.color import temp_tint_to_wb
from render.core.curves import apply_lut1d, make_base_curve_lut
from render.core.enhance import clarity
from render.core.hsl import hsl_adjust_rgb
from render.core.huesat import apply_local_warm_sat
from render.core.lut3d import LUT3D
from render.core.skin import skin_mask
from render.core.split_tone import split_tone_rgb
from render.core.usercal import apply_usercal_rgb
from render.modules.exposure import soft_highlight_rolloff
from render.modules.refine import RefineStage

FEATURES = (
    "exposure", "whitebalance", "curves", "huesat", "clarity", "colorcal",
    "calibration", "hsl", "split_tone", "skin", "stylize", "refine",
)

_DCP_PATH = (Path(__file__).resolve().parents[2] / "profiles"
             / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")


def _color_steps():
    colors = np.array([
        [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0],
        [0, 1, 1], [1, 0, 1], [0.5, 0.5, 0.5], [0, 0, 0],
    ], dtype=np.float32)
    return np.repeat(np.repeat(colors.reshape(8, 1, 3), 8, axis=1), 1, axis=0)


def _gray_ramp():
    return np.linspace(0.0, 1.0, 256, dtype=np.float32).reshape(256, 1, 1)


def _warm_highlight():
    img = np.full((64, 64, 3), 0.05, dtype=np.float32)
    img[28:36, 28:36] = (0.9, 0.3, 0.05)
    return img


def _skin_patch():
    img = np.full((64, 64, 3), 128, dtype=np.uint8)
    img[16:48, 16:48] = (210, 155, 130)
    return img


def _random_small():
    return np.random.default_rng(20260820).random((64, 64, 3), dtype=np.float32)


def compute(feature: str) -> np.ndarray:
    if feature == "exposure":
        return soft_highlight_rolloff(_gray_ramp() * 2.0, knee=0.9)
    if feature == "whitebalance":
        from render.core.calibration import load_dcp
        prof = load_dcp(_DCP_PATH)
        return temp_tint_to_wb(prof, 5000.0, 10.0).astype(np.float32)
    if feature == "curves":
        lut = make_base_curve_lut(eotf="srgb", gamma=2.2, n=4096)
        return apply_lut1d(_color_steps(), lut)
    if feature == "huesat":
        return apply_local_warm_sat(
            _warm_highlight(), sat_scale=2.0, spot_sat_scale=2.0,
            hue_center=22.5, hue_halfwidth=17.5, sat_min=0.05, val_min=0.6,
            coverage_max=0.0015)
    if feature == "clarity":
        return clarity(_color_steps(), strength=0.3)
    if feature == "colorcal":
        from render import _native as native
        if not native.available():
            raise RuntimeError("native DLL 缺失，无法生成 colorcal golden")
        u8 = (_color_steps() * 255.0 + 0.5).astype(np.uint8)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        params = native.PixoRenderColorCalParams(
            saturation=0.2, vibrance=0.1, hueDeg=5.0, skinProtect=0.5)
        return native.colorcal_apply_lab(lab, params).astype(np.float32)
    if feature == "calibration":
        return apply_usercal_rgb(
            _color_steps(), shadow_tint=20.0, red_hue=5.0, red_sat=15.0,
            green_hue=-4.0, green_sat=10.0, blue_hue=3.0, blue_sat=-10.0)
    if feature == "hsl":
        bands = [{"name": "red", "hue_center": 0.0, "width": 40.0,
                  "hue_shift": 5.0, "saturation": 20.0, "luminance": 0.0}]
        return hsl_adjust_rgb(_color_steps(), bands)
    if feature == "split_tone":
        return split_tone_rgb(_color_steps(), 30.0, 30.0, 210.0, 40.0)
    if feature == "skin":
        return skin_mask(_skin_patch()).astype(np.float32)
    if feature == "stylize":
        g = np.linspace(0.0, 1.0, 2, dtype=np.float32)
        r, gg, b = np.meshgrid(g, g, g, indexing="ij")
        lut = LUT3D(np.stack([1.0 - r, 1.0 - gg, 1.0 - b], axis=-1))
        u8 = (_color_steps() * 255.0 + 0.5).astype(np.uint8)
        return lut.apply(u8, strength=0.5).astype(np.float32)
    if feature == "refine":
        img = _random_small()
        gray = RefineStage._gray(img)
        return RefineStage._sharpen_gray(img, 0.25, gray)
    raise KeyError(f"未知 golden feature: {feature}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
