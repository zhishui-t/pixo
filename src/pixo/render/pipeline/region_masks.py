"""render.pipeline.region_masks —— F13 掩码通道的分辨率/语义适配器。

三渲染入口 (web/session 预览线 / web/export 全质量线 / loop 合成后端) 共用，
把 loop 侧分割产出的 region_masks (二值 0/255 uint8, 首轮 preview 分辨率)
适配为消费契约形态:

    ctx.state["region_masks"] = {prompt: float32 HxW 软掩码, 0..1}

契约要点 (消费方 region_adjust order=57, dev-3 F12):
  - 坐标系 = 渲染**最终帧** (post-compose): 掩码来自对已渲染 preview 的分割,
    天然是构图后坐标。compose (order=22) 在消费点之前可能裁剪改画幅, 因此
    适配目标 shape 用 compute_crop_rect 从本渲染参数预测 post-compose 帧,
    而非渲染入口图 shape (入口 shape 适配在裁剪链路会静默错位)。
  - 透传纪律 (stage 缓存稳定性): 输入已是 float32 且 shape 命中时**原对象
    返回** —— session stage 缓存指纹 _ndarray_digest 含 data_ptr, 逐渲染
    新建数组会使指纹永变、缓存永不命中。上游 (loop) 每轮注入同一批数组,
    透传保住跨轮命中; 只有 shape 真变 (如换构图) 才重采样 + 一次全链失效。
  - 插值: 下采样 INTER_AREA (面积平均, 保覆盖比例) / 上采样 INTER_LINEAR;
    两线同函数 → 同语义 (tier 口径差教训: 两线增益比漂移实测 <0.005 EV,
    见 .agent-team/spike/spike_f13_dual_line.py)。
  - 整数输入按 /255 归一 (二值 0/255 → 恰 0/1); float 输入视为已 [0,1],
    仅在需要重采样/转换时 clip。羽化归消费 stage (region_adjust 尺度相对
    高斯羽化), 本层不做 —— 适配即语义中性。
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

import cv2
import numpy as np

_LOGGER = logging.getLogger(__name__)


def _post_compose_shape(shape: tuple[int, int],
                        compose_params: Optional[Mapping[str, Any]],
                        ) -> tuple[int, int]:
    """预测 compose 裁剪后的消费帧 (h, w)。

    与 modules/compose.ComposeStage.process 同源 (compute_crop_rect 纯函数);
    旋转/翻转保尺寸, 只有裁剪矩形影响 shape。compose_params None / 空dict
    → 原样返回 (调用方在管线无 compose stage 时传 None)。
    """
    h, w = shape
    if not compose_params:
        return h, w
    from pixo.render.modules.compose import compute_crop_rect

    cp = compose_params
    x0, y0, cw, ch = compute_crop_rect(
        h, w,
        mode=cp.get("mode", "free"),
        ratio=cp.get("ratio", None),
        center=cp.get("center", [0.5, 0.5]),
        x=float(cp.get("x", 0.0) or 0.0),
        y=float(cp.get("y", 0.0) or 0.0),
        width=float(cp.get("width", 0.0) or 0.0),
        height=float(cp.get("height", 0.0) or 0.0),
    )
    return ch, cw


def adapt_region_masks(
    masks: Mapping[str, Any],
    shape: Optional[tuple[int, int]] = None,
    compose_params: Optional[Mapping[str, Any]] = None,
) -> dict[str, np.ndarray]:
    """region_masks → float32 [0,1] 软掩码 dict, 对齐到渲染消费帧。

    参数:
      masks: prompt → 掩码数组 (uint8 0/255 二值 / float 0..1; HxW 或 HxWx1)。
      shape: 渲染入口图 (h, w); None = 不做尺寸适配 (仅 dtype 归一, loop 侧
        首轮转换用)。
      compose_params: 本渲染的 compose stage 参数 (None/空 = 无裁剪预测)。

    返回: 新 dict; 值在「已 float32 且 shape 命中」时为**原数组对象** (透传,
    见模块 docstring 缓存纪律), 否则为重采样/转换后的新数组。

    单个掩码转换失败: 跳过该掩码并 warn (掩码通道降级不阻断渲染; 缺掩码的
    区域由消费 stage 静默跳过), 其余掩码照常适配。
    """
    target: Optional[tuple[int, int]] = None
    if shape is not None:
        target = _post_compose_shape(tuple(shape), compose_params)

    out: dict[str, np.ndarray] = {}
    for name, mask in dict(masks).items():
        try:
            arr = np.asarray(mask)
        except Exception as exc:  # noqa: BLE001 - 坏掩码降级跳过
            _LOGGER.warning("region_masks[%r] 无法转数组, 跳过: %s: %s",
                            name, type(exc).__name__, exc)
            continue
        if arr.ndim == 3 and arr.shape[2] == 1:
            arr = arr[:, :, 0]
        if target is not None and arr.dtype == np.float32 and \
                arr.ndim == 2 and arr.shape == target:
            out[name] = arr  # 透传: 保 data_ptr 指纹稳定 → 缓存命中
            continue
        try:
            if np.issubdtype(arr.dtype, np.integer):
                arr = arr.astype(np.float32) / 255.0
            else:
                arr = arr.astype(np.float32)
            if arr.ndim != 2 or arr.size == 0:
                raise ValueError(f"掩码需为非空 HxW/HxWx1, 实际 {arr.shape}")
            if target is not None and arr.shape != target:
                th, tw = target
                interp = (cv2.INTER_AREA if arr.shape[0] > th
                          else cv2.INTER_LINEAR)
                arr = cv2.resize(arr, (tw, th), interpolation=interp)
            out[name] = np.clip(arr, 0.0, 1.0)
        except Exception as exc:  # noqa: BLE001 - 坏掩码降级跳过
            _LOGGER.warning("region_masks[%r] 适配失败, 跳过: %s: %s",
                            name, type(exc).__name__, exc)
    return out


def adapt_state_extras(
    extras: Mapping[str, Any],
    entry_shape: tuple[int, int],
    compose_params: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """state_extras dict 的渲染入口适配: region_masks 键适配到消费帧, 其余原样。

    无 region_masks 键时**原 dict 对象返回** (零开销); 有则返回浅拷贝 +
    适配后的 region_masks (归一化框等分辨率无关键不动)。
    """
    if not isinstance(extras, Mapping) or "region_masks" not in extras:
        return dict(extras)
    out = dict(extras)
    masks = out.get("region_masks")
    if isinstance(masks, Mapping) and masks:
        out["region_masks"] = adapt_region_masks(
            masks, entry_shape, compose_params)
    return out


__all__ = ["adapt_region_masks", "adapt_state_extras"]
