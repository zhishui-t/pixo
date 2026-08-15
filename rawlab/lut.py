"""3D LUT 风格映射 (阶段3) —— 三线性插值, NumPy 向量化。

支持:
  - 标准 .cube (LUT_3D_SIZE N, 行序 r 最慢 g 中 b 最快, 0-1)
  - Hald CLUT (阶段3 扩展: hald n³ 网格 → 3D LUT)
  - LUT 强度混合 (0-1): out = mix(orig, lut(orig), strength)

⚠️ 色彩域 (guanlan 8-10 教训): LUT 定义在 **sRGB gamma 域**查表。
  应用前输入必须是 gamma 编码的 sRGB (0-255 8bit 或 0-1 非线性),
  不能在线性域直套 (否则肤色 RMS 0.094 肉眼可见)。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


class LUT3D:
    """3D LUT: 三线性插值查找。

    应用性能: 256³ 预计算查表 (构建一次性缓存),
    half_size (3032x2020) ≈ 0.2s 达标; 全尺寸 ≈ 1.6s。
    """

    def __init__(self, data: np.ndarray):
        """data: (N, N, N, 3) float32 0-1, 索引序 [r, g, b]。"""
        self.data = data.astype(np.float32)
        self.n = data.shape[0]
        self.scale = self.n - 1
        self._table = None   # 256³ 查表 (惰性构建)

    @classmethod
    def from_cube(cls, path: str | Path) -> "LUT3D":
        """解析标准 .cube 文件 (LUT_3D_SIZE N + N³ 行 RGB)。"""
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        n = None
        vals = []
        for ln in lines:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if ln.upper().startswith("LUT_3D_SIZE"):
                n = int(ln.split()[-1])
                continue
            if ln.upper().startswith(("TITLE", "DOMAIN_MIN", "DOMAIN_MAX")):
                continue
            parts = ln.split()
            if len(parts) >= 3:
                vals.append([float(parts[0]), float(parts[1]), float(parts[2])])
        if n is None or len(vals) != n ** 3:
            raise ValueError(f"非法 .cube: {path} (size={n}, rows={len(vals)})")
        arr = np.array(vals, dtype=np.float32).reshape(n, n, n, 3)
        return cls(arr)

    def _build_table(self):
        """预计算 256³ 查表 (uint8 输出, 50MB)。"""
        if self._table is not None:
            return
        ri, gi, bi = np.meshgrid(np.arange(256), np.arange(256), np.arange(256),
                                 indexing="ij")
        # 直接对 256³ 输入做三线性 (等价 apply 但用整数网格)
        x = np.stack([ri, gi, bi], axis=-1).astype(np.float32) / 255.0
        n = self.n
        s = self.scale
        pos = x * s
        i0 = np.floor(pos).astype(np.int32)
        i1 = np.minimum(i0 + 1, s)
        f = pos - i0
        i0 = np.clip(i0, 0, s)
        i1 = np.clip(i1, 0, s)
        flat = self.data.reshape(-1, 3)

        def gather(r, g, b):
            return flat[(r * n + g) * n + b]

        c000 = gather(i0[..., 0], i0[..., 1], i0[..., 2])
        c001 = gather(i0[..., 0], i0[..., 1], i1[..., 2])
        c010 = gather(i0[..., 0], i1[..., 1], i0[..., 2])
        c011 = gather(i0[..., 0], i1[..., 1], i1[..., 2])
        c100 = gather(i1[..., 0], i0[..., 1], i0[..., 2])
        c101 = gather(i1[..., 0], i0[..., 1], i1[..., 2])
        c110 = gather(i1[..., 0], i1[..., 1], i0[..., 2])
        c111 = gather(i1[..., 0], i1[..., 1], i1[..., 2])

        fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
        out = (
            c000 * (1 - fr) * (1 - fg) * (1 - fb)
            + c001 * (1 - fr) * (1 - fg) * fb
            + c010 * (1 - fr) * fg * (1 - fb)
            + c011 * (1 - fr) * fg * fb
            + c100 * fr * (1 - fg) * (1 - fb)
            + c101 * fr * (1 - fg) * fb
            + c110 * fr * fg * (1 - fb)
            + c111 * fr * fg * fb
        )
        self._table = (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)

    def apply(self, rgb8: np.ndarray, strength: float = 1.0) -> np.ndarray:
        """应用 LUT 到 8bit RGB 图 (sRGB gamma 域)。

        256³ 查表: 构建一次性 (~16s 缓存), 应用 half_size ~0.2s。
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


def hald_to_lut(hald: np.ndarray) -> LUT3D:
    """Hald CLUT 图 → 3D LUT。

    Hald: n³ 网格排列成 n²×n² 大图, 像素 RGB 直接编码 cube 坐标:
      idx = round(pixel/255 × (n-1)), 坐标 [r,g,b] = (r*n+g)*n+b。
    """
    h, w = hald.shape[:2]
    if h != w:
        raise ValueError("Hald CLUT 必须是正方形")
    n = int(round(h ** (1.0 / 3.0)))
    if n ** 3 != h:
        raise ValueError(f"Hald 尺寸 {h} 不是 n³")
    data = hald.astype(np.float32) / 255.0
    # 重排: h×h → (n²,n²) → 每像素是 [r,g,b] 坐标的立方体
    img = data.reshape(n * n, n * n, 3)
    # 像素 (y,x) → cube 坐标: y = r*n + g? 需按官方布局
    # 官方: idx = round(pixel*255*(n-1)/255); cube idx = (r*n+g)*n+b
    # 大图布局: 行 y = r*n + g (r 最慢), 列 x = b (b 最快)
    cube = np.zeros((n, n, n, 3), dtype=np.float32)
    # 采样: 大图 (y, x) 像素颜色即坐标 (r,g,b) 处的 LUT 输出
    #   y 行对应 (r, g), x 列对应 b
    for r in range(n):
        for g in range(n):
            for b in range(n):
                cube[r, g, b] = img[r * n + g, b]
    return LUT3D(cube)


# ── LUT 库注册 (guanlan luts/ 复用) ──
_LUT_DIR = Path(r"K:\work\project\guanlan\luts")

_LUT_REGISTRY = {
    "astia": "astia.cube",
    "classic_chrome": "classic_chrome.cube",
    "classic_neg": "classic_neg.cube",
    "eterna": "eterna.cube",
    "provia": "provia.cube",
    "velvia": "velvia.cube",
    "reala_ace": "reala_ace.cube",
    "nostalgic_neg": "nostalgic_neg.cube",
    "bleach_bypass": "bleach_bypass.cube",
    "kodak_vision3_250d": "kodak_vision3_250d.cube",
    "kodak_vision3_500t": "kodak_vision3_500t.cube",
    "mono_redux": "MonoPhotoRedux.cube",
    "pan_teal_orange": "pan_teal_orange.cube",
    "pan_cinetone": "pan_cinetone.cube",
}

_cache: dict = {}


def load_lut(style_id: str) -> LUT3D:
    """加载注册 LUT (缓存), 并预热 256³ 查表。

    首次加载含建表 ~16s (一次); 之后 apply 命中缓存 ~0.2s (half_size)。
    """
    if style_id in _cache:
        return _cache[style_id]
    name = _LUT_REGISTRY.get(style_id)
    if not name:
        raise KeyError(f"未注册 LUT: {style_id} (可选: {list(_LUT_REGISTRY)})")
    lut = LUT3D.from_cube(_LUT_DIR / name)
    lut._build_table()  # 预热查表 (一次性 16s)
    _cache[style_id] = lut
    return lut
