"""rawlux.core.io —— RAW 解码 / Stage3 输入 (兼容层, 回指 rawlab.engine.decode)。

迁移目标: 原 engine/decode.py 的 decode_raw / decode_stage3_like 等。
当前阶段保留旧模块, 本文件仅作兼容回指 (rawlab.engine 旧名继续可用)。
公开面已剔除全部 dng_ 符号: dng 名以私有导入绑定, 对外只暴露 clean 名。
旧 dng 名仅在 rawlab.engine 保留兼容。
"""
from __future__ import annotations

# dng 底层以私有名导入, 不进入模块公开命名空间
from rawlab.engine.decode import (  # noqa: F401
    decode_dng_stage3_like as _dng_decode_stage3_like,
    _read_dng_opcode_list as _dng_read_opcode_list,
    _apply_dng_vignette as _dng_apply_vignette,
    decode_raw,
    camera_neutral_wb,
)

# clean 公开别名
decode_stage3_like = _dng_decode_stage3_like
# 私有 helpers (带下划线, 不进公开面)
_read_opcode_list = _dng_read_opcode_list
_apply_vignette = _dng_apply_vignette

__all__ = ["decode_raw", "decode_stage3_like", "camera_neutral_wb"]
