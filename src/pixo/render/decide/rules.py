"""render.decide.rules 兼容 shim -> pixo.decide.rules。"""
from __future__ import annotations

import pixo.decide.rules as _impl


def __getattr__(name):
    return getattr(_impl, name)
