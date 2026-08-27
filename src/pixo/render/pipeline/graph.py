"""render.pipeline.graph —— Stage 插件框架与 Pipeline (原生实现)。"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Type, Union

import numpy as np

from .context import (  # noqa: F401
    DOMAIN_LINEAR_CAM, DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB,
    StageParams, StageContext, StageResult,
)


class PipelineError(RuntimeError):
    """管线契约违约 (Stage 声明输出域与实际写入不符等)。"""


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
    # 参数 schema: {"<name>": {"type": "float"|"int"|"str"|"bool"|"float_or_str",
    #                          "min": .., "max": .., "choices": [...]}}
    # 各字段均可选; float_or_str 额外放行数值向量 (如 whitebalance 手动 [r,g,b] 系数)。
    # 基类默认为只读代理 (L1): 防止 update/赋值污染类级共享状态;
    # 子类整体重绑定 param_schema = {...} 不受影响。
    param_schema: Mapping[str, dict] = MappingProxyType({})

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
        """取本 Stage 参数: 外部覆盖 > 实例参数 > 默认; 声明 param_schema 时校验。

        仅当本 Stage 声明了该参数的 schema 且取到的值非 None 时执行校验;
        非法抛 ValueError (信息含 stage 名、参数名、值、约束)。
        """
        value = ctx.params_for(self.name).get(key, self.params.get(key, default))
        schema = self.param_schema.get(key)
        if schema and value is not None:
            self._validate_param(key, value, schema)
        return value

    @staticmethod
    def _is_numeric_seq(v) -> bool:
        """是否为非空数值向量/嵌套数值向量 (whitebalance 手动 [r,g,b] 系数、
        warmth_curve [[wb_B,r,g,b],...] 等); 递归接受列表/元组嵌套。"""
        if isinstance(v, (list, tuple)) and len(v) > 0:
            return all(Stage._is_numeric_seq(x)
                       if isinstance(x, (list, tuple))
                       else (isinstance(x, Real) and not isinstance(x, bool))
                       for x in v)
        return False

    def _curve_dict_check(self, v) -> bool:
        """user_curve 类 dict 结构预检: 合法返回 True; 未知键/非点集挂 raise ValueError。

        数值不做深校验 (交给 _apply_user_curve 等); 只查: dict 非空、键合法、
        每个键值为非空 [[x,y],...] 点集 (list/tuple)。
        """
        allowed = {"rgb", "red", "green", "blue", "luminance"}
        if not isinstance(v, dict) or not v:
            return False
        unknown = set(v) - allowed
        if unknown:
            raise ValueError(
                f"[{self.name}] 参数含未知曲线键 {sorted(unknown)}; 合法键: {sorted(allowed)}")
        for k, pts in v.items():
            if not isinstance(pts, (list, tuple)) or len(pts) == 0:
                raise ValueError(
                    f"[{self.name}] 曲线键 '{k}' 需为非空 [[x,y],...] 点集")
        return True

    def _validate_param(self, key: str, value, schema: dict) -> None:
        """按 param_schema 校验单个参数; 非法抛 ValueError (信息含约束)。"""
        typ = schema.get("type")
        numeric = isinstance(value, Real) and not isinstance(value, bool)
        ok = True
        if typ == "float":
            ok = numeric
        elif typ == "int":
            ok = isinstance(value, Integral) and not isinstance(value, bool)
        elif typ == "str":
            ok = isinstance(value, str)
        elif typ == "bool":
            ok = isinstance(value, bool)
        elif typ == "float_or_str":
            # 数值 / 字符串都放行; 另放行数值向量 (手动系数); dict 走曲线结构预检
            # (非法曲线 dict 由 _curve_dict_check 抛 ValueError); range 只对数值生效
            ok = numeric or isinstance(value, str) or self._is_numeric_seq(value)
            # 空容器 (list/tuple/dict) = no-op, 放行
            if not ok and isinstance(value, (list, tuple, dict)) and len(value) == 0:
                ok = True
            if not ok and isinstance(value, dict):
                ok = self._curve_dict_check(value)
        if not ok:
            raise ValueError(
                f"[{self.name}] 参数 '{key}' 非法: 值 {value!r} 类型不符, 期望 {typ}")
        if numeric:
            if "min" in schema and value < schema["min"]:
                raise ValueError(
                    f"[{self.name}] 参数 '{key}' 非法: 值 {value!r} 小于下限 {schema['min']}")
            if "max" in schema and value > schema["max"]:
                raise ValueError(
                    f"[{self.name}] 参数 '{key}' 非法: 值 {value!r} 大于上限 {schema['max']}")
        if "choices" in schema and value not in schema["choices"]:
            raise ValueError(
                f"[{self.name}] 参数 '{key}' 非法: 值 {value!r} 不在允许值 {schema['choices']}")

    def run(self, ctx: StageContext) -> StageResult:
        """统一执行入口 (Pipeline 调用): 校验域 → process → 后验输出域 → 记录。"""
        if self.domain_in and ctx.domain != self.domain_in:
            raise ValueError(
                f"[{self.name}] 域不匹配: 期望输入 {self.domain_in}, 实际 {ctx.domain}")
        result = StageResult(name=self.name, order=self.order,
                             domain_in=self.domain_in, domain_out=self.domain_out)
        ctx.results.append(result)   # 先入链, process 内可写 metrics
        t0 = time.perf_counter()
        writes_before = ctx.image_writes
        self.process(ctx)
        result.time_s = time.perf_counter() - t0
        # domain_out 后验 (深审遗留项): process 实际写入 (set_image) 后,
        # ctx.domain 必须等于声明的 domain_out; 未写 = 恒等直通合法
        # (如 compose 无裁剪/旋转路径不 set_image, "未写即未变")。
        if (self.domain_out is not None
                and ctx.image_writes > writes_before
                and ctx.domain != self.domain_out):
            raise PipelineError(
                f"[{self.name}] 域不匹配: 声明输出 {self.domain_out}, "
                f"实际写入 {ctx.domain}")
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

    def to_config(self) -> Dict[str, Any]:
        """导出当前管线为可重建的配置 dict (pipeline_from_config 的反函数)。

        - name   : 管线名
        - stages : [s.name for s in self.stages] (按执行顺序)
        - params : self.params 深拷贝 (不共享引用, 改导出不影响原管线)
        - output : (getattr output 或 {}) 深拷贝
        JSON 可序列化 (json.dumps 可直接用)。可由 pipeline_from_config 重建。
        """
        import copy
        return {
            "name": self.name,
            "stages": [s.name for s in self.stages],
            "params": copy.deepcopy(self.params),
            "output": copy.deepcopy(getattr(self, "output", {}) or {}),
        }

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
        from pixo.render.core.io import decode_raw

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

__all__ = [
    "DOMAIN_LINEAR_CAM", "DOMAIN_LINEAR_RGB", "DOMAIN_GAMMA_RGB",
    "StageParams", "StageContext", "StageResult", "Stage",
    "PipelineError", "register_stage", "STAGE_REGISTRY", "available_stages",
    "Pipeline",
]
