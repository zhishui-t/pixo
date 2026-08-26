"""engine.decode —— RAW 解码 (采集层, 非 Style 插件)。

原则:
  - output_color=raw 拿纯相机 RGB (不做任何色彩矩阵), 色彩交给 Stage2。
  - use_camera_wb=False, 白平衡系数由 Stage2 自行乘 (AsShot / auto 可控)。
  - AHD demosaic (质量优先); half_size=True 走半分辨率 (闭环诊断/快速预览)。
"""
from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path
from typing import Tuple, Union

import numpy as np
import rawpy

# P1 预览解码结果缓存：key=(raw_path, output_scale, mtime, size)。
# rawpy 首次访问 raw_image_visible / raw_pattern / black_level 等属性会触发
# DNG/RAW 解压（实测 ~1.3s）；同一文件重复预览时直接复用最终 RGB，避免重复解压。
# 磁盘缓存用于跨进程冷启动：首次 CFA 解码后落盘，后续新进程直接加载 half RGB。
# LRU（上限 _LRU_MAX）：原实现满 8 条全清，热点条目被连带逐出导致重复解压。
_DECODE_CACHE: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_DECODE_CACHE_DIR = Path(
    os.environ.get(
        "PIXO_RENDER_DECODE_CACHE_DIR",
        str(Path(__file__).resolve().parents[1] / "bench" / "cache" / "decode")))

_LRU_MAX = 8


def _lru_get(cache: dict, key: tuple):
    """LRU 命中：返回值并刷新 recency；未命中返回 None。

    兼容被 monkeypatch 成普通 dict 的 cache（无 move_to_end 时跳过刷新）。
    """
    value = cache.get(key)
    if value is not None:
        move_to_end = getattr(cache, "move_to_end", None)
        if move_to_end is not None:
            move_to_end(key)
    return value


def _lru_put(cache: dict, key: tuple, value, limit: int = _LRU_MAX) -> None:
    """LRU 写入：插入并刷新 recency，超限淘汰最旧一条（不再全清）。"""
    cache[key] = value
    move_to_end = getattr(cache, "move_to_end", None)
    if move_to_end is not None:
        move_to_end(key)
    while len(cache) > limit:
        oldest = next(iter(cache))
        del cache[oldest]


def _decode_cache_key(raw_path: Union[str, Path],
                      output_scale: float) -> tuple | None:
    try:
        p = Path(raw_path)
        st = p.stat()
        return (str(p), float(output_scale), int(st.st_mtime_ns), st.st_size)
    except Exception:
        return None


def _decode_cache_path(cache_key: tuple | None) -> Path | None:
    if cache_key is None:
        return None
    try:
        _DECODE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(repr(cache_key).encode("utf-8")).hexdigest()
        return _DECODE_CACHE_DIR / f"{h}.npy"
    except Exception:
        return None


def decode_raw(raw_path: Union[str, Path], half_size: bool = False,
               demosaic: str = "AHD") -> Tuple[np.ndarray, rawpy.RawPy]:
    """解码 RAW → 相机原始 RGB 线性图 (float32, 0-1 相对白电平, 高光可 >1)。

    NEF/普通 RAW 仍走 AHD half_size 生产路径; DNG 同款 CFA 路径只由
    decode_stage3_like() 显式供 DNG 验证工具使用, 不混入批量渲染。
    """
    algo = {"AHD": rawpy.DemosaicAlgorithm.AHD,
            "LINEAR": rawpy.DemosaicAlgorithm.LINEAR}.get(demosaic,
                                                          rawpy.DemosaicAlgorithm.AHD)
    raw = rawpy.imread(str(raw_path))
    rgb16 = raw.postprocess(
        use_camera_wb=False,
        output_bps=16,
        output_color=rawpy.ColorSpace.raw,
        no_auto_bright=True,
        half_size=half_size,
        user_wb=[1.0, 1.0, 1.0, 1.0],
        demosaic_algorithm=algo,
    )
    img = rgb16.astype(np.float32) / 65535.0
    return img, raw


def decode_cfa_half(raw: rawpy.RawPy, output_scale: float = 1.0,
                    raw_path: Union[str, Path, None] = None) -> np.ndarray:
    """C++ CFA 2×2 分箱快速解码（P1 预览）。

    输入 rawpy 已 imread 的 RawPy 对象，使用 raw_image_visible / raw_pattern /
    black_level_per_channel / white_level 输出 (H/2, W/2, 3) float32 线性相机 RGB。
    仅走 native；不可用/异常由上层回退 decode_raw(half_size=True)。
    raw_path 非空时启用跨 RawPy 对象的解码结果缓存，避免重复解压。
    """
    from .._native import decode_cfa_half as _native_decode

    cache_key = _decode_cache_key(raw_path, output_scale) if raw_path is not None else None
    if cache_key is not None and _lru_get(_DECODE_CACHE, cache_key) is not None:
        return _DECODE_CACHE[cache_key]
    cache_path = _decode_cache_path(cache_key)
    if cache_path is not None and cache_path.exists():
        try:
            out = np.load(cache_path, allow_pickle=False)
            if cache_key is not None:
                _lru_put(_DECODE_CACHE, cache_key, out)
            return out
        except Exception:
            pass

    cfa = np.array(raw.raw_image_visible, dtype=np.uint16, copy=True)
    pattern = np.asarray(raw.raw_pattern, dtype=np.int32)
    flat = pattern.ravel()
    desc = raw.color_desc
    if isinstance(desc, bytes):
        desc = desc.decode("latin1")
    desc = str(desc).upper()
    # 按 color_desc 把每个 2x2 线性位置映射到 R/G/B；G 可能有两个位置共用同一 color id。
    r_pos = [p for p in range(4) if desc[int(flat[p])] == "R"]
    g_pos = [p for p in range(4) if desc[int(flat[p])] == "G"]
    b_pos = [p for p in range(4) if desc[int(flat[p])] == "B"]
    if len(r_pos) != 1 or len(b_pos) != 1 or len(g_pos) != 2:
        raise ValueError(
            f"raw_pattern/color_desc 无法映射 2x2: desc={desc!r}, pattern={flat.tolist()}")
    pattern_r = int(r_pos[0])
    pattern_b = int(b_pos[0])
    pattern_g0 = int(g_pos[0])
    pattern_g1 = int(g_pos[1])
    black_by_pos = [float(raw.black_level_per_channel[int(flat[p])]) for p in range(4)]
    out = _native_decode(
        cfa,
        pattern_r=pattern_r,
        pattern_g0=pattern_g0,
        pattern_g1=pattern_g1,
        pattern_b=pattern_b,
        black=black_by_pos,
        white_level=float(raw.white_level),
        output_scale=float(output_scale),
    )
    if cache_key is not None:
        _lru_put(_DECODE_CACHE, cache_key, out)
        if cache_path is not None:
            try:
                np.save(cache_path, out, allow_pickle=False)
            except Exception:
                pass
    return out


def _read_opcode_list(raw_path: str) -> dict:
    """读取本机 Nikon DNG 的 OpcodeList2/3 (FixVignetteRadial / WarpRectilinear)。

    返回 {'vignette': (params5, (cx, cy)) | None,
          'warp': (planes, coeffs[plane][4], (cx, cy)) | None}
    """
    import struct
    with open(str(raw_path), "rb") as f:
        b = f.read()
    e = "<"
    out: dict = {}

    def parse_ifd(off):
        if off <= 0 or off + 2 > len(b):
            return
        n = struct.unpack(e + "H", b[off:off + 2])[0]
        for i in range(min(n, 80)):
            base = off + 2 + i * 12
            if base + 12 > len(b):
                break
            tag, typ, cnt, vo = struct.unpack(e + "HHII", b[base:base + 12])
            if tag in (0xC741, 0xC74E):
                raw = b[vo:vo + cnt]
                if len(raw) < 8:
                    continue
                count = struct.unpack(">I", raw[:4])[0]
                j = 4
                for _ in range(count):
                    if j + 12 > len(raw):
                        break
                    opid, ver, flags = struct.unpack(">III", raw[j:j + 12])
                    j += 12
                    if opid == 3 and j + 56 <= len(raw):
                        nb = struct.unpack(">I", raw[j:j + 4])[0]
                        j += 4
                        params = struct.unpack(">5d", raw[j:j + 40]); j += 40
                        cx, cy = struct.unpack(">2d", raw[j:j + 16]); j += 16
                        out.setdefault("vignette", (params, (cx, cy)))
                    elif opid == 1 and j + 8 <= len(raw):
                        nb, planes = struct.unpack(">II", raw[j:j + 8]); j += 8
                        coeffs = []
                        for _ in range(planes):
                            if j + 48 > len(raw):
                                break
                            coeffs.append(struct.unpack(">6d", raw[j:j + 48])); j += 48
                        if j + 16 <= len(raw):
                            cx, cy = struct.unpack(">2d", raw[j:j + 16]); j += 16
                        out.setdefault("warp", (planes, coeffs, (cx, cy)))
                    else:
                        break
            elif tag == 0x014A and cnt:
                for so in struct.unpack(e + "I" * cnt, b[vo:vo + 4 * cnt])[:2]:
                    parse_ifd(so)

    if len(b) >= 8:
        parse_ifd(struct.unpack(e + "I", b[4:8])[0])
    return out


def _apply_vignette(lin: np.ndarray, op) -> np.ndarray:
    """对线性化 CFA mosaic 应用 FixVignetteRadial (OpcodeList2)。"""
    params, (cx, cy) = op
    H, W = lin.shape
    ch = W * cx
    cv = H * cy
    maxr = float(np.hypot(max(abs(cv), abs(cv - H)),
                          max(abs(ch), abs(ch - W))))
    if maxr <= 0:
        return lin
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    r2 = ((xx - ch) ** 2 + (yy - cv) ** 2) / (maxr * maxr)
    gain = (1.0 + params[0] * r2 + params[1] * r2 ** 2 + params[2] * r2 ** 3
            + params[3] * r2 ** 4 + params[4] * r2 ** 5)
    return np.clip(np.rint(lin.astype(np.float64) * gain), 0, 65535).astype(np.uint16)


def _raw_make(raw_path) -> str:
    """读 TIFF IFD0 的 Make 标签 (0x010F) → 相机厂商字符串; 失败返回 ""。

    NEF/DNG 都是 TIFF 基格式; rawpy 不暴露 make, 这里手工解析头部。
    """
    import struct
    try:
        b = open(str(raw_path), "rb").read(64 * 1024)
        if len(b) < 8 or b[:4] not in (b"II\x2a\x00", b"MM\x00\x2a"):
            return ""
        e = "<" if b[:2] == b"II" else ">"
        off = struct.unpack(e + "I", b[4:8])[0]
        if off <= 0 or off + 2 > len(b):
            return ""
        n = struct.unpack(e + "H", b[off:off + 2])[0]
        for i in range(min(n, 128)):
            base = off + 2 + i * 12
            if base + 12 > len(b):
                break
            tag, typ, cnt, vo = struct.unpack(e + "HHII", b[base:base + 12])
            if tag == 0x010F and typ == 2 and cnt > 0:
                if cnt <= 4:  # 内联 ASCII
                    return b[base + 8:base + 8 + cnt].split(b"\x00")[0].decode(
                        "latin1", "ignore")
                return b[vo:vo + cnt].split(b"\x00")[0].decode("latin1", "ignore")
        return ""
    except Exception:
        return ""


def decode_stage3_like(raw_path: Union[str, Path],
                          dng_pair: Union[str, Path, None] = None,
                          white_level: int | None = None,
                          opcodes: dict | None = None) -> Tuple[np.ndarray, rawpy.RawPy]:
    """DNG 预览 Stage3 的 rawpy 侧近似复刻 (不使用 DNG SDK)。

    链路对齐 dng_negative::BuildStage3Image:
      1) raw mosaic 按 BlackLevel/WhiteLevel 线性化 (ttShort, round half-up);
      2) 以 downScale ~ ceil(max(H,W)/1024) 做 dng_fast_interpolator:
         每个 downScale x downScale 单元内, 各 CFA 颜色取整数平均;
      3) 输出 (H3,W3,3) float32 相机 RGB。
    """
    raw = rawpy.imread(str(raw_path))
    is_dng = str(raw_path).lower().endswith(".dng")
    mosaic = raw.raw_image_visible.astype(np.int64)
    colors = raw.raw_colors
    H, W = mosaic.shape
    ds = max(1, int(np.ceil(max(H, W) / 1024.0)))
    # rawpy color_desc 'RGBG': 0->R(0), 1->G(1), 2->B(2), 3->G(1)
    desc = raw.color_desc.decode("latin1") if isinstance(raw.color_desc, bytes) else str(raw.color_desc)
    color_map = []
    for ch in desc[:4]:
        color_map.append({"R": 0, "G": 1, "B": 2}.get(ch, 1))
    black = np.array(raw.black_level_per_channel, dtype=np.int64)
    # NEF -> DNG 转换实测: Adobe DNG 对 Nikon Z5 用 WhiteLevel=15892, 不是
    # rawpy 的 white_level=16383, 也不是 camera_white_level=15311。
    # DNG 文件本身两者相等 (15892), 行为不变。
    # E3 修复: 15892 是 Nikon Z5 的 NEF→DNG 实测值, 仅对 Nikon (Make 含
    # "nikon", 大小写不敏感) 套用; 其它厂商的非 DNG 回退 rawpy 的 white_level。
    if white_level is None:
        if is_dng:
            white_level = int(raw.white_level)
        elif "nikon" in _raw_make(raw_path).lower():
            white_level = 15892
        else:
            white_level = int(raw.white_level)
    white = np.full(4, int(white_level), dtype=np.int64)
    lin = np.zeros_like(mosaic, dtype=np.uint16)
    for c in range(4):
        m = colors == c
        if not np.any(m):
            continue
        num = (mosaic[m] - black[c]) * 65535
        rng = max(int(white[c] - black[c]), 1)
        lin[m] = np.clip((num + rng // 2) // rng, 0, 65535).astype(np.uint16)
    if opcodes is None:
        opcodes = _read_opcode_list(str(dng_pair or raw_path))
    if opcodes.get("vignette") is not None:
        lin = _apply_vignette(lin, opcodes["vignette"])

    H3 = (H + ds // 2) // ds
    W3 = (W + ds // 2) // ds
    # 边缘按 edge_repeat: 横向补到 W3*ds
    pad_w = W3 * ds - W
    if pad_w > 0:
        lin = np.pad(lin, ((0, 0), (0, pad_w)), mode="edge")
        colors_pad = np.pad(colors, ((0, 0), (0, pad_w)), mode="edge")
    else:
        colors_pad = colors
    # 每个输出像素对应 ds x ds 单元; 同色整数平均, G 由两个 CFA 位置合并
    out = np.zeros((H3, W3, 3), dtype=np.int64)
    cnt = np.zeros((H3, W3, 3), dtype=np.int64)
    for c in range(4):
        plane = color_map[c]
        mask = (colors_pad == c).astype(np.int64)
        # 只保留有效输出高度范围
        mask = mask[:H3 * ds, :]
        cells = (lin[:H3 * ds, :].astype(np.int64) * mask)
        cells = cells.reshape(H3, ds, W3, ds)
        n = mask.reshape(H3, ds, W3, ds).sum(axis=(1, 3))
        out[..., plane] += cells.sum(axis=(1, 3))
        cnt[..., plane] += n
    rgb = ((out + (cnt // 2)) // np.maximum(cnt, 1)).astype(np.uint16)
    img = rgb.astype(np.float32) / 65535.0
    if opcodes.get("warp") is not None:
        from .warp import warp_rectilinear
        planes, coeffs, center = opcodes["warp"]
        paspect = float(raw.sizes.pixel_aspect)
        if paspect == 1.0:
            # rawpy 把本机 Z5 的 pixel aspect 四舍五入成 1.0; SDK 实际为
            # 1/1.000825273 (由 DNG DefaultScale 计算得出)。
            paspect = 0.9991754075139148
        img = warp_rectilinear(img, planes, coeffs, center,
                                   pixel_aspect=paspect)
    return img, raw


def camera_neutral_wb(raw: rawpy.RawPy) -> np.ndarray:
    """相机 As Shot 白平衡系数 (R,G,B 乘数, 归一化 G=1)。

    rawpy.camera_whitebalance 与 Nikon MakerNote WhiteBalanceRBCoeff 一致。
    """
    wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
    if wb[1] > 0:
        wb = wb / wb[1]
    return wb.astype(np.float32)


# 相机 WB 缓存：raw.camera_whitebalance 首次访问同样会触发 DNG 解压（~1.3s）。
# 与 _DECODE_CACHE 同款 LRU（满额淘汰最旧一条，不再全清）。
_WB_CACHE: "OrderedDict[tuple, np.ndarray]" = OrderedDict()


def camera_neutral_wb_cached(raw: rawpy.RawPy,
                             raw_path: Union[str, Path, None] = None) -> np.ndarray:
    """返回 As Shot WB；raw_path 非空时使用跨 RawPy 对象缓存。"""
    key = _decode_cache_key(raw_path, 0.0) if raw_path is not None else None
    if key is not None and _lru_get(_WB_CACHE, key) is not None:
        return _WB_CACHE[key]
    wb = camera_neutral_wb(raw)
    if key is not None:
        _lru_put(_WB_CACHE, key, wb)
    return wb

__all__ = ["decode_raw", "decode_cfa_half", "decode_stage3_like",
           "camera_neutral_wb", "camera_neutral_wb_cached"]
