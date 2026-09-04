"""engine.hsl_oklch —— OKLCh 域人工 8 色段调整 (band schema v2, M-O1)。

结构对齐 engine.hsl 的 hsl_adjust_rgb (逐段环状余弦掩码 + protect 中性保护 +
全 0 快路径逐位 no-op), 工作域换成 OKLCh (经 core.oklab, 内部全程 float64):

  - hue_shift  → h 角度平移 (度, 掩码+protect 加权, % 360 环绕连续);
  - saturation → C 缩放 C' = C*(1+sat/100*m*protect), 上界 C_max(L) 用
    **tanh 软限幅**渐进逼近 (禁止硬截断——根治 HSV 饱和硬剪出的平台/断层);
  - luminance  → L 缩放 clip(L*(1+lum/100*m*protect), 0, 1);
  - protect    = smoothstep(C / C_NEUTRAL): C≈0 中性灰任何参数不动。

逐位纪律 (对齐 hsl 的 no-op 保证, 并补 OKLCh 特有的一条):
  - 全 0 参数 → 快路径原值直通 (连转换都不做);
  - 所有 band 掩码全零 → 原值直通;
  - 掩码外像素 (mask==0) → **绕过域重建**原值直通。sRGB↔OKLCh 往返
    (极坐标 C·cos/sin 重建 + gamma 编码) 非逐位可逆, 若未触及像素也重建,
    f32 出口会在暗部舍入边界出现 ~1ulp 抖动——touch 掩码合成兜住逐位不变。

软限幅定义 (仅作用在"增量"上, 保证未增强像素逐位不变):
    e = C_boosted - C (增强量), room = C_max(L) - C (剩余色域余量)
    C' = C + room*tanh(e/room)      (e>0 且 room>0)
    C' = C_boosted                  (e<=0, 即饱和度调低/掩码外 → 精确恒等)
e→0 时 C1 连续 (斜率 1), e→∞ 渐近 C_max(L) 永不越界, 无平台无硬折。

C_max(L) —— sRGB 色域 (L,C) 包络 (色相无关的保守上界):
  以 257³ 网格采样全 RGB 立方 → OKLCh, 每 1/64 L bin 取最大 C, ×1.03 保守余量
  (独立验证: 200 万随机域内色 max(C-LUT) = -6.8e-3, 全部严格在界内)。
  64 段线性插值 (np.interp) 精确捕捉包络陡边 (多项式拟合残差 ±12% 不可用)。
  已知近似: 包络是"各色相 cusps 的最大值", 低 cusp 色相强增饱和后仍可能轻微
  越域, 由 oklab_to_srgb 的 linear clip 兜底 (软限幅把越域量压到渐近尾,
  远温和于 HSV 硬截断)。逐色相 cusp 精化属 M-O2。

band schema v2 (设计 §2.2 / 审核盲点 A1 兼容):
  band dict 新增可选键 "domain": "hsv"|"oklch", **缺省 "hsv"**——13 张存量
  胶片卡 (无 domain 键) 全部按旧 HSV 语义走 core.hsl 旧内核, 逐位不变、零迁移。
  新卡/新 UI 写 domain:"oklch" + OKLCh 角度中心 (见 DEFAULT_BANDS_OKLCH)。
  分派在 modules.hsl.HslStage: Stage 级 color_domain 参数决定无 domain 键
  band 的归属; band 级 domain 键逐段覆盖 (可混用, 先 hsv 后 oklch 顺序应用)。
"""
from __future__ import annotations

import numpy as np

from .hsl import _ring_mask, _validate_band
from .huesat import _smoothstep
from .oklab import oklab_to_oklch, oklab_to_srgb, oklch_to_oklab, srgb_to_oklab

__all__ = ["oklch_adjust_rgb", "DEFAULT_BANDS_OKLCH", "C_NEUTRAL"]

# ---------------------------------------------------------------------------
# 常数
# ---------------------------------------------------------------------------

# 中性保护区半径: C < C_NEUTRAL 时 protect 渐入 0 (平滑, C1), 近灰噪声/肤底不被放大
C_NEUTRAL = 0.02

# OKLCh 8 带默认中心 (感知色相角重标定初值, 设计 §2.2; M-O2 拟合后可修订)。
# 全部参数 0 → 运行无效果/结构模板, 与 DEFAULT_BANDS 同纪律。带 domain 键自描述。
DEFAULT_BANDS_OKLCH = [
    {"name": "red",     "domain": "oklch", "hue_center": 29,  "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "orange",  "domain": "oklch", "hue_center": 55,  "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "yellow",  "domain": "oklch", "hue_center": 100, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "green",   "domain": "oklch", "hue_center": 145, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "aqua",    "domain": "oklch", "hue_center": 195, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "blue",    "domain": "oklch", "hue_center": 264, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "purple",  "domain": "oklch", "hue_center": 295, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
    {"name": "magenta", "domain": "oklch", "hue_center": 327, "width": 45, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0},
]

# sRGB 色域 (L,C) 包络查表: x = L 节点 [0, bin 中心 ×64, 1], y = max C ×1.03 余量。
# 生成: 257³ 网格采样 → oklab_to_oklch, 每 1/64 L bin 取 max C, 2026-08-28。
_C_MAX_LUT_X = np.concatenate([[0.0], (np.arange(64, dtype=np.float64) + 0.5) / 64.0, [1.0]])
_C_MAX_LUT_Y = np.asarray((
    0.000000, 0.000000, 0.021653, 0.031229, 0.043305, 0.055732, 0.065887, 0.077032,
    0.089108, 0.099505, 0.110888, 0.121984, 0.132834, 0.144635, 0.155053, 0.166428,
    0.177611, 0.188621, 0.200549, 0.211241, 0.222847, 0.233269, 0.244600, 0.255802,
    0.266882, 0.277848, 0.289689, 0.300438, 0.312056, 0.322611, 0.321716, 0.311736,
    0.305868, 0.302812, 0.301936, 0.302975, 0.304722, 0.307057, 0.309641, 0.312310,
    0.315495, 0.318632, 0.321951, 0.325113, 0.328740, 0.332166, 0.330077, 0.308463,
    0.287041, 0.268053, 0.273607, 0.279132, 0.284631, 0.290103, 0.295549, 0.300971,
    0.303672, 0.291648, 0.272065, 0.255662, 0.241863, 0.231005, 0.222699, 0.209466,
    0.085861, 0.000000,
), dtype=np.float64)


def _cmax_of_l(L: np.ndarray) -> np.ndarray:
    """sRGB 色域包络 C_max(L) (色相无关保守上界, 64 段线性插值, 端点截断)。"""
    return np.interp(L, _C_MAX_LUT_X, _C_MAX_LUT_Y)


def _soft_limit_chroma(c_boosted: np.ndarray, c: np.ndarray, L: np.ndarray) -> np.ndarray:
    """饱和度软限幅: 仅压"增强量", 未增强像素精确恒等 (掩码外逐位不变的根基)。

    e>0 且有余量 → C + room*tanh(e/room) (C1 渐近 C_max(L));
    e<=0 (调低饱和/未增强) 或零余量 (已在色域边) → 原值返回。
    """
    e = c_boosted - c
    room = _cmax_of_l(L) - c
    room_safe = np.where(room > 1e-9, room, 1.0)   # 防 0 除; 零余量走恒等分支
    soft = c + room_safe * np.tanh(e / room_safe)
    return np.where((e > 0.0) & (room > 1e-9), soft, c_boosted)


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------

def oklch_adjust_rgb(img01, bands, smooth: float = 1.0):
    """对 gamma RGB [0,1] 应用 OKLCh 域各色段调整 (结构对齐 hsl_adjust_rgb)。

    bands: band dict 列表 (或 None/[] → 不变; 键结构同 hsl, 语义为 OKLCh 角度)。
    out = 逐段顺序应用后的 float32 [0,1] 图 (中性灰 C≈0 不动)。
    smooth ∈ [0,1] 掩码锐度。全 0 参数走快路径逐位 no-op。
    """
    img01 = np.asarray(img01, dtype=np.float64)
    if not bands:
        return img01.astype(np.float32)
    for band in bands:
        _validate_band(band)
    # 全 0 快路径: 逐位 no-op (连色彩空间转换都不做)
    if all(float(b.get("hue_shift", 0.0)) == 0.0
           and float(b.get("saturation", 0.0)) == 0.0
           and float(b.get("luminance", 0.0)) == 0.0 for b in bands):
        return img01.astype(np.float32)

    smooth = float(np.clip(smooth, 0.0, 1.0))
    lch = oklab_to_oklch(srgb_to_oklab(img01))
    L = lch[..., 0]
    C = lch[..., 1]
    h = lch[..., 2]
    protect = _smoothstep(C / C_NEUTRAL)   # 中性保护: C≈0 的像素任何参数不变 (初值一次)
    touched = np.zeros(img01.shape[:-1], dtype=bool)   # 掩码内像素 (逐位直通的互补集)
    for band in bands:
        c = float(band["hue_center"]) % 360.0
        w = float(band["width"])
        m = _ring_mask(h, c, w, smooth)
        hs = float(band.get("hue_shift", 0.0))
        sat = float(band.get("saturation", 0.0))
        lum = float(band.get("luminance", 0.0))
        if hs != 0.0 or sat != 0.0 or lum != 0.0:
            touched |= m > 0.0
        if hs != 0.0:
            h = (h + hs * m * protect) % 360.0
        if sat != 0.0:
            C = _soft_limit_chroma(C * (1.0 + sat / 100.0 * m * protect), C, L)
        if lum != 0.0:
            L = np.clip(L * (1.0 + lum / 100.0 * m * protect), 0.0, 1.0)
    if not touched.any():
        # 所有掩码全零: 无任何参数触达 → 原值直通 (逐位, 与全 0 快路径同级)
        return img01.astype(np.float32)
    out = oklab_to_srgb(oklch_to_oklab(np.stack([L, C, h], axis=-1)))
    # 掩码外像素原值直通: sRGB↔OKLCh 往返 (极坐标重建 + gamma 编码) 非逐位可逆,
    # 未触及像素必须绕过重建, 否则 f32 出口在暗部舍入边界出现 ~1ulp 抖动。
    out = np.where(touched[..., None], out, img01.astype(np.float32))
    return np.clip(out, 0.0, 1.0).astype(np.float32)
