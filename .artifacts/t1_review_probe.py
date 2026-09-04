"""t1 复核探针 (测试工程师1, 2026-08-28) —— 独立复现 oklab.py 宣称的实测精度。

独立性声明: 本探针不复用交付测试的代码路径; 正向链路与 Ottosson 原文逆矩阵
常数均为本探针独立重写 (原文常数取自 Bottosson 2020 博客公布值), 仅 import
被测模块做对照。每项输出与交付宣称值逐条对照。
"""
import sys
import numpy as np

sys.path.insert(0, "src")
from pixo.render.core.oklab import (
    srgb_to_oklab, oklab_to_srgb, oklab_to_oklch, oklch_to_oklab,
    _M1_LSRGB_TO_LMS, _M2_LMSP_TO_LAB, _M1_INV_LMS_TO_LSRGB, _M2_INV_LAB_TO_LMSP,
)

# ---- Ottosson 2020 原文公布常数 (探针独立抄录) ----
M1_PUB = np.array([
    [+0.4122214708, +0.5363325363, +0.0514459929],
    [+0.2119034982, +0.6806995451, +0.1073969566],
    [+0.0883024619, +0.2817188376, +0.6299787005]])
M2_PUB = np.array([
    [+0.2104542553, +0.7936177850, -0.0040720468],
    [+1.9779984951, -2.4285922050, +0.4505937099],
    [+0.0259040371, +0.7827717662, -0.8086757660]])
M1_INV_PUB = np.array([
    [+4.0767416614, -3.3077115913, +0.2309699292],
    [-1.2684380046, +2.6097574011, -0.3413193965],
    [-0.0041960865, -0.7034186157, +1.7076147010]])
M2_INV_PUB = np.array([
    [+1.0000000000, +0.3963377774, +0.2158037573],
    [+1.0000000000, -0.1055613458, -0.0638541728],
    [+1.0000000000, -0.0894841820, -1.2914855480]])

ANCHORS = {  # 原文公布示例值 (6 位小数)
    "red":   ((1, 0, 0), (0.627955, 0.224863, 0.125846)),
    "green": ((0, 1, 0), (0.866440, -0.233888, 0.179498)),
    "blue":  ((0, 0, 1), (0.452014, -0.032457, -0.311528)),
}

print("=== A. 交付正向常数与原文逐位核对 ===")
print("M1 == 原文:", np.array_equal(_M1_LSRGB_TO_LMS, M1_PUB))
print("M2 == 原文:", np.array_equal(_M2_LMSP_TO_LAB, M2_PUB))
print("交付逆矩阵 == 原文公布逆矩阵 (应为 False, 宣称有意偏离):",
      np.array_equal(_M1_INV_LMS_TO_LSRGB, M1_INV_PUB) or np.array_equal(_M2_INV_LAB_TO_LMSP, M2_INV_PUB))

print("\n=== B. 原文逆矩阵不互逆 (宣称: M2inv*M2 偏差 ~5.5e-8, L 列 0.9999999985) ===")
d_m2 = np.abs(M2_INV_PUB @ M2_PUB - np.eye(3))
d_m1 = np.abs(M1_INV_PUB @ M1_PUB - np.eye(3))
print(f"M2inv_pub @ M2 - I  max|d| = {d_m2.max():.3e}")
print(f"M1inv_pub @ M1 - I  max|d| = {d_m1.max():.3e}")
print("M2inv_pub 第 1 列 (L 列):", M2_INV_PUB[:, 0])
num_inv_m2 = np.linalg.inv(M2_PUB)
print(f"np.linalg.inv(M2) vs 冻结常数 max|d| = {np.abs(num_inv_m2 - _M2_INV_LAB_TO_LMSP).max():.3e} (宣称 <5e-13)")
num_inv_m1 = np.linalg.inv(M1_PUB)
print(f"np.linalg.inv(M1) vs 冻结常数 max|d| = {np.abs(num_inv_m1 - _M1_INV_LMS_TO_LSRGB).max():.3e} (宣称 <5e-13)")

print("\n=== C. 原文逆矩阵往返误差 (宣称 ~2e-6) vs 交付数值逆 (宣称网格 1.8e-10) ===")

def _decode(rgb01):
    c = np.clip(np.asarray(rgb01, dtype=np.float64), 0.0, None)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def _encode(lin):
    return np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(lin, 1.0 / 2.4) - 0.055)

def fwd(rgb):  # 独立正向: gamma sRGB -> Oklab
    lin = _decode(rgb)
    lms = lin @ M1_PUB.T
    lms_ = np.cbrt(lms)
    return lms_ @ M2_PUB.T

def inv_pub(lab):  # 原文公布逆常数版逆变换 (linear 域 clip + encode, 与交付策略一致)
    lms_ = lab @ M2_INV_PUB.T
    lms = lms_ ** 3
    lin = np.clip(lms @ M1_INV_PUB.T, 0.0, 1.0)
    return _encode(lin)

def inv_num(lab):  # 数值逆常数版 (用交付冻结常数)
    lms_ = lab @ _M2_INV_LAB_TO_LMSP.T
    lms = lms_ ** 3
    lin = np.clip(lms @ _M1_INV_LMS_TO_LSRGB.T, 0.0, 1.0)
    return _encode(lin)

ax = np.arange(33) / 32.0
grid = np.stack(np.meshgrid(ax, ax, ax, indexing="ij"), axis=-1).reshape(-1, 3)
for tag, invf in (("原文逆常数", inv_pub), ("交付数值逆", inv_num)):
    lab = fwd(grid)
    # 用被测正向做同样网格 (隔离探针 fwd 与交付 fwd 的常数一致性)
    err = np.abs(invf(srgb_to_oklab(grid)).astype(np.float64) - grid).max()
    print(f"[{tag}] 网格 1/32 (35937 点) 往返 max err = {err:.3e}")

rng = np.random.default_rng(20260828)
rnd = rng.random((500_000, 3))
err_pub = np.abs(inv_pub(srgb_to_oklab(rnd)).astype(np.float64) - rnd).max()
err_num = np.abs(oklab_to_srgb(srgb_to_oklab(rnd)).astype(np.float64) - rnd).max()
print(f"[原文逆常数] 随机 50 万点往返 max err = {err_pub:.3e} (宣称 ~2e-6)")
print(f"[交付数值逆] 随机 50 万点往返 max err = {err_num:.3e} (宣称 3.0e-8)")

print("\n=== D. f32 中间交接物理下限 (宣称: lab 以 f32 交接时往返下限 ~7e-7) ===")
for n in (500_000, 2_000_000):
    r = np.random.default_rng(7).random((n, 3))
    lab32 = srgb_to_oklab(r).astype(np.float32)          # lab 以 f32 交接 (假设反事实)
    back = oklab_to_srgb(lab32.astype(np.float64)).astype(np.float64)
    print(f"f32 lab 交接 {n:>9,} 点: max err = {np.abs(back - r).max():.3e}")

print("\n=== E. 锚点 / 灰轴 / OKLCh / 端点 (宣称: 锚点 7 位吻合, 灰轴 C≈3.7e-8, lch 往返 2.9e-16) ===")
for name, (srgb, ref) in ANCHORS.items():
    got = srgb_to_oklab(np.array([srgb], dtype=np.float64))[0]
    diff = np.abs(got - np.array(ref))
    print(f"{name:>5}: got {np.round(got, 7)}, |diff vs 原文6位公布| max = {diff.max():.2e}")
gray = np.linspace(0, 1, 65)
g3 = np.stack([gray] * 3, axis=-1)
lch_g = oklab_to_oklch(srgb_to_oklab(g3))
print(f"灰轴 C max = {lch_g[:, 1].max():.3e} (宣称 ≈3.7e-8)")
lab_r = srgb_to_oklab(np.random.default_rng(3).random((10_000, 3)))
rt = oklch_to_oklab(oklab_to_oklch(lab_r))
print(f"OKLCh 往返 max = {np.abs(rt - lab_r).max():.3e} (宣称 2.9e-16)")
w = oklab_to_srgb(srgb_to_oklab(np.ones((1, 3))))
b = oklab_to_srgb(srgb_to_oklab(np.zeros((1, 3))))
print(f"白端点 sRGB 往返逐位: {np.array_equal(w, np.ones((1, 3), np.float32))}, "
      f"黑端点 lab 逐位零: {np.array_equal(srgb_to_oklab(np.zeros((1, 3))), np.zeros((1, 3)))}")
h1 = oklch_to_oklab(np.array([[0.6, 0.1, 1.0]])); h361 = oklch_to_oklab(np.array([[0.6, 0.1, 361.0]]))
print(f"h 环绕 361°≡1° 偏差 = {np.abs(h1 - h361).max():.3e} (宣称 ~1e-16)")

print("\n=== F. 批量 vs 单像素逐位 (独立抽查, 宣称 4 API 全一致) ===")
img = np.random.default_rng(7).random((5, 6, 3))
lab = srgb_to_oklab(img); lch = oklab_to_oklch(lab)
for fn, src in ((srgb_to_oklab, img), (oklab_to_srgb, lab),
                (oklab_to_oklch, lab), (oklch_to_oklab, lch)):
    batched = fn(src)
    ok = all(np.array_equal(np.asarray(batched[i, j]), np.asarray(fn(src[i, j])))
             for i in range(5) for j in range(6))
    print(f"{fn.__name__}: 批量==单像素 逐位 {ok}")

print("\n=== G. 交付往返 vs 探针独立正向交叉验证 (常数一致性) ===")
cross = np.abs(srgb_to_oklab(grid) - fwd(grid)).max()
print(f"交付 srgb_to_oklab vs 探针独立正向 (原文常数) 网格 max|d| = {cross:.3e}")
