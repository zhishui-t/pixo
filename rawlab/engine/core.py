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

    def __init__(self, raw_path: Union[str, Path], raw=None, prof=None,
                 config: Optional[Dict[str, Any]] = None):
        self.raw_path = Path(raw_path)
        self.raw = raw            # rawpy.RawPy 对象 (生命周期由 Pipeline 管理)
        self.prof = prof          # DcpProfile | None
        self.config = config or {}
        self.image: Optional[np.ndarray] = None
        self.domain: Optional[str] = None
        self.state: Dict[str, Any] = {}      # Stage 间共享状态 (ev, wb, cct, 矩阵...)
        self.results: List["StageResult"] = []

    def set_image(self, img: np.ndarray, domain: str):
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


class Stage(ABC):
    """渲染 Stage 插件基类。

    子类必须:
      - 定义类属性 name / order / domain_in / domain_out (或由 @register_stage 注入)
      - 实现 process(ctx)
    可选覆盖:
      - wants(ctx) -> bool : 按上下文决定是否执行 (默认 True)
      - default_params() -> dict : 该 Stage 默认参数
    """

    name: str = "stage"
    order: int = 100
    domain_in: Optional[str] = None   # None = 任意域
    domain_out: Optional[str] = None

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        defaults = self.default_params()
        self.params = StageParams({**defaults, **(params or {})})

    def default_params(self) -> Dict[str, Any]:
        return {}

    def wants(self, ctx: StageContext) -> bool:
        return True

    @abstractmethod
    def process(self, ctx: StageContext) -> None:
        """处理 ctx.image (域=domain_in), 结果写回 ctx.set_image(..., domain_out)。"""

    # ---- 便捷工具 ----
    def p(self, ctx: StageContext, key: str, default=None):
        """取本 Stage 参数: 外部覆盖 > 实例参数 > 默认。"""
        return ctx.params_for(self.name).get(key, self.params.get(key, default))

    def run(self, ctx: StageContext) -> StageResult:
        """统一执行入口 (Pipeline 调用): 校验域 → process → 记录。"""
        if self.domain_in and ctx.domain != self.domain_in:
            raise ValueError(
                f"[{self.name}] 域不匹配: 期望输入 {self.domain_in}, 实际 {ctx.domain}")
        result = StageResult(name=self.name, order=self.order,
                             domain_in=self.domain_in, domain_out=self.domain_out)
        ctx.results.append(result)   # 先入链, process 内可写 metrics
        t0 = time.perf_counter()
        self.process(ctx)
        result.time_s = time.perf_counter() - t0
        return result


# ---- Stage 注册表 (插件机制核心) ----
STAGE_REGISTRY: Dict[str, Type[Stage]] = {}


def register_stage(name: str, order: Optional[int] = None,
                   domain_in: Optional[str] = None,
                   domain_out: Optional[str] = None):
    """类装饰器: 把一个 Stage 实现注册进全局插件表。

    用法:
        @register_stage("exposure", order=1,
                        domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_LINEAR_CAM)
        class ExposureStage(Stage): ...
    """
    def deco(cls: Type[Stage]) -> Type[Stage]:
        cls.name = name
        if order is not None:
            cls.order = order
        cls.domain_in = domain_in
        cls.domain_out = domain_out
        STAGE_REGISTRY[name] = cls
        return cls
    return deco


def available_stages() -> Dict[str, Type[Stage]]:
    """已注册插件清单 (按 order 排序)。"""
    return dict(sorted(STAGE_REGISTRY.items(),
                       key=lambda kv: kv[1].order))


# ---- Pipeline (统一整合层) ----
class Pipeline:
    """按声明顺序执行 Stage 插件链。

    构造参数:
      stages : Stage 实例或已注册名字的列表 (None = 按注册 order 全链)
      params : {"<stage_name>": {...}} 外部参数覆盖
      config : 引擎级配置 (half_size 等, 由 run_file 注入)
    """

    def __init__(self, stages: Optional[List[Union[Stage, str]]] = None,
                 params: Optional[Dict[str, Dict[str, Any]]] = None,
                 name: str = "default"):
        self.name = name
        self.params = params or {}
        use_default = stages is None
        self.stages: List[Stage] = [self._resolve(s) for s in stages] if stages is not None \
            else [cls() for cls in available_stages().values()]
        if use_default:
            self.stages.sort(key=lambda s: s.order)

    @staticmethod
    def _resolve(spec: Union[Stage, str]) -> Stage:
        if isinstance(spec, Stage):
            return spec
        if spec in STAGE_REGISTRY:
            return STAGE_REGISTRY[spec]()
        raise KeyError(f"未注册的 Stage: {spec} (可用: {list(STAGE_REGISTRY)})")

    def describe(self) -> List[Dict[str, Any]]:
        return [{"name": s.name, "order": s.order,
                 "domain_in": s.domain_in, "domain_out": s.domain_out,
                 "enabled": True} for s in self.stages]

    def run(self, ctx: StageContext, probe_dir: Optional[Path] = None) -> np.ndarray:
        """执行全链, 返回最终图像。probe_dir 非空时逐 Stage 落盘中间图。"""
        for stage in self.stages:
            if not stage.wants(ctx):
                continue
            stage.run(ctx)
            if probe_dir is not None:
                self._dump_probe(probe_dir, ctx)
        return ctx.image

    @staticmethod
    def _dump_probe(probe_dir: Path, ctx: StageContext):
        import cv2
        probe_dir.mkdir(parents=True, exist_ok=True)
        stage_name = ctx.results[-1].name
        img = ctx.image
        if ctx.domain == DOMAIN_GAMMA_RGB:
            out8 = (np.clip(img, 0, 1) * 255.0 + 0.5).astype(np.uint8)
        else:
            out8 = (np.clip(img / max(float(np.percentile(img, 99.9)), 1e-6), 0, 1)
                    * 255.0 + 0.5).astype(np.uint8)
        cv2.imwrite(str(probe_dir / f"{len(ctx.results):02d}_{stage_name}.jpg"),
                    cv2.cvtColor(out8, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 92])

    # ---- 便捷: 从文件跑完整管线 ----
    def run_file(self, raw_path: Union[str, Path], prof=None, half_size: bool = False,
                 probe_dir: Optional[Path] = None,
                 extra_params: Optional[Dict[str, Dict[str, Any]]] = None) -> np.ndarray:
        """解码 RAW → 跑全链 → 返回 8bit RGB (sRGB)。

        解码放在 Pipeline 层 (非 Stage): 解码是引擎的"采集"环节, 不属于风格化插件。
        prof 缺省时回退到 build_default_pipeline/pipeline_from_config 绑定的 prof。
        """
        from rawlab.engine.decode import decode_raw

        img, raw = decode_raw(raw_path, half_size=half_size)
        config: Dict[str, Any] = {"half_size": half_size}
        if extra_params:
            config["stages"] = {**self.params, **extra_params}
        else:
            config["stages"] = self.params
        ctx = StageContext(raw_path, raw=raw,
                           prof=prof if prof is not None else getattr(self, "prof", None),
                           config=config)
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["half_size"] = half_size
        try:
            self.run(ctx, probe_dir=probe_dir)
            out = ctx.image
        finally:
            try:
                raw.close()
            except Exception:
                pass
        # 终检: 输出必须是 gamma 域 → 8bit sRGB
        if ctx.domain != DOMAIN_GAMMA_RGB:
            raise RuntimeError(
                f"管线最终域不是 {DOMAIN_GAMMA_RGB} 而是 {ctx.domain}: "
                f"缺少 gamma 编码 Stage (tone)?")
        return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
