"""render —— pixo 命名空间兼容 shim（转发到 pixo.render / pixo.vision / pixo.meta）。

迁移期间的过渡入口：现有 `import render.*` 继续可用，实际实现位于
`pixo.render.*`、`pixo.vision.*`、`pixo.meta.*`。本 shim 只做转发，不复制实现。
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

import pixo.render as _pixo_render


class _AliasLoader(importlib.abc.Loader):
    """把 shim 名称加载为真实 pixo 模块对象（保持模块身份一致）。"""

    def __init__(self, real_name: str):
        self.real_name = real_name
        self._real_spec = None
        self._real_name = None
        self._real_package = None

    def create_module(self, spec):
        module = importlib.import_module(self.real_name)
        # 保存真实 pixo 模块的元数据；import 系统会临时改写为 shim 名，
        # 这里在 exec 阶段恢复，避免 __package__ != __spec__.parent 告警。
        self._real_spec = module.__spec__
        self._real_name = module.__name__
        self._real_package = module.__package__
        return module

    def exec_module(self, module) -> None:
        module.__spec__ = self._real_spec
        module.__name__ = self._real_name
        module.__package__ = self._real_package


class _AliasFinder(importlib.abc.MetaPathFinder):
    """将 render.* 映射到 pixo.render.* / pixo.*；缺失时交给标准 PathFinder。"""

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("render."):
            return None
        rel = fullname[len("render."):]
        for real_name in (f"pixo.render.{rel}", f"pixo.{rel}"):
            try:
                spec = importlib.util.find_spec(real_name)
            except (ImportError, AttributeError, ValueError):
                continue
            if spec is not None:
                return importlib.util.spec_from_loader(
                    fullname, _AliasLoader(real_name))
        return None


if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())

# 保留顶层 render/ 目录路径，使 render/tests 等 shim 侧测试目录仍可被发现。
__path__ = [str(Path(__file__).resolve().parent)]

__version__ = getattr(_pixo_render, "__version__", "0.1.0")
__all__ = list(getattr(_pixo_render, "__all__", []))


def __getattr__(name):
    """顶层 render 属性转发到 pixo.render。"""
    return getattr(_pixo_render, name)
