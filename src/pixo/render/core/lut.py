"""3D LUT 风格映射 (阶段3) —— 复用 engine.lut3d (四面体插值 + .cube 1D shaper + DOMAIN)。

支持:
  - 标准 .cube (LUT_3D_SIZE N, 行序 r 最慢 g 中 b 最快, 0-1)
  - LUT_1D_SIZE 1D shaper (先于 3D LUT 应用) 与 DOMAIN_MIN/DOMAIN_MAX 缩放
  - Hald CLUT (阶段3 扩展: hald n³ 网格 → 3D LUT)
  - LUT 强度混合 (0-1): out = mix(orig, lut(orig), strength)

⚠️ 色彩域 (guanlan 8-10 教训): LUT 定义在 **sRGB gamma 域**查表。
  应用前输入必须是 gamma 编码的 sRGB (0-255 8bit 或 0-1 非线性),
  不能在线性域直套 (否则肤色 RMS 0.094 肉眼可见)。

数学实现统一放在 render.core.lut3d, 本模块仅做兼容再导出 + LUT 库注册。
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path

from .lut3d import LUT3D, hald_to_lut, parse_cube  # noqa: F401

__all__ = ["LUT3D", "hald_to_lut", "parse_cube", "load_lut", "load_lut_path"]


# ── LUT 库注册 (guanlan luts/ 复用; 环境变量 PIXO_RENDER_LUT_DIR 优先, 旧值仅作回退) ──
_LUT_DIR = Path(os.environ.get("PIXO_RENDER_LUT_DIR", str(Path(__file__).resolve().parents[4].parent / "guanlan" / "luts")))

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

# 统一 LUT 缓存（此前 style.py 的 StylizeStage._loaded 与本模块 _cache 两套
# 无锁无上限字典并存，各 ~50MB/表可无限堆积）。单 dict + 锁 + LRU 上限 4 表。
_LUT_CACHE: "OrderedDict[tuple, LUT3D]" = OrderedDict()
_LUT_CACHE_LOCK = threading.Lock()
_LUT_CACHE_MAX = 4


def _lut_cache_get(key: tuple):
    with _LUT_CACHE_LOCK:
        lut = _LUT_CACHE.get(key)
        if lut is not None:
            _LUT_CACHE.move_to_end(key)
        return lut


def _lut_cache_put(key: tuple, lut: LUT3D) -> None:
    with _LUT_CACHE_LOCK:
        _LUT_CACHE[key] = lut
        _LUT_CACHE.move_to_end(key)
        while len(_LUT_CACHE) > _LUT_CACHE_MAX:
            oldest = next(iter(_LUT_CACHE))
            del _LUT_CACHE[oldest]


def load_lut(style_id: str) -> LUT3D:
    """加载注册 LUT (缓存)。仅解析 .cube（快）；不预热 256³ 查表。

    256³ u8 表由 ``apply()`` 惰性构建——现仅测试与金样本生成器走该路径；
    stylize 生产路径走 ``apply_f32``（native float 四面体）不建表，加载期
    建表（~16s/表）已成为纯浪费，t111 移除。
    """
    key = ("id", str(style_id))
    lut = _lut_cache_get(key)
    if lut is not None:
        return lut
    name = _LUT_REGISTRY.get(style_id)
    if not name:
        raise KeyError(f"未注册 LUT: {style_id} (可选: {list(_LUT_REGISTRY)})")
    lut = LUT3D.from_cube(_LUT_DIR / name)
    _lut_cache_put(key, lut)
    return lut


def load_lut_path(path) -> LUT3D:
    """按 .cube 文件路径加载 LUT（与 load_lut 共享同一锁 + LRU 缓存）。

    供 stylize stage 的 lut_path 参数使用；此前 StylizeStage._loaded 把
    路径串喂给 load_lut（注册表查不到必然 KeyError），本入口才是路径语义。
    同 load_lut：仅解析，不预热 u8 表。
    """
    key = ("path", str(path))
    lut = _lut_cache_get(key)
    if lut is not None:
        return lut
    lut = LUT3D.from_cube(Path(path))
    _lut_cache_put(key, lut)
    return lut
