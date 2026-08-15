"""engine.calibration —— 每机标定数据 (Z5 II Camera Standard)。

数据来源: tools/fit_neutral_trim.py 在拟合集上计算中性轴按亮度分段校正,
写入本目录 z5ii_neutral_trim.json。这是**每机一个**的标定常量,
替换旧管线 WB_CAL=[0.90,1,1] 的全局拟合补丁: 只动低色度区、按亮度分段。

band 中心 (Lab L): [8, 32, 72, 128, 184, 224, 248]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

# 标定文件 (fit_neutral_trim.py 生成)
_CAL_FILE = Path(__file__).resolve().parent / "z5ii_neutral_trim.json"
_cached: Optional[dict] = None


def _load() -> Optional[dict]:
    global _cached
    if _cached is None:
        if _CAL_FILE.exists():
            _cached = json.loads(_CAL_FILE.read_text(encoding="utf-8"))
        else:
            _cached = {}
    return _cached


def camera_neutral_trim(prof) -> Tuple[Optional[list], Optional[list]]:
    """按 DCP 名称查每机中性校正曲线 → (a_curve, b_curve) | (None, None)。"""
    name = getattr(prof, "name", "")
    cal = _load() or {}
    entry = cal.get(name)
    if not entry:
        return None, None
    a = entry.get("neutral_a_curve")
    b = entry.get("neutral_b_curve")
    return (list(a) if a else None, list(b) if b else None)
