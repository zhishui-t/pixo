"""render.state.exceptions 兼容 shim -> pixo.state.exceptions。"""
from __future__ import annotations

import pixo.state.exceptions as _impl


def __getattr__(name):
    return getattr(_impl, name)
