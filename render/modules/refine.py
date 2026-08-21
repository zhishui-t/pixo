"""Stage refine (order=70) —— 精修 (gamma_rgb → gamma_rgb, 显示域轻量打磨)。

全部可关、默认轻量。相对旧版的两处性能优化 (2026-08-16, 目标 half_size <2.5s):
  1. 锐化: 亮度 unsharp 改在**灰空间**做 (Rec.709 灰 + 高斯, 细节加回 RGB
     三通道), 替代全分辨率 Lab 往返 (视觉等效, 省 ~0.4s)。
  2. 色度降噪: 改 **1/4 降采样 RGB 色度替换** —— 小图整体高斯后上采样,
     只取它的"色度" (RGB − 灰), 与全图"亮度" (灰) 重组:
        out = gray(img) + (blur_up(img) − gray(blur_up(img)))
     色度是低频量, 1/4 计算足够; 亮度细节完全保留。

参数:
  highlight_desat  高光去色强度 0..1 (默认 0.6)
  sharpen          锐化幅度 0..1 (默认 0.25)
  chroma_denoise   色度降噪 sigma (默认 0.8, 0=关)
"""
from __future__ import annotations

import cv2
import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB

_RGB_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# 问题清单 A1 的显示域补强: 线性域局部暖色高光 (huesat stage) 覆盖
# 烟花/线性暖点; 5607/5603/0479 在 gamma HSV 口径下仍差 70+ 饱和,
# 这里按 (wb_B, 暖色覆盖率) 做最后的 gamma 域 S 补强。
_WARM_SAT_HUE_LO, _WARM_SAT_HUE_HI = 5.0, 38.0
_WARM_SAT_S_MIN, _WARM_SAT_V_MIN = 140.0, 180.0
_WARM_SAT_BROAD_COV_MIN = 0.02
_WARM_SAT_SPOT_COV = (0.001, 0.05)


def _build_warm_luts():
    """暖色带平滑权重的一维浮点 LUT (H 0..179 / S,V 0..255)。

    H/S/V 在 cv2 HSV uint8 中都是整数, 直接用 np.take 查表与旧逐像素
    smoothstep 数学等价 (实测随机 6MP maxdiff=0.0), 且省约 18% 时间。
    """
    h = np.arange(180, dtype=np.float32)
    hw = (np.clip((h - _WARM_SAT_HUE_LO) / 6.0, 0.0, 1.0)
          * np.clip((_WARM_SAT_HUE_HI - h) / 6.0, 0.0, 1.0))
    hw = (hw * hw * (3.0 - 2.0 * hw)).astype(np.float32)
    h_lut = np.zeros(256, np.float32)
    h_lut[:180] = hw
    sv = np.arange(256, dtype=np.float32)
    sw = np.clip((sv - 80.0) / 30.0, 0.0, 1.0)
    sw = (sw * sw * (3.0 - 2.0 * sw)).astype(np.float32)
    vw = np.clip((sv - 100.0) / 40.0, 0.0, 1.0)
    vw = (vw * vw * (3.0 - 2.0 * vw)).astype(np.float32)
    return h_lut, sw, vw


_WARM_H_LUT, _WARM_S_LUT, _WARM_V_LUT = _build_warm_luts()


def _check_warm_sat_curve(curve) -> np.ndarray:
    arr = np.asarray(curve, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2 or arr.shape[0] < 2:
        raise ValueError(f"warm_sat_curve 需 ≥2 个 [wb_B, gain] 结点 (shape={arr.shape})")
    if not np.all(np.diff(arr[:, 0]) > 0):
        raise ValueError("warm_sat_curve 结点 wb_B 必须严格递增")
    if arr[:, 1].min() < 0.0 or arr[:, 1].max() > 1.0:
        raise ValueError("warm_sat_curve 增益必须在 [0, 1] 内")
    return arr


def _check_warm_sat_spot(windows) -> np.ndarray:
    arr = np.asarray(windows, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 3 or arr.shape[0] < 1:
        raise ValueError(f"warm_sat_spot 需 ≥1 个 [wb_lo, wb_hi, gain] 窗口 (shape={arr.shape})")
    if np.any(arr[:, 0] > arr[:, 1]):
        raise ValueError("warm_sat_spot 窗口下界必须 ≤ 上界")
    if arr[:, 2].min() < 0.0 or arr[:, 2].max() > 1.0:
        raise ValueError("warm_sat_spot 增益必须在 [0, 1] 内")
    return arr


def _check_warm_hue_curve(curve) -> np.ndarray:
    arr = np.asarray(curve, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2 or arr.shape[0] < 2:
        raise ValueError(f"warm_hue_curve 需 ≥2 个 [wb_B, deg] 结点 (shape={arr.shape})")
    if not np.all(np.diff(arr[:, 0]) > 0):
        raise ValueError("warm_hue_curve 结点 wb_B 必须严格递增")
    if arr[:, 1].min() < -15.0 or arr[:, 1].max() > 15.0:
        raise ValueError("warm_hue_curve 色相偏移必须在 [-15, 15] 度内")
    return arr


def apply_warm_sat_gamma(img01, wb, curve=None, spot_windows=None,
                         hue_curve=None) -> np.ndarray:
    """gamma HSV 域暖色饱和补强 (float RGB 0..1 → float RGB 0..1)。

    - 暖色高光覆盖率 ≥2%: 按 wb_B 查 broad 增益曲线 (5607/5603/5376);
    - 覆盖率 0.1%~5% 的小面积火点: 按 spot 窗口给增益 (0479), 5236 的
      覆盖率 ≈0.01% 不触发 (锚点安全);
    - 大面积暖色室内 (0376/0364/0367) 的 wb_B 曲线结点为 0, 不增强;
    - warm_hue_curve: 按 wb_B 做 ±15° 的 HSV 暖色色相微调 (用户反馈:
      1 金黄→偏红一点, 3/4/5/7/8/9 偏红→偏黄一点)。
    """
    if curve is None and spot_windows is None and hue_curve is None:
        return img01
    if wb is None:
        return img01
    curve_arr = _check_warm_sat_curve(curve) if curve is not None else None
    spot_arr = _check_warm_sat_spot(spot_windows) if spot_windows is not None else None
    hue_arr = _check_warm_hue_curve(hue_curve) if hue_curve is not None else None
    wb_b = float(wb[2] / max(float(wb[1]), 1e-9))

    u8 = (np.clip(img01, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    hsv_u8 = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)
    hsv = hsv_u8.astype(np.float32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # 饱和度: 高饱和暖色硬掩码 (与人工验收口径一致)
    hard = ((h >= _WARM_SAT_HUE_LO) & (h <= _WARM_SAT_HUE_HI)
            & (s >= _WARM_SAT_S_MIN) & (v >= _WARM_SAT_V_MIN))
    coverage = float(hard.mean()) if hard.size else 0.0
    gain = 0.0
    if curve_arr is not None and coverage >= _WARM_SAT_BROAD_COV_MIN:
        gain = float(np.interp(wb_b, curve_arr[:, 0], curve_arr[:, 1]))
    if gain <= 0.0 and spot_arr is not None             and _WARM_SAT_SPOT_COV[0] <= coverage < _WARM_SAT_SPOT_COV[1]:
        for wb_lo, wb_hi, win_gain in spot_arr:
            if wb_lo <= wb_b <= wb_hi:
                gain = max(gain, float(win_gain))

    # 色相: 略放宽 S/V 的暖色掩码 (肤色/中饱和暖色也纳入), 覆盖率 >=2% 才动
    hue_shift = 0.0
    if hue_arr is not None:
        hue_hard = ((h >= _WARM_SAT_HUE_LO) & (h <= _WARM_SAT_HUE_HI)
                    & (s >= 80.0) & (v >= 100.0))
        if float(hue_hard.mean()) >= _WARM_SAT_BROAD_COV_MIN:
            hue_shift = float(np.interp(wb_b, hue_arr[:, 0], hue_arr[:, 1]))
    if gain <= 0.0 and hue_shift == 0.0:
        return img01

    # C++ 原生路径优先: 在 uint8 HSV 上原位修改 H/S, 由调用方再 HSV2RGB。
    try:
        from .._native import available as _native_available, warm_sat_gamma_u8
        if _native_available() and (gain > 0.0 or hue_shift != 0.0):
            warm_sat_gamma_u8(hsv_u8, float(gain), float(hue_shift))
            return cv2.cvtColor(hsv_u8, cv2.COLOR_HSV2RGB).astype(np.float32) / 255.0
    except Exception:
        pass

    # 一维 LUT 查表 (H 为 uint8 整数, 与逐像素 smoothstep 数学等价)
    hw = np.take(_WARM_H_LUT, h.astype(np.int32))

    s2 = s
    if gain > 0.0:
        s2 = np.clip(s * (1.0 + gain * hw.astype(np.float32)), 0.0, 255.0)

    h2 = h
    if hue_shift != 0.0:
        sw = np.take(_WARM_S_LUT, s.astype(np.int32))
        vw = np.take(_WARM_V_LUT, v.astype(np.int32))
        hue_w = hw * sw * vw
        h2 = (h + hue_shift * hue_w.astype(np.float32)) % 180.0

    out8 = cv2.cvtColor(np.stack([h2, s2, v], axis=-1).astype(np.uint8),
                        cv2.COLOR_HSV2RGB)
    return out8.astype(np.float32) / 255.0


@register_stage("refine", order=70,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class RefineStage(Stage):
    name = "refine"

    param_schema = {
        "highlight_desat": {"type": "float", "min": 0.0, "max": 1.0},
        "sharpen": {"type": "float", "min": 0.0, "max": 1.0},
        "chroma_denoise": {"type": "float", "min": 0.0, "max": 5.0},
        "warm_sat_curve": {"type": "float_or_str"},   # [[wb_B, gain], ...] 大面积暖色
        "warm_sat_spot": {"type": "float_or_str"},    # [[wb_lo, wb_hi, gain], ...] 小面积火点
        "warm_hue_curve": {"type": "float_or_str"},   # [[wb_B, deg], ...] 暖色色相微调
    }

    def default_params(self):
        # sharpen 默认 0.35: 基座质感 (此前 0.25 偏软, "没质感"反馈)。
        return {"highlight_desat": 0.6, "sharpen": 0.35, "chroma_denoise": 0.8,
                "warm_sat_curve": None, "warm_sat_spot": None,
                "warm_hue_curve": None}

    def process(self, ctx: StageContext) -> None:
        img = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)
        hd = float(self.p(ctx, "highlight_desat"))
        sh = float(self.p(ctx, "sharpen"))
        cd = float(self.p(ctx, "chroma_denoise"))

        if hd <= 0.0 and sh <= 0.0 and cd <= 0.0:
            return
        gray = self._gray(img)  # 复用: 三个子步骤共享一次 Rec709 灰
        # 三个子步骤共享一次 HSV 饱和保护权重 (原各自计算, 全图 3× HSV
        # 转换拖慢 ~0.8s; 低频权重, 先算后传)
        native = False
        try:
            from .._native import (available as _native_available,
                                   refine_sat_protection as _native_sat,
                                   refine_sharpen as _native_sharpen,
                                   refine_chroma as _native_chroma,
                                   refine_highlight as _native_highlight,
                                   refine_apply as _native_apply)
            if _native_available():
                native = True
        except Exception:
            native = False

        if native:
            try:
                sat_protect = _native_sat(img)
            except Exception:
                native = False
                sat_protect = self._sat_protection(img)
        else:
            sat_protect = self._sat_protection(img)

        if sh > 0.0:
            blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
            if native:
                try:
                    img = _native_sharpen(img, gray, sat_protect, blur, sh)
                except Exception:
                    native = False
                    img = self._sharpen_gray(img, sh, gray, sat_protect)
            else:
                img = self._sharpen_gray(img, sh, gray, sat_protect)
        if cd > 0.0:
            h, w = img.shape[:2]
            small = cv2.resize(img, (max(w // 4, 4), max(h // 4, 4)),
                               interpolation=cv2.INTER_AREA)
            small_blur = cv2.GaussianBlur(small, (0, 0), cd)
            gray_blur_s = self._gray(small_blur)
            gray_blur = cv2.resize(gray_blur_s, (w, h),
                                   interpolation=cv2.INTER_LINEAR)[:, :, np.newaxis]
            blur_up = cv2.resize(small_blur, (w, h), interpolation=cv2.INTER_LINEAR)
            if native:
                try:
                    if hd > 0.0:
                        # 一次调用完成 chroma+highlight，减少一次全图输出分配。
                        img = _native_apply(img, gray, sat_protect, None,
                                            blur_up, gray_blur, 0.0, cd, hd)
                    else:
                        img = _native_chroma(img, gray, sat_protect, blur_up,
                                             gray_blur, cd)
                except Exception:
                    native = False
                    img = self._chroma_denoise_small(img, cd, gray, sat_protect)
            else:
                img = self._chroma_denoise_small(img, cd, gray, sat_protect)
        if hd > 0.0:
            if native:
                try:
                    if cd <= 0.0:
                        img = _native_highlight(img, gray, sat_protect, hd)
                    # cd>0 时已在上面的 fused 调用中完成 highlight
                except Exception:
                    native = False
                    img = self._highlight_desat(img, hd, gray, sat_protect)
            else:
                img = self._highlight_desat(img, hd, gray, sat_protect)
        # A1 显示域暖色饱和补强 (gamma HSV, 见 apply_warm_sat_gamma)
        warm_curve = self.p(ctx, "warm_sat_curve", None)
        warm_spot = self.p(ctx, "warm_sat_spot", None)
        warm_hue = self.p(ctx, "warm_hue_curve", None)
        if warm_curve is not None or warm_spot is not None or warm_hue is not None:
            img = apply_warm_sat_gamma(
                img, ctx.state.get("wb_cam", ctx.state.get("wb")),
                curve=warm_curve, spot_windows=warm_spot, hue_curve=warm_hue)
        # 原生路径中 cd>0 的融合内核已做过最终 clip；只有单独 highlight 末尾
        # 未 clip，需要保留一次 np.clip 以保证与纯 Python 路径一致。
        if native and (cd > 0.0 or hd <= 0.0):
            ctx.set_image(img.astype(np.float32), DOMAIN_GAMMA_RGB)
        else:
            ctx.set_image(np.clip(img, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)

    @staticmethod
    def _gray(img: np.ndarray) -> np.ndarray:
        return (img @ _RGB_WEIGHTS).astype(np.float32)

    @staticmethod
    def _sharpen_gray(img: np.ndarray, sh: float, gray: np.ndarray,
                      sat_protect: np.ndarray | None = None) -> np.ndarray:
        """灰空间 unsharp: 只锐化亮度, 原色度乘性保留 (无色偏)。

        旧实现 img + k·detail 等价于 luma_sharp + chroma, 但直接逐通道 clip 会把
        高亮饱和色 (烟花橙) 的 R 通道截到 1.0 → 色度被抹成白 (实测暗夜烟花
        S 69→19)。现在 luma_sharp 与 chroma 重组后做**逐像素色域软压缩**: 只
        在 luma_sharp ± chroma 越界时按比例收 chroma, 不硬裁单通道。
        """
        blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
        detail = (gray - blur).astype(np.float32)
        # 高饱和色不参与亮度 unsharp (小亮斑锐化会把 R 通道推向白点, 抹掉
        # 烟花色度); 中性/低饱和区保持原锐化强度。
        if sat_protect is None:
            sat_protect = RefineStage._sat_protection(img)
        gray3 = gray[:, :, np.newaxis]
        chroma = img - gray3
        luma = np.clip(gray + sh * 12.0 * detail * (1.0 - sat_protect),
                       0.0, 1.0)
        luma3 = luma[:, :, np.newaxis]
        out = luma3 + chroma
        # 色域软压缩: 只压越界方向的色度, 不改变色相, 也不硬裁单通道
        over = np.maximum(out - 1.0, 0.0)
        if over.any():
            pos = np.maximum(chroma, 0.0).sum(axis=-1, keepdims=True)
            scale = np.where(pos > 1e-6,
                             np.minimum(1.0, (1.0 - luma3) / np.maximum(pos, 1e-6)),
                             1.0)
            out = luma3 + chroma * scale
        under = np.minimum(out, 0.0)
        if under.any():
            neg = np.maximum(-chroma, 0.0).sum(axis=-1, keepdims=True)
            scale = np.where(neg > 1e-6,
                             np.minimum(1.0, luma3 / np.maximum(neg, 1e-6)),
                             1.0)
            out = luma3 + chroma * scale
        return np.clip(out, 0.0, 1.0)

    @staticmethod
    def _sat_protection(img: np.ndarray, lo: float = 0.08,
                        hi: float = 0.32) -> np.ndarray:
        """HSV 饱和保护权重 0..1: S≤lo 全量处理 (近中性), S≥hi 完全不处理
        (饱和色, 如烟花橙黄/霓虹)。smoothstep 过渡, 保持 C1。"""
        u8 = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        sat = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)[..., 1].astype(np.float32) / 255.0
        x = np.clip((sat - float(lo)) / max(float(hi) - float(lo), 1e-9),
                    0.0, 1.0)
        return (x * x * (3.0 - 2.0 * x)).astype(np.float32)

    @staticmethod
    def _chroma_denoise_small(img: np.ndarray, cd: float, gray: np.ndarray,
                              sat_protect: np.ndarray | None = None) -> np.ndarray:
        """1/4 降采样色度降噪: 只替换色度 (RGB−灰), 亮度细节不动。

        2026-08 烟花修复: 旧实现无条件用降采样模糊色度替换全图色度, 小面积
        高饱和亮斑 (烟花/霓虹) 被平均进暗背景 → 饱和度崩塌 (实测暗夜烟花
        S 153→32)。现在按两点保护原色度:
          1) 像素自身饱和度高 → 不降噪 (信号色, 非噪点);
          2) 原色度与模糊色度差异大 (小亮斑/色边) → 不替换, 防止细节被抹平。
        仅低饱和且与邻域一致的像素走降采样色度降噪。
        """
        h, w = img.shape[:2]
        small = cv2.resize(img, (max(w // 4, 4), max(h // 4, 4)),
                           interpolation=cv2.INTER_AREA)
        small_blur = cv2.GaussianBlur(small, (0, 0), cd)
        # 模糊图的灰也在 1/4 上算 (灰是低频量), 再上采样
        gray_blur_s = RefineStage._gray(small_blur)
        gray_blur = cv2.resize(gray_blur_s, (w, h),
                               interpolation=cv2.INTER_LINEAR)[:, :, np.newaxis]
        blur_up = cv2.resize(small_blur, (w, h), interpolation=cv2.INTER_LINEAR)
        chroma_orig = img - gray[:, :, np.newaxis]
        chroma_blur = blur_up - gray_blur
        # 饱和度保护: S≥0.32 的原图色度完整保留
        if sat_protect is None:
            sat_protect = RefineStage._sat_protection(img)
        protect = sat_protect[:, :, np.newaxis]
        # 2026-08-19 修复: 旧"差异保护"把随机彩色噪点也判成细节, 导致
        # chroma_denoise 在天空/高 ISO 上完全不生效。小面积烟花/霓虹已由
        # sat_protect (S≥0.32 全保留) 覆盖, 这里只保留饱和度保护。
        blend = protect
        out = gray[:, :, np.newaxis] + (chroma_blur
                                        + blend * (chroma_orig - chroma_blur))
        return np.clip(out, 0.0, 1.0)

    @staticmethod
    def _highlight_desat(img: np.ndarray, strength: float, gray: np.ndarray,
                         sat_protect: np.ndarray | None = None) -> np.ndarray:
        """高光去色: 亮度越高的像素色度越向中性回拉 (匹配相机高光处理)。

        相机预览对高光 (含未完全裁切的中高光) 渲染为近中性; CM 色彩链路
        会把中高光 (Rec709 灰 0.55~0.9, L*≈160~240) 染上较强色偏 (实测
        b 达 -18)。阈值从旧版 0.88 下探到 0.55, 平滑过渡到 0.85 全量。

        2026-08 烟花修复: 只对低饱和高光去色; 高饱和暖色 (烟花橙黄) 保留
        —— 旧实现按亮度无差别去色, 亮暖色饱和度被压低 (实测 -65/255)。
        """
        L = gray
        w_lum = np.clip((L - 0.55) / 0.30, 0.0, 1.0)
        w_lum = w_lum * w_lum * (3.0 - 2.0 * w_lum)
        # S≥0.32 → 保护权重 1, 不去色; S≤0.08 → 全量 (近中性高光)。
        if sat_protect is None:
            sat_protect = RefineStage._sat_protection(img)
        w = w_lum * (1.0 - sat_protect) * strength
        w = w[:, :, np.newaxis]
        return (img * (1.0 - w) + L[:, :, np.newaxis] * w).astype(np.float32)
