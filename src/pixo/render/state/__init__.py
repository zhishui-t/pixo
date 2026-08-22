"""render.state 兼容 shim -> pixo.state。"""
from __future__ import annotations

import pixo.state as _impl


def __getattr__(name):
    return getattr(_impl, name)
