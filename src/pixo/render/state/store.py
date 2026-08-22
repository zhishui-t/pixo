"""render.state.store 兼容 shim -> pixo.state.store。"""
from __future__ import annotations

import pixo.state.store as _impl


def __getattr__(name):
    return getattr(_impl, name)
