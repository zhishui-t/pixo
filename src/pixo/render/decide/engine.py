"""render.decide.engine 兼容 shim -> pixo.decide.engine。"""
from __future__ import annotations

import pixo.decide.engine as _impl


def __getattr__(name):
    return getattr(_impl, name)
