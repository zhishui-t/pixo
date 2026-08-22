"""render.decide.rule_engine 兼容 shim -> pixo.decide.rule_engine。"""
from __future__ import annotations

import pixo.decide.rule_engine as _impl


def __getattr__(name):
    return getattr(_impl, name)
