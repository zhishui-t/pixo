"""gate golden 用例定义：生成器与校验测试共享，保证输入与计算口径一致。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from pixo.render.core.color import temp_tint_to_wb
from pixo.render.core.curves import apply_lut1d, make_base_curve_lut
from pixo.render.core.enhance import clarity
from pixo.render.core.hsl import hsl_adjust_rgb
from pixo.render.core.hsl_oklch import DEFAULT_BANDS_OKLCH, oklch_adjust_rgb
from pixo.render.core.huesat import apply_local_warm_sat
from pixo.render.core.lut3d import LUT3D
from pixo.render.core.skin import skin_mask, skin_mask_oklab
from pixo.render.core.split_tone import split_tone_rgb
from pixo.render.core.split_tone_oklab import split_tone_oklab_rgb
from pixo.render.core.usercal import apply_usercal_rgb
from pixo.render.modules.exposure import soft_highlight_rolloff
from pixo.render.modules.refine import RefineStage

FEATURES = (
    "exposure", "whitebalance", "curves", "huesat", "clarity", "colorcal",
    "calibration", "hsl", "hsl_oklch", "split_tone", "split_tone_oklab",
    "skin", "skin_oklch", "stylize", "refine",
    # 标定数据敏感 case (t36 §5 门禁缺口关闭): 触达正式标定表的 auto 路径,
    # 换表即漂移 (前置 15 case 均为纯函数+显式参数, 对表替换零敏感)。
    "exposure_cal_auto", "warmth_cal_auto",
)

_DCP_PATH = (Path(__file__).resolve().parents[3] / "resources" / "dcp"
                     / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")


class _CalAutoRaw:
    """标定 auto case 的最小 raw 桩: _auto_ev 经 state["camera_wb"] 取 wb_B,
    raw 仅需满足 _subject_box 的 getattr 探测 (无 subject box → 全图探针)。"""

    camera_whitebalance = [2.0, 1.0, 1.5, 1.0]


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
        from pixo.render.core.calibration import load_dcp
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
        from pixo.render import _native as native
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
    if feature == "hsl_oklch":
        # OKLCh 域 8 带典型参数（设计 §2.5）：DEFAULT_BANDS_OKLCH 骨架
        # （感知色相角中心 + domain:"oklch" 戳）+ 红带 hue/sat、绿带 sat、
        # 蓝带 hue/lum 典型量（与 hsv 版 hsl case 同量级），三条参数路径
        # （hue_shift/saturation 软限幅/luminance）各至少一条被触达。
        # 输入用种子随机图而非 _color_steps()：纯色是 sRGB 色域顶点，
        # 软限幅在包络处渐近 + clip 精确拉回，色阶图上多数行会"巧合地"
        # 逐位不动，锁不住掩码形状；随机图覆盖全色相/色度平面。
        bands = [dict(b) for b in DEFAULT_BANDS_OKLCH]
        bands[0]["hue_shift"] = 5.0    # red 29°
        bands[0]["saturation"] = 20.0
        bands[3]["saturation"] = 15.0  # green 145°
        bands[5]["hue_shift"] = -8.0   # blue 264°
        bands[5]["luminance"] = 10.0
        return oklch_adjust_rgb(_random_small(), bands)
    if feature == "split_tone":
        return split_tone_rgb(_color_steps(), 30.0, 30.0, 210.0, 40.0)
    if feature == "split_tone_oklab":
        # 与 hsv 版 split_tone case 完全同参（30/30/210/40），供 reviewer
        # 在同一输入上做 hsv↔oklch 域 A/B 对照（语义对齐验证）。
        return split_tone_oklab_rgb(_color_steps(), 30.0, 30.0, 210.0, 40.0)
    if feature == "skin":
        return skin_mask(_skin_patch()).astype(np.float32)
    if feature == "skin_oklch":
        # OKLab 域肤色掩码（终审 G-1）：与 hsv 版 skin case 同一 _skin_patch()
        # 输入构造，走 skin_mask_oklab（float [0,1] 契约，显式 /255；uint8 直传
        # 在函数内同为 /255，逐位等价）。锁定 SKIN_OKLAB_* 椭圆几何：经典肤色块
        # (210,155,130) 应在核内（d≈0.85 → 全量 1），128 灰底应在核外（d≈1.43 → 0），
        # 常数漂移使 d 越过 1±band 边界即翻红。
        return skin_mask_oklab(_skin_patch() / 255.0).astype(np.float32)
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
    if feature == "exposure_cal_auto":
        # 正式曝光标定表敏感 case (t36 §5): 走 ExposureStage._auto_ev 完整
        # auto 决策链 —— 固定网格 med 探针 (真 DCP cam→sRGB) → 二维表
        # (src/pixo/render/target_offset.json) med 主键 + wb_B 邻域二次插值
        # (ctx.state["camera_wb"] 驱动)。平坦场亮度定标使探针 med ≈ −4.54,
        # 落在表结点密集段 (−4.632/−4.555/−4.478…, 非端点钳位); wb_B = 1.5
        # 落在 1.371~1.506 插值段 —— 换表即漂移。ev 应用与现有 exposure case
        # 同式 (线性增益 + soft_highlight_rolloff)。
        from pixo.render.core.calibration import load_dcp
        from pixo.render.pipeline.graph import DOMAIN_LINEAR_CAM, StageContext
        from pixo.render.modules.exposure import ExposureStage
        prof = load_dcp(_DCP_PATH)
        rng = np.random.default_rng(20260904)
        img = np.full((64, 64, 3), 0.04, dtype=np.float32)
        img += (rng.random((64, 64, 1)).astype(np.float32) - 0.5) * 0.004
        ctx = StageContext(
            "cal_auto.nef", raw=_CalAutoRaw(), prof=prof,
            config={"stages": {"exposure": {"target_offset": 0.0}}})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["camera_wb"] = np.array([2.0, 1.0, 1.5], dtype=np.float32)
        ev = ExposureStage()._auto_ev(ctx)
        return soft_highlight_rolloff(img * np.float32(2.0 ** ev), knee=0.9)
    if feature == "warmth_cal_auto":
        # 正式 warmth 分桶曲线敏感 case (t36 §5): _load_warm_cal 读
        # configs/calibration/warmth_curve.json (缺失/非法即 raise —— 不允许
        # 静默回退制造"仍在锁表"假象) → apply_warmth 曲线分支 (优先于内置
        # 斜率模型) 得三通道增益, 乘种子线性 cam RGB (运行时同式)。
        # wb_B = 2.0 取结点 1.8027~2.3984 插值段 (增益非恒等, 对结点值敏感)。
        from pixo.render.modules.white_balance import (
            DEFAULT_WARM_CAL_FILE, _load_warm_cal, apply_warmth)
        cal = _load_warm_cal(DEFAULT_WARM_CAL_FILE)
        if cal is None or cal.get("curve") is None:
            raise RuntimeError(
                "正式 warmth 曲线缺失/非法: warmth_cal_auto case 依赖 "
                "configs/calibration/warmth_curve.json")
        wb = np.array([1.244, 1.0, 2.0], dtype=np.float32)
        gain = apply_warmth(wb, None, warmth=1.0,
                            cal={"curve": cal["curve"]})
        return _random_small() * gain
    raise KeyError(f"未知 golden feature: {feature}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
