"""Stage colorcal (order=50) —— 色彩校准 (gamma_rgb → gamma_rgb, Lab 域)。

原则 (替代旧管线 HSV +12 饱和 / WB_CAL=0.9 全局补丁):
  - **中性轴校准**: neutral_a/neutral_b 只作用于低色度区 (高斯权重按 C 衰减),
    修正系统性中性偏色, 但不污染饱和色 (WB_CAL 的教训)。
  - 饱和度/自然饱和度/色相旋转都在 Lab 域做, 可独立控制、可关闭。
  - 肤色保护: 肤色带内的饱和度增益自动衰减 (保肤自然)。

参数:
  saturation    饱和度增益 (0=不变, 0.2=+20%)
  vibrance      自然饱和度 (低饱和区多增, 高饱和区少增, 防溢出)
  hue           色相旋转角度 (度, 默认 0)
  neutral_a     中性轴 a 偏移 (标量, 只动低色度区)
  neutral_b     中性轴 b 偏移 (标量)
  neutral_a_curve  按亮度分段的 a 校正曲线 (7 点, 对应 L 中心 [8,32,72,128,184,224,248])
  neutral_b_curve  同上 b; 每机标定一次 (校准数据见 engine/calibration.py)
  neutral_sigma 中性区高斯半径 (C* 单位, 默认 14)
  skin_protect  肤色保护强度 0..1 (默认 0.7)
  gamut_soft    超出 sRGB 色域的软压缩 (默认 0.5)
"""
from __future__ import annotations

import cv2
import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB

_NEUTRAL_CENTERS = np.array([8, 32, 72, 128, 184, 224, 248], dtype=np.float32)

# 场景色偏窗口 (问题清单 B4/A4): 同一暖尾色温下方向不一致的 outlier,
# 用 (wb_R, wb_B) 二维窗口做有界 Lab 色偏修正 (单键 wb_B 无法区分)。
_SCENE_TRIM_BOUND = 24.0


def _check_scene_trim(windows) -> np.ndarray:
    """scene_trim 校验 → (n,6) [[wb_r_lo,wb_r_hi,wb_b_lo,wb_b_hi,da,db], ...]。

    窗口语义: 相机 WB 的 R 系数与 B 系数都落在窗口内时, 中性轴追加
    da/db (Lab, 0..255 坐标)。da/db 带界 [-24, 24]。
    """
    arr = np.asarray(windows, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 6 or arr.shape[0] < 1:
        raise ValueError(
            f"scene_trim 需 ≥1 个 [wb_r_lo,wb_r_hi,wb_b_lo,wb_b_hi,da,db] 窗口 "
            f"(实际 shape={arr.shape})")
    if np.any(arr[:, 0] > arr[:, 1]) or np.any(arr[:, 2] > arr[:, 3]):
        raise ValueError("scene_trim 窗口下界必须 ≤ 上界")
    if arr[:, 4:].min() < -_SCENE_TRIM_BOUND or arr[:, 4:].max() > _SCENE_TRIM_BOUND:
        raise ValueError(f"scene_trim 的 da/db 必须在 [-{_SCENE_TRIM_BOUND}, "
                         f"{_SCENE_TRIM_BOUND}] 内")
    return arr


def _check_scene_skin_trim(windows) -> np.ndarray:
    """scene_skin_trim 校验 → (n,6) [[wb_lo,wb_hi,da,db], ...] (按 wb_B 键)。"""
    arr = np.asarray(windows, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 4 or arr.shape[0] < 1:
        raise ValueError(
            f"scene_skin_trim 需 ≥1 个 [wb_b_lo,wb_b_hi,da,db] 窗口 "
            f"(实际 shape={arr.shape})")
    if np.any(arr[:, 0] > arr[:, 1]):
        raise ValueError("scene_skin_trim 窗口下界必须 ≤ 上界")
    if arr[:, 2:].min() < -_SCENE_TRIM_BOUND or arr[:, 2:].max() > _SCENE_TRIM_BOUND:
        raise ValueError(f"scene_skin_trim 的 da/db 必须在 [-{_SCENE_TRIM_BOUND}, "
                         f"{_SCENE_TRIM_BOUND}] 内")
    return arr


def _scene_skin_trim_for_wb(wb, windows: np.ndarray) -> tuple[float, float]:
    """按相机 WB 蓝系数查 scene_skin_trim 窗口 → 累加肤色区 (da, db)。"""
    if wb is None:
        return 0.0, 0.0
    b = float(wb[2] / max(float(wb[1]), 1e-9))
    da = db = 0.0
    for b_lo, b_hi, win_da, win_db in windows:
        if b_lo <= b <= b_hi:
            da += float(win_da)
            db += float(win_db)
    return da, db


def _check_scene_hue(windows) -> np.ndarray:
    arr = np.asarray(windows, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 3 or arr.shape[0] < 1:
        raise ValueError(f"scene_hue 需 ≥1 个 [wb_lo,wb_hi,deg] 窗口 (shape={arr.shape})")
    if np.any(arr[:, 0] > arr[:, 1]):
        raise ValueError("scene_hue 窗口下界必须 ≤ 上界")
    if arr[:, 2].min() < -15.0 or arr[:, 2].max() > 15.0:
        raise ValueError("scene_hue 色相旋转必须在 [-15,15] 度内")
    return arr


def _scene_hue_for_wb(wb, windows: np.ndarray) -> float:
    if wb is None:
        return 0.0
    b = float(wb[2] / max(float(wb[1]), 1e-9))
    deg = 0.0
    for b_lo, b_hi, win_deg in windows:
        if b_lo <= b <= b_hi:
            deg += float(win_deg)
    return deg


def _scene_trim_for_wb(wb, windows: np.ndarray) -> tuple[float, float]:
    """按相机 WB (r, g, b) 查 scene_trim 窗口 → 累加 (da, db)。"""
    if wb is None:
        return 0.0, 0.0
    r = float(wb[0] / max(float(wb[1]), 1e-9))
    b = float(wb[2] / max(float(wb[1]), 1e-9))
    da = db = 0.0
    for r_lo, r_hi, b_lo, b_hi, win_da, win_db in windows:
        if r_lo <= r <= r_hi and b_lo <= b <= b_hi:
            da += float(win_da)
            db += float(win_db)
    return da, db


@register_stage("colorcal", order=50,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class ColorCalStage(Stage):
    name = "colorcal"

    param_schema = {
        "saturation": {"type": "float", "min": -1.0, "max": 1.0},
        "vibrance": {"type": "float", "min": -1.0, "max": 1.0},
        "hue": {"type": "float"},
        "neutral_a": {"type": "float"},
        "neutral_b": {"type": "float"},
        "neutral_mode": {"type": "str", "choices": ["adaptive", "static", "off"]},
        "neutral_damping": {"type": "float", "min": 0.0, "max": 1.0},
        "neutral_sigma": {"type": "float", "min": 0.0},
        "skin_protect": {"type": "float", "min": 0.0, "max": 1.0},
        "skin_trim": {"type": "float_or_str"},       # [da, db] 肤色区 Lab 偏移 (软加权)
        "scene_trim": {"type": "float_or_str"},     # [[wb_r_lo,r_hi,b_lo,b_hi,da,db], ...]
        "gamut_soft": {"type": "float", "min": 0.0},
    }

    def default_params(self):
        return {"saturation": 0.0, "vibrance": 0.0, "hue": 0.0,
                "neutral_a": 0.0, "neutral_b": 0.0,
                "neutral_a_curve": None, "neutral_b_curve": None,
                "neutral_mode": "static",        # static(默认, 相机观感标定) | adaptive | off
                "neutral_damping": 0.85,          # adaptive 回消系数
                "neutral_sigma": 14.0,
                "skin_protect": 0.7, "skin_trim": None, "scene_trim": None,
                "scene_skin_trim": None, "scene_hue": None, "gamut_soft": 0.5}

    def _neutral_curves(self, ctx: StageContext):
        """中性校正曲线: 参数显式给定 > 每机 CCT 标定 (engine.calibration) > None。

        static 模式按渲染时 CCT (ctx.state['cct_k'], whitebalance Stage 写入)
        在分段标定桶间插值选曲线; 缺 cct 回退 6500K。
        """
        a_curve = self.p(ctx, "neutral_a_curve", None)
        b_curve = self.p(ctx, "neutral_b_curve", None)
        if a_curve is None and b_curve is None and ctx.prof is not None:
            try:
                from ..core.calibration import camera_look_curves
                cct = float(ctx.state.get("cct_k", 6500.0))
                a_curve, b_curve = camera_look_curves(ctx.prof, cct)
            except Exception:
                pass
        return a_curve, b_curve

    def _skin_trim_offsets(self, ctx: StageContext):
        """解析 skin_trim=[da,db] (Lab, 0..255 坐标), 带界 [-24,24]; 非法抛 ValueError。"""
        v = self.p(ctx, "skin_trim", None)
        if v is None:
            return 0.0, 0.0
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise ValueError(f"[colorcal] skin_trim 需为 [da, db] (实际 {v!r})")
        da, db = float(v[0]), float(v[1])
        if abs(da) > 24.0 or abs(db) > 24.0:
            raise ValueError(f"[colorcal] skin_trim 越界: {v!r}, 允许 [-24,24]")
        return da, db

    def process(self, ctx: StageContext) -> None:
        sat = float(self.p(ctx, "saturation"))
        vib = float(self.p(ctx, "vibrance"))
        hue = float(self.p(ctx, "hue"))
        na = float(self.p(ctx, "neutral_a"))
        nb = float(self.p(ctx, "neutral_b"))
        sigma = float(self.p(ctx, "neutral_sigma"))
        skin = float(self.p(ctx, "skin_protect"))
        mode = str(self.p(ctx, "neutral_mode", "adaptive"))

        img = np.clip(ctx.image, 0.0, 1.0)

        # 场景色偏窗口 (B4/A4): 按 (wb_R, wb_B) 追加有界 Lab 偏移;
        # neutral_mode='off' 时仍生效 (这是显式场景修正, 非自动中性校准)。
        scene_da = scene_db = 0.0
        scene_windows = self.p(ctx, "scene_trim", None)
        if scene_windows is not None:
            scene_arr = _check_scene_trim(scene_windows)
            scene_wb = ctx.state.get("wb_cam", ctx.state.get("wb"))
            scene_da, scene_db = _scene_trim_for_wb(scene_wb, scene_arr)
            ctx.state["scene_trim"] = [float(scene_da), float(scene_db)]
        scene_active = scene_da != 0.0 or scene_db != 0.0
        na += scene_da
        nb += scene_db

        # 肤色区显式偏移 (skin_trim): 仅按 skin_mask 软加权, 修"肤色过红"类反馈
        skin_trim_da, skin_trim_db = self._skin_trim_offsets(ctx)
        scene_skin_da = scene_skin_db = 0.0
        scene_skin_windows = self.p(ctx, "scene_skin_trim", None)
        if scene_skin_windows is not None:
            scene_skin_arr = _check_scene_skin_trim(scene_skin_windows)
            scene_skin_wb = ctx.state.get("wb_cam", ctx.state.get("wb"))
            scene_skin_da, scene_skin_db = _scene_skin_trim_for_wb(
                scene_skin_wb, scene_skin_arr)
        skin_trim_da += scene_skin_da
        skin_trim_db += scene_skin_db
        skin_trim_active = skin_trim_da != 0.0 or skin_trim_db != 0.0

        scene_hue_deg = 0.0
        scene_hue_windows = self.p(ctx, "scene_hue", None)
        if scene_hue_windows is not None:
            scene_hue_arr = _check_scene_hue(scene_hue_windows)
            scene_hue_wb = ctx.state.get("wb_cam", ctx.state.get("wb"))
            scene_hue_deg = _scene_hue_for_wb(scene_hue_wb, scene_hue_arr)
        scene_hue_active = scene_hue_deg != 0.0
        hue += scene_hue_deg

        # 仅中性校正且非 Phase1.5 增强 (sat/vib/hue 全 0) → 快速路径。
        # adaptive: 每图在 1/4 Lab 上测量各亮度带中性漂移并回消 (CM 链路的
        #   中性误差随场景光照变化, 静态标定只能消中位, 单张方差 ±5 仍在);
        # static: 用显式曲线/每机标定数据。
        # neutral_mode='off' → 不碰自动/每机中性轴校准, 但显式 scene_trim
        #   仍走一次快速路径 (有界、按 (wb_R,wb_B) 窗口命中才生效)。
        if (sat == 0.0 and vib == 0.0 and hue == 0.0
                and (mode != "off" or scene_active) and not skin_trim_active
                and not scene_hue_active):
            if mode == "off":
                self._apply_neutral_fast(ctx, img, na, nb, sigma, "static",
                                         None, None)
            else:
                a_curve, b_curve = (self._neutral_curves(ctx) if mode == "static"
                                    else (None, None))
                self._apply_neutral_fast(ctx, img, na, nb, sigma, mode,
                                         a_curve, b_curve)
            return

        a_curve, b_curve = (self._neutral_curves(ctx) if mode != "off"
                            else (None, None))
        # 全默认 → 直通 (省一次 Lab 往返 ~1s)
        if (sat == 0.0 and vib == 0.0 and hue == 0.0 and na == 0.0 and nb == 0.0
                and a_curve is None and b_curve is None and not skin_trim_active
                and not scene_hue_active):
            return

        u8 = (img * 255.0 + 0.5).astype(np.uint8)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
        C = np.sqrt((a - 128.0) ** 2 + (b - 128.0) ** 2)

        # 1) 中性轴校准: 标量 + 按亮度分段曲线, 高斯权重按 C 衰减 (不动饱和色)
        if na != 0.0 or nb != 0.0 or a_curve is not None or b_curve is not None:
            w = np.exp(-(C ** 2) / (2.0 * sigma * sigma))
            if a_curve is not None or b_curve is not None:
                a_off = (np.interp(L, _NEUTRAL_CENTERS, a_curve).astype(np.float32)
                         if a_curve is not None else 0.0)
                b_off = (np.interp(L, _NEUTRAL_CENTERS, b_curve).astype(np.float32)
                         if b_curve is not None else 0.0)
                a = a + (na + a_off) * w
                b = b + (nb + b_off) * w
            else:
                a = a + na * w
                b = b + nb * w

        # 1b) 肤色区显式偏移 (软掩码加权; 与 saturation 的 skin_protect 共用椭圆)
        if skin_trim_active:
            from ..core.skin import skin_mask as _skin_mask_ellipse
            skin_trim_mask = _skin_mask_ellipse(u8).astype(np.float32)
            a = a + skin_trim_da * skin_trim_mask
            b = b + skin_trim_db * skin_trim_mask

        # 2) 色相旋转
        if hue != 0.0:
            rad = np.deg2rad(hue)
            ca, cb = a - 128.0, b - 128.0
            a = 128.0 + ca * np.cos(rad) - cb * np.sin(rad)
            b = 128.0 + ca * np.sin(rad) + cb * np.cos(rad)

        # 3) 饱和度 + 自然饱和度 (肤色保护)
        gain = 1.0 + sat
        if vib != 0.0:
            # 自然饱和度: 按现有色度反向加权 (低饱和多增)
            gain = gain + vib * np.clip(1.0 - C / 128.0, 0.0, 1.0)
        if skin > 0.0:
            # 肤色保护: 椭圆肤色软掩码 (engine.skin.skin_mask, 与磨皮 Stage 共用,
            # 替代旧线性角框), 保护系数衰减增益
            from ..core.skin import skin_mask as _skin_mask_ellipse
            skin_mask2d = _skin_mask_ellipse(u8).astype(np.float32)
            gain = 1.0 + (gain - 1.0) * (1.0 - skin * skin_mask2d)
        a = 128.0 + (a - 128.0) * gain
        b = 128.0 + (b - 128.0) * gain

        lab2 = np.stack([L, a, b], axis=-1)
        lab2 = np.clip(lab2, 0, 255).astype(np.uint8)
        out = cv2.cvtColor(lab2, cv2.COLOR_LAB2RGB)

        # 4) 色域软压缩: 越界通道按比例向灰回拉 (防 Lab 往返导致的硬裁)
        out = out.astype(np.float32) / 255.0
        gs = float(self.p(ctx, "gamut_soft"))
        if gs > 0.0:
            over = np.maximum(out - 1.0, 0.0)
            scale = 1.0 / (1.0 + gs * over.sum(axis=-1, keepdims=True))
            out = out * scale
        ctx.set_image(np.clip(out, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)
        if scene_active:
            ctx.results[-1].metrics["scene_trim"] = [float(scene_da), float(scene_db)]
        if skin_trim_active:
            ctx.results[-1].metrics["skin_trim"] = [skin_trim_da, skin_trim_db]
        if scene_hue_active:
            ctx.results[-1].metrics["scene_hue"] = scene_hue_deg

    # ---- 仅中性校正的快速路径 (基座默认) ----
    _BAND_EDGES = [0, 16, 48, 96, 160, 208, 240, 256]

    def _adaptive_curves(self, Ls: np.ndarray, As: np.ndarray, Bs: np.ndarray,
                         damping: float):
        """在 1/4 降采样 Lab 上测量各亮度带中性漂移 → 回消曲线 (7 点)。

        中性候选 C<=10; 每带样本 ≥0.2% 才有效; 回消 -damping×中位。
        """
        Cs = np.sqrt((As - 128.0) ** 2 + (Bs - 128.0) ** 2)
        # 候选阈值 14: 1/4 降采样的色彩平均化会把亮带中性像素的 C 推到
        # 12-13 (略超 10), 收紧阈值会导致亮带 (L>200) 零候选、校正缺失。
        neutral = Cs <= 14.0
        min_n = max(32, int(Ls.size * 0.0005))
        da = np.zeros(7, dtype=np.float64)
        db = np.zeros(7, dtype=np.float64)
        for k in range(7):
            lo, hi = self._BAND_EDGES[k], self._BAND_EDGES[k + 1]
            m = neutral & (Ls >= lo) & (Ls < hi)
            n = int(m.sum())
            if n < min_n:
                continue
            da[k] = -damping * float(np.median(As[m] - 128.0))
            db[k] = -damping * float(np.median(Bs[m] - 128.0))
        return da, db

    def _apply_neutral_fast(self, ctx: StageContext, img: np.ndarray,
                            na: float, nb: float, sigma: float, mode: str,
                            a_curve, b_curve) -> None:
        """快速中性轴校正 (不软化细节)。

        1/4 降采样 Lab 上计算亮度 L、色度 C 与平台型权重 w (C<=10 全量,
        之外高斯衰减)。校正量:
          - adaptive: 每图测量各亮度带中性漂移 → 回消 (damping);
          - static:   显式曲线 / 每机标定 (engine.calibration)。
        各亮度带 Lab 偏移预转成 RGB 色偏向量 (tint), 全图按 L 在带间线性
        混合; 最终 out = img + w_up · tint(L)。w 与 tint 均为低频量,
        上采样无损; 只加色偏、不动亮度细节。
        """
        u8 = (img * 255.0 + 0.5).astype(np.uint8)
        h, w = u8.shape[:2]
        # 1/2 降采样: 1/4 的色彩平均化会把小面积中性高光 (L>208) 混入
        # 相邻饱和像素, 亮带候选为零 → 亮带漂移无人校正; 1/2 缓解此问题
        # (测量开销 ~0.1s, 可接受)。
        small = cv2.resize(u8, (max(w // 2, 4), max(h // 2, 4)),
                           interpolation=cv2.INTER_AREA)
        lab_s = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
        Ls, As, Bs = lab_s[:, :, 0], lab_s[:, :, 1], lab_s[:, :, 2]
        Cs = np.sqrt((As - 128.0) ** 2 + (Bs - 128.0) ** 2)
        # 平台型权重: C <= neutral_plateau (12) 全量校正 (拟合在相机预览
        # C<12 中性像素上测偏移, 平台须覆盖到 12, 否则留下残差), 之后
        # 高斯衰减到 0 (不动饱和色)。
        plateau = 12.0
        tail = np.maximum(Cs - plateau, 0.0)
        w_s = np.exp(-(tail ** 2) / (2.0 * sigma * sigma)).astype(np.float32)
        w_up = cv2.resize(w_s, (w, h), interpolation=cv2.INTER_LINEAR)[:, :, None]
        L_up = cv2.resize(Ls, (w, h), interpolation=cv2.INTER_LINEAR)

        # 每带 Lab 偏移 → RGB tint 向量 (在带中心 L 上精确求差)
        if mode == "adaptive":
            damping = float(self.p(ctx, "neutral_damping", 0.85))
            da, db = self._adaptive_curves(Ls, As, Bs, damping)
            ctx.state["neutral_adaptive_a"] = [round(float(v), 2) for v in da]
            ctx.state["neutral_adaptive_b"] = [round(float(v), 2) for v in db]
        else:
            da = np.asarray(a_curve, dtype=np.float64) if a_curve is not None else np.zeros(7)
            db = np.asarray(b_curve, dtype=np.float64) if b_curve is not None else np.zeros(7)
        tints = np.zeros((7, 3), dtype=np.float32)
        for k, Lc in enumerate(_NEUTRAL_CENTERS):
            base = np.uint8([[[Lc, 128, 128]]])
            shifted = np.clip(np.float32([[[Lc, 128 + (na + da[k]), 128 + (nb + db[k])]]]),
                              0, 255).astype(np.uint8)
            rgb_base = cv2.cvtColor(base, cv2.COLOR_LAB2RGB).astype(np.float32)
            rgb_shift = cv2.cvtColor(shifted, cv2.COLOR_LAB2RGB).astype(np.float32)
            tints[k] = (rgb_shift - rgb_base)[0, 0]

        # L 带间线性混合在 1/2 分辨率做 (tint 是低频量), 再上采样 ——
        # 省去全图 searchsorted + 7×3 fancy gather 的 ~0.4s。
        Lc = _NEUTRAL_CENTERS  # float32, 递增
        li = np.clip(np.searchsorted(Lc, Ls) - 1, 0, len(Lc) - 2)
        t = np.clip((Ls - Lc[li]) / (Lc[li + 1] - Lc[li]), 0.0, 1.0)[:, :, None]
        tint_s = (tints[li] * (1.0 - t) + tints[li + 1] * t).astype(np.float32)
        tint_up = cv2.resize(tint_s, (w, h), interpolation=cv2.INTER_LINEAR)

        out = img + w_up * tint_up / 255.0
        ctx.set_image(np.clip(out, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)
        if ctx.state.get("scene_trim"):
            ctx.results[-1].metrics["scene_trim"] = [
                float(ctx.state["scene_trim"][0]), float(ctx.state["scene_trim"][1])]
