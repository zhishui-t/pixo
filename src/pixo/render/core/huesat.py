"""engine.huesat —— DCP HueSatMap / LookTable 解码与应用 (纯函数, 无 I/O)。

权威依据:
  - DNG 1.4 规范 (Camera Profile 章节, HueSatMap / LookTable)
  - Adobe 参考实现 (dng_render.cpp / dng_color_spec.cpp) 经 RawTherapee
    rtengine/dcp.cc 移植

应用域 (2026-08 域修复, 见 dsh-plan-task-p4/research/hsmap-domain.md):
  Adobe DNG SDK 在**线性 ProPhoto(ROMM RGB, D50)、影调曲线之前**应用
  HueSatMap 与 LookTable, 而非旧实现的 gamma_rgb (sRGB 编码、tone 之后)。
  本模块输入/输出均为**线性 sRGB(D65)** (engine.color 的域转换函数负责
  sRGB ↔ ProPhoto 往返); 阶段内: 线性 sRGB → 线性 ProPhoto → HSV 查表 →
  逆回线性 sRGB。域转换与 HSV 往返全部用 float64 计算 (恒等表 max|Δ| ≤ 1e-6)。

解码约定 (与 RT/Adobe 参考实现一致, 已用本机 DCP 数据实测验证):
  1. 每个表项 = 3 个 float: (hue_shift_deg, sat_scale, val_scale)。
     hue_shift_deg: 色相偏移, 单位**度** (0..360 体系);
     sat_scale/val_scale: **乘数** (1.0 = 不变)。
  2. 表布局: 平面索引 = ((v * hue_divs) + h) * sat_divs + s, s 变化最快,
     v 最慢。即 table 形状 (hue_divs, sat_divs, val_divs, 3)。
  3. dims 来源: ProfileHueSatMapDims (0xC6F9); 旧版联合标签
     ProfileHueSatMapData (0xC726) 的 dims 按 DNG 规范取自
     ProfileLookTableDims (0xC725) —— 本机 DCP 正是这种形态。
  4. 编码 (ProfileHueSatMapEncoding 0xC6FC): 0=线性, 1=sRGB gamma;
     本机 DCP 的 0xC6FC 实为 125 点影调曲线 (历史兼容, 见 dcp.py),
     无有效 encoding → 按线性处理。
  5. 应用: HSV 域三线性插值 (H 轴环绕), 然后
     H += strength * hue_shift_deg (mod 360);
     S *= 1 + strength * (sat_scale - 1);
     V *= 1 + strength * (val_scale - 1)。
     encoding=1 时 V 轴先在 sRGB gamma 域查表 (与参考实现一致)。
  6. RGB↔HSV 用自实现 float64 转换 (cv2 仅支持 float32, 精度不够满足
     恒等表 ≤1e-6 验收), 约定与 cv2 全范围 float 一致: H ∈ [0, 360),
     S/V ∈ [0, 1]。
  7. 表构造工具 make_hue_sat_map: 按 (hue_center, hue_halfwidth, sat_scale)
     列表生成恒等基表 + 指定 hue 带 sat_scale 写入 (三线性平滑边缘), 用于
     T5 品红带拟合固化 (见 dsh-plan-task-p4/research/band-drift.md 方案 b)。
"""
from __future__ import annotations

import numpy as np

from .tone import (
    apply_hue_sat_map as _apply_hue_sat_map_table,
    srgb_decode,
    srgb_encode,
)

# HSV 与 RGB 互转用全范围 float 约定: H ∈ [0, 360), S/V ∈ [0, 1]
_H_MIN = 0.0
_H_MAX = 360.0


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """RGB (float64, ≥0, 可 >1 线性高光) → (H_deg, S, V); H∈[0,360), S∈[0,1], V≥0。

    6 扇区标准公式, float64 计算 (与 cv2 全范围 float 约定一致, 但精度更高)。
    灰/黑 (delta=0) → H=0, S=0。向量化, 支持 (...,3)。
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    delta = mx - mn
    # 除零安全: delta==0 (灰/黑) → S=0, H=0
    with np.errstate(divide="ignore", invalid="ignore"):
        d_inv = np.divide(1.0, delta, out=np.zeros_like(delta), where=delta > 0.0)
        s = np.divide(delta, mx, out=np.zeros_like(delta), where=mx > 0.0)
        seg = np.where(mx == r, (g - b) * d_inv % 6.0,
                       np.where(mx == g, (b - r) * d_inv + 2.0,
                                (r - g) * d_inv + 4.0))
    h = (60.0 * seg) % _H_MAX
    return h, s, mx


def _hsv_to_rgb(h_deg: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """(H_deg, S, V) (float64) → RGB (float64, ≥0; V>1 时分量可 >1)。_rgb_to_hsv 的逆。"""
    h = h_deg % _H_MAX
    sector = h / 60.0
    i = np.floor(sector).astype(np.int64) % 6
    f = sector - np.floor(sector)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                  [v, q, p, p, t, v])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                  [t, v, v, q, p, p])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                  [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def _resolve_dims(prof) -> tuple[int, int, int] | None:
    """HueSatMap dims: 0xC6F9 (hue_sat_dims)。LookTable dims 用 0xC725。"""
    dims = getattr(prof, "hue_sat_dims", None)
    if not dims or len(dims) < 3 or min(dims) < 1:
        return None
    h, s, v = int(dims[0]), int(dims[1]), int(dims[2])
    if h < 2 or s < 2:
        return None
    return h, s, v


def decode_table(data, dims: tuple[int, int, int] | None) -> np.ndarray | None:
    """把 DCP 原始表数据解包为 (H, S, V, 3) float32 表 (hue_shift_deg, sat_scale, val_scale)。

    布局 (与 RT/Adobe 参考一致): 平面索引 = ((v*H)+h)*S+s。
    数据量不足/维度不符返回 None (调用方直通)。
    """
    if data is None or dims is None:
        return None
    h, s, v = dims
    need = h * s * v * 3
    if len(data) < need:
        return None
    flat = np.asarray(data, dtype=np.float32).reshape(-1)[:need]
    # flat[v, h, s, ch] → (V, H, S, 3) → transpose → (H, S, V, 3)
    table = flat.reshape(v, h, s, 3).transpose(1, 2, 0, 3)
    return np.ascontiguousarray(table)


def _srgb_encode_v(v: np.ndarray) -> np.ndarray:
    """sRGB EOTF 编码 (encoding=1 时 V 轴用; 与参考实现 gammatab_srgb1 一致)。"""
    v = np.clip(v, 0.0, None)
    return np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.power(v, 1.0 / 2.4) - 0.055)


def _srgb_decode_v(v_enc: np.ndarray) -> np.ndarray:
    """sRGB EOTF 解码 (encoding=1 时 V 轴查表后从编码域回线性域)。"""
    v_enc = np.clip(v_enc, 0.0, None)
    return np.where(v_enc <= 0.04045, v_enc / 12.92,
                    np.power((v_enc + 0.055) / 1.055, 2.4))


def _smoothstep(x: np.ndarray | float) -> np.ndarray | float:
    """C1 连续平滑阶跃: 0→1 单调 (smoothstep, 端点导数 0), 用于带边缘滚降。"""
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _sat_rolloff(s: float, sat_min: float = 0.05) -> float:
    """S 近中性保护区滚降权重 (low#1 修复): 跨 [0, sat_min] 的完整 smoothstep。

    保护区 [0, sat_min] 内: S=0 → 0 (恒等, 近中性不动), S≥sat_min → 1 (全效);
    幂次 6 把 smoothstep 曲线底部压陡 —— 原式 smoothstep(sj/sat_min) 在
    S=0.03 (带的 60%) 处权重 0.65, 会误伤近中性亮部 (band-drift.md §边界副作用:
    S∈[0.03,0.08] 的近中性高光); 幂 6 后 S=0.03 权重 ≈0.07 (验收: ≈0.1 以下)。
    """
    x = float(np.clip(s / max(sat_min, 1e-9), 0.0, 1.0))
    return float(_smoothstep(x) ** 6.0)


def _identity_table(h_divs: int, s_divs: int, v_divs: int) -> np.ndarray:
    """(H,S,V,3) 恒等表: 每格 (hue_shift=0, sat_scale=1, val_scale=1)。"""
    t = np.zeros((h_divs, s_divs, v_divs, 3), dtype=np.float32)
    t[..., 0] = 0.0
    t[..., 1] = 1.0
    t[..., 2] = 1.0
    return t


def _flatten_dcp(table: np.ndarray) -> list:
    """(H,S,V,3) 表 → DCP 扁平列表: index = ((v*H)+h)*S+s, 每格 3 值交错。"""
    return table.transpose(2, 0, 1, 3).reshape(-1).tolist()


def make_hue_sat_map(points, h_divs: int = 90, s_divs: int = 16, v_divs: int = 16,
                     sat_min: float = 0.05, val_min: float = 0.6,
                     edge_deg: float | None = None) -> list:
    """构造 HueSatMap 表 (T5, 品红带固化; 见 dsh-plan-task-p4/research/band-drift.md 方案 b)。

    points: list[(hue_center, hue_halfwidth, sat_scale[, val_min])]
      hue_center    色相带中心 (度, 0..360)
      hue_halfwidth 色相带半宽 (度); 带内 sat_scale 全效
      sat_scale     该带目标 sat_scale (色度乘数; 1.0=不变, <1 压缩)
      val_min       (可选 4 元组) 该带 V 窗口下限; 缺省用函数参数 val_min
    返回: 长度 h_divs*s_divs*v_divs*3 的 float 列表 (DcpProfile.hue_sat_map 直接可写):
      hue_shift 平面全 0; sat_scale 平面在指定 hue 带写入指定值 (三线性平滑边缘),
      其余区域恒等 (sat_scale=1); val_scale 平面恒 1。points 为空 → 恒等表。

    表坐标语义 (对齐 apply_table_to_hsv / Adobe 参考实现):
      - hue 轴: 0..360 → 0..h_divs (环绕); 带边缘 smoothstep 滚降, 边缘宽
        edge_deg (缺省 = 1 个 hue 格 = 360/h_divs 度);
      - sat 轴: 0..1 → 0..s_divs-1; S<sat_min (缺省 0.05) 的近中性区用跨
        [0, sat_min] 的完整 smoothstep 滚降到恒等 (low#1: 幂 6 压陡底部,
        S=0.03 权重 ≈0.07 < 0.1, 防误伤近中性亮部, 见 _sat_rolloff);
      - val 轴: 0..1 → 0..v_divs-1; V<val_min (缺省 0.6) 的中低光区平滑过渡到恒等
        (V 窗口; encoding=1 时引擎先把线性 V 做 sRGB gamma 编码再查表, 故
        val_min 是"编码后/感知"坐标 —— 与拟合阶段 gamma 域 V≥0.6 口径一致)。
    多个 band 时 sat_scale 乘性合成 (每个带独立缩放)。
    """
    table = _identity_table(h_divs, s_divs, v_divs)
    if not points:
        return _flatten_dcp(table)
    if edge_deg is None:
        edge_deg = 360.0 / h_divs
    v_edge = 1.0 / (v_divs - 1)
    for point in points:
        center, halfwidth, sat_scale = (float(point[0]), float(point[1]),
                                        float(point[2]))
        point_val_min = float(point[3]) if len(point) >= 4 else float(val_min)
        center = center % 360.0
        if halfwidth < 0 or sat_scale <= 0.0:
            continue
        for i in range(h_divs):
            hue_i = i * 360.0 / h_divs
            d = abs((hue_i - center) % 360.0)
            d = min(d, 360.0 - d)                 # 角距离 (环绕安全)
            if d <= halfwidth:
                wh = 1.0
            elif d <= halfwidth + edge_deg:
                wh = 1.0 - float(_smoothstep((d - halfwidth) / edge_deg))
            else:
                wh = 0.0
            if wh <= 0.0:
                continue
            for j in range(s_divs):
                sj = j / (s_divs - 1)
                ws = _sat_rolloff(sj, sat_min)
                for k in range(v_divs):
                    vk = k / (v_divs - 1)
                    wv = float(_smoothstep((vk - (point_val_min - v_edge)) / v_edge))
                    w = wh * ws * wv
                    if w > 1e-9:
                        table[i, j, k, 1] *= (1.0 + (sat_scale - 1.0) * w)
    return _flatten_dcp(table)


def _tri_index(pos: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把连续坐标 pos (值域 [0, n-1]) 拆成 (i0, i1, frac), i1=i0+1 且钳位到 n-1。"""
    pos = np.clip(pos, 0.0, float(n - 1))
    i0 = np.floor(pos).astype(np.int32)
    i0 = np.minimum(i0, n - 2)
    frac = (pos - i0).astype(np.float32)
    return i0, i0 + 1, frac


def apply_table_to_hsv(h_deg: np.ndarray, s: np.ndarray, v: np.ndarray,
                       table: np.ndarray, dims: tuple[int, int, int],
                       encoding: int = 0, strength: float = 1.0
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """对 HSV 图应用 HueSatMap/LookTable 表 (三线性插值, H 轴环绕)。

    返回 (H_deg, S, V), 与输入同形; strength=0 恒等。
    """
    if strength <= 0.0:
        return h_deg, s, v
    h_divs, s_divs, v_divs = dims

    # H 轴: 0..360 → 0..h_divs (环绕); S/V 轴: 0..1 → 0..n-1
    h_pos = (h_deg / _H_MAX) * float(h_divs)
    h0 = np.floor(h_pos).astype(np.int32) % h_divs
    h1 = (h0 + 1) % h_divs
    fh = (h_pos - np.floor(h_pos)).astype(np.float32)

    s0, s1, fs = _tri_index(s * (s_divs - 1), s_divs)
    v_axis = _srgb_encode_v(v) if encoding == 1 else v
    v0, v1, fv = _tri_index(v_axis * (v_divs - 1), v_divs)

    def corner(h_idx, s_idx, v_idx):
        return table[h_idx, s_idx, v_idx]  # (..., 3)

    c000 = corner(h0, s0, v0)
    c001 = corner(h0, s0, v1)
    c010 = corner(h0, s1, v0)
    c011 = corner(h0, s1, v1)
    c100 = corner(h1, s0, v0)
    c101 = corner(h1, s0, v1)
    c110 = corner(h1, s1, v0)
    c111 = corner(h1, s1, v1)

    fh, fs, fv = fh[..., None], fs[..., None], fv[..., None]
    # 三线性: 先 s/v 双线性, 再 h 线性
    top = (c000 * (1 - fs) * (1 - fv) + c001 * (1 - fs) * fv
           + c010 * fs * (1 - fv) + c011 * fs * fv)
    bot = (c100 * (1 - fs) * (1 - fv) + c101 * (1 - fs) * fv
           + c110 * fs * (1 - fv) + c111 * fs * fv)
    interp = top * (1 - fh) + bot * fh  # (..., 3)

    hue_shift = interp[..., 0]
    sat_scale = interp[..., 1]
    val_scale = interp[..., 2]

    h_out = (h_deg + strength * hue_shift) % _H_MAX
    s_out = np.clip(s * (1.0 + strength * (sat_scale - 1.0)), 0.0, 1.0)
    # encoding=1: DNG RefBaselineHueSatMap 语义 —— V 轴先过 4096 项
    # sRGB encode table, 缩放后再过 decode table; 没有"近恒等短路"
    # (旧 1e-5 短路在边界处不连续且偏离 SDK)。encode/decode 表与
    # dng_render.BuildHueSatMapEncodingTable(subSample=false) 逐项一致。
    # encoding=0: 直接线性 V。
    # V 只钳下界: 线性域高光 (>1) 应保留 (查表坐标在 _tri_index 已钳到边界行)。
    if encoding == 1:
        v_encoded_out = np.clip(v_axis * (1.0 + strength * (val_scale - 1.0)),
                                0.0, None)
        v_out = np.clip(srgb_decode(v_encoded_out), 0.0, None)
    else:
        v_out = np.clip(v * (1.0 + strength * (val_scale - 1.0)), 0.0, None)
    # 保持输入精度: float64 输入 (线性域路径) 不降级到 float32 (恒等表 ≤1e-6)
    return (h_out.astype(h_deg.dtype), s_out.astype(s.dtype),
            v_out.astype(v.dtype))


def get_hue_sat_table(prof) -> tuple[np.ndarray | None, tuple[int, int, int] | None, int]:
    """(table, dims, encoding): 取 HueSatMap (0xC6FA 数据)。"""
    dims = _resolve_dims(prof)
    data = getattr(prof, "hue_sat_map", None) or getattr(prof, "hue_sat_map1", None)
    encoding = int(getattr(prof, "hue_sat_encoding", None) or 0)
    return decode_table(data, dims), dims, encoding


def get_look_table(prof) -> tuple[np.ndarray | None, tuple[int, int, int] | None, int]:
    """(table, dims, encoding): 取 LookTable (0xC726 数据 + 0xC725 dims)。"""
    dims = getattr(prof, "look_table_dims", None)
    if not dims or len(dims) < 3:
        return None, None, 0
    dims = (int(dims[0]), int(dims[1]), int(dims[2]))
    data = getattr(prof, "look_table", None)
    encoding = int(getattr(prof, "look_table_encoding", None) or 0)
    return decode_table(data, dims), dims, encoding


def apply_hue_sat_map(rgb_linear: np.ndarray, prof, strength: float = 1.0) -> np.ndarray:
    """线性 sRGB(D65) → 线性 ProPhoto → HSV → HueSatMap → 逆回线性 sRGB。

    无数据/strength=0 直通 (原样返回)。输入为线性域 (float32, 可 >1 高光);
    高光保留 (查表坐标钳到 V 边界行, 输出不截顶)。
    """
    table, dims, encoding = get_hue_sat_table(prof)
    if table is None or strength <= 0.0:
        return rgb_linear
    return _apply_table_linear(rgb_linear, table, dims, encoding, strength)


def apply_hue_sat_map_prophoto(pp: np.ndarray, prof, strength: float = 1.0) -> np.ndarray:
    """对 DNG SDK 同款 Camera→ProPhoto 中间图应用 HueSatMap (真 0xC6FA)。

    走 dng_render.apply_hue_sat_map: float32/4096 表插值, 与
    RefBaselineHueSatMap 同语义, 且 6MP 级输入比 float64 通用 HSV 快约一个量级。
    """
    table, dims, encoding = get_hue_sat_table(prof)
    if table is None or strength <= 0.0:
        return pp
    return _apply_hue_sat_map_table(pp, table, dims, encoding, strength)


def apply_look_table_prophoto(pp: np.ndarray, prof, strength: float = 1.0) -> np.ndarray:
    """对 DNG SDK 同款 Camera→ProPhoto 中间图应用 LookTable (0xC726)。"""
    table, dims, encoding = get_look_table(prof)
    if table is None or strength <= 0.0:
        return pp
    return _apply_hue_sat_map_table(pp, table, dims, encoding, strength)


def apply_look_table(rgb_linear: np.ndarray, prof, strength: float = 1.0) -> np.ndarray:
    """兼容旧路径: 线性 sRGB → 标准 ProPhoto → HSV → LookTable → 逆回线性 sRGB。"""
    table, dims, encoding = get_look_table(prof)
    if table is None or strength <= 0.0:
        return rgb_linear
    return _apply_table_linear(rgb_linear, table, dims, encoding, strength)


def _apply_table_prophoto(pp: np.ndarray, table: np.ndarray,
                          dims: tuple[int, int, int], encoding: int,
                          strength: float, clip_hi: bool = True) -> np.ndarray:
    """在已给定的线性 ProPhoto 数组上做 HSV 三线性查表, 返回 ProPhoto。"""
    x = np.asarray(pp, dtype=np.float64)
    x = np.clip(x, 0.0, 1.0 if clip_hi else None)
    h, s, v = _rgb_to_hsv(x)
    h2, s2, v2 = apply_table_to_hsv(h, s, v, table, dims, encoding, strength)
    out = _hsv_to_rgb(h2, s2, v2)
    return np.clip(out, 0.0, 1.0 if clip_hi else None).astype(np.float32)


def _apply_table_linear(rgb_linear: np.ndarray, table: np.ndarray,
                        dims: tuple[int, int, int], encoding: int,
                        strength: float) -> np.ndarray:
    """兼容旧路径: 线性 sRGB → 标准 ProPhoto → 查表 → 逆回线性 sRGB。"""
    from .color import (linear_prophoto_to_linear_srgb,
                                     linear_srgb_to_linear_prophoto)

    x = np.asarray(rgb_linear, dtype=np.float32)
    pp = linear_srgb_to_linear_prophoto(x)
    out_pp = _apply_table_prophoto(pp, table, dims, encoding, strength,
                                    clip_hi=False)
    out = linear_prophoto_to_linear_srgb(out_pp.astype(np.float64))
    return np.clip(out, 0.0, None).astype(np.float32)


# ---------------------------------------------------------------------------
# 局部暖色高光饱和 (A1/B5: 烟花/霓虹/暖灯, 不写死全局 DCP)
# ---------------------------------------------------------------------------

def _smoothstep01(x: np.ndarray) -> np.ndarray:
    """smoothstep 别名 (保持模块内部命名一致)。"""
    return _smoothstep(x)


def apply_local_warm_sat(rgb_linear: np.ndarray, sat_scale: float = 1.0,
                         spot_sat_scale: float | None = None,
                         hue_center: float = 22.5, hue_halfwidth: float = 17.5,
                         sat_min: float = 0.05, val_min: float = 0.6,
                         coverage_max: float = 0.0015,
                         contrast_sigma_frac: float = 0.006,
                         contrast_thr: float = 0.03,
                         contrast_soft: float = 0.08,
                         coverage: float | None = None) -> np.ndarray:
    """对线性 sRGB 中的**局部暖色高光**做饱和度增强 (线性 ProPhoto HSV 域)。

    动机 (问题清单 A1/B5):
      烟花/暖灯橙黄在 LR 中更饱和 (0479/5607/5603 暖色带 S 差 73-78);
      但把暖色带写进全局 DCP HueSatMap 会破坏 5236 高光锚点。
      本函数用空间局部性代替全局 HSM 带:
        - 暖色高光像素占比极低 (≤ coverage_max, 实测 5607/5603 ≈ 0.05%,
          5236 ≈ 0.02% 但高色度目标为 0) → 全部增强;
        - 占比高 (烟花 0479 ≈ 6%, 室内暖场 0376 ≈ 31%) → 只增强与局部背景
          有明显 V 反差的小光斑/火点, 不整片加饱和, 锚点安全。
      sat_scale = 1.0 恒等; >1 增强 (低覆盖暖点实测 3.3 ≈ C 中位对齐 LR)。
      spot_sat_scale 为高覆盖场景的局部反差火点单独给增益 (实测 2.2,
      缺省 = sat_scale)。

    域与数值:
      与 DCP HueSatMap 同域执行 (线性 ProPhoto, tone 前, float64);
      V 窗口按 sRGB-encoded 感知 V 判断 (val_min 缺省 0.6), 与拟合口径一致。
      S 轴近中性保护区 (S<sat_min) 快速滚降, 不碰中性高光。
    """
    broad_scale = float(sat_scale)
    spot_scale = float(spot_sat_scale) if spot_sat_scale is not None else broad_scale
    if broad_scale <= 1.0 and spot_scale <= 1.0:
        return rgb_linear

    input_dtype = np.asarray(rgb_linear).dtype
    target_dtype = np.float32 if input_dtype != np.float64 else np.float64

    # C++ 完整内核优先（broad + spot）；coverage 覆盖参数是 Python 调试口，
    # C ABI 未透传该字段，因此提供 coverage 时走 Python 参考实现。
    try:
        from .._native import (available as _native_available,
                               PixoRenderWarmSatParams,
                               apply_local_warm_sat_native)
        if _native_available() and coverage is None:
            _native_params = PixoRenderWarmSatParams(
                satScale=broad_scale,
                spotSatScale=spot_scale,
                hueCenter=float(hue_center),
                hueHalfwidth=float(hue_halfwidth),
                satMin=float(sat_min),
                valMin=float(val_min),
                coverageMax=float(coverage_max),
                contrastSigmaFrac=float(contrast_sigma_frac),
                contrastThr=float(contrast_thr),
                contrastSoft=float(contrast_soft),
            )
            _native_out, _native_handled = apply_local_warm_sat_native(
                rgb_linear, _native_params)
            if _native_handled:
                return _native_out
    except Exception:
        pass

    from .color import (linear_prophoto_to_linear_srgb,
                                     linear_srgb_to_linear_prophoto)

    x = np.asarray(rgb_linear, dtype=target_dtype)
    pp = linear_srgb_to_linear_prophoto(x)
    pp = np.clip(pp, 0.0, None)
    try:
        from .._native import available as _native_available
        from .._native import rgb_to_hsv, hsv_to_rgb
        from .._native import rgb_to_hsv_f32, hsv_to_rgb_f32
        _use_native = _native_available()
    except Exception:
        _use_native = False
    if _use_native and pp.dtype == np.float32:
        h, s, v = rgb_to_hsv_f32(pp)
    elif _use_native and pp.dtype == np.float64:
        h, s, v = rgb_to_hsv(pp)
    else:
        h, s, v = _rgb_to_hsv(pp)
    v_enc = _srgb_encode_v(v)

    # 色相带: [center-half, center+half] 内全效, 边缘 smoothstep 滚降
    lo, hi = float(hue_center - hue_halfwidth), float(hue_center + hue_halfwidth)
    edge_deg = max(float(hue_halfwidth) * 0.25, 1.0)
    hue_w = (_smoothstep01(np.clip((h - lo) / edge_deg, 0.0, 1.0))
             * _smoothstep01(np.clip((hi - h) / edge_deg, 0.0, 1.0)))
    # S 轴近中性保护 (与 make_hue_sat_map 同款幂次滚降)
    sat_w = _smoothstep01(np.clip(s / max(float(sat_min), 1e-9), 0.0, 1.0)) ** 6.0
    # V 窗口: encoded V 在 val_min 附近平滑过渡 (窗口软边 0.05)
    val_w = _smoothstep01(np.clip((v_enc - (float(val_min) - 0.05)) / 0.08,
                                  0.0, 1.0))
    base_w = (hue_w * sat_w * val_w).astype(target_dtype)

    # 硬掩码只用于覆盖率决策 (与拟合探针口径一致: H∈[5,40], S≥0.05, encV≥0.6)
    hard = ((h >= lo) & (h <= hi) & (s >= float(sat_min))
            & (v_enc >= float(val_min)))
    if coverage is None:
        coverage = float(hard.mean())
    if coverage <= float(coverage_max):
        w = base_w
        scale = broad_scale
    else:
        scale = spot_scale
        # 局部反差门: 只增强相对局部背景明显更亮的暖色高光 (火点/烟花),
        # 大面积暖色区 (暖光室内、日落天空) 保持不动。
        import cv2
        min_dim = max(min(pp.shape[:2]), 1)
        sigma = max(3.0, min_dim * float(contrast_sigma_frac))
        v_blur = cv2.GaussianBlur(v_enc, (0, 0), sigma)
        detail = v_enc - v_blur
        spot_w = _smoothstep01(
            np.clip((detail - float(contrast_thr)) / max(float(contrast_soft), 1e-6),
                    0.0, 1.0))
        w = base_w * spot_w

    s2 = np.clip(s * (1.0 + (scale - 1.0) * w), 0.0, 1.0)
    if _use_native and pp.dtype == np.float32:
        out_pp = hsv_to_rgb_f32(h, s2, v)
    elif _use_native and pp.dtype == np.float64:
        out_pp = hsv_to_rgb(h, s2, v)
    else:
        out_pp = _hsv_to_rgb(h, s2, v)
    out = linear_prophoto_to_linear_srgb(out_pp)
    return np.clip(out, 0.0, None).astype(target_dtype)

__all__ = ["apply_hue_sat_map", "apply_look_table", "apply_hue_sat_map_prophoto", "apply_look_table_prophoto", "make_hue_sat_map", "get_hue_sat_table", "get_look_table"]
