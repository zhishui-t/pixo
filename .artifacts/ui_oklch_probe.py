# UI_OKLCH_SPEC 数据探针: 用已交付内核实测 HSV 度 vs OKLCh 度对应关系。
# 事实来源: src/pixo/render/core/oklab.py + hsl_oklch.py + hsl.py (2026-08-28 交付)。
import sys
sys.path.insert(0, "src")

import numpy as np
from pixo.render.core.huesat import _hsv_to_rgb
from pixo.render.core.oklab import srgb_to_oklab, oklab_to_oklch, oklch_to_oklab, oklab_to_srgb
from pixo.render.core.hsl import DEFAULT_BANDS
from pixo.render.core.hsl_oklch import DEFAULT_BANDS_OKLCH, C_NEUTRAL

np.set_printoptions(suppress=True)


def srgb01_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(float(np.clip(c, 0, 1)) * 255)) for c in rgb)


# ---- 1) 8 带中心对照 ----
print("== A. 8 带中心 (旧 HSV vs 新 OKLCh) ==")
hsv_c = {b["name"]: b["hue_center"] for b in DEFAULT_BANDS}
okl_c = {b["name"]: b["hue_center"] for b in DEFAULT_BANDS_OKLCH}
for name in hsv_c:
    print(f"{name:8s} hsv={hsv_c[name]:>3}  oklch={okl_c[name]:>3}  delta={okl_c[name]-hsv_c[name]:+d}")

# ---- 2) 纯色相锚点: HSV(H,100%,100%) -> OKLCh h (同色在 OKLCh 环上的角度) ----
print("\n== B. 纯色相锚点映射 (HSV h -> OKLCh h, S=V=100% 样本) ==")
hs = np.arange(0.0, 360.0, 30.0)
rgb = _hsv_to_rgb(hs, np.ones_like(hs), np.ones_like(hs))
lch = oklab_to_oklch(srgb_to_oklab(rgb))
for h_hsv, L, C, h_ok in zip(hs, lch[:, 0], lch[:, 1], lch[:, 2]):
    print(f"hsv {h_hsv:>5.0f} -> oklch {h_ok:6.1f}  (delta {h_ok - h_hsv:+6.1f})  L={L:.3f} C={C:.3f}")

# ---- 3) hue 随 S/V 的稳定性: 同 HSV 色相在 (S=1,V=0.5) 与 (S=0.5,V=1) 的 OKLCh h 漂移 ----
print("\n== C. OKLCh h 对 S/V 的漂移 (同 HSV 色相, max |h_ok - h_ok(S=V=1)|) ==")
rgb2 = _hsv_to_rgb(hs, np.ones_like(hs) * 0.5, np.ones_like(hs))
rgb3 = _hsv_to_rgb(hs, np.ones_like(hs), np.ones_like(hs) * 0.5)
h2 = oklab_to_oklch(srgb_to_oklab(rgb2))[:, 2]
h3 = oklab_to_oklch(srgb_to_oklab(rgb3))[:, 2]
for h_hsv, d2, d3 in zip(hs, np.abs(h2 - lch[:, 2]), np.abs(h3 - lch[:, 2])):
    print(f"hsv {h_hsv:>5.0f}: d(S=50%)={d2:5.1f}  d(V=50%)={d3:5.1f}")

# ---- 4) OKLCh 8 带中心的参考色板 (CSS oklch 同款取样: L=0.70, C=0.12) ----
print("\n== D. 8 带 OKLCh 中心色板 (L=0.70 C=0.12) vs 旧 HSV 中心色板 (S=100% V=100%) ==")
L7 = np.full(8, 0.70)
C12 = np.full(8, 0.12)
h8 = np.array([b["hue_center"] for b in DEFAULT_BANDS_OKLCH], dtype=np.float64)
rgb_okl = oklab_to_srgb(oklch_to_oklab(np.stack([L7, C12, h8], axis=-1)))
rgb_hsv = _hsv_to_rgb(np.array([b["hue_center"] for b in DEFAULT_BANDS], dtype=np.float64),
                      np.ones(8), np.ones(8))
for b, r_ok, r_hv in zip(DEFAULT_BANDS_OKLCH, rgb_okl, rgb_hsv):
    print(f"{b['name']:8s} oklch@{b['hue_center']:>3}: {srgb01_to_hex(r_ok)}   hsv 旧中心: {srgb01_to_hex(r_hv)}")

# ---- 5) split_tone 示例: 同参数值 45 / 210 在两域下的感知色差 ----
print("\n== E. split_tone 默认 hue 45/210 双域对比 ==")
for h in (45.0, 210.0):
    rgb_h = _hsv_to_rgb(np.array([h]), np.array([1.0]), np.array([1.0]))
    lch_h = oklab_to_oklch(srgb_to_oklab(rgb_h))[0]
    tint_okl = oklab_to_srgb(oklch_to_oklab(np.array([[0.70, 0.15, h]])))[0]
    print(f"hue={h}: hsv 域纯色 {srgb01_to_hex(rgb_h[0])} (= oklch {lch_h[2]:.1f}°) "
          f"| oklch 域取 h={h} 色 {srgb01_to_hex(tint_okl)}")

# ---- 6) C 刻度锚点: 常见内容的色度量级 (供滑杆刻度/文案) ----
print("\n== F. C 量级锚点 (sRGB 常见色 -> C) ==")
samples = {
    "纯红(255,0,0)": (1, 0, 0), "肤色(243,199,170)": (243/255, 199/255, 170/255),
    "天空(135,185,225)": (135/255, 185/255, 225/255), "植被(90,130,70)": (90/255, 130/255, 70/255),
    "中性灰(128)": (0.502, 0.502, 0.502), "艳橙(255,140,0)": (1, 140/255, 0),
    "深蓝(30,60,160)": (30/255, 60/255, 160/255),
}
cmax_y = None
from pixo.render.core.hsl_oklch import _cmax_of_l
for name, rgbv in samples.items():
    lchv = oklab_to_oklch(srgb_to_oklab(np.asarray(rgbv, dtype=np.float64)))
    print(f"{name:22s} L={lchv[0]:.3f}  C={lchv[1]:.3f}  h={lchv[2]:6.1f}  C_max(L)={float(_cmax_of_l(lchv[0])):.3f}")
print(f"\nC_NEUTRAL (中性保护阈值) = {C_NEUTRAL}")
print("C_max(L) 包络峰 ≈", float(_cmax_of_l(np.linspace(0.01, 0.99, 99)).max()))
