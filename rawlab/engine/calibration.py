"""engine.calibration —— 每机标定数据 (Z5 II Camera Standard)。

数据来源: tools/fit_camera_look.py 在拟合集上计算中性轴按亮度分段校正,
写入本目录 z5ii_neutral_trim.json。这是**每机一个**的标定常量,
替换旧管线 WB_CAL=[0.90,1,1] 的全局拟合补丁: 只动低色度区、按亮度分段。

band 中心 (Lab L): [8, 32, 72, 128, 184, 224, 248]

格式 (Phase 2 起支持按 CCT 分段):
  旧格式 (静态曲线):
    {"<dcp_name>": {"neutral_a_curve": [...], "neutral_b_curve": [...]}}
  新格式 (按 CCT 分段, fit_camera_look.py 生成):
    {
      "default": {"neutral_a_curve": [...], "neutral_b_curve": [...]},   # 全集中位
      "by_cct": [[cct_center, {"neutral_a_curve": [...], "neutral_b_curve": [...]}], ...]
    }
  camera_look_curves(prof, cct) 按 cct 在 by_cct 桶间线性插值 (桶外钳位);
  旧格式 (无 by_cct) 兼容返回静态曲线。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

# 标定文件 (fit_camera_look.py 生成)
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


def _curve_or_none(entry, key: str) -> Optional[list]:
    """从曲线条目取某键的曲线列表; 缺失/空 → None。"""
    if not isinstance(entry, dict):
        return None
    v = entry.get(key)
    return list(v) if v else None


def _lerp_curve(c1, c2, t: float) -> Optional[list]:
    """两条曲线逐点线性插值; 一侧缺失时回退另一侧 (7 点, 长度不一致取公共前缀)。"""
    if c1 is None and c2 is None:
        return None
    if c1 is None:
        return [float(v) for v in c2]
    if c2 is None:
        return [float(v) for v in c1]
    a = np.asarray(c1, dtype=np.float64)
    b = np.asarray(c2, dtype=np.float64)
    if a.shape != b.shape:
        n = min(a.size, b.size)
        a, b = a[:n], b[:n]
    return [float(v) for v in (a * (1.0 - t) + b * t)]


def _interp_cct(by_cct: Sequence, cct: float) -> Tuple[Optional[list], Optional[list]]:
    """by_cct 桶 → (a_curve, b_curve): 按 cct 在桶间线性插值, 桶外钳位。

    by_cct: [[cct_center, {"neutral_a_curve": [...], "neutral_b_curve": [...]}], ...]
    桶无需预排序 (内部按 cct_center 升序); 空/全 None 桶 → (None, None)。
    """
    rows: List[Tuple[float, Optional[list], Optional[list]]] = []
    for item in by_cct:
        try:
            center = float(item[0])
            entry = item[1] if isinstance(item[1], dict) else {}
        except (TypeError, IndexError, ValueError):
            continue
        a = _curve_or_none(entry, "neutral_a_curve")
        b = _curve_or_none(entry, "neutral_b_curve")
        if a is None and b is None:
            continue
        rows.append((center, a, b))
    if not rows:
        return None, None
    rows.sort(key=lambda r: r[0])
    centers = [r[0] for r in rows]
    a_curves = [r[1] for r in rows]
    b_curves = [r[2] for r in rows]

    if len(rows) == 1:
        return a_curves[0], b_curves[0]

    # 桶间区间 + 比例; 桶外钳位到端点
    if cct <= centers[0]:
        i, t = 0, 0.0
    elif cct >= centers[-1]:
        i, t = len(rows) - 2, 1.0
    else:
        i = int(np.searchsorted(centers, cct)) - 1
        i = max(0, min(i, len(rows) - 2))
        span = centers[i + 1] - centers[i]
        t = (cct - centers[i]) / span if span > 0 else 0.0

    return (_lerp_curve(a_curves[i], a_curves[i + 1], t),
            _lerp_curve(b_curves[i], b_curves[i + 1], t))


def camera_look_curves(prof, cct: float = 6500.0) -> Tuple[Optional[list], Optional[list]]:
    """按 CCT 取相机观感校正曲线 → (a_curve, b_curve)。

    新格式 (有 by_cct): 按 cct 在桶间线性插值 (桶外钳位)。
    旧格式 (无 by_cct): 按 prof.name 取静态曲线; 退 default; 均无 → (None, None)。
    """
    if cct is None:
        cct = 6500.0
    else:
        cct = float(cct)
    name = getattr(prof, "name", "")
    cal = _load() or {}

    by_cct = cal.get("by_cct")
    if by_cct:
        a, b = _interp_cct(by_cct, cct)
        if a is not None or b is not None:
            return a, b
        # by_cct 存在但空/全 None → 退回 default 静态曲线

    entry = cal.get(name) if isinstance(cal.get(name), dict) else None
    if entry is None:
        entry = cal.get("default") if isinstance(cal.get("default"), dict) else None
    if not entry:
        return None, None
    return (_curve_or_none(entry, "neutral_a_curve"),
            _curve_or_none(entry, "neutral_b_curve"))


def camera_neutral_trim(prof) -> Tuple[Optional[list], Optional[list]]:
    """返回每机静态中性校正曲线 (default) → (a_curve, b_curve) | (None, None)。

    内部改为返回 default 曲线 (新格式 {"default": ...}), 即全集中位静态曲线;
    兼容旧格式 {"<dcp_name>": {...}} (按 name 查)。按 CCT 分段请用 camera_look_curves。
    """
    name = getattr(prof, "name", "")
    cal = _load() or {}
    entry = cal.get("default") if isinstance(cal.get("default"), dict) else None
    if entry is None:
        entry = cal.get(name) if isinstance(cal.get(name), dict) else None
    if not entry:
        return None, None
    a = entry.get("neutral_a_curve")
    b = entry.get("neutral_b_curve")
    return (list(a) if a else None, list(b) if b else None)
