"""阶段1: 相机曝光+色彩还原管线 (base渲染 → 三通道 tone LUT → Lab post-cal)。

数据文件 (out/exp_compare/):
  tone_lut_final.json  — 拟合得到的 256 点三通道 LUT (base输出 → 相机值)
  post_cal.json        — Lab 空间 5 标量后校正

用法:
  from rawlab.cal_step1 import render_step1
  rgb8 = render_step1(raw_path, prof, half_size=False)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .dcp import DcpProfile
from .render import (decode_raw, camera_neutral_wb, apply_dcp_matrix,
                     gamma_encode, apply_highlight_correction)

_CAL_DIR = Path(__file__).resolve().parent / "out" / "exp_compare"


def load_step1_lut() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = json.load(open(_CAL_DIR / "tone_lut_final.json", encoding="utf-8"))
    return tuple(
        np.clip(np.array(data[k], dtype=np.float32).round(), 0, 255).astype(np.uint8)
        for k in ("lut_r", "lut_g", "lut_b")
    )


def load_post_cal() -> dict:
    return json.load(open(_CAL_DIR / "post_cal.json", encoding="utf-8"))


def load_exp_offset() -> list[float] | None:
    p = _CAL_DIR / "exp_offset.json"
    if not p.exists():
        return None
    return json.load(open(p, encoding="utf-8"))["coef"]


def per_photo_offset(rgb8: np.ndarray, coef: list[float] | None) -> float:
    """按画面中位亮度预测曝光偏移 (gamma 域)。"""
    if coef is None:
        return 0.0
    med = float(np.median(cv2.cvtColor(rgb8, cv2.COLOR_RGB2GRAY)))
    return float(np.polyval(coef, med))


def apply_tone_lut(rgb8: np.ndarray,
                   luts: Optional[tuple[np.ndarray, ...]] = None) -> np.ndarray:
    if luts is None:
        luts = load_step1_lut()
    return np.stack([luts[c][rgb8[:, :, c]] for c in range(3)], axis=-1)


def apply_post_cal(rgb8: np.ndarray, post: Optional[dict] = None) -> np.ndarray:
    if post is None:
        post = load_post_cal()
    lab = cv2.cvtColor(rgb8, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
    L = np.clip(128 + post["s"] * (L - 128) + post["L_off"], 0, 255)
    a = np.clip(128 + post["g"] * (a - 128) + post["a_off"], 0, 255)
    b = np.clip(128 + post["g"] * (b - 128) + post["b_off"], 0, 255)
    return cv2.cvtColor(np.stack([L, a, b], axis=-1).astype(np.uint8),
                        cv2.COLOR_LAB2RGB)


def render_step1(raw_path: str | Path, prof: Optional[DcpProfile],
                 half_size: bool = False) -> np.ndarray:
    """阶段1 成品: 对齐相机预览的 8bit RGB。"""
    img, raw = decode_raw(raw_path, half_size=half_size)
    wb = camera_neutral_wb(raw, prof)
    lin = apply_dcp_matrix(img, wb, prof)
    out = apply_highlight_correction(gamma_encode(lin))
    off = per_photo_offset(out, load_exp_offset())
    if off:
        out = np.clip(out.astype(np.float32) + off, 0, 255).astype(np.uint8)
    out = apply_tone_lut(out)
    return apply_post_cal(out)
