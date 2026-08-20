"""3D LUT 风格映射 (阶段3) —— 复用 engine.lut3d (四面体插值 + .cube 1D shaper + DOMAIN)。

支持:
  - 标准 .cube (LUT_3D_SIZE N, 行序 r 最慢 g 中 b 最快, 0-1)
  - LUT_1D_SIZE 1D shaper (先于 3D LUT 应用) 与 DOMAIN_MIN/DOMAIN_MAX 缩放
  - Hald CLUT (阶段3 扩展: hald n³ 网格 → 3D LUT)
  - LUT 强度混合 (0-1): out = mix(orig, lut(orig), strength)

⚠️ 色彩域 (guanlan 8-10 教训): LUT 定义在 **sRGB gamma 域**查表。
  应用前输入必须是 gamma 编码的 sRGB (0-255 8bit 或 0-1 非线性),
  不能在线性域直套 (否则肤色 RMS 0.094 肉眼可见)。

数学实现统一放在 rawlab.engine.lut3d, 本模块仅做兼容再导出 + LUT 库注册。
"""
from __future__ import annotations

import os
from pathlib import Path

from rawlab.engine.lut3d import LUT3D, hald_to_lut, parse_cube  # noqa: F401

__all__ = ["LUT3D", "hald_to_lut", "parse_cube", "load_lut"]


# ── LUT 库注册 (guanlan luts/ 复用; 环境变量 RAWLAB_LUT_DIR 优先, 旧值仅作回退) ──
_LUT_DIR = Path(os.environ.get("RAWLAB_LUT_DIR", r"K:\work\project\guanlan\luts"))

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
    lut._build_table()  # 预热查表 (一次性, 分块)
    _cache[style_id] = lut
    return lut
