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
# 容量治理 (R2 条数 LRU 上限 8 → 字节预算): 条目实测量级差异巨大 (本机实测
# 一次解码 ≈ 70 MiB, 见 _decode_cache_budget_bytes 注释), 按条数上限对不同
# 尺寸档/机型无法表达统一内存意图。改为字节预算: env PIXO_DECODE_CACHE_MB
# (缺省 2048), 条目按数组 nbytes 计, 超预算淘汰最旧直到达标; OrderedDict
# LRU 结构与命中 move_to_end 保持不变。
_DECODE_CACHE: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_DECODE_CACHE_DIR = Path(
    os.environ.get(
        "PIXO_RENDER_DECODE_CACHE_DIR",
        str(Path(__file__).resolve().parents[1] / "bench" / "cache" / "decode")))

# WB 系数缓存条目极小 (3 float), 保持条数 LRU; 解码缓存改字节预算 (见上)。
_LRU_MAX = 8
# 解码缓存字节预算缺省 (MiB)。本机 bench/cache/decode 实测单条解码条目
# (2020, 3032, 3) float32 = 73,495,680 B ≈ 70.1 MiB → 缺省 2048 MiB ≈ 29 条,
# 取代旧 8 条 (~561 MiB) 上限; 亦兼容 quarter 档 (~17 MiB) 等小条目高频复用。
_DECODE_CACHE_MB_DEFAULT = 2048.0


def _decode_cache_budget_bytes() -> int:
    """解码缓存字节预算: env PIXO_DECODE_CACHE_MB (MiB, 缺省 2048)。

    非法值回退缺省; ≤0 视为关闭解码缓存 (每次仍可用磁盘缓存预热)。
    每次 put 时读取 env (解码本身秒级, 一次 getenv 可忽略), 便于测试
    与运行时调参即时生效。
    """
    raw = os.environ.get("PIXO_DECODE_CACHE_MB")
    mb = _DECODE_CACHE_MB_DEFAULT
    if raw is not None:
        try:
            mb = float(raw)
        except ValueError:
            mb = _DECODE_CACHE_MB_DEFAULT
    if mb <= 0.0:
        return 0
    return int(mb * 1024 * 1024)


def _entry_nbytes(value) -> int:
    """条目字节估算: ndarray 用 nbytes, 其余 (monkeypatch 注入等) 记 0。"""
    n = getattr(value, "nbytes", None)
    return int(n) if n else 0


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
    """LRU 写入（条数上限, 供 _WB_CACHE 等): 插入并刷新 recency，超限淘汰最旧。"""
    cache[key] = value
    move_to_end = getattr(cache, "move_to_end", None)
    if move_to_end is not None:
        move_to_end(key)
    while len(cache) > limit:
        oldest = next(iter(cache))
        del cache[oldest]


def _decode_cache_put(cache: dict, key: tuple, value) -> None:
    """解码缓存写入（字节预算 LRU）：插入刷新 recency，超预算淘汰最旧。

    - 预算 ≤0 → 不写缓存（关闭）；
    - 超预算时从最旧端淘汰直到达标；单条即超预算时保留最新一条
      （刚解码即丢会使缓存彻底失效、每次重复解码）；
    - 兼容被 monkeypatch 成普通 dict 的 cache（无 move_to_end 时跳过刷新，
      淘汰按插入序迭代）。
    """
    budget = _decode_cache_budget_bytes()
    if budget <= 0:
        return
    cache[key] = value
    move_to_end = getattr(cache, "move_to_end", None)
    if move_to_end is not None:
        move_to_end(key)
    total = sum(_entry_nbytes(v) for v in cache.values())
    while total > budget and len(cache) > 1:
        oldest = next(iter(cache))
        total -= _entry_nbytes(cache[oldest])
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

    生产解码路径 (preview cfa_half / export 全分辨率)。
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
        # R28: 必须显式钉 gamma=(1,1)。rawpy 缺省 gamma=(2.222, 4.5) 会把
        # 一条 dcraw 曲线烘进"线性"输出 ⇒ export 主线 (_render_full_quality
        # → 本函数) 长期在 gamma 污染域上跑 WB×矩阵→EOTF 双重编码
        # (实测 DSC_5236 half 解码 median 0.064 vs 真线性 0.013-0.014,
        # 与 preview 主线 decode_cfa_half 输出差 ΔE 21-41)。实证:
        # .artifacts/_r28_recipe_generalization.py Q1 + R28 报告。
        gamma=(1.0, 1.0),
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
                _decode_cache_put(_DECODE_CACHE, cache_key, out)
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
        _decode_cache_put(_DECODE_CACHE, cache_key, out)
        if cache_path is not None:
            try:
                np.save(cache_path, out, allow_pickle=False)
            except Exception:
                pass
    return out



# ---------------------------------------------------------------------------
# R30 DNG 复刻线退役: _read_opcode_list / _apply_vignette / _raw_make /
# decode_stage3_like (DNG SDK Stage1/2 近似复刻, 仅供已删除的 DNG 验证线)
# 整体移除 —— 生产链自 OWN PIPELINE 起零触碰, tone_table 数据源亦断供
# (.artifacts/R30_dng_replica_retirement.md)。camera_neutral_wb* 为生产
# 消费 (export/preview 的 camera_wb state 注入) 保留。
# ---------------------------------------------------------------------------
def camera_neutral_wb(raw: rawpy.RawPy) -> np.ndarray:
    """相机 As Shot 白平衡系数 (R,G,B 乘数, 归一化 G=1)。

    rawpy.camera_whitebalance 与 Nikon MakerNote WhiteBalanceRBCoeff 一致。
    """
    wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
    if wb[1] > 0:
        wb = wb / wb[1]
    return wb.astype(np.float32)


# 相机 WB 缓存：raw.camera_whitebalance 首次访问同样会触发 DNG 解压（~1.3s）。
# 条目极小 (3 float), 保持条数 LRU (_lru_put, 满额淘汰最旧一条);
# 解码缓存 (_DECODE_CACHE) 已改字节预算 (_decode_cache_put)。
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

__all__ = ["decode_raw", "decode_cfa_half",
           "camera_neutral_wb", "camera_neutral_wb_cached"]
