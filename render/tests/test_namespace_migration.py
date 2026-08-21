"""P1-1 命名空间迁移双入口验证：pixo.render + render shim。"""
from __future__ import annotations

import pixo.meta
import pixo.render
import pixo.vision
import render
import render.meta
import render.pipeline
import render.vision


def test_pixo_render_and_render_shim_importable():
    """pixo.render 与顶层 render 均可导入，且顶层 render 转发版本信息。"""
    assert pixo.render.__name__ == "pixo.render"
    assert render.__name__ == "render"
    assert render.__version__ == pixo.render.__version__


def test_shim_submodules_share_identity():
    """render.* shim 与 pixo.* 实际模块保持同一对象身份。"""
    assert render.pipeline is pixo.render.pipeline
    assert render.vision is pixo.vision
    assert render.meta is pixo.meta


def test_pixo_vision_meta_importable():
    """pixo.vision / pixo.meta 顶层命名空间可导入。"""
    assert pixo.vision.__name__ == "pixo.vision"
    assert pixo.meta.__name__ == "pixo.meta"
