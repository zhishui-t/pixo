# spike (r10 疑难): OKLab 椭圆肤色掩码 native 对齐验证驱动。
#
# 问题: colorcal oklch 域旁路 native (纯 Python float 路径 131ms vs native 8.5ms,
# 15x, F11)。堵法 = native 内核内嵌 OKLab 掩码; 前提 = 掩码能与
# core/skin.py::skin_mask_oklab 逐位对齐 (oklab.cpp v1.4.0 已证 sRGB→OKlab
# f64 链逐位一致, 本 spike 验证掩码全链: 转换 + 椭圆 + smoothstep)。
#
# 做什么:
#   1. 构造混合语料 (随机 [0,1] / 越界 [-0.3,1.3] / 结构化肤色+中性+扫描)
#   2. Python 参考链 skin_mask_oklab 逐像素掩码
#   3. 运行 C++ 原型 (spike_oklch_mask.exe, 同 MinGW g++ -O2 编译)
#   4. 逐位比较 (mismatch 数 / max ULP / max |Δ|); 512x512 perf 对照
#
# 用法: python .agent-team/spike/spike_oklch_mask.py
# 产物属 spike, 不入主代码; 结论回收后可删。
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np

SPIKE_DIR = Path(__file__).resolve().parent
EXE = SPIKE_DIR / "spike_oklch_mask.exe"
RGB_BIN = SPIKE_DIR / "_spike_rgb.bin"
MASK_BIN = SPIKE_DIR / "_spike_mask.bin"

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pixo.render.core.skin import skin_mask_oklab  # noqa: E402


def run_cpp(rgb_flat: np.ndarray, repeats: int = 1) -> tuple[np.ndarray, float]:
    """rgb_flat (n,3) f32 → (mask (n,) f32, exe 墙钟秒)。"""
    rgb = np.ascontiguousarray(rgb_flat, dtype=np.float32)
    rgb.tofile(RGB_BIN)
    t0 = time.perf_counter()
    subprocess.run([str(EXE), str(RGB_BIN), str(rgb.shape[0]), str(MASK_BIN),
                    str(repeats)], check=True, capture_output=True)
    dt = time.perf_counter() - t0
    mask = np.fromfile(MASK_BIN, dtype=np.float32)
    return mask, dt


def ulp_dist_f32(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """正域 f32 的 ULP 距离 (掩码 ∈ [0,1], 同号单调可直接整型差)。"""
    ai = a.view(np.int32).astype(np.int64)
    bi = b.view(np.int32).astype(np.int64)
    return np.abs(ai - bi)


def main() -> int:
    if not EXE.exists():
        print(f"[ERR] 缺 {EXE}, 先编译:")
        print(r'  D:\code\mingw64\bin\g++.exe -O2 -std=c++20 '
              f'-o "{EXE}" "{SPIKE_DIR / "spike_oklch_mask.cpp"}"')
        return 2

    rng = np.random.default_rng(20260907)
    corpora = {
        "random_[0,1]": rng.uniform(0.0, 1.0, size=(100_000, 3)),
        "random_[-0.3,1.3]": rng.uniform(-0.3, 1.3, size=(100_000, 3)),
        "random_8bit_grid": (rng.integers(0, 256, size=(100_000, 3))
                             .astype(np.float32) / 255.0),
        "skin+neutral+edges": _structured(),
    }

    all_ok = True
    for name, rgb64 in corpora.items():
        rgb = np.asarray(rgb64, dtype=np.float32)
        # Python 参考链 (与 color_cal.py oklch 分支同一入口 _skin_region_mask)
        ref = skin_mask_oklab(rgb.reshape(-1, 1, 3))[:, 0]
        got, _ = run_cpp(rgb)
        assert got.shape == ref.shape, (got.shape, ref.shape)
        n_mismatch = int(np.count_nonzero(got.view(np.int32) != ref.view(np.int32)))
        if n_mismatch:
            ulp = ulp_dist_f32(got, ref)
            print(f"[FAIL] {name}: mismatch {n_mismatch}/{rgb.shape[0]}, "
                  f"max ULP {int(ulp.max())}, "
                  f"max |Δ| {float(np.abs(got - ref).max()):.3e}")
            all_ok = False
        else:
            print(f"[OK]   {name}: bit-exact ({rgb.shape[0]} px)")

    # ---- perf 信号 (512x512, C++ 单线程原型 vs Python 参考链) ----
    img = rng.uniform(0.0, 1.0, size=(512 * 512, 3)).astype(np.float32)
    t0 = time.perf_counter()
    ref = skin_mask_oklab(img.reshape(-1, 1, 3))[:, 0]
    py_dt = time.perf_counter() - t0
    _, exe_dt = run_cpp(img, repeats=3)
    print(f"[perf] 512x512: python {py_dt * 1e3:.1f} ms | "
          f"C++ 单线程原型 (3 次含进程启动) {exe_dt * 1e3 / 3:.1f} ms/次")

    print("[SPIKE]", "PASS — OKLab 掩码可逐位对齐, native oklch 内核路线可行"
          if all_ok else "FAIL — 存在逐位分歧, 需查常数/操作序")
    return 0 if all_ok else 1


def _structured() -> np.ndarray:
    """结构化语料: 肤色带扫描 / 中性灰 / 马氏距离边界 d≈1 与 d≈1.25 / 极值。"""
    rows = []
    # 中性灰 + 黑白
    for v in (0.0, 0.18, 0.5, 0.9, 1.0):
        rows.append([v, v, v])
    # 典型肤色 (RGB 三角) 扫掠
    for t in np.linspace(0.0, 1.0, 512):
        rows.append([0.35 + 0.4 * t, 0.2 + 0.35 * t, 0.15 + 0.3 * t])
    # gamma 编码边界 0.04045 附近 (EOTF 分支切换)
    for d in (-1e-6, -1e-7, 0.0, 1e-7, 1e-6, 1e-3):
        v = 0.04045 + d
        rows.extend([[v, v, v], [v, 0.5, 0.5], [0.5, v, 0.5], [0.5, 0.5, v]])
    # 越界极值 (入参清洗 clip 行为)
    rows.extend([[-0.5, 0.2, 0.2], [1.5, 0.2, 0.2], [0.2, -0.5, 1.5],
                 [-1.0, -1.0, -1.0], [2.0, 2.0, 2.0]])
    return np.asarray(rows, dtype=np.float32)


if __name__ == "__main__":
    raise SystemExit(main())
