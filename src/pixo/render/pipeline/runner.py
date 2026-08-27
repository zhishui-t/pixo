"""render.pipeline.runner —— 渲染执行公共样板 (三渲染入口收敛)。

session._render_with_params / web.export._render_full_quality /
api.Renderer.render_preview_full 三处重复的
"build pipeline → StageContext → set_image(LINEAR_CAM) → state 注入 →
run → gamma 终检 → 量化" 样板收敛到此。

调用方差异保留在各入口:
  - decode 来源 (session tier 缓存 / export decode_raw / api cfa_half+缩放);
  - config 键 (preview/long_edge/decode_mode 的取值各入口不同);
  - session 的 stage 缓存循环 (用 prepare_render_ctx + finalize_gamma_output
    两个原语, 循环本身留在 session);
  - pipe 可由调用方显式传入 (tests monkeypatch 各自模块的
    build_default_pipeline 绑定, 保留缝隙)。

行为约定: 与各入口原内联实现逐位一致 (同一操作顺序与数值路径),
金样本 gate (render_bench) 锁定。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

import numpy as np

from .context import DOMAIN_GAMMA_RGB, DOMAIN_LINEAR_CAM, StageContext
from .graph import Pipeline


def prepare_render_ctx(pipe: Pipeline, img: np.ndarray,
                       raw_path: Union[str, Path], prof, config: dict,
                       mode: str = "export", *, raw=None,
                       state_inject: Optional[Dict[str, Any]] = None,
                       copy_input: bool = False) -> StageContext:
    """样板前半: StageContext 构建 + LINEAR_CAM 起始图 + state 注入。

    - ctx.state["half_size"] 由 config["half_size"] 派生 (三入口现状一致);
    - state_inject: 逐键注入 ctx.state (camera_wb / face_boxes 等),
      条件与取值由调用方决定, None/空 dict 不注入;
    - copy_input: 输入图来自共享缓存 (session tier) 时拷贝一份,
      防下游原地写污染缓存。
    """
    ctx = StageContext(raw_path, raw=raw, prof=prof, config=config, mode=mode)
    ctx.set_image(img.copy() if copy_input else img, DOMAIN_LINEAR_CAM)
    ctx.state["half_size"] = bool(config.get("half_size", False))
    if state_inject:
        for key, value in state_inject.items():
            ctx.state[key] = value
    return ctx


def finalize_gamma_output(ctx: StageContext, output_bps: int,
                          label: str = "管线") -> np.ndarray:
    """样板后半: gamma 终检 + 量化 (8→uint8 / 16→uint16)。"""
    if ctx.domain != DOMAIN_GAMMA_RGB:
        raise RuntimeError(
            f"{label}最终域不是 {DOMAIN_GAMMA_RGB} 而是 {ctx.domain}")
    if output_bps == 16:
        return (np.clip(ctx.image, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
    return (np.clip(ctx.image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _resolve_pipe(pipe: Optional[Pipeline], prof, params) -> Pipeline:
    if pipe is not None:
        return pipe
    from .presets import build_default_pipeline
    return build_default_pipeline(prof=prof, params=params)


def run_full_pipeline(img: np.ndarray, prof, params: dict, config: dict,
                      output_bps: int = 8, mode: str = "export", *,
                      raw_path: Union[str, Path], raw=None,
                      state_inject: Optional[Dict[str, Any]] = None,
                      pipe: Optional[Pipeline] = None,
                      copy_input: bool = False,
                      label: str = "管线") -> np.ndarray:
    """完整执行: 构链 (或用传入 pipe) → 注入 → run → gamma 终检 → 量化。

    pipe 缺省由 build_default_pipeline(prof, params) 构建; 需保留
    monkeypatch 缝隙的调用方可显式传入自建 pipe (此时 prof/params 仅
    进 ctx/config, 不再用于构链)。
    """
    pipe = _resolve_pipe(pipe, prof, params)
    ctx = prepare_render_ctx(pipe, img, raw_path, prof, config, mode,
                             raw=raw, state_inject=state_inject,
                             copy_input=copy_input)
    pipe.run(ctx)
    return finalize_gamma_output(ctx, output_bps, label=label)


def run_pipeline_float(img: np.ndarray, prof, params: dict, config: dict,
                       mode: str = "export", *,
                       raw_path: Union[str, Path], raw=None,
                       state_inject: Optional[Dict[str, Any]] = None,
                       pipe: Optional[Pipeline] = None,
                       copy_input: bool = False) -> np.ndarray:
    """完整执行但返回 gamma 域 float (不量化)。

    供需要浮点/线性后处理的调用方 (Renderer.render 调整路径) 免除
    8bit 量化往返损失 (L9): 量化发生在 finalize, 本函数直接给
    ctx.image (gamma float32)。
    """
    pipe = _resolve_pipe(pipe, prof, params)
    ctx = prepare_render_ctx(pipe, img, raw_path, prof, config, mode,
                             raw=raw, state_inject=state_inject,
                             copy_input=copy_input)
    pipe.run(ctx)
    if ctx.domain != DOMAIN_GAMMA_RGB:
        raise RuntimeError(
            f"管线最终域不是 {DOMAIN_GAMMA_RGB} 而是 {ctx.domain}")
    return ctx.image


__all__ = ["prepare_render_ctx", "finalize_gamma_output",
           "run_full_pipeline", "run_pipeline_float"]
