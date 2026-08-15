"""渲染管线 —— 阶段0/1核心: rawpy 解码 → DCP 色彩矩阵 → 曝光 → gamma → 输出。

管线（完全无 Adobe 依赖）:
    NEF/RAW → rawpy 解码(相机原始 RGB, 16bit)
           → 白平衡(相机 As Shot)
           → ColorMatrix1: 相机RGB → XYZ(D50)
           → Bradford: D50 → D65
           → 线性 sRGB
           → 曝光调整(线性域 rgb *= 2^ev)
           → 对比度 S 曲线(查表)
           → gamma 1/2.2 编码 → 8bit JPEG

验收(阶段1): 任意 Z5 II RAW 完整渲染, 曝光调整正确, 单张 < 2s。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import rawpy

from .dcp import (
    DcpProfile,
    load_dcp,
    BRADFORD_D50_TO_D65,
    XYZ_D65_TO_SRGB,
)


def decode_raw(raw_path: str | Path, half_size: bool = False) -> Tuple[np.ndarray, rawpy.RawPy]:
    """解码 RAW → 相机原始 RGB 线性图 (float32, 0-1 归一化)。

    output_color=raw 跳过 LibRaw 的色彩矩阵, 拿到纯相机 RGB,
    供 DCP 矩阵自行处理。half_size=True 走半分辨率 demosaic (闭环诊断用)。
    """
    raw = rawpy.imread(str(raw_path))
    rgb16 = raw.postprocess(
        use_camera_wb=False,       # 白平衡我们自己乘
        output_bps=16,
        output_color=rawpy.ColorSpace.raw,
        no_auto_bright=True,
        half_size=half_size,
        user_wb=[1.0, 1.0, 1.0, 1.0],
        demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR,  # 全尺寸 1.5s; AHD 2.0s 质量增益有限
    )
    img = rgb16.astype(np.float32) / 65535.0
    # rawpy.ColorSpace.raw 输出顺序是 RGB
    return img, raw


def camera_neutral_wb(raw: rawpy.RawPy, prof: DcpProfile | None = None) -> np.ndarray:
    """相机 As Shot 白平衡系数 (R,G,B 三通道乘数, 归一化到 G=1)。

    2026-08-14 定稿: 直接使用 rawpy 的 camera_whitebalance
    (与 Nikon MakerNote WhiteBalanceRBCoeff 一致, 357/256=1.3945,
    225/128=1.7578 实证)。FM 链路下白平衡即乘此系数, 无需额外处理。
    """
    wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
    if wb[1] > 0:
        wb = wb / wb[1]
    return wb.astype(np.float32)


def apply_dcp_matrix(img: np.ndarray, wb: np.ndarray, prof: DcpProfile) -> np.ndarray:
    """相机 RGB → 线性 sRGB (D65)。

    权威链路 (2026-08-14 定稿, 依据 Adobe dng_color_spec.cpp fCameraToPCS):
        cameraRGB × wb(camera_whitebalance) → ForwardMatrix1 → XYZ(D50)
        → Bradford (D50→D65) → sRGB 线性
    ⚠️ 关键: 用 ForwardMatrix 直接映射 (FM 行和 = D50 白点),
        NOT ColorMatrix (CM 输出白点=校准照明体StdA, 需额外适配)。
        实测: 中性 spread=1, 皮肤 a=+12 方向正确。
    """
    fm = np.array(prof.matrix3(prof.forward_matrix1), dtype=np.float32)
    if fm.shape != (3, 3):
        raise ValueError("DCP 无有效 ForwardMatrix1")

    # 预合成: M_total = SRGB @ BRADFORD @ FM (3x3 矩阵一次乘法)
    brad = np.array(BRADFORD_D50_TO_D65, dtype=np.float32)
    srgb = np.array(XYZ_D65_TO_SRGB, dtype=np.float32)
    m_total = srgb @ brad @ fm  # 输入=WB相机RGB → 输出=线性 sRGB

    img = img.astype(np.float32)
    # 1) 白平衡 (相机 As Shot)
    img = img * wb.astype(np.float32)[np.newaxis, np.newaxis, :]

    # 2) 一次矩阵乘: WB相机RGB → 线性 sRGB
    h, w = img.shape[:2]
    rgb = img.reshape(-1, 3) @ m_total.T
    rgb = np.clip(rgb, 0.0, None).reshape(h, w, 3)
    return rgb.astype(np.float32)


# Bradford 色适应矩阵 (锥响应对角 + 逆变换), 构造自 StdA→D65
def _bradford_matrix():
    m = np.array([[0.8951, 0.2664, -0.1614],
                  [-0.7502, 1.7135, 0.0367],
                  [0.0389, -0.0685, 1.0296]])
    src = m @ np.array([1.098466, 1.0, 0.355823])
    dst = m @ np.array([0.95047, 1.0, 1.08883])
    return np.linalg.inv(m) @ np.diag(dst / src) @ m


_BRADFORD_STDA_TO_D65 = _bradford_matrix()


def apply_exposure(rgb_linear: np.ndarray, ev: float) -> np.ndarray:
    """线性域曝光: rgb *= 2^ev。"""
    return rgb_linear * (2.0 ** ev)


def apply_s_curve(rgb_linear: np.ndarray, strength: float = 0.0) -> np.ndarray:
    """对比度 S 曲线 (strength 0-1, 0 = 不变)。

    中点 0.5 锚定, 映射 = sigmoid 变体; 全程保持 0-1。
    """
    if strength <= 1e-6:
        return rgb_linear
    x = np.clip(rgb_linear, 0.0, 1.0)
    k = 1.0 + 6.0 * strength  # 斜率系数
    y = 1.0 / (1.0 + np.exp(-k * (x - 0.5) * 2.0))
    # 归一化保持 [0,1] 端点
    y0 = 1.0 / (1.0 + np.exp(k))
    y1 = 1.0 / (1.0 + np.exp(-k))
    return ((y - y0) / (y1 - y0)).astype(np.float32)


def gamma_encode(rgb_linear: np.ndarray, gamma: float = 2.2) -> np.ndarray:
    """gamma 编码 → 8bit (计划书阶段1: rgb^(1/2.2))。

    性能: 16bit 量化查找表 (65536 项) 直接索引 (0.65s), 避免逐像素幂。
    """
    v = np.clip(rgb_linear, 0.0, 1.0)
    idx = (v * 65535.0 + 0.5).astype(np.uint16)
    lut = (np.power(np.arange(65536, dtype=np.float32) / 65535.0,
                    1.0 / gamma) * 255.0 + 0.5).astype(np.uint8)
    return lut[idx]


def apply_highlight_correction(out8: np.ndarray, lum_thr: float = 165.0,
                               strength: float = 0.7) -> np.ndarray:
    """高光色彩校正: 高光区 B 通道回拉 (修正 FM 矩阵高光偏蓝)。

    2026-08-14 实证: ForwardMatrix 输出高光区 B/G=1.33-1.39 (线性域),
    gamma 后高光 b=-13 (品红), JPEG 高光 b≈+0.4 中性。
    校正: 高光区 B 向 G 靠拢 (B 偏高时), 保持 R/G 不动, 平滑过渡。
    """
    out = out8.astype(np.float32)
    gray = 0.2126 * out[:, :, 0] + 0.7152 * out[:, :, 1] + 0.0722 * out[:, :, 2]
    # 平滑权重: 亮度在 [thr-30, thr] 之间渐变, 避免硬边界
    w = np.clip((gray - (lum_thr - 30)) / 30.0, 0.0, 1.0)
    r, g, b = out[:, :, 0], out[:, :, 1], out[:, :, 2]
    delta = (b - g) * w * strength
    delta = np.clip(delta, 0, None)
    out[:, :, 2] = np.clip(b - delta, 0, 255)
    return np.clip(out, 0, 255).astype(np.uint8)


# 曝光校准 (2026-08-14 重拟合, WB_CAL=0.9 生效后, 200 张 6x6 分区):
#   分段点 (luma → 需要 EV), 线性插值, 端点外推
EXPOSURE_CAL_TABLE = [
    (36, 0.522),
    (73, 0.042),
    (126, 0.227),
    (154, 0.197),
    (176, 0.133),
]


def exposure_cal_ev(luma_med: float) -> float:
    """按中位亮度查分段校准 EV (线性插值, 端点外推)。"""
    xs = [p[0] for p in EXPOSURE_CAL_TABLE]
    ys = [p[1] for p in EXPOSURE_CAL_TABLE]
    ev = None
    if luma_med <= xs[0]:
        ev = ys[0]
    elif luma_med >= xs[-1]:
        ev = ys[-1]
    else:
        for i in range(len(xs) - 1):
            if xs[i] <= luma_med <= xs[i + 1]:
                t = (luma_med - xs[i]) / (xs[i + 1] - xs[i])
                ev = ys[i] + t * (ys[i + 1] - ys[i])
                break
    if ev is None:
        ev = 0.0
    return ev


# WB 校准 (2026-08-14 批量 200 张扫描 R∈{0.9,0.92,0.94}):
#   R=0.90 最优: Δa=+1.78 (72% |Δa|<3), 消偏红 Δa 原 +5.8
#   B 保持 1.0 (Δb=-2.3 已可接受)
WB_CAL = np.array([0.90, 1.0, 1.0], dtype=np.float32)

# 饱和度校准 (2026-08-14 批量: dsat 中位 -11.8 → 发灰)
#   gamma 域 HSV S 通道 +12
SATURATION_CAL = 12.0

# 对比度校准 (200 张批量: 自研 std 比相机低 9.6 → amount 0.2 后残差 -3.0)
CONTRAST_CAL = 0.2


def apply_saturation_cal(out8: np.ndarray, amount: float = SATURATION_CAL) -> np.ndarray:
    """饱和度校准 (发灰修复): gamma 域 HSV S 通道偏移。

    2026-08-14 批量: 自研饱和比相机低 11.8 → +12 对齐。
    """
    if abs(amount) < 0.5:
        return out8
    bgr = cv2.cvtColor(out8, cv2.COLOR_RGB2BGR)
    hsv = bgr.astype(np.float32)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] + amount, 0, 255)
    out_bgr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return cv2.cvtColor(out_bgr, cv2.COLOR_BGR2RGB)


def apply_contrast_cal(out8: np.ndarray, amount: float = CONTRAST_CAL) -> np.ndarray:
    """gamma 域对比度曲线 (发灰修复): 绕中点拉伸 + 端点软压缩。

    2026-08-14 批量: 自研 std 34 vs 相机 40, 差 -9.6; amount=0.2 补足。
    """
    if amount <= 0:
        return out8
    x = out8.astype(np.float32)
    y = 128.0 + (x - 128.0) * (1.0 + amount)
    dark = np.clip((40 - y) / 40, 0, 1)
    bright = np.clip((y - 215) / 40, 0, 1)
    y = np.where(y < 40, y * (1 - 0.5 * dark), y)
    y = np.where(y > 215, 255 - (255 - y) * (1 - 0.5 * bright), y)
    return np.clip(y, 0, 255).astype(np.uint8)


def render(raw_path: str | Path, prof: DcpProfile | None, exposure_ev: float = 0.0,
           contrast: float = 0.0, gamma: float = 2.2,
           half_size: bool = False,
           highlight_correct: bool = True,
           apply_cal: bool = True) -> np.ndarray:
    """完整渲染: 解码 → DCP 色彩 → 曝光(+自适应校准) → S曲线 → gamma
    → 高光校正 → WB校准 → 对比度校准。

    返回 8bit RGB 图。
    apply_cal=True: 按画面亮度自适应校准曝光 (对齐相机预览, 2 轮迭代)。
    """
    img, raw = decode_raw(raw_path, half_size=half_size)
    if prof is not None:
        wb = camera_neutral_wb(raw, prof) * WB_CAL
        img = apply_dcp_matrix(img, wb, prof)
    if apply_cal:
        # 两轮迭代: 先粗渲染测亮度 → 查校准 EV → 最终渲染
        img = apply_exposure(img, exposure_ev)
        probe = gamma_encode(apply_s_curve(img, contrast))
        med = float(np.median(cv2.cvtColor(probe, cv2.COLOR_RGB2GRAY)))
        img = apply_exposure(img, exposure_cal_ev(med))
    else:
        img = apply_exposure(img, exposure_ev)
    img = apply_s_curve(img, contrast)
    out8 = gamma_encode(img, gamma)
    if highlight_correct:
        out8 = apply_highlight_correction(out8)
    out8 = apply_contrast_cal(out8)
    out8 = apply_saturation_cal(out8)
    return out8


def render_with_lut(raw_path: str | Path, prof: DcpProfile | None,
                    lut: Optional["LUT3D"] = None,
                    exposure_ev: float = 0.0, contrast: float = 0.0,
                    gamma: float = 2.2, lut_strength: float = 1.0,
                    half_size: bool = False) -> np.ndarray:
    """渲染 + 套 LUT (sRGB gamma 域) → 8bit RGB。

    ⚠️ 2026-08-14 修复: 曝光测量必须基于"挂 LUT 后"的画面 (测量=渲染)。
    否则曝光闭环在无 LUT 渲染上算, 套 LUT 后亮度偏移 (L81→L161 爆炸)。
    """
    rgb8 = render(raw_path, prof, exposure_ev, contrast, gamma, half_size=half_size)
    if lut is not None:
        rgb8 = lut.apply(rgb8, strength=lut_strength)
    return rgb8


def render_to_jpeg(raw_path: str | Path, prof: DcpProfile | None, out_path: str | Path,
                   exposure_ev: float = 0.0, contrast: float = 0.0,
                   gamma: float = 2.2, half_size: bool = False) -> Tuple[float, Path]:
    """渲染并写 JPEG, 返回 (耗时秒, 输出路径)。"""
    t0 = time.perf_counter()
    rgb8 = render(raw_path, prof, exposure_ev, contrast, gamma, half_size=half_size)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(out), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    dt = time.perf_counter() - t0
    return dt, out
