"""render.state.machine 兼容 shim -> pixo.state.machine。"""
from __future__ import annotations

import pixo.state.machine as _impl


def __getattr__(name):
    return getattr(_impl, name)
