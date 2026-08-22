"""pixo.vision.health —— Pixo Vision 模型健康检查。

vision_health() 返回结构化状态供 DSH Agent / UI 展示。
真实 YOLOE 的信息来自 YoloeSegmenter.health_info()，本模块不直接
import torch/ultralytics（AGPL 隔离由 render/vision/segmenters/yoloe.py
单文件承担）。
"""
from __future__ import annotations

from typing import Any, Callable

from .aesthetic import aesthetic_health_info
from .context import clip_health_info
from .geometry import horizon_health_info
from .person import fairface_health_info

VISION_PACKAGE_VERSION = "0.1.0"
MOCK_SEGMENTER_VERSION = "0.1.0"
YOLOE_SEGMENTER_PROVIDER = "ultralytics"

# 暴露实际 YoloeSegmenter 类供导入/测试替换；适配器缺失时为 None。
try:
    from .segmenters.yoloe import YoloeSegmenter as _OriginalYoloeSegmenter

    _ORIGINAL_YOLOE_SEGMENTER: Any = _OriginalYoloeSegmenter
except Exception:
    _ORIGINAL_YOLOE_SEGMENTER = None

YoloeSegmenter: Any = _ORIGINAL_YOLOE_SEGMENTER


def _get_yoloe_segmenter_class() -> Any | None:
    """返回可用的 YoloeSegmenter 类。

    优先使用外部替换值（测试桩）；否则动态读取 segmenters.yoloe，
    以兼容对原模块类的 monkeypatch。
    """
    if YoloeSegmenter is not None and YoloeSegmenter is not _ORIGINAL_YOLOE_SEGMENTER:
        return YoloeSegmenter
    try:
        from .segmenters.yoloe import YoloeSegmenter as cls

        return cls
    except Exception:
        return _ORIGINAL_YOLOE_SEGMENTER


def get_yoloe_segmenter() -> Any | None:
    """创建并返回一个 YoloeSegmenter 实例，用于读取健康信息。

    构造函数只解析模型路径，不触发真实模型加载；如需验证已加载状态，
    可向 vision_health(yoloe_segmenter=...) 注入实例。
    """
    cls = _get_yoloe_segmenter_class()
    if cls is None:
        return None
    return cls()


def _model_info(
    *,
    name: str,
    type: str,
    provider: str,
    available: bool,
    ready: bool,
    loaded: bool,
    version: str | None,
    detail: str,
    model_path: str | None = None,
) -> dict[str, Any]:
    """构造单个模型的健康信息。"""
    return {
        "name": name,
        "type": type,
        "provider": provider,
        "available": available,
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "loaded": loaded,
        "version": version,
        "detail": detail,
        "model_path": model_path,
    }


def _safe_health(factory: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """调用健康信息工厂；异常时返回 not_ready 占位。"""
    try:
        return dict(factory())
    except Exception as exc:
        return {
            "name": "unknown",
            "type": "real",
            "provider": "unknown",
            "available": False,
            "ready": False,
            "loaded": False,
            "version": None,
            "detail": f"健康信息获取失败：{exc}",
        }


def _normalize_real_info(info: dict[str, Any]) -> dict[str, Any]:
    """把 YoloeSegmenter.health_info() 转换为统一的健康信息结构。"""
    return _model_info(
        name=str(info.get("name", "YOLOE-26L-seg")),
        type=str(info.get("type", "real")),
        provider=str(info.get("provider", YOLOE_SEGMENTER_PROVIDER)),
        available=bool(info.get("available", False)),
        ready=bool(info.get("ready", False)),
        loaded=bool(info.get("loaded", False)),
        version=info.get("version"),
        detail=str(info.get("detail", "YOLOE-26L-seg 状态未知。")),
        model_path=info.get("model_path"),
    )


def _unavailable_real_info(detail: str) -> dict[str, Any]:
    """构造真实模型未就绪的降级信息。"""
    return _model_info(
        name="YOLOE-26L-seg",
        type="real",
        provider=YOLOE_SEGMENTER_PROVIDER,
        available=False,
        ready=False,
        loaded=False,
        version=None,
        detail=detail,
    )


def _yoloe_health_info() -> dict[str, Any]:
    """从 YoloeSegmenter 获取真实模型健康信息；失败时返回 not_ready。"""
    try:
        segmenter = get_yoloe_segmenter()
        if segmenter is None:
            return _unavailable_real_info(
                "YoloeSegmenter 适配器不可用，真实分割模型未就绪。"
            )
        return _normalize_real_info(segmenter.health_info())
    except Exception as exc:
        return _unavailable_real_info(f"获取 YOLOE 健康信息失败：{exc}")


def vision_health(
    yoloe_segmenter: Any | None = None,
) -> dict[str, Any]:
    """返回各模型可用性、版本、加载状态。

    可通过 yoloe_segmenter 参数注入测试/外部已加载实例；缺省按需创建
    YoloeSegmenter 读取健康信息。真实模型未就绪时整体返回 not_ready。
    """
    if yoloe_segmenter is not None:
        try:
            real_info = _normalize_real_info(yoloe_segmenter.health_info())
        except Exception as exc:
            real_info = _unavailable_real_info(
                f"获取 YOLOE 健康信息失败：{exc}"
            )
    else:
        real_info = _yoloe_health_info()

    mock_info = _model_info(
        name="MockSegmenter",
        type="mock",
        provider="numpy",
        available=True,
        ready=True,
        loaded=True,
        version=MOCK_SEGMENTER_VERSION,
        detail="合成 mask，用于测量/闭环测试；不接真实语义模型。",
    )
    aesthetic_info = _safe_health(aesthetic_health_info)
    horizon_info = _safe_health(horizon_health_info)
    fairface_info = _safe_health(fairface_health_info)
    clip_info = _safe_health(clip_health_info)
    overall_ready = bool(real_info.get("ready", False))

    return {
        "status": "ready" if overall_ready else "not_ready",
        "ready": overall_ready,
        "available": overall_ready,
        "version": VISION_PACKAGE_VERSION,
        "segmenter": dict(real_info),
        "models": {
            "mock_segmenter": dict(mock_info),
            "mock": dict(mock_info),
            "yoloe_seg": dict(real_info),
            "yoloe_segmenter": dict(real_info),
            "yoloe": dict(real_info),
            "segmenter": dict(real_info),
            "aesthetic": dict(aesthetic_info),
            "aesthetic_scorer": dict(aesthetic_info),
            "horizon": dict(horizon_info),
            "horizon_detector": dict(horizon_info),
            "fairface": dict(fairface_info),
            "fairface_age": dict(fairface_info),
            "clip": dict(clip_info),
            "clip_context": dict(clip_info),
        },
        "mock_segmenter": dict(mock_info),
        "mock": dict(mock_info),
        "yoloe_segmenter": dict(real_info),
        "yoloe": dict(real_info),
        "aesthetic": dict(aesthetic_info),
        "horizon": dict(horizon_info),
        "fairface": dict(fairface_info),
        "clip": dict(clip_info),
    }


__all__ = [
    "vision_health",
    "get_yoloe_segmenter",
    "VISION_PACKAGE_VERSION",
]
