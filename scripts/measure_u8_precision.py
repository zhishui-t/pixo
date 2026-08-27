"""量化渲染管线三处 uint8 中转量化的精度代价 (16-bit 导出精度改造 go/no-go 依据)。

[状态更新 t109] colorcal Lab 路径已完成 float 化改造 (native F32 内核
PixoRenderColorCalApplyLabF32 + Python float 镜像, 旧 u8 链保留为 legacy
兜底)。本脚本的 colorcal 段因此测量的是 legacy-u8 链 vs float 生产路径的
增益 (即已兑现的收益, 保留作历史依据与回归参照); stylize/refine 段仍为
现状测量。详细结论见 docs/metrics/u8_midpoint_precision.md 附记。

被测三处量化点 (渲染深审定位, 详见 docs/metrics/u8_midpoint_precision.md):
  1. modules/color_cal.py  全量 Lab 路径:
       - 输入端  : `u8 = (img*255+0.5).astype(np.uint8)` + `cv2.cvtColor(u8, RGB2LAB)`
                  (RGB→u8 + cv2 uint8 Lab 整数量化)
       - 输出端  : native 内核 uint8 Lab 输出 (colorcal.cpp ApplyColorCalLab 的
                  uint8* labOut) / python 回退 `lab2.astype(np.uint8)`,
                  随后 `cv2.cvtColor(lab2, LAB2RGB)` uint8 → uint8 RGB → /255
  2. modules/style.py + core/lut3d.py  LUT 应用:
       - 输入端  : `u8 = (clip(img)*255+0.5).astype(np.uint8)` → 256^3 整数网格 gather
       - 输出端  : 预计算表 `_table` 值 `(out*255+0.5).astype(np.uint8)` → /255
  3. modules/refine.py  HSV 处理的 uint8 中转 (native refine.cpp RefineSatProtection
     内部 `static_cast<int>(Clamp01(rgb)*255+0.5)` + RefineSatLut, 与 python 回退
     `_sat_protection` 的 u8 HSV 同口径; 另有参数门控的 apply_warm_sat_gamma 全
     u8 HSV 往返, 仅 warm_* 参数启用时生效)。

方法: 对每张样本 RAW, 以导出主线 (web/export.py `_render_full_quality` 同构:
全分辨率 decode_raw + build_default_pipeline 全 12 stage, 输出 float gamma RGB)
渲染 baseline, 再以 monkeypatch 把量化往返替换为 float 直通 (只换量化语句,
算法逻辑/参数与生产完全一致), 比较两版输出 (cv2 float32 Lab) 的 ΔE76 与
RGB 8bit 网格残差, 并按 stage 单独 patch 分解各自贡献。

三个测量配置 (真实生产预设):
  A = configs/styles/lr_adobe_standard_baseline.json (colorcal saturation=-0.06
      → 全量 Lab 路径, native 内核; refine sat_protection u8; 无 LUT)
  B = A + stylize lut=astia (生产注册的胶片 LUT, 触发 stylize 量化)
  C = configs/styles/lr_baseline.json (colorcal 走 scene_trim/scene_hue 窗口;
      refine warm_sat_curve/spot/hue 全启用 → warm HSV 全 u8 往返被测)

用法:
  python scripts/measure_u8_precision.py                 # 5 张自动选样, 全量测量
  python scripts/measure_u8_precision.py --samples "a.NEF,b.NEF"   # 指定样本
  python scripts/measure_u8_precision.py --corpus K:/data/photo --pick-only  # 只打印选样

不修改任何 src/ 生产代码: 所有 patch 仅在本进程内 monkeypatch。
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2  # noqa: E402

logging.getLogger("exifread").setLevel(logging.CRITICAL)  # 扫描语料时的批量告警

from pixo.render.core.io import camera_neutral_wb_cached, decode_raw  # noqa: E402
from pixo.render.pipeline.context import (  # noqa: E402
    DOMAIN_GAMMA_RGB,
    DOMAIN_LINEAR_CAM,
    StageContext,
)
from pixo.render.pipeline.presets import build_default_pipeline  # noqa: E402
from pixo.render.core.calibration import load_dcp  # noqa: E402

DCP = ROOT / "resources" / "dcp" / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
PRESET_A = ROOT / "configs" / "styles" / "lr_adobe_standard_baseline.json"
PRESET_C = ROOT / "configs" / "styles" / "lr_baseline.json"
CORPUS_DIRS = [
    "厦门/1", "厦门/101XM_02", "厦门/102XM_03", "厦门/103XM_04", "2026春节",
]
LUT_ID = "astia"  # core/lut.py 注册的生产胶片 LUT


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def ev100(meta_path: str) -> float | None:
    """EXIF 曝光设置 → EV100 = log2(N^2/t) - log2(ISO/100) (场景亮度代理)。"""
    from pixo.meta import extract
    e = extract(meta_path)["exposure"]
    N = e.get("aperture_value")
    t = e.get("shutter_seconds")
    iso = e.get("iso")
    if not N or not t or not iso:
        return None
    return math.log2(float(N) ** 2 / float(t)) - math.log2(float(iso) / 100.0)


def auto_pick_samples(corpus: Path, n: int = 5) -> list[Path]:
    """按 EV100 分位选样 (暗光 2 / 正常 2 / 高调 1), 目录尽量分散。"""
    cands: list[tuple[Path, float]] = []
    for sub in CORPUS_DIRS:
        d = corpus / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.NEF")):
            try:
                ev = ev100(str(f))
            except Exception:
                ev = None
            if ev is not None:
                cands.append((f, ev))
    if len(cands) < n:
        raise SystemExit(f"语料可用样本不足: {len(cands)} < {n}")
    evs = np.array([ev for _, ev in cands])
    # 每个目录内按 |EV-med| 取中位样本, 再全局按分位挑选
    by_dir: dict[str, list[tuple[Path, float]]] = {}
    for f, ev in cands:
        by_dir.setdefault(str(f.parent), []).append((f, ev))
    med = float(np.median(evs))
    dir_rep = {d: min(v, key=lambda r: abs(r[1] - med)) for d, v in by_dir.items()}
    picks: list[tuple[Path, float]] = []
    # 暗光: 全局 EV 最低段; 高调: 最高段; 其余取目录代表
    order = sorted(cands, key=lambda r: r[1])
    picks.append(order[0])
    picks.append(order[max(1, len(order) // 20)])
    for d in sorted(dir_rep):
        if len(picks) >= n:
            break
        r = dir_rep[d]
        if all(p[0] != r[0] for p in picks):
            picks.append(r)
    hi = order[-1]
    if all(p[0] != hi[0] for p in picks):
        picks = picks[: n - 1] + [hi]
    return [p for p, _ in picks[:n]]


def load_preset_params(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return dict(cfg.get("params") or {})


# ---------------------------------------------------------------------------
# float 直通内核 (量化往返的 float 等价实现, 算法逐行镜像生产代码)
# ---------------------------------------------------------------------------
def rgb_to_lab255(img01: np.ndarray) -> np.ndarray:
    """float RGB [0,1] → OpenCV Lab 的 0..255 坐标 (L*255/100, a+128, b+128)。

    生产路径是 `cv2.cvtColor(u8, RGB2LAB)` (uint8 整数 Lab); 本函数用 cv2 的
    float 路径得到同一坐标系下的连续值, 消除输入端两次 u8 量化。
    """
    arr = np.clip(np.asarray(img01, np.float32), 0.0, 1.0)
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
    lab[..., 0] *= np.float32(255.0 / 100.0)
    lab[..., 1:] += np.float32(128.0)
    return lab


def lab255_to_rgb01(lab255: np.ndarray) -> np.ndarray:
    """0..255 Lab 坐标 (float) → float RGB [0,1] (cv2 float LAB2RGB)。"""
    lab = np.ascontiguousarray(lab255, dtype=np.float32).copy()
    lab[..., 0] *= np.float32(100.0 / 255.0)
    lab[..., 1:] -= np.float32(128.0)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


_SKIN_COS = math.cos(0.65)
_SKIN_SIN = math.sin(0.65)


def _skin_mask_lab(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """肤色椭圆软掩码 —— 逐式镜像 colorcal.cpp::SkinMask (常量同 core/skin.py)。"""
    da = a.astype(np.float64) - 140.0
    db = b.astype(np.float64) - 150.0
    u = da * _SKIN_COS + db * _SKIN_SIN
    v = -da * _SKIN_SIN + db * _SKIN_COS
    d2 = (u / 22.0) ** 2 + (v / 14.0) ** 2
    d = np.sqrt(np.maximum(d2, 0.0)).astype(np.float32)
    t = np.clip((d - 1.0) / 0.25, 0.0, 1.0)
    return (1.0 - t * t * (3.0 - 2.0 * t)).astype(np.float32)


def colorcal_apply_lab_float(lab, sat, vib, hue_deg, na, nb, sigma, skin,
                             trim_a, trim_b, curve_a, curve_b) -> np.ndarray:
    """float 版 colorcal.cpp::ApplyColorCalLab —— 同算法, 输出不 cast uint8。

    逐分支镜像 (含 C 由原始 a/b 计算、skin mask 由原始 a/b 计算、hue 分支的
    double 精度旋转、vibrance/skin 的增益顺序)。仅去掉输出端 uint8 截断。
    """
    from pixo.render.modules.color_cal import _NEUTRAL_CENTERS
    L = lab[..., 0]
    a_orig = lab[..., 1]
    b_orig = lab[..., 2]
    a128 = a_orig - np.float32(128.0)
    b128 = b_orig - np.float32(128.0)
    C = np.sqrt(a128 * a128 + b128 * b128)
    has_curves = curve_a is not None or curve_b is not None
    neutral_active = na != 0.0 or nb != 0.0 or has_curves
    skin_trim_active = trim_a != 0.0 or trim_b != 0.0
    need_skin = skin_trim_active or skin > 0.0
    skin_mask = _skin_mask_lab(a_orig, b_orig) if need_skin else None

    a = a_orig.copy()
    b = b_orig.copy()
    if neutral_active:
        tail = np.maximum(C - np.float32(12.0), np.float32(0.0))
        w = np.exp(-(tail * tail) / np.float32(2.0 * sigma * sigma))
        if has_curves:
            a_off = (np.interp(L, _NEUTRAL_CENTERS, curve_a).astype(np.float32)
                     if curve_a is not None else np.float32(0.0))
            b_off = (np.interp(L, _NEUTRAL_CENTERS, curve_b).astype(np.float32)
                     if curve_b is not None else np.float32(0.0))
            a = a + (np.float32(na) + a_off) * w
            b = b + (np.float32(nb) + b_off) * w
        else:
            a = a + np.float32(na) * w
            b = b + np.float32(nb) * w
    if skin_trim_active:
        a = a + np.float32(trim_a) * skin_mask
        b = b + np.float32(trim_b) * skin_mask

    if hue_deg != 0.0:
        rad = float(hue_deg) * (math.pi / 180.0)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        ca = a.astype(np.float64) - 128.0
        cb = b.astype(np.float64) - 128.0
        ad = 128.0 + ca * cos_r - cb * sin_r
        bd = 128.0 + ca * sin_r + cb * cos_r
        if vib != 0.0 or skin > 0.0:
            gain = np.float32(1.0 + sat)
            if vib != 0.0:
                gain = gain + np.float32(vib) * np.clip(
                    np.float32(1.0) - C / np.float32(128.0), np.float32(0.0),
                    np.float32(1.0))
            if skin > 0.0:
                gain = np.float32(1.0) + (gain - np.float32(1.0)) * (
                    np.float32(1.0) - np.float32(skin) * skin_mask)
            ad = 128.0 + (ad - 128.0) * gain.astype(np.float64)
            bd = 128.0 + (bd - 128.0) * gain.astype(np.float64)
        else:
            gain = np.float64(1.0 + sat)
            ad = 128.0 + (ad - 128.0) * gain
            bd = 128.0 + (bd - 128.0) * gain
        out = np.stack([L.astype(np.float64), ad, bd], axis=-1)
    else:
        gain = np.float32(1.0 + sat)
        if vib != 0.0:
            gain = gain + np.float32(vib) * np.clip(
                np.float32(1.0) - C / np.float32(128.0), np.float32(0.0),
                np.float32(1.0))
        if skin > 0.0:
            gain = np.float32(1.0) + (gain - np.float32(1.0)) * (
                np.float32(1.0) - np.float32(skin) * skin_mask)
        a = np.float32(128.0) + (a - np.float32(128.0)) * gain
        b = np.float32(128.0) + (b - np.float32(128.0)) * gain
        out = np.stack([L, a, b], axis=-1)
    return np.clip(out, 0.0, 255.0).astype(np.float32)


def float_refine_sat_protection(rgb: np.ndarray, lo: float = 0.08,
                                hi: float = 0.32) -> np.ndarray:
    """float 版 native refine.cpp::RefineSatProtection。

    生产: rgb→u8 int (refine.cpp:193-195) → RefineSatLut[max*256+min] (cv2 8bit
    HSV 的 S 平面) → smoothstep。float 版直接 S=(max-min)/max (float), 同一
    smoothstep, 去掉输入端 u8 量化。返回 (H,W) float32, 兼容 native 包装签名。
    """
    arr = np.clip(np.asarray(rgb, np.float32), 0.0, 1.0)
    mx = arr.max(axis=-1)
    mn = arr.min(axis=-1)
    sat = np.zeros_like(mx)
    np.divide(mx - mn, mx, out=sat, where=mx > np.float32(1e-8))
    x = np.clip((sat - np.float32(lo)) / np.float32(max(hi - lo, 1e-9)),
                np.float32(0.0), np.float32(1.0))
    return (x * x * (np.float32(3.0) - np.float32(2.0) * x)).astype(np.float32)


WARM_STATS: dict = {"gain": [], "hue_shift": [], "coverage": []}


def float_apply_warm_sat_gamma(img01, wb, curve=None, spot_windows=None,
                               hue_curve=None) -> np.ndarray:
    """float 版 refine.py::apply_warm_sat_gamma —— 同一门控与增益, HSV 全 float。

    门控/覆盖率/增益查表逻辑与生产逐行一致 (阈值换算到 cv2 float HSV 的
    0..1 / 0..360 标度); 差异仅在生产先 RGB→u8→HSV(u8) 再 HSV(u8)→u8→RGB,
    本版 RGB→HSV(float)→RGB(float)。
    """
    from pixo.render.modules.refine import (
        _WARM_SAT_BROAD_COV_MIN,
        _WARM_SAT_HUE_HI,
        _WARM_SAT_HUE_LO,
        _WARM_SAT_SPOT_COV,
        _WARM_SAT_S_MIN,
        _WARM_SAT_V_MIN,
        _WARM_H_LUT,
        _WARM_S_LUT,
        _WARM_V_LUT,
        _check_warm_hue_curve,
        _check_warm_sat_curve,
        _check_warm_sat_spot,
    )
    if curve is None and spot_windows is None and hue_curve is None:
        return img01
    if wb is None:
        return img01
    curve_arr = _check_warm_sat_curve(curve) if curve is not None else None
    spot_arr = _check_warm_sat_spot(spot_windows) if spot_windows is not None else None
    hue_arr = _check_warm_hue_curve(hue_curve) if hue_curve is not None else None
    wb_b = float(wb[2] / max(float(wb[1]), 1e-9))

    hsv = cv2.cvtColor(np.clip(np.asarray(img01, np.float32), 0.0, 1.0),
                       cv2.COLOR_RGB2HSV)          # H 0..360, S/V 0..1
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    h2u = h * 0.5                                   # 生产 u8 H 标度 0..179
    s255, v255 = s * 255.0, v * 255.0

    hard = ((h2u >= _WARM_SAT_HUE_LO) & (h2u <= _WARM_SAT_HUE_HI)
            & (s255 >= _WARM_SAT_S_MIN) & (v255 >= _WARM_SAT_V_MIN))
    coverage = float(hard.mean()) if hard.size else 0.0
    gain = 0.0
    if curve_arr is not None and coverage >= _WARM_SAT_BROAD_COV_MIN:
        gain = float(np.interp(wb_b, curve_arr[:, 0], curve_arr[:, 1]))
    if gain <= 0.0 and spot_arr is not None \
            and _WARM_SAT_SPOT_COV[0] <= coverage < _WARM_SAT_SPOT_COV[1]:
        for wb_lo, wb_hi, win_gain in spot_arr:
            if wb_lo <= wb_b <= wb_hi:
                gain = max(gain, float(win_gain))

    hue_shift = 0.0
    if hue_arr is not None:
        hue_hard = ((h2u >= _WARM_SAT_HUE_LO) & (h2u <= _WARM_SAT_HUE_HI)
                    & (s255 >= 80.0) & (v255 >= 100.0))
        if float(hue_hard.mean()) >= _WARM_SAT_BROAD_COV_MIN:
            hue_shift = float(np.interp(wb_b, hue_arr[:, 0], hue_arr[:, 1]))
    WARM_STATS["gain"].append(gain)
    WARM_STATS["hue_shift"].append(hue_shift)
    WARM_STATS["coverage"].append(coverage)
    if gain <= 0.0 and hue_shift == 0.0:
        return img01

    hw = np.interp(h2u, np.arange(256), _WARM_H_LUT)      # H 为连续值 → 线性插值
    s2 = s255
    if gain > 0.0:
        s2 = np.clip(s255 * (1.0 + gain * hw), 0.0, 255.0)
    h2 = h2u
    if hue_shift != 0.0:
        sw = np.interp(s255, np.arange(256), _WARM_S_LUT)
        vw = np.interp(v255, np.arange(256), _WARM_V_LUT)
        hue_w = hw * sw * vw
        h2 = (h2u + hue_shift * hue_w) % 180.0
    hsv2 = np.stack([h2 * 2.0, s2 / 255.0, v], axis=-1).astype(np.float32)
    return cv2.cvtColor(hsv2, cv2.COLOR_HSV2RGB)


# ---------------------------------------------------------------------------
# monkeypatch: ColorCalStage.process (生产逐行拷贝, 仅量化语句可切换 float)
# ---------------------------------------------------------------------------
_FLOAT_IO = {"on": False}   # False = 与生产 bit 一致 (保真自检用); True = float 直通


def _colorcal_process_patched(self, ctx: StageContext) -> None:
    """modules/color_cal.py::ColorCalStage.process 的逐行拷贝。

    _FLOAT_IO['on']=True 时仅替换三处量化往返:
      Q1+Q2 输入端: u8 RGB + cv2 uint8 Lab  →  cv2 float Lab (0..255 坐标)
      Q3  输出端  : native uint8 Lab 内核   →  colorcal_apply_lab_float
      Q4  输出端  : cv2 uint8 LAB2RGB + /255 → cv2 float LAB2RGB
    其余 (scene/skin/hue 门控, native gamut_soft, python 回退分支, metrics
    写入) 与生产完全一致。_FLOAT_IO['on']=False 时即生产原实现, 用于拷贝
    保真自检 (输出必须与未 patch 渲染 bit 一致)。
    """
    import ctypes

    import cv2
    import numpy as np

    from pixo.render.modules.color_cal import (
        _NEUTRAL_CENTERS,
        _check_scene_hue,
        _check_scene_skin_trim,
        _check_scene_trim,
        _scene_hue_for_wb,
        _scene_skin_trim_for_wb,
        _scene_trim_for_wb,
    )
    from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB

    sat = float(self.p(ctx, "saturation"))
    vib = float(self.p(ctx, "vibrance"))
    hue = float(self.p(ctx, "hue"))
    na = float(self.p(ctx, "neutral_a"))
    nb = float(self.p(ctx, "neutral_b"))
    sigma = float(self.p(ctx, "neutral_sigma"))
    skin = float(self.p(ctx, "skin_protect"))
    mode = str(self.p(ctx, "neutral_mode", "adaptive"))

    img = ctx.image

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
    if (sat == 0.0 and vib == 0.0 and hue == 0.0 and na == 0.0 and nb == 0.0
            and a_curve is None and b_curve is None and not skin_trim_active
            and not scene_hue_active):
        return

    gs = float(self.p(ctx, "gamut_soft"))
    if _FLOAT_IO["on"]:
        u8 = None                                   # float 直通, 无 u8 中转
        lab = rgb_to_lab255(img)                   # ← Q1+Q2 替换
    else:
        u8 = (img * 255.0 + 0.5).astype(np.uint8)   # 生产原句
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)

    native_ok = False
    try:
        from pixo.render._native import (available as _native_available,
                                         colorcal_apply_lab as _native_colorcal_apply_lab,
                                         gamut_soft as _native_gamut_soft,
                                         PixoRenderColorCalParams)
        if _native_available():
            if _FLOAT_IO["on"]:
                # ← Q3 替换: float 内核 (无 uint8 Lab 输出)
                lab2f = colorcal_apply_lab_float(
                    lab, sat, vib, hue, na, nb, sigma, skin,
                    skin_trim_da, skin_trim_db,
                    (np.asarray(a_curve, dtype=np.float32)
                     if a_curve is not None else None),
                    (np.asarray(b_curve, dtype=np.float32)
                     if b_curve is not None else None))
                out = lab255_to_rgb01(lab2f)       # ← Q4 替换: float LAB2RGB
            else:
                curve_a = (np.asarray(a_curve, dtype=np.float32)
                           if a_curve is not None else None)
                curve_b = (np.asarray(b_curve, dtype=np.float32)
                           if b_curve is not None else None)
                params = PixoRenderColorCalParams(
                    saturation=sat, vibrance=vib, hueDeg=hue,
                    neutralA=na, neutralB=nb, neutralSigma=sigma,
                    skinProtect=skin, skinTrimA=skin_trim_da,
                    skinTrimB=skin_trim_db,
                    curveA=(curve_a.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            if curve_a is not None else None),
                    curveB=(curve_b.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            if curve_b is not None else None))
                lab2 = _native_colorcal_apply_lab(lab, params)
                out = cv2.cvtColor(lab2, cv2.COLOR_LAB2RGB)
                out = out.astype(np.float32) / 255.0
            if gs > 0.0:
                out = _native_gamut_soft(out, gs)
            else:
                out = np.clip(out, 0.0, 1.0)
            ctx.set_image(out, DOMAIN_GAMMA_RGB)
            native_ok = True
    except Exception:
        native_ok = False

    if not native_ok:
        L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]
        C = np.sqrt((a - 128.0) ** 2 + (b - 128.0) ** 2)

        if na != 0.0 or nb != 0.0 or a_curve is not None or b_curve is not None:
            plateau = 12.0
            tail = np.maximum(C - plateau, 0.0)
            w = np.exp(-(tail ** 2) / (2.0 * sigma * sigma))
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

        skin_mask2d = None
        if skin_trim_active or skin > 0.0:
            if _FLOAT_IO["on"]:
                skin_mask2d = _skin_mask_lab(lab[:, :, 1], lab[:, :, 2])
            else:
                from pixo.render.core.skin import skin_mask as _skin_mask_ellipse
                skin_mask2d = _skin_mask_ellipse(u8).astype(np.float32)
        if skin_trim_active:
            a = a + skin_trim_da * skin_mask2d
            b = b + skin_trim_db * skin_mask2d

        if hue != 0.0:
            rad = np.deg2rad(hue)
            ca, cb = a - 128.0, b - 128.0
            a = 128.0 + ca * np.cos(rad) - cb * np.sin(rad)
            b = 128.0 + ca * np.sin(rad) + cb * np.cos(rad)

        gain = 1.0 + sat
        if vib != 0.0:
            gain = gain + vib * np.clip(1.0 - C / 128.0, 0.0, 1.0)
        if skin > 0.0:
            gain = 1.0 + (gain - 1.0) * (1.0 - skin * skin_mask2d)
        a = 128.0 + (a - 128.0) * gain
        b = 128.0 + (b - 128.0) * gain

        lab2 = np.stack([L, a, b], axis=-1)
        if _FLOAT_IO["on"]:
            out = lab255_to_rgb01(lab2)            # ← Q4 替换 (回退分支)
        else:
            lab2 = np.clip(lab2, 0, 255).astype(np.uint8)
            out = cv2.cvtColor(lab2, cv2.COLOR_LAB2RGB)

        out = out.astype(np.float32) / 1.0 if _FLOAT_IO["on"] else \
            out.astype(np.float32) / 255.0
        if gs > 0.0:
            over = np.maximum(out - 1.0, 0.0)
            scale = 1.0 / (1.0 + gs * over.sum(axis=-1, keepdims=True))
            out = out * scale
        ctx.set_image(np.clip(out, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)
    if scene_active:
        ctx.results[-1].metrics["scene_trim"] = [float(scene_da), float(scene_db)]
    if skin_trim_active:
        ctx.results[-1].metrics["skin_trim"] = [float(skin_trim_da), float(skin_trim_db)]
    if scene_hue_active:
        ctx.results[-1].metrics["scene_hue"] = scene_hue_deg


def _stylize_process_patched(self, ctx: StageContext) -> None:
    """modules/style.py::StylizeStage.process 的 float 直通版。

    生产: u8 → 256^3 u8 gather 表 → /255。本版直接 LUT3D.lookup(float)
    (core/lut3d.py 既有 float 四面体插值, 与建表同一算法), 去掉输入端
    (256 级网格 gather) 与输出端 (表值 u8) 两次量化; strength 混合同式。
    """
    import numpy as np
    from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB

    lut = self._get_lut(ctx)
    strength = float(self.p(ctx, "lut_strength"))
    if lut is None or strength <= 0.0:
        return
    img = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)
    out = lut.lookup(img)
    if strength < 1.0:
        out = img * (1.0 - strength) + out * strength
        out = np.clip(out, 0.0, 1.0)
    ctx.set_image(out.astype(np.float32), DOMAIN_GAMMA_RGB)


# ---------------------------------------------------------------------------
# patch 安装/卸载
# ---------------------------------------------------------------------------
class Patches:
    def __init__(self, colorcal: bool = False, stylize: bool = False,
                 refine: bool = False):
        self.enable = {"colorcal": colorcal, "stylize": stylize, "refine": refine}
        self._saved = {}

    def __enter__(self):
        from pixo.render import _native as native_mod
        from pixo.render.modules import color_cal, refine as refine_mod, style

        if self.enable["colorcal"]:
            self._saved["cc_process"] = color_cal.ColorCalStage.process
            color_cal.ColorCalStage.process = _colorcal_process_patched
            _FLOAT_IO["on"] = True
        if self.enable["stylize"]:
            self._saved["st_process"] = style.StylizeStage.process
            style.StylizeStage.process = _stylize_process_patched
        if self.enable["refine"]:
            self._saved["nat_sat"] = native_mod.refine_sat_protection
            native_mod.refine_sat_protection = float_refine_sat_protection
            self._saved["py_sat"] = refine_mod.RefineStage._sat_protection
            refine_mod.RefineStage._sat_protection = staticmethod(
                lambda img, lo=0.08, hi=0.32: float_refine_sat_protection(
                    img, lo, hi))
            self._saved["warm"] = refine_mod.apply_warm_sat_gamma
            refine_mod.apply_warm_sat_gamma = float_apply_warm_sat_gamma
        return self

    def __exit__(self, *exc):
        from pixo.render import _native as native_mod
        from pixo.render.modules import color_cal, refine as refine_mod, style

        if "cc_process" in self._saved:
            color_cal.ColorCalStage.process = self._saved["cc_process"]
            _FLOAT_IO["on"] = False
        if "st_process" in self._saved:
            style.StylizeStage.process = self._saved["st_process"]
        if "nat_sat" in self._saved:
            native_mod.refine_sat_protection = self._saved["nat_sat"]
        if "py_sat" in self._saved:
            refine_mod.RefineStage._sat_protection = self._saved["py_sat"]
        if "warm" in self._saved:
            refine_mod.apply_warm_sat_gamma = self._saved["warm"]
        return False


# ---------------------------------------------------------------------------
# 渲染 harness (与 web/export.py::_render_full_quality 同构, 但保留 float 输出)
# ---------------------------------------------------------------------------
def render_variant(raw_path: Path, prof, img: np.ndarray, raw, wb,
                   params: dict, patches: dict) -> np.ndarray:
    """全分辨率跑默认管线, 返回最终 float32 gamma RGB [0,1] (导出量化前)。"""
    WARM_STATS.update(gain=[], hue_shift=[], coverage=[])
    pipe = build_default_pipeline(prof=prof, params=params)
    ctx = StageContext(
        raw_path, raw=raw, prof=prof,
        config={"stages": dict(params), "half_size": False,
                "preview": False, "long_edge": 0, "decode_mode": None})
    ctx.set_image(img.copy(), DOMAIN_LINEAR_CAM)
    ctx.state["half_size"] = False
    if wb is not None:
        ctx.state["camera_wb"] = wb
    with Patches(**patches):
        pipe.run(ctx)
    if ctx.domain != DOMAIN_GAMMA_RGB:
        raise RuntimeError(f"管线最终域 {ctx.domain} != gamma_rgb")
    return np.clip(ctx.image, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# ΔE76 度量
# ---------------------------------------------------------------------------
def _to_lab(img01: np.ndarray) -> np.ndarray:
    """float32 gamma RGB [0,1] → cv2 float Lab (L 0..100)。分块控制内存。"""
    h = img01.shape[0]
    out = np.empty(img01.shape, dtype=np.float32)
    step = max(1, (1 << 28) // (img01.shape[1] * 3 * 4))  # ~256MB/块
    for r0 in range(0, h, step):
        r1 = min(h, r0 + step)
        out[r0:r1] = cv2.cvtColor(img01[r0:r1].astype(np.float32),
                                  cv2.COLOR_RGB2LAB)
    return out


def delta_report(base: np.ndarray, other: np.ndarray) -> dict:
    """两版输出 (float gamma RGB) 的差异报告。"""
    lab_a = _to_lab(base)
    lab_b = _to_lab(other)
    dl = lab_a[..., 0] - lab_b[..., 0]
    da = lab_a[..., 1] - lab_b[..., 1]
    db = lab_a[..., 2] - lab_b[..., 2]
    de = np.sqrt(dl * dl + da * da + db * db).astype(np.float32)
    rep = {
        "dE_mean": float(de.mean()),
        "dE_p50": float(np.percentile(de, 50)),
        "dE_p95": float(np.percentile(de, 95)),
        "dE_p99": float(np.percentile(de, 99)),
        "dE_max": float(de.max()),
        "dE_gt_1": float((de > 1.0).mean()),
        "dL_mean": float(np.abs(dl).mean()),
        "da_mean": float(np.abs(da).mean()),
        "db_mean": float(np.abs(db).mean()),
    }
    del lab_a, lab_b, dl, da, db, de

    # RGB 域 8bit 网格残差 (生产 u8 编码: (x*255+0.5) 取整)
    c1 = (base * 255.0 + 0.5).astype(np.int16)
    c2 = (other * 255.0 + 0.5).astype(np.int16)
    d8 = (c1 - c2)
    rep["rgb_max8"] = int(np.abs(d8).max())
    rep["rgb_mean8"] = float(np.abs(d8).mean())
    for ch, name in enumerate("RGB"):
        dch = np.abs(d8[..., ch])
        rep[f"{name}_pct_ne0"] = float((dch > 0).mean())
        rep[f"{name}_max8"] = int(dch.max())
    ad8 = np.abs(d8)
    for k in (1, 2, 3):
        rep[f"rgb_pct_ge{k}"] = float((ad8 >= k).mean())
    del c1, c2, d8, ad8

    # 16-bit 导出口径: 两版各自量化到 uint16 后的 ΔE (TIFF16 用户所见)
    q1 = (base * 65535.0 + 0.5).astype(np.uint16).astype(np.float32) / 65535.0
    q2 = (other * 65535.0 + 0.5).astype(np.uint16).astype(np.float32) / 65535.0
    l1, l2 = _to_lab(q1), _to_lab(q2)
    de16 = np.sqrt(((l1 - l2) ** 2).sum(-1)).astype(np.float32)
    rep["dE16_mean"] = float(de16.mean())
    rep["dE16_p95"] = float(np.percentile(de16, 95))
    rep["dE16_max"] = float(de16.max())
    return rep


def _selfchecks(s, prof, img, raw, wb, params, base_out) -> None:
    """保真自检 (仅首样本): ① 渲染确定性; ② process 拷贝 bit 一致;
    ③ float numpy colorcal 内核 vs native DLL (u8 截断口径) 等效性。"""
    chk = render_variant(s, prof, img, raw, wb, params, {})
    det = int(np.abs(chk.astype(np.float32) - base_out).max())
    del chk

    from pixo.render.modules import color_cal as cc_mod
    orig = cc_mod.ColorCalStage.process
    cc_mod.ColorCalStage.process = _colorcal_process_patched
    _FLOAT_IO["on"] = False
    try:
        chk2 = render_variant(s, prof, img, raw, wb, params, {})
    finally:
        cc_mod.ColorCalStage.process = orig
        _FLOAT_IO["on"] = False
    bitdiff = int(np.abs(chk2.astype(np.float32) - base_out).max())
    del chk2
    gc.collect()
    print(f"  [selfcheck] copy-fidelity maxdiff={bitdiff} (须=0)  "
          f"determinism maxdiff={det} (须=0)")
    if bitdiff != 0 or det != 0:
        raise SystemExit("保真自检失败: process 拷贝或渲染非确定")

    lab_in = rgb_to_lab255(base_out)
    from pixo.render._native import (PixoRenderColorCalParams,
                                     colorcal_apply_lab as nat_cc)
    p = params.get("colorcal", {})
    pm = PixoRenderColorCalParams(
        saturation=float(p.get("saturation", 0.0) or 0.0), vibrance=0.0,
        hueDeg=0.0, neutralA=0.0, neutralB=0.0, neutralSigma=14.0,
        skinProtect=0.0, skinTrimA=0.0, skinTrimB=0.0,
        curveA=None, curveB=None)
    sub = np.ascontiguousarray(lab_in[::16, ::16])
    native_out = nat_cc(sub, pm)
    mine = colorcal_apply_lab_float(
        sub, float(p.get("saturation", 0.0) or 0.0), 0.0, 0.0, 0.0, 0.0,
        14.0, 0.0, 0.0, 0.0, None, None)
    mine_u8 = np.clip(mine, 0, 255).astype(np.uint8)  # cpp 为截断 cast
    mismatch = float((native_out != mine_u8).any(-1).mean())
    md = float(np.abs(native_out.astype(np.float32) - mine).max())
    print(f"  [selfcheck] float-kernel vs DLL(u8): mismatch_px="
          f"{mismatch * 100:.4f}%  max|ΔLab|={md:.3f}")
    del lab_in, sub, native_out, mine, mine_u8
    gc.collect()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="K:/data/photo", help="语料根目录")
    ap.add_argument("--samples", default=None,
                    help="逗号分隔的 NEF 路径列表 (缺省按 EV100 自动选 5 张)")
    ap.add_argument("--pick-only", action="store_true", help="只打印自动选样结果")
    ap.add_argument("--dcp", default=str(DCP))
    args = ap.parse_args()

    np.seterr(all="ignore")
    print(f"pixo u8 midpoint precision measurement  corpus={args.corpus}")
    print(f"python {sys.version.split()[0]}  numpy {np.__version__}  "
          f"opencv {cv2.__version__}")

    if args.samples:
        samples = [Path(p) for p in args.samples.split(",")]
    else:
        samples = auto_pick_samples(Path(args.corpus))
    if args.pick_only:
        for s in samples:
            print(" ", s)
        return

    from pixo.meta import extract
    print("\n=== 样本 (EXIF 摘要) ===")
    for s in samples:
        m = extract(str(s))
        e = m["exposure"]
        print(f"  {s.name:16s} {s.parent.name:12s} {m['camera']['model']:12s} "
              f"{str(m['camera'].get('lens', ''))[:28]:28s} f/{e['aperture_value']} "
              f"{e['shutter_speed']}s ISO{e['iso']} EC{e['exposure_compensation']} "
              f"EV100={ev100(str(s)):.2f}")

    prof = load_dcp(args.dcp)
    params_a = load_preset_params(PRESET_A)
    params_c = load_preset_params(PRESET_C)
    from pixo.render.core.lut import load_lut
    lut = load_lut(LUT_ID)
    params_b = json.loads(json.dumps(params_a))  # 深拷贝 (无 ndarray)
    params_b.setdefault("stylize", {})["lut"] = lut
    print(f"\n配置: A=lr_adobe_standard_baseline  B=A+stylize[{LUT_ID}]  "
          f"C=lr_baseline  LUT={LUT_ID} (n={lut.n})")

    variants = [
        ("A_base", params_a, {}),
        ("A_cc", params_a, {"colorcal": True}),
        ("A_rf", params_a, {"refine": True}),
        ("A_all", params_a, {"colorcal": True, "refine": True}),
        ("B_base", params_b, {}),
        ("B_lut", params_b, {"stylize": True}),
        ("C_base", params_c, {}),
        ("C_cc", params_c, {"colorcal": True}),
        ("C_rf", params_c, {"refine": True}),
        ("C_all", params_c, {"colorcal": True, "refine": True}),
    ]

    all_rows: list[dict] = []
    for si, s in enumerate(samples):
        t0 = time.time()
        print(f"\n===== [{si + 1}/{len(samples)}] {s} =====")
        img, raw = decode_raw(str(s), half_size=False)
        wb = None
        try:
            wb = camera_neutral_wb_cached(raw, s)
        except Exception:
            pass
        wb_b = float(wb[2] / wb[1]) if wb is not None else float("nan")
        print(f"  decode {img.shape}  wb_cam={np.round(wb, 3) if wb is not None else None}"
              f"  wb_B={wb_b:.3f}")

        outs: dict[str, np.ndarray] = {}
        for name, params, patches in variants:
            t1 = time.time()
            if name.endswith("_base"):
                outs.clear()          # 换组: 只保留本组 base, 控内存
                gc.collect()
                outs[name] = render_variant(s, prof, img, raw, wb, params,
                                            patches)
                print(f"  {name:8s} {time.time() - t1:6.1f}s  "
                      f"mean={outs[name].mean():.5f}")
                if si == 0 and name == "A_base":
                    _selfchecks(s, prof, img, raw, wb, params, outs["A_base"])
                continue
            cur = render_variant(s, prof, img, raw, wb, params, patches)
            base_name = name.split("_", 1)[0] + "_base"
            rep = delta_report(outs[base_name], cur)
            row = {"sample": s.name, "variant": name, "wb_B": wb_b,
                   "warm": dict(WARM_STATS), **rep}
            all_rows.append(row)
            print(f"  {name:8s} {time.time() - t1:6.1f}s  vs base: "
                  f"ΔE76 mean={rep['dE_mean']:.4f} p95={rep['dE_p95']:.4f} "
                  f"p99={rep['dE_p99']:.4f} max={rep['dE_max']:.3f} "
                  f">1ΔE={rep['dE_gt_1'] * 100:.3f}%  "
                  f"dL/da/db={rep['dL_mean']:.3f}/{rep['da_mean']:.3f}/"
                  f"{rep['db_mean']:.3f}  "
                  f"rgb8 max={rep['rgb_max8']} mean={rep['rgb_mean8']:.4f}  "
                  f"ΔE16 mean={rep['dE16_mean']:.4f} max={rep['dE16_max']:.3f}")
            if name.startswith("C_") and row["warm"]["gain"]:
                print(f"           warm_sat gate: gain={row['warm']['gain']} "
                      f"hue_shift={row['warm']['hue_shift']} "
                      f"coverage={row['warm']['coverage']}")
            print(f"           rgb8残差: R≠0={rep['R_pct_ne0'] * 100:.2f}% "
                  f"G≠0={rep['G_pct_ne0'] * 100:.2f}% "
                  f"B≠0={rep['B_pct_ne0'] * 100:.2f}%  "
                  f"|d|≥1={(rep['rgb_pct_ge1']) * 100:.2f}% "
                  f"≥2={(rep['rgb_pct_ge2']) * 100:.2f}% "
                  f"≥3={(rep['rgb_pct_ge3']) * 100:.2f}%  "
                  f"R/G/B max={rep['R_max8']}/{rep['G_max8']}/{rep['B_max8']}")
            del cur
            gc.collect()

        outs.clear()                 # 仅剩当前组 base, 清空即可
        gc.collect()
        gc.collect()
        print(f"  sample time {time.time() - t0:.1f}s")
        try:
            raw.close()
        except Exception:
            pass
        del img, outs
        gc.collect()

    # ---- 汇总 ----
    print("\n===== 汇总 (各 stage 贡献, 5 样本) =====")
    print(f"{'variant':10s} {'ΔE mean':>8s} {'ΔE p95':>8s} {'ΔE max':>8s} "
          f"{'%>1ΔE':>7s} {'rgb8max':>7s} {'ΔE16max':>8s}")
    for name, _, _ in variants:
        if name.endswith("_base"):
            continue
        rows = [r for r in all_rows if r["variant"] == name]
        if not rows:
            continue
        print(f"{name:10s} "
              f"{np.mean([r['dE_mean'] for r in rows]):8.4f} "
              f"{np.mean([r['dE_p95'] for r in rows]):8.4f} "
              f"{max(r['dE_max'] for r in rows):8.3f} "
              f"{np.mean([r['dE_gt_1'] for r in rows]) * 100:6.3f}% "
              f"{max(r['rgb_max8'] for r in rows):7d} "
              f"{max(r['dE16_max'] for r in rows):8.3f}")


if __name__ == "__main__":
    main()
