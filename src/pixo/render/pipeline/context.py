"""engine.core —— 渲染引擎插件框架 (统一整合层)。

设计目标 (2026-08 重构):
  1. 渲染管线 = 有序 Stage 插件链, 由 Pipeline 统一调度。
  2. 每个 Stage 是纯插件: 只声明 (name, order, 输入/输出色彩域) 并实现 process()。
     注册即接入, 无需改 Pipeline; 顺序/参数/开关全部外部可配。
  3. StageContext 承载: 当前图像 + 色彩域 + 元数据 (RAW/DCP/WB/EV) + 参数 + 探针结果,
     Stage 之间只通过 ctx 交换状态, 不互相 import。
  4. 色彩域显式声明 (domain), Pipeline 自动校验链接合法性, 杜绝"域错位"类 bug
     (旧管线教训: LUT 在 sRGB gamma 域查表却拿到线性域输入)。

色彩域约定:
  linear_cam : 相机原始 RGB, 线性, float32 (白平衡未乘, 曝光可在此域做)
  linear_rgb : 线性 sRGB (D65), float32, 可 >1 (高光余量)
  gamma_rgb  : sRGB gamma 编码, float32 0..1 (display-referred)
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

import numpy as np

# ---- 色彩域 ----
DOMAIN_LINEAR_CAM = "linear_cam"
DOMAIN_LINEAR_RGB = "linear_rgb"
DOMAIN_GAMMA_RGB = "gamma_rgb"


@dataclass
class StageParams:
    """单个 Stage 的可调参数 (外部覆盖用)。"""
    values: Dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key):
        return self.values[key]

    def get(self, key, default=None):
        return self.values.get(key, default)

    def merge(self, overrides: Optional[Dict[str, Any]] = None) -> "StageParams":
        v = dict(self.values)
        if overrides:
            v.update(overrides)
        return StageParams(v)


class StageContext:
    """管线运行上下文: 图像 + 域 + 元数据 + 各 Stage 输出。"""

    # 渲染模式合法值 (M6 显式化): preview = 降采样预览链 (clarity/skin 等
    # 走降采样口径), export = 全质量主线。
    MODE_PREVIEW = "preview"
    MODE_EXPORT = "export"

    def __init__(self, raw_path: Union[str, Path], raw=None, prof=None,
                 config: Optional[Dict[str, Any]] = None,
                 mode: str = MODE_EXPORT):
        self.raw_path = Path(raw_path)
        self.raw = raw            # rawpy.RawPy 对象 (生命周期由 Pipeline 管理)
        self.prof = prof          # DcpProfile | None
        self.config = config or {}
        # 渲染模式 (M6): "preview" / "export"。缺省 export —— 直接构造 ctx
        # 的老调用方语义不变 (clarity/skin 的 config 键回退仍生效)。
        self.mode = mode
        self.image: Optional[np.ndarray] = None
        self.domain: Optional[str] = None
        self.image_writes = 0     # set_image 计数 (Stage.run 的 domain_out 后验)
        self.state: Dict[str, Any] = {}      # Stage 间共享状态 (ev, wb, cct, 矩阵...)
        self.results: List["StageResult"] = []

    def set_image(self, img: np.ndarray, domain: str):
        self.image_writes += 1
        self.image = img
        self.domain = domain

    def params_for(self, stage_name: str) -> StageParams:
        v = self.config.get("stages", {}).get(stage_name)
        if v is None:
            return StageParams()
        return v if isinstance(v, StageParams) else StageParams(v)


@dataclass
class StageResult:
    """单个 Stage 的运行记录 (含耗时与指标, 供探针/验收)。"""
    name: str
    order: int
    time_s: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    domain_in: Optional[str] = None
    domain_out: Optional[str] = None

__all__ = [
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
    "StageParams", "StageContext", "StageResult",
]
