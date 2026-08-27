"""pipeline.runner 公共渲染样板测试 (三入口样板合并)。

覆盖:
  - prepare_render_ctx: LINEAR_CAM 起始域 / mode / half_size 派生 / state 注入 / copy_input
  - finalize_gamma_output: gamma 终检 + 8/16bit 量化
  - run_full_pipeline / run_pipeline_float: 注入 pipe 接线 + 返回类型

运行: python -m pytest tests/unit/test_pipeline_runner.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.pipeline.context import (DOMAIN_GAMMA_RGB,
                                          DOMAIN_LINEAR_CAM, StageContext)
from pixo.render.pipeline.runner import (finalize_gamma_output,
                                         prepare_render_ctx,
                                         run_full_pipeline,
                                         run_pipeline_float)


class _FakePipe:
    """假 Pipeline: run 把图写成 0.5 的 gamma 图并记录 ctx。"""

    def __init__(self):
        self.ctx_seen = None

    def run(self, ctx):
        self.ctx_seen = ctx
        ctx.set_image(np.full(ctx.image.shape, 0.5, np.float32),
                      DOMAIN_GAMMA_RGB)


def test_prepare_render_ctx_domain_mode_state():
    pipe = _FakePipe()
    ctx = prepare_render_ctx(pipe, np.zeros((4, 4, 3), np.float32),
                             "x.nef", prof=None,
                             config={"half_size": True, "stages": {}},
                             mode="preview", state_inject={"camera_wb": 1.5})
    assert ctx.domain == DOMAIN_LINEAR_CAM
    assert ctx.mode == "preview"
    assert ctx.state["half_size"] is True          # 由 config["half_size"] 派生
    assert ctx.state["camera_wb"] == 1.5           # state_inject 逐键注入


def test_prepare_render_ctx_no_inject_when_empty():
    pipe = _FakePipe()
    ctx = prepare_render_ctx(pipe, np.zeros((4, 4, 3), np.float32),
                             "x.nef", prof=None,
                             config={"half_size": False})
    assert ctx.mode == "export"                    # 缺省 export
    assert ctx.state == {"half_size": False}       # 空 inject 不引入键


def test_prepare_render_ctx_copy_input():
    pipe = _FakePipe()
    img = np.zeros((4, 4, 3), np.float32)
    ctx = prepare_render_ctx(pipe, img, "x.nef", None,
                             {"half_size": False}, copy_input=True)
    ctx.image[0, 0, 0] = 9.0
    assert img[0, 0, 0] == 0.0                     # 下游写不污染共享输入


def test_finalize_gamma_output_quantize_and_check():
    ctx = StageContext("x.nef")
    ctx.set_image(np.full((4, 4, 3), 0.5, np.float32), DOMAIN_GAMMA_RGB)
    out8 = finalize_gamma_output(ctx, 8)
    assert out8.dtype == np.uint8 and out8[0, 0, 0] == 128   # 0.5*255+0.5
    out16 = finalize_gamma_output(ctx, 16)
    assert out16.dtype == np.uint16 and out16[0, 0, 0] == 32768

    ctx.set_image(ctx.image, DOMAIN_LINEAR_CAM)
    with pytest.raises(RuntimeError, match="最终域"):
        finalize_gamma_output(ctx, 8, label="预览管线")


def test_run_full_pipeline_uses_injected_pipe():
    """pipe 显式注入 (monkeypatch 缝隙语义): 不经 build_default_pipeline。"""
    pipe = _FakePipe()
    out = run_full_pipeline(np.zeros((4, 4, 3), np.float32), None, {},
                            {"half_size": True, "stages": {}},
                            output_bps=8, mode="preview",
                            raw_path="x.nef", pipe=pipe, label="预览管线")
    assert out.dtype == np.uint8
    assert out[0, 0, 0] == 128
    assert pipe.ctx_seen is not None
    assert pipe.ctx_seen.mode == "preview"
    assert pipe.ctx_seen.state["half_size"] is True


def test_run_pipeline_float_returns_gamma_float():
    """float 变体: 不量化, 直接返回 gamma 域 float32 (L9 免 8bit 往返)。"""
    pipe = _FakePipe()
    out = run_pipeline_float(np.zeros((4, 4, 3), np.float32), None, {},
                             {"half_size": False, "stages": {}},
                             raw_path="x.nef", pipe=pipe)
    assert out.dtype == np.float32
    assert float(out[0, 0, 0]) == 0.5
