"""render.state.trace 兼容 shim -> pixo.trace。"""
from __future__ import annotations

import pixo.trace as _impl


def __getattr__(name):
    return getattr(_impl, name)
