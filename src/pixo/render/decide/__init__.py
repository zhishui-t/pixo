"""render.decide 兼容 shim -> pixo.decide。"""
from __future__ import annotations

import pixo.decide as _impl


def __getattr__(name):
    return getattr(_impl, name)
