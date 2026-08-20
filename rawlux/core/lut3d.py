"""engine.lut3d —— 四面体 3D LUT (Kasson 1993) + .cube 解析 (1D shaper + DOMAIN)。

权威依据:
  - Kasson & Plouffe & Nin (1993), "Performing color space conversions with
    three-dimensional linear interpolation", J. Electronic Imaging.
    四面体插值把单位立方体按三个分数分量 fr/fg/fb 的排序划分为 6 个四面体,
    用 4 顶点重心坐标插值; 相比三线性插值无"扇形"误差 (fan error),
    且对线性(仿射)函数在顶点/面/边/体心处均精确重建。
  - .cube 格式 (Iridas/Resolve 通用): LUT_1D_SIZE (1D shaper) / LUT_3D_SIZE
    (3D LUT) / DOMAIN_MIN / DOMAIN_MAX (输入窗口) / TITLE。

约定:
  - 所有 LUT 输入/输出归一化到 [0,1] (float)。8bit 图经 apply() 按 /255 归一化。
  - data 索引序 [r, g, b] (r 最慢, b 最快), 与 .cube 文件行序一致
    (reshape(N,N,N,3) 的 C 序: 最末轴 b 变化最快)。
  - DOMAIN_MIN/MAX 定义输入窗口 (归一化 0..1 单位): 输入 v 线性映射为
        t = (v - DOMAIN_MIN) / (DOMAIN_MAX - DOMAIN_MIN)
    窗口外截断到 [0,1] (等价于对输入做增益/平移缩放, 默认 [0,1] 为恒等)。
  - 1D shaper 先于 3D LUT 应用 (shaper 自身定义在 [0,1] 上, 线性插值采样)。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Union

import numpy as np


def tetrahedral_interp(data: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """四面体插值 (Kasson 1993), numpy 向量化实现。

    data: (N, N, N, 3) float32, 整数格点 [r, g, b] 处的 LUT 输出值。
    pos : (..., 3) 浮点格点坐标, 取值 [0, N-1] (越界截断)。
    返回: (..., 3) float32。

    算法: 单位立方体按分数分量排序划分为 6 个四面体, 四顶点 =
      c000 → c000+最大分量轴 → c000+最大轴+次大轴 → c111,
    重心坐标 = (1-fmax, fmax-fmid, fmid-fmin, fmin)。
    对线性函数精确重建 (顶点/面/边/体心均无插值误差)。
    """
    data = np.asarray(data, dtype=np.float32)
    n = data.shape[0]
    s = n - 1
    pos = np.clip(np.asarray(pos, dtype=np.float32), 0.0, float(s))
    i0 = np.floor(pos).astype(np.int32)
    f = pos - i0
    i1 = np.minimum(i0 + 1, s)
    i0 = np.clip(i0, 0, s)

    # 立方体 8 顶点 (r, g, b 各取 0/1 组合; 命名 c[r][g][b])
    c000 = data[i0[..., 0], i0[..., 1], i0[..., 2]]
    c001 = data[i0[..., 0], i0[..., 1], i1[..., 2]]
    c010 = data[i0[..., 0], i1[..., 1], i0[..., 2]]
    c011 = data[i0[..., 0], i1[..., 1], i1[..., 2]]
    c100 = data[i1[..., 0], i0[..., 1], i0[..., 2]]
    c101 = data[i1[..., 0], i0[..., 1], i1[..., 2]]
    c110 = data[i1[..., 0], i1[..., 1], i0[..., 2]]
    c111 = data[i1[..., 0], i1[..., 1], i1[..., 2]]

    fsort = np.sort(f, axis=-1)          # 升序: [fmin, fmid, fmax]
    fmin = fsort[..., 0:1]
    fmid = fsort[..., 1:2]
    fmax = fsort[..., 2:3]

    max_axis = np.argmax(f, axis=-1)     # 最大分数分量所在轴 (0/1/2)
    min_axis = np.argmin(f, axis=-1)     # 最小分数分量所在轴

    w0 = 1.0 - fmax                      # c000 的权重
    w1 = fmax - fmid                     # c000+最大轴 的权重
    w2 = fmid - fmin                     # c000+最大轴+次大轴 的权重
    w3 = fmin                            # c111 的权重

    is_max_r = (max_axis == 0)[..., None].astype(np.float32)
    is_max_g = (max_axis == 1)[..., None].astype(np.float32)
    is_max_b = (max_axis == 2)[..., None].astype(np.float32)
    v1 = c100 * is_max_r + c010 * is_max_g + c001 * is_max_b

    is_min_r = (min_axis == 0)[..., None].astype(np.float32)
    is_min_g = (min_axis == 1)[..., None].astype(np.float32)
    is_min_b = (min_axis == 2)[..., None].astype(np.float32)
    v2 = c011 * is_min_r + c101 * is_min_g + c110 * is_min_b

    return (c000 * w0 + v1 * w1 + v2 * w2 + c111 * w3).astype(np.float32)


def _interp1d(lut: np.ndarray, x: np.ndarray) -> np.ndarray:
    """对 0..1 输入做 1D LUT 线性插值 (lut: (m,) float32, 定义在 [0,1] 均匀采样)。"""
    m = lut.shape[0] - 1
    xc = np.clip(x, 0.0, 1.0)
    pos = xc * m
    i0 = np.floor(pos).astype(np.int32)
    i1 = np.minimum(i0 + 1, m)
    frac = pos - i0
    return lut[i0] * (1.0 - frac) + lut[i1] * frac


class LUT3D:
    """3D LUT: 四面体插值查找 (Kasson 1993)。

    应用性能: 256³ 预计算查表 (分块构建, 峰值内存 <512MB, 惰性缓存),
    之后 apply() 直接整数索引, half_size (3032x2020) ≈ 0.2s。
    """

    def __init__(self, data: np.ndarray, shaper: np.ndarray | None = None,
                 domain_min: float = 0.0, domain_max: float = 1.0):
        """data: (N, N, N, 3) float32 0-1, 索引序 [r, g, b]。

        shaper    : 可选 1D LUT (m,) float32, 先于 3D LUT 应用, 定义在 [0,1]。
        domain_min/max: 输入窗口 (归一化 0..1 单位), 窗口外截断。
        """
        data = np.asarray(data, dtype=np.float32)
        if data.ndim != 4 or data.shape[3] != 3 or \
                data.shape[0] != data.shape[1] or data.shape[1] != data.shape[2]:
            raise ValueError(f"3D LUT data 必须是 (N, N, N, 3), 实得 {data.shape}")
        self.data = data
        self.n = data.shape[0]
        self.scale = self.n - 1
        self.shaper = None if shaper is None else np.asarray(shaper, dtype=np.float32).reshape(-1)
        if self.shaper is not None and self.shaper.size < 2:
            raise ValueError("1D shaper 至少需要 2 个采样点")
        self.domain_min = float(domain_min)
        self.domain_max = float(domain_max)
        if not (self.domain_max > self.domain_min):
            raise ValueError(f"非法 DOMAIN: [{domain_min}, {domain_max}]")
        self._table: np.ndarray | None = None   # 256³ 查表 (惰性构建)

    # ------------------------------------------------------------------ 解析
    @classmethod
    def from_cube(cls, path: Union[str, Path]) -> "LUT3D":
        """解析标准 .cube 文件 → LUT3D (含 LUT_1D_SIZE shaper + DOMAIN)。"""
        return parse_cube(path)

    # ------------------------------------------------------------------ 应用
    def _prepare_input(self, x: np.ndarray) -> np.ndarray:
        """归一化输入 (...,3) float32 ∈ [0,1] → 域缩放 + 1D shaper → [0,1]。"""
        t = (x - self.domain_min) / (self.domain_max - self.domain_min)
        t = np.clip(t, 0.0, 1.0)
        if self.shaper is not None:
            t = _interp1d(self.shaper, t)
        return t.astype(np.float32)

    def lookup(self, x: np.ndarray) -> np.ndarray:
        """float 输入 x (...,3) ∈ [0,1] → LUT 输出 (...,3) float32。

        直接四面体插值 (不经 256³ 缓存), 用于高精度/浮点图/单测。
        """
        t = self._prepare_input(np.asarray(x, dtype=np.float32))
        return tetrahedral_interp(self.data, t * self.scale)

    def _build_table(self, chunk: int = 16) -> None:
        """分块预计算 256³ 查表 (uint8 输出, 最终 50MB)。

        chunk 沿第一轴 (r) 切块, 每块只物化 (chunk,256,256,3) 中间量,
        避免一次性 meshgrid 256³ 带来的 ~1GB 峰值内存 (目标 <512MB)。
        """
        if self._table is not None:
            return
        chunk = max(1, int(chunk))
        s = self.scale
        parts: list[np.ndarray] = []
        for r0 in range(0, 256, chunk):
            r1 = min(r0 + chunk, 256)
            rr = np.arange(r0, r1, dtype=np.float32)
            gg = np.arange(256, dtype=np.float32)
            bb = np.arange(256, dtype=np.float32)
            R, G, B = np.meshgrid(rr, gg, bb, indexing="ij")
            x = (np.stack([R, G, B], axis=-1) / 255.0).astype(np.float32)
            t = self._prepare_input(x)
            out = tetrahedral_interp(self.data, t * s)
            parts.append((np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
        self._table = np.concatenate(parts, axis=0)

    def apply(self, rgb8: np.ndarray, strength: float = 1.0) -> np.ndarray:
        """应用 LUT 到 8bit RGB 图 (sRGB gamma 域)。

        rgb8 : (..., 3) uint8, 0..255。
        256³ 查表: 构建一次性 (分块, 惰性), 应用 half_size ~0.2s。
        strength : 0..1 强度混合 (0=原图)。
        """
        self._build_table()
        flat = self._table.reshape(-1, 3)
        r = rgb8[..., 0].astype(np.int32)
        g = rgb8[..., 1].astype(np.int32)
        b = rgb8[..., 2].astype(np.int32)
        idx = r * 65536 + g * 256 + b
        out = flat[idx]
        if strength < 1.0:
            out = (rgb8.astype(np.float32) * (1.0 - strength)
                   + out.astype(np.float32) * strength)
            out = np.clip(out, 0, 255).astype(np.uint8)
        return out


# ---------------------------------------------------------------------------
# .cube 解析
# ---------------------------------------------------------------------------

def parse_cube(path: Union[str, Path]) -> LUT3D:
    """解析 .cube 文件 → LUT3D。

    支持关键字: TITLE / DOMAIN_MIN / DOMAIN_MAX / LUT_1D_SIZE / LUT_3D_SIZE。
    1D shaper 值紧跟在 LUT_1D_SIZE 后 (每行一个); 3D 值紧跟在 LUT_3D_SIZE 后
    (每行三个, 行序 r 最慢、b 最快)。DOMAIN 缺省 [0.0, 1.0]。
    """
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    domain_min = 0.0
    domain_max = 1.0
    n1d: int | None = None
    n3d: int | None = None
    shaper_vals: list[float] = []
    lut3d_vals: list[list[float]] = []
    pending: str | None = None   # "1d" 或 "3d"

    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        up = ln.upper()
        if up.startswith("TITLE"):
            continue
        if up.startswith("DOMAIN_MIN"):
            domain_min = float(ln.split()[-1])
            continue
        if up.startswith("DOMAIN_MAX"):
            domain_max = float(ln.split()[-1])
            continue
        if up.startswith("LUT_1D_SIZE"):
            n1d = int(ln.split()[-1])
            shaper_vals = []
            pending = "1d"
            continue
        if up.startswith("LUT_3D_SIZE"):
            n3d = int(ln.split()[-1])
            lut3d_vals = []
            pending = "3d"
            continue
        # 数据行
        parts = ln.split()
        if pending == "1d":
            if parts:
                shaper_vals.append(float(parts[0]))
                if n1d is not None and len(shaper_vals) >= n1d:
                    pending = None
        elif pending == "3d":
            if len(parts) >= 3:
                lut3d_vals.append([float(parts[0]), float(parts[1]), float(parts[2])])
                if n3d is not None and len(lut3d_vals) >= n3d ** 3:
                    pending = None
        # 无 pending 时的游离数字行直接忽略 (防御)

    if n3d is None or len(lut3d_vals) != n3d ** 3:
        raise ValueError(
            f"非法 .cube: {path} (LUT_3D_SIZE={n3d}, rows={len(lut3d_vals)})")
    if n1d is not None and len(shaper_vals) != n1d:
        raise ValueError(
            f"非法 .cube: {path} (LUT_1D_SIZE={n1d}, rows={len(shaper_vals)})")
    if not (domain_max > domain_min):
        raise ValueError(
            f"非法 .cube: {path} (DOMAIN [{domain_min}, {domain_max}])")

    data = np.array(lut3d_vals, dtype=np.float32).reshape(n3d, n3d, n3d, 3)
    shaper = np.array(shaper_vals, dtype=np.float32) if n1d is not None else None
    return LUT3D(data, shaper=shaper, domain_min=domain_min, domain_max=domain_max)


# ---------------------------------------------------------------------------
# Hald CLUT
# ---------------------------------------------------------------------------

def hald_to_lut(hald: np.ndarray) -> LUT3D:
    """Hald CLUT 图 → 3D LUT。

    官方布局 (Hald CLUT, ImageMagick / RawTherapee / 3D LUT Creator 通用):
      - Hald 图为 N²×N² 像素, 编码 N×N×N 的 3D LUT (N = 等级)。
      - 整图划分为 N×N 个 N×N tile; tile 内 r 沿 x 轴 (最快), g 沿 y 轴,
        b 决定 tile (最慢, 按 tile 行优先扫描: 先扫一行 tile 的 b=0..N-1)。
      - 像素坐标: x = (b % N)·N + r, y = (b // N)·N + g。
      - 像素颜色 (归一化 0..1) 即该 (r, g, b) 格点的 LUT 输出值。
    """
    h, w = hald.shape[:2]
    if h != w:
        raise ValueError("Hald CLUT 必须是正方形")
    n = int(round(math.sqrt(h)))
    if n * n != h:
        raise ValueError(f"Hald 尺寸 {h} 不是 n² (N²×N² 布局)")
    img = np.asarray(hald, dtype=np.float32) / 255.0
    cube = np.zeros((n, n, n, 3), dtype=np.float32)
    for b in range(n):
        ty, tx = divmod(b, n)
        # tile (ty, tx): 行 = g (沿 y), 列 = r (沿 x) → cube[r, g, b] = tile[g, r]
        tile = img[ty * n:(ty + 1) * n, tx * n:(tx + 1) * n, :]   # (n, n, 3)
        cube[:, :, b, :] = np.transpose(tile, (1, 0, 2))          # 转置: [r, g, :]
    return LUT3D(cube)

__all__ = ["tetrahedral_interp", "LUT3D", "parse_cube", "hald_to_lut"]
