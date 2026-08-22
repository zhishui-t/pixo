"""adjustments.highlights_shadows —— 高光/阴影公开接口。

当前实现由 ToneStage 的 six-key/曲线参数承载。
"""
from __future__ import annotations

from ..modules.tone_map import ToneStage

__all__ = ["ToneStage"]
