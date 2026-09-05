"""engine.huesat_oklch —— HSM→OKLCh 控制点云的 OKLCh 域连续形变。

路线图"阶段二起用 OKLCh 连续形变替代 DCP HSM"的运行时接线: 数据资产为
configs/color/hsm_oklch_*.json (t17 convert_hsm_to_oklch 产出, schema
``pixo.hsm_oklch_points.v1``) —— DCP HueSatMap/LookTable 逐网格节点的
OKLCh 语义转译: 每点 = (h, c, l = 查表前像素 OKLCh 坐标;
dh = 色相增量(度, ±180 折回); c_gain/l_gain = 色度/亮度增益)。

方法 (与 core.huesat 的 HSV 三线性同风格, O(px) 纯 numpy —— core 隔离纪律:
运行时不用 scipy):
  1. 加载期把散点栅格化为规则 3D 表 (Shepard IDW 填充): 对每个格中心取
     K 近邻点反距离加权 (p=2); 距离的 h 轴用环距 (min(|Δh|, 360−|Δh|)),
     c/l 轴按跨度归一量纲 (c∈[0,c_hi] 窄、l∈[0,1] 宽 → wc=1/c_hi);
  2. 运行时对像素 OKLCh 坐标三线性插值 (h 环绕) 出 (dh, c_gain, l_gain),
     strength 线性混合到恒等 (语义同 apply_table_to_hsv):
     h' = h + strength·dh;  c' = c·(1 + strength·(c_gain−1));
     l' = l·(1 + strength·(l_gain−1));
  3. 色域软限幅复用 hsl_oklch._soft_limit_chroma (仅压增强量, tanh 渐近
     C_max(L), 未增强像素精确恒等);
  4. 近中性/无效应像素的 no-op: 插值结果 |dh| < eps_dh 且 |gain−1| < eps_gain
     的像素 (touch 掩码外) 绕过 OKLCh 重建原值直通 —— sRGB↔OKLCh 往返
     (极坐标重建 + gamma 编码) 非逐位可逆, 同 hsl_oklch 的 touch 纪律;
     恒等点云 (全点 |dh|<eps 且 |gain−1|<eps) 或 strength≤0 → 整图原值
     直通 (连域转换都不做, 全 0 no-op 纪律; 本函数输入即控制点数据非用户
     参数, touch 直通豁免条款不适用——恒等判定照常生效)。

已知近似 (报告口径):
  - 栅格化是"散点 IDW → 规则表 → 三线性"的两级插值, 相对直接 IDW 在格间
    有平滑偏差 (点密处 <1% 增益差, 单测对照);
  - 点云采样未覆盖 l < 0.40 (HSM 表深阴影节点经转译后 l 下界) 与
    c > 0.357 色域角, 该区域钳到边界行/列取近邻效应。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .hsl_oklch import _soft_limit_chroma
from .oklab import oklab_to_oklch, oklab_to_srgb, oklch_to_oklab, srgb_to_oklab

__all__ = ["OklchDeform", "load_oklch_deform", "is_identity_deform",
           "apply_oklch_deform", "rasterize_points"]

# 栅格维度 (h 5°/bin 环绕; c/l 轴 bin 数): 格中心 IDW 填充, 运行时三线性。
_GRID_H = 72
_GRID_C = 24
_GRID_L = 24
_C_HI = 0.37                 # c 轴上界 (点云 max 0.357 + 余量; 像素超界钳边)
_IDW_K = 8                   # Shepard 近邻数
_IDW_POWER = 2.0
_EPS_D2 = 1e-12              # IDW 距离平方正则 (格中心恰在点上 → 直接取值)


@dataclass(frozen=True)
class OklchDeform:
    """点云栅格化产物 (不可变; table 为 (Hb, Cb, Lb, 3) dh/c_gain/l_gain)。"""

    table: np.ndarray
    strength: float
    eps_dh: float              # 恒等判定阈 (度; 点云 identity_eps.dh_deg)
    eps_gain: float            # 恒等判定阈 (增益; identity_eps.gain)
    source: str = ""


def is_identity_deform(spec: OklchDeform) -> bool:
    """恒等点云: 全部格 |dh|<eps 且 |gain−1|<eps → 整图 no-op。"""
    t = spec.table
    return bool(np.all(np.abs(t[..., 0]) < spec.eps_dh)
                and np.all(np.abs(t[..., 1] - 1.0) < spec.eps_gain)
                and np.all(np.abs(t[..., 2] - 1.0) < spec.eps_gain))


# ---------------------------------------------------------------------------
# 加载与栅格化
# ---------------------------------------------------------------------------

def rasterize_points(points: np.ndarray, grid: tuple[int, int, int] = (
        _GRID_H, _GRID_C, _GRID_L), c_hi: float = _C_HI,
        idw_k: int = _IDW_K, idw_power: float = _IDW_POWER) -> np.ndarray:
    """散点 (n,6) [h,c,l,dh,c_gain,l_gain] → 规则表 (Hb,Cb,Lb,3) (Shepard IDW)。

    对每个格中心取环距 h + 量纲归一 c/l 的 K 近邻反距离加权 (p=idw_power);
    格中心恰在控制点上 (d²<eps) 时直接取该点值。纯 numpy 分块, 无 scipy。
    """
    hb, cb, lb = grid
    pts = np.asarray(points, dtype=np.float64)
    h_axis = (np.arange(hb, dtype=np.float64) + 0.5) * (360.0 / hb)
    c_axis = (np.arange(cb, dtype=np.float64) + 0.5) * (c_hi / cb)
    l_axis = (np.arange(lb, dtype=np.float64) + 0.5) / lb
    hh, cc, ll = np.meshgrid(h_axis, c_axis, l_axis, indexing="ij")
    centers = np.stack([hh.ravel(), cc.ravel(), ll.ravel()], axis=1)  # (g,3)

    wc = 1.0 / max(c_hi, 1e-9)     # c 跨度窄 → 放大到与 l 同量纲
    ph = np.radians(pts[:, 0])
    pc = pts[:, 1] * wc
    pl = pts[:, 2]
    pv = pts[:, 3:6]               # (n,3) dh/c_gain/l_gain

    out = np.empty((centers.shape[0], 3), dtype=np.float64)
    block = 4096
    ph_pts = ph[None, :]
    for lo in range(0, centers.shape[0], block):
        ctr = centers[lo:lo + block]
        dh_ring = np.radians(ctr[:, 0])[:, None] - ph_pts
        # 环距 (弧度域差值折回 ±π 后取绝对值)
        dh_ring = np.abs((dh_ring + np.pi) % (2.0 * np.pi) - np.pi)
        dc = (ctr[:, 1][:, None] - pc[None, :])
        dl = (ctr[:, 2][:, None] - pl[None, :])
        d2 = dh_ring * dh_ring + dc * dc + dl * dl
        k = min(idw_k, pts.shape[0])
        idx = np.argpartition(d2, k - 1, axis=1)[:, :k]
        dk2 = np.take_along_axis(d2, idx, axis=1)
        vv = pv[idx]                                   # (b,k,3)
        exact = dk2[:, 0] < _EPS_D2
        w = 1.0 / np.maximum(dk2, _EPS_D2) ** (idw_power / 2.0)
        num = (vv * w[..., None]).sum(axis=1)
        den = w.sum(axis=1)
        out[lo:lo + block] = np.where(exact[:, None], vv[:, 0, :],
                                      num / den[:, None])
    return out.reshape(hb, cb, lb, 3)


def load_oklch_deform(path: str | Path,
                      grid: tuple[int, int, int] = (_GRID_H, _GRID_C, _GRID_L)
                      ) -> OklchDeform:
    """点云 JSON → OklchDeform (栅格化按点云内容哈希缓存, 进程内复用)。"""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    if doc.get("schema") != "pixo.hsm_oklch_points.v1":
        raise ValueError(f"点云 schema 不支持: {doc.get('schema')!r} ({path})")
    pts = doc["points"]
    if not pts:
        raise ValueError(f"点云为空: {path}")
    arr = np.asarray([[p["h"], p["c"], p["l"], p["dh"], p["c_gain"],
                       p["l_gain"]] for p in pts], dtype=np.float64)
    key = hashlib.sha1(
        (raw + json.dumps(list(grid))).encode("utf-8")).hexdigest()
    cached = _RASTER_CACHE.get(key)
    if cached is None:
        cached = rasterize_points(arr, grid)
        _RASTER_CACHE[key] = cached
    eps = doc.get("identity_eps") or {}
    return OklchDeform(table=cached,
                       strength=float(doc.get("strength", 1.0)),
                       eps_dh=float(eps.get("dh_deg", 1e-2)),
                       eps_gain=float(eps.get("gain", 1e-2)),
                       source=path.name)


_RASTER_CACHE: dict[str, np.ndarray] = {}


# ---------------------------------------------------------------------------
# 运行时应用
# ---------------------------------------------------------------------------

def _tri_index(pos: np.ndarray, n: int):
    """连续坐标 [0, n-1] → (i0, i1, frac), 钳位 (c/l 轴超界取边界行)。"""
    pos = np.clip(pos, 0.0, float(n - 1))
    i0 = np.floor(pos).astype(np.int64)
    i0 = np.minimum(i0, n - 2)
    frac = pos - i0.astype(np.float64)
    return i0, i0 + 1, frac


def _trilinear(table: np.ndarray, h: np.ndarray, c: np.ndarray, l: np.ndarray
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(Hb,Cb,Lb,3) 表在 OKLCh 坐标上的三线性插值 (h 轴环绕) → (dh,cg,lg)。"""
    hb, cb, lb = table.shape[:3]
    h_pos = (h % 360.0) / 360.0 * hb
    h0 = np.floor(h_pos).astype(np.int64) % hb
    h1 = (h0 + 1) % hb
    fh = h_pos - np.floor(h_pos)
    c0, c1, fc = _tri_index(c, cb)
    l0, l1, fl = _tri_index(l, lb)
    fh, fc, fl = fh[..., None], fc[..., None], fl[..., None]
    c000 = table[h0, c0, l0]; c001 = table[h0, c0, l1]
    c010 = table[h0, c1, l0]; c011 = table[h0, c1, l1]
    c100 = table[h1, c0, l0]; c101 = table[h1, c0, l1]
    c110 = table[h1, c1, l0]; c111 = table[h1, c1, l1]
    top = (c000 * (1 - fc) * (1 - fl) + c001 * (1 - fc) * fl
           + c010 * fc * (1 - fl) + c011 * fc * fl)
    bot = (c100 * (1 - fc) * (1 - fl) + c101 * (1 - fc) * fl
           + c110 * fc * (1 - fl) + c111 * fc * fl)
    interp = top * (1 - fh) + bot * fh
    return interp[..., 0], interp[..., 1], interp[..., 2]


def apply_oklch_deform(rgb01_gamma, spec: OklchDeform,
                       strength: float | None = None) -> np.ndarray:
    """gamma sRGB [0,1] → OKLCh 域连续形变 → gamma sRGB float32。

    strength 缺省用 spec.strength; ≤0 或恒等点云 → 原值直通 (逐位)。
    插值恒等 (|dh|<eps 且 |gain−1|<eps) 的像素绕过 OKLCh 重建原值直通。
    """
    img = np.asarray(rgb01_gamma, dtype=np.float64)
    s = float(spec.strength if strength is None else strength)
    if s <= 0.0 or is_identity_deform(spec):
        return img.astype(np.float32)

    lch = oklab_to_oklch(srgb_to_oklab(img))
    L, C, h = lch[..., 0], lch[..., 1], lch[..., 2]
    dh, cg, lg = _trilinear(spec.table, h, C, L)
    # strength 线性混合到恒等 (语义同 apply_table_to_hsv)
    h2 = (h + s * dh) % 360.0
    c2 = C * (1.0 + s * (cg - 1.0))
    l2 = np.clip(L * (1.0 + s * (lg - 1.0)), 0.0, 1.0)
    c2 = _soft_limit_chroma(c2, C, l2)      # 软限幅仅压增强量
    touched = ((np.abs(dh) >= spec.eps_dh)
               | (np.abs(cg - 1.0) >= spec.eps_gain)
               | (np.abs(lg - 1.0) >= spec.eps_gain))
    if not touched.any():
        return img.astype(np.float32)
    out = oklab_to_srgb(oklch_to_oklab(np.stack([l2, c2, h2], axis=-1)))
    out = np.where(touched[..., None], out, img.astype(np.float32))
    return np.clip(out, 0.0, 1.0).astype(np.float32)
