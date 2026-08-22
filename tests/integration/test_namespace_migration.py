"""P1-1 命名空间迁移双入口验证：pixo.render + render shim。"""
from __future__ import annotations

import pixo.meta
import pixo.render
import pixo.vision
import pixo.render
import pixo.meta
import pixo.render.pipeline
import pixo.vision


def test_pixo_render_importable():
    """pixo.render 可作为主包导入，版本信息一致。"""
    assert pixo.render.__name__ == "pixo.render"
    assert pixo.render.__version__ is not None


def test_submodules_share_identity():
    """pixo.* 子模块可导入且保持同一对象身份。"""
    assert pixo.render.pipeline is pixo.render.pipeline
    assert pixo.vision is pixo.vision
    assert pixo.meta is pixo.meta


def test_pixo_vision_meta_importable():
    """pixo.vision / pixo.meta 顶层命名空间可导入。"""
    assert pixo.vision.__name__ == "pixo.vision"
    assert pixo.meta.__name__ == "pixo.meta"
