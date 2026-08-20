"""Stage tone (order=30) —— 影调 (linear_rgb → gamma_rgb)。

基座影调 = sRGB EOTF 曲线基 (DCP ProfileToneCurve 默认关闭, 保留为 Adobe look 开关):
  - profile_curve=False (默认): 用精确 sRGB EOTF 曲线基 (或纯 1/2.2 幂, 参数 eotf)。
  - profile_curve=True: 用 DCP ProfileToneCurve 影调曲线 LUT (Adobe look, 可选);
    无曲线时回退曲线基。
  - use_filmic=True: 用 filmic 影调重塑曲线 (Phase 1.5 增强层, 默认不用)。

默认关闭 ProfileToneCurve 的实测依据 (2026-08-16 A/B, 6 张 NEF vs 相机预览):
  DCP ProfileToneCurve 的强黑色趾部 (x=0.01 → y=0.0043) 使我方暗部裁切 5-7%,
  而相机预览自身 lo_clip 仅 0~1.9% (机内曲线温和, 不压暗部)。换 sRGB EOTF 基座
  曲线 (profile_curve=False) 后: lo_clip 0.13~0.71%、hi_clip 0.4~0.75%、
  d_a 从 +2.33 改善到 +0.17 —— 与相机预览明显更接近。

RGB 三通道共用同一条亮度曲线 ⇒ 中性灰在任何亮度层级保持中性。

参数:
  profile_curve  使用 DCP ProfileToneCurve (默认 False; True = Adobe look)
  eotf           曲线基编码: 'srgb'(默认, 精确 sRGB EOTF) | 'power22'
  gamma          eotf='power22' 的幂 / filmic 基础 (默认 2.2)
  brightness     显示亮度增益 (EV, 线性域预乘, 每机校准常量)
  use_filmic     Phase 1.5 filmic 曲线 (默认 False, 优先于 profile_curve)
  contrast/toe/shoulder  filmic 参数 (use_filmic=True 时生效)
"""
from __future__ import annotations

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB
from ..core.curves import (make_filmic_lut, make_base_curve_lut, apply_lut1d,
                      apply_lut1d_fast, parse_profile_curve, curve_lut_from_points)

_LUT_CACHE = {}
_PROFILE_CACHE = {}
_LRFIT_CACHE = None
_N_FAST = 16384  # 热路径 LUT 级数 (最近邻, 量化误差 <1/32768 不可感知)


def _get_lrfit():
    """LR 标定 v3: (gains[3], 共享曲线 LUT) float32 0..1; 文件缺失 → None。

    engine/lr_tone_curve.json 格式:
      {"version": 3, "gains": [r,g,b], "curve": [1024 点 0..255]}
    语义 (tools/fit_lr_tone_v2.py 拟合):
      - gains: 线性域逐通道增益, 吸收 LR 与我们的全局色差 (亮度标度+WB/色调方向);
      - curve: 一条共享影调曲线 (v1 三通道曲线的均值, 已去除单张照片的
        WB 烘焙), 三通道同曲线 → 中性像素任意层级保持中性。
    历史教训 (2026-08): v1 逐通道 CDF 曲线把拟合照片的白平衡烘焙进曲线,
    换一张照片 (5236) 就整体发蓝 (用户报"一黄一蓝, RGB 标反?"), 实为
    逐通道直方图匹配的跨图缺陷, 不是通道标反。
    """
    global _LRFIT_CACHE
    if _LRFIT_CACHE is None:
        try:
            import json as _json
            from pathlib import Path as _P
            p = _P(__file__).resolve().parent.parent / "lr_tone_curve.json"
            if not p.exists():
                _LRFIT_CACHE = None
            else:
                data = _json.loads(p.read_text(encoding="utf-8"))
                gains = np.asarray(data.get("gains", [1.0, 1.0, 1.0]),
                                   dtype=np.float32)
                curve = np.asarray(data["curve"], dtype=np.float64) / 255.0
                # 防呆: 曲线退化 (如 0..1 误存又除 255) 时直接判无效
                if float(curve.max()) < 0.1:
                    _LRFIT_CACHE = None
                else:
                    grid = np.linspace(0.0, 1.0, _N_FAST, dtype=np.float64)
                    lut = np.interp(grid, np.linspace(0.0, 1.0, len(curve)),
                                    curve).astype(np.float32)
                    _LRFIT_CACHE = (gains, lut)
        except Exception:
            _LRFIT_CACHE = None
    return _LRFIT_CACHE


def _get_lut(gamma: float, contrast: float, toe: float, shoulder: float) -> np.ndarray:
    key = ("f", round(gamma, 3), round(contrast, 4), round(toe, 4), round(shoulder, 4))
    lut = _LUT_CACHE.get(key)
    if lut is None:
        lut = make_filmic_lut(4096, contrast=contrast, toe=toe, shoulder=shoulder)
        _LUT_CACHE[key] = lut
    return lut


def _get_base_lut(eotf: str, gamma: float) -> np.ndarray:
    key = ("b", str(eotf), round(float(gamma), 3))
    lut = _LUT_CACHE.get(key)
    if lut is None:
        lut = make_base_curve_lut(eotf=str(eotf), gamma=float(gamma), n=_N_FAST)
        _LUT_CACHE[key] = lut
    return lut


def _get_profile_lut(prof) -> np.ndarray | None:
    """DCP 影调曲线 LUT (缓存; 无曲线返回 None)。"""
    if prof is None:
        return None
    lut = _PROFILE_CACHE.get(id(prof))
    if lut is None:
        parsed = parse_profile_curve(getattr(prof, "profile_tone_curve", None))
        lut = curve_lut_from_points(*parsed, _N_FAST) if parsed else None
        _PROFILE_CACHE[id(prof)] = lut
    return lut


_RGB_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _check_highlight_compress_curve(curve) -> np.ndarray:
    arr = np.asarray(curve, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2 or arr.shape[0] < 2:
        raise ValueError(f"highlight_compress_curve 需 ≥2 个 [wb_B, gain] 结点 (shape={arr.shape})")
    if not np.all(np.diff(arr[:, 0]) > 0):
        raise ValueError("highlight_compress_curve 结点 wb_B 必须严格递增")
    if arr[:, 1].min() < 0.0 or arr[:, 1].max() > 0.5:
        raise ValueError("highlight_compress_curve 增益必须在 [0, 0.5] 内")
    return arr


def _ssclip(v):
    """smoothstep 0..1 (C1)。"""
    v = np.clip(v, 0.0, 1.0)
    return v * v * (3.0 - 2.0 * v)


# T1.5 四键幅度系数: 各键满载(±1)时区域作用的 lerp/scale 强度。
# 实测调参保证: 全 4 键在 [-0.8, 0.8] 范围内灰阶 ramp 单调、白/黑点不硬 clip。
# (极端 +-1.0 时除 whites 压缩外仍单调; 测试取 +-0.8 覆盖常规使用区间。)
_SIXKEY_GAIN = 0.7


def _band(x, lo, hi, rec):
    """带通掩码 [0,1]: 在 [lo, hi] 间升至峰值区, 两端 smoothstep 滚降回 0。

    rec: 上沿恢复宽度 → 掩码在高端归 0, 使端点恒等(白点不越 1、黑非负)。
    与 highlight_compress 的 up*down 同型。
    """
    up = _ssclip((x - lo) / max(hi - lo, 1e-6))
    down = _ssclip((hi + rec - x) / max(rec, 1e-6))
    return up * down


def _apply_sixkey(x: np.ndarray, ctx, stage) -> np.ndarray:
    """T1.5 Highlights/Shadows/Whites/Blacks 四键 (线性域, EOTF 之前)。

    全 0 → 原样返回 (逐位一致)。实现: 亮度代理 L=x@[.2126 .7152 .0722],
    三通道乘/混合同一标量带通掩码 ⇒ 中性灰不偏色、灰阶 ramp 单调:
      - highlights: 亮部带(0.55-0.78);   >0 提高光 / <0 压高光。
      - shadows:    暗部带(0-0.14);      >0 提阴影 / <0 压阴影。
      - whites:     近白肩带(0.75-0.90); >0 提白 / <0 压白。
      - blacks:     近黑带(0-0.08);      >0 提黑 / <0 压黑。
    提升方向用 lerp 向白 (x'=x(1-d)+d, 0<=x'<=1 ⇒ 白点不越 1 硬裁);
    压缩方向用缩放 (x'=x(1-d), 0<=x'<=x ⇒ 黑点保持非负)。带通两端归 0
    恢复恒等 ⇒ 区域隔离 (只改目标色段)、端点恒等。
    """
    h = float(stage.p(ctx, "highlights"))
    s_ = float(stage.p(ctx, "shadows"))
    w = float(stage.p(ctx, "whites"))
    b = float(stage.p(ctx, "blacks"))
    if h == 0.0 and s_ == 0.0 and w == 0.0 and b == 0.0:
        return x
    L = (x @ _RGB_WEIGHTS).astype(np.float32)  # (H,W) 线性亮度代理
    K = _SIXKEY_GAIN
    out = x
    # (参数名, 掩码 (lo,hi,rec))
    for name, v, params in (("highlights", h, (0.55, 0.78, 0.28)),
                            ("shadows", s_, (0.00, 0.14, 0.36)),
                            ("whites", w, (0.75, 0.90, 0.16)),
                            ("blacks", b, (0.00, 0.08, 0.20))):
        if v == 0.0:
            continue
        mask = _band(L, *params)
        d = np.clip(abs(v) * K * mask, 0.0, 1.0)[..., None]
        if v > 0.0:
            out = out * (1.0 - d) + d          # 提升: lerp 向白, 不越 1
        else:
            out = out * (1.0 - d)              # 压缩: 缩放, 保持非负
    return out


def _parse_user_curve_points(points, name):
    """解析 [[x,y],...] 用户曲线控制点并校验 (x∈[0,1] 且单调不减)。"""
    if not isinstance(points, (list, tuple)) or len(points) == 0:
        raise ValueError(
            f"user_curve.{name} 需为非空 [[x,y],...] 控制点列表")
    arr = np.asarray(points, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(
            f"user_curve.{name} 每个控制点必须为 [x,y] 二元组")
    xs = arr[:, 0]
    ys = arr[:, 1]
    if not np.all((xs >= 0.0) & (xs <= 1.0)):
        raise ValueError(
            f"user_curve.{name} 控制点 x 必须在 [0,1] 内")
    if np.any(np.diff(xs) < 0.0):
        raise ValueError(
            f"user_curve.{name} 控制点 x 必须单调不减 (允许相等)")
    return xs, ys


def _apply_user_curve(img, user_curve, n: int = 4096) -> np.ndarray:
    """在 gamma 域 RGB 图上应用用户控制点曲线 (rgb → 分通道 → luminance)。

    user_curve 结构 (JSON 友好):
      - [[x,y],...]                     RGB 主曲线 (三通道同 LUT)
      - {"rgb":[[x,y],...]}             同上
      - {"red":[[..]], "green":[[..]], "blue":[[..]]}  分通道 (缺省恒等)
      - {"luminance":[[x,y],...]}       亮度曲线 (Rec.709 Y, 按 newY/max(oldY,eps)
                                         等比缩放 RGB 保色调, clip [0,1])
    可同时给 rgb+per-channel+luminance, 应用顺序: rgb → per-channel → luminance。
    None/空 → 原样返回 (no-op)。
    """
    img = np.asarray(img, dtype=np.float32).copy()
    if user_curve is None:
        return img
    if isinstance(user_curve, (list, tuple)):
        if len(user_curve) == 0:
            return img
        xs, ys = _parse_user_curve_points(user_curve, "rgb")
        lut = curve_lut_from_points(xs, ys, n)
        for c in range(3):
            img[..., c] = apply_lut1d_fast(img[..., c], lut)
        return img
    if not isinstance(user_curve, dict):
        raise ValueError(
            "user_curve 须为 [[x,y],...] 或 "
            "{rgb/red/green/blue/luminance: [[x,y],...]} 结构")
    if not user_curve:
        return img
    allowed = {"rgb", "red", "green", "blue", "luminance"}
    unknown = set(user_curve) - allowed
    if unknown:
        raise ValueError(
            f"user_curve 含未知键 {sorted(unknown)}; 合法键: {sorted(allowed)}")
    if "rgb" in user_curve:
        xs, ys = _parse_user_curve_points(user_curve["rgb"], "rgb")
        lut = curve_lut_from_points(xs, ys, n)
        for c in range(3):
            img[..., c] = apply_lut1d_fast(img[..., c], lut)
    per_ch = {"red": 0, "green": 1, "blue": 2}
    for ch in ("red", "green", "blue"):
        if ch in user_curve:
            xs, ys = _parse_user_curve_points(user_curve[ch], ch)
            lut = curve_lut_from_points(xs, ys, n)
            img[..., per_ch[ch]] = apply_lut1d_fast(img[..., per_ch[ch]], lut)
    if "luminance" in user_curve:
        xs, ys = _parse_user_curve_points(user_curve["luminance"], "luminance")
        lut = curve_lut_from_points(xs, ys, n)
        old_y = (img @ _RGB_WEIGHTS).astype(np.float32)  # Rec.709 Y
        new_y = apply_lut1d_fast(old_y, lut)
        scale = new_y / np.maximum(old_y, 1e-9)
        img = img * scale[..., np.newaxis]
        img = np.clip(img, 0.0, 1.0)
    return img


@register_stage("tone", order=30,
                domain_in=DOMAIN_LINEAR_RGB, domain_out=DOMAIN_GAMMA_RGB)
class ToneStage(Stage):
    name = "tone"

    param_schema = {
        "profile_curve": {"type": "bool"},
        "eotf": {"type": "str", "choices": ["srgb", "power22", "lrfit"]},
        "gamma": {"type": "float", "min": 1.0, "max": 4.0},
        "brightness": {"type": "float"},
        "use_filmic": {"type": "bool"},
        "contrast": {"type": "float", "min": 0.0, "max": 1.0},
        "toe": {"type": "float", "min": 0.0, "max": 1.0},
        "shoulder": {"type": "float", "min": 0.0, "max": 1.0},
        "highlight_compress_curve": {"type": "float_or_str"},
        "user_curve": {"type": "float_or_str"},
        # T1.5 曝光六键中的 Highlights/Shadows/Whites/Blacks 四键 (-1..1, 0=no-op):
        # 线性域亮度掩码乘性作用, 中性不偏色、ramp 单调、白/黑点不硬clip。
        "highlights": {"type": "float", "min": -1.0, "max": 1.0},
        "shadows": {"type": "float", "min": -1.0, "max": 1.0},
        "whites": {"type": "float", "min": -1.0, "max": 1.0},
        "blacks": {"type": "float", "min": -1.0, "max": 1.0},
    }

    def default_params(self):
        # profile_curve 默认 False: 基座用 sRGB EOTF, ProfileToneCurve 作 Adobe look 开关
        # (依据见模块头注释的暗部裁切实测)。
        # brightness 默认 +0.25: 基座整体亮度 (此前标定对齐相机预览偏暗, 实测
        # 发暗; +0.25EV 显示亮度把中位提到观感舒适区, 仍低于裁切阈值)。
        return {"profile_curve": False, "eotf": "srgb", "gamma": 2.2,
                "brightness": 0.5, "use_filmic": False,
                "contrast": 0.12, "toe": 0.0, "shoulder": 0.35,
                "highlight_compress_curve": None,
                "user_curve": None,
                "highlights": 0.0, "shadows": 0.0, "whites": 0.0, "blacks": 0.0}

    def process(self, ctx: StageContext) -> None:
        use_filmic = bool(self.p(ctx, "use_filmic"))
        use_profile = bool(self.p(ctx, "profile_curve"))
        brightness = float(self.p(ctx, "brightness"))
        gamma = float(self.p(ctx, "gamma"))
        eotf = str(self.p(ctx, "eotf"))
        x = ctx.image * (2.0 ** brightness)
        # T1.5 四键: Highlights/Shadows/Whites/Blacks (线性域, EOTF 之前)。
        # 全 0 时 _apply_sixkey 直接原样返回 (逐位一致); 三通道乘同一标量亮度
        # 掩码 → 中性灰不偏色、灰阶 ramp 单调; 白/黑端点不硬 clip。
        x = _apply_sixkey(x, ctx, self)

        if eotf == "lrfit":
            # LR 标定影调 (v3, tools/fit_lr_tone_v2.py): 线性增益 + 共享曲线。
            # 增益吸收全局色差, 曲线只做影调 —— 中性像素保持中性, 且可跨图
            # 泛化 (v1 逐通道曲线会把单张照片的 WB 烘焙进曲线, 跨图发蓝)。
            # 注意: 曲线已含 LR 的亮度锚定, 此处不再乘 brightness。
            lrfit = _get_lrfit()
            if lrfit is not None:
                gains, lut = lrfit
                xc = np.clip(ctx.image.astype(np.float32) * gains, 0.0, 1.0)
                y = np.empty_like(xc)
                for c in range(3):
                    y[..., c] = apply_lut1d_fast(xc[..., c], lut)
                profile_used = False
            else:
                y = apply_lut1d_fast(x, _get_base_lut("srgb", gamma))
                profile_used = False
        elif use_filmic:
            lut = _get_lut(gamma, float(self.p(ctx, "contrast")),
                           float(self.p(ctx, "toe")), float(self.p(ctx, "shoulder")))
            y = apply_lut1d_fast(x, lut)
            profile_used = False
        elif use_profile:
            profile_lut = _get_profile_lut(ctx.prof)
            if profile_lut is not None:
                y = apply_lut1d_fast(x, profile_lut)
                profile_used = True
            else:
                # 无 DCP 曲线 → 回退曲线基 (精确 sRGB EOTF / 纯 1/2.2 幂)
                y = apply_lut1d_fast(x, _get_base_lut(eotf, gamma))
                profile_used = False
        else:
            y = apply_lut1d_fast(x, _get_base_lut(eotf, gamma))
            profile_used = False

        # 用户控制点曲线 (T1.4): 在 gamma 域对 EOTF/影调结果施加
        # (rgb → 分通道 → luminance), highlight_compress 之前。
        # user_curve 为嵌套 list/dict (JSON 友好), 结构合法性由 core 参数校验层
        # (_curve_dict_check) + _apply_user_curve 双重把关, 统一走 self.p()。
        user_curve = self.p(ctx, "user_curve", None)
        if user_curve is not None:
            y = _apply_user_curve(y, user_curve)

        # 高光软压缩 (按 wb_B 曲线): 只压 gamma 亮段, 不碰中灰/暗部。
        hc_curve = self.p(ctx, "highlight_compress_curve", None)
        hc_gain = 0.0
        if hc_curve is not None:
            hc_arr = _check_highlight_compress_curve(hc_curve)
            wb = ctx.state.get("wb_cam", ctx.state.get("wb"))
            if wb is not None:
                wb_b = float(wb[2] / max(float(wb[1]), 1e-9))
                hc_gain = float(np.interp(wb_b, hc_arr[:, 0], hc_arr[:, 1]))
        if hc_gain > 0.0:
            L = (y @ _RGB_WEIGHTS).astype(np.float32)
            up = np.clip((L - 0.70) / 0.10, 0.0, 1.0)
            down = np.clip((0.94 - L) / 0.06, 0.0, 1.0)
            up = up * up * (3.0 - 2.0 * up)
            down = down * down * (3.0 - 2.0 * down)
            w = up * down
            y = y * (1.0 - hc_gain * w[..., np.newaxis])
        ctx.set_image(np.clip(y, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)
        ctx.state["tone_highlight_compress"] = hc_gain
        ctx.state["tone_brightness"] = brightness
        ctx.state["tone_profile_curve"] = profile_used
        ctx.state["tone_eotf"] = eotf
