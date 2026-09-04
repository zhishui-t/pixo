"""render.core.split_tone_oklab —— 分离色调 OKLab 域染色 (M-O1, 设计 §2.3)。

语义对齐 core.split_tone.split_tone_rgb (shadows/highlights hue+sat、balance、
strength、sat=0 逐位 no-op), 唯一改动是**染色色的构造域**:

  - 亮度分域不动: Rec.709 Y + smoothstep (与旧内核同一 _smoothstep/
    _shadow_weight —— 分域与色彩域无关, 逐位同权);
  - 染色改 OKLab 域构造: 目标染色 = (L=像素 Oklab L, C=sat/100·C_ref(L),
    h=hue°) → oklch_to_oklab → oklab_to_srgb 得 sRGB 染色, 再混合
    out = img*(1-w) + tint*w  (w = 区域权重 × strength, 与旧内核同式);
  - C_ref(L) = sRGB 色域 (L,C) 包络 (复用 hsl_oklch._cmax_of_l, 含 ×1.03
    余量; 越域由 oklab_to_srgb 的 linear clip 兜底)。近白/近黑 C_ref→0,
    高光染色在 L 高区**自然低 C** (感知线性) —— 替代 HSV "V 取像素亮度"
    在近白处硬剪出的色相漂移; 纯黑像素任何 sat 逐位不变。
    已知近似 (对齐 hsl_oklch 同条): 包络是色相无关的 cusp 最大值, 低 cusp
    色相 (如蓝) 高 sat 或近白 (L→1 色域收缩为白点) 时请求染色会被 clip
    收缩并旋转 hue —— 染色量始终微小 (近白 C_ref 陡降), 感知只是轻微冷/暖
    调; 逐色相 cusp 精化属 M-O2。

逐位纪律 (对齐 hsl_oklch/split_tone 既有保证):
  - 两区 sat 全 0 或 strength<=0 → 快路径原值直通 (连色彩空间转换都不做);
  - 单区 sat=0 → 该区分支整段跳过 (与旧内核同构), 其零权重区像素不被任何
    算术触达;
  - 权重恰为 0 的像素: 混合 out*(1-0)+tint*0 在 f64 下精确恒等 (tint 有限
    非负, oklab_to_srgb 出口保证 [0,1] 无 NaN)。

dtype 契约 (设计 §1.3, 队长裁决 2026-08-28): Oklab/OKLCh 是内部工作域全程
float64 (srgb_to_oklab/oklch_to_oklab 出口 f64); 仅 oklab_to_srgb (sRGB 渲染
域出口) 出 float32 —— 染色 f32 上升回 f64 参与混合, 最终统一 clip+astype(f32)。

Stage 分派: modules.split_tone.SplitToneStage 按 color_domain ∈ {"hsv","oklch"}
选择 split_tone_rgb / split_tone_oklab_rgb (枚举对齐设计 §1.2 与 HslStage;
参数名不变, UI/胶片卡零改动)。
"""
from __future__ import annotations

import numpy as np

from .oklab import oklab_to_srgb, oklch_to_oklab, srgb_to_oklab
from .split_tone import _RGB_WEIGHTS, _shadow_weight
from .hsl_oklch import _cmax_of_l

__all__ = ["split_tone_oklab_rgb"]


def _tint_rgb(hue: float, sat: float, L: np.ndarray) -> np.ndarray:
    """固定 hue/sat 的染色色: (L=像素L, C=sat/100·C_ref(L), h=hue°) → sRGB。

    C_ref(L) 为色域包络上界: sat=100 即该亮度下 sRGB 可达的最强染色 (色相
    无关保守界), 近白/近黑自然趋 0。出口 float32 (oklab_to_srgb 契约),
    调用方按需升 f64 混合。
    """
    c = (float(sat) / 100.0) * _cmax_of_l(L)
    lch = np.stack([L, c, np.full_like(L, float(hue) % 360.0)], axis=-1)
    return oklab_to_srgb(oklch_to_oklab(lch))


def split_tone_oklab_rgb(img01, shadows_hue, shadows_sat,
                         highlights_hue, highlights_sat,
                         balance: float = 0.5, strength: float = 1.0) -> np.ndarray:
    """对 gamma RGB [0,1] 施加 OKLab 域分离色调染色, 返回 float32 [0,1]。

    参数与 split_tone_rgb 完全同名同义:
      shadows_hue/shadows_sat       阴影染色 hue(0..360)/饱和(0..100)
      highlights_hue/highlights_sat 高光染色 hue/sat
      balance   分界亮度 (0..1, 默认 0.5);
      strength  整体强度 (0..1, 默认 1.0)。
    两区全 0 饱和或 strength<=0 → 逐位 no-op。
    """
    img = np.asarray(img01, dtype=np.float64)
    if shadows_sat == 0 and highlights_sat == 0:
        return np.asarray(img01, dtype=np.float32)
    if strength <= 0.0:
        return np.asarray(img01, dtype=np.float32)
    y = np.clip(img @ _RGB_WEIGHTS, 0.0, 1.0)
    ws = _shadow_weight(y, balance)
    wh = 1.0 - ws
    # 像素 Oklab L (f64 内部域, 契约 §1.3); 只取 L, a/b 丢弃
    L = srgb_to_oklab(img)[..., 0]
    out = img.copy()
    if float(shadows_sat) > 0:
        tint = _tint_rgb(shadows_hue, float(shadows_sat), L).astype(np.float64)
        w = (ws * float(strength))[..., np.newaxis]
        out = out * (1.0 - w) + tint * w
    if float(highlights_sat) > 0:
        tint = _tint_rgb(highlights_hue, float(highlights_sat), L).astype(np.float64)
        w = (wh * float(strength))[..., np.newaxis]
        out = out * (1.0 - w) + tint * w
    return np.clip(out, 0.0, 1.0).astype(np.float32)
