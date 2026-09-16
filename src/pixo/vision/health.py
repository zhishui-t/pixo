"""pixo.vision.health —— Pixo Vision 模型健康检查。

vision_health() 返回结构化状态供 DSH Agent / UI 展示。
真实分割栈信息缺省取 multi_router 聚合（各路由后端 loaded/degraded/
last_error），本模块不直接 import torch 等重依赖（ultralytics 依赖已随
YOLOE 移除清零，t110 AGPL 清偿；torch/transformers 限各 vision 适配器
文件内懒 import）。
"""
from __future__ import annotations

from typing import Any, Callable

from .aesthetic import aesthetic_health_info
from .geometry import horizon_health_info

VISION_PACKAGE_VERSION = "0.1.0"
MOCK_SEGMENTER_VERSION = "0.1.0"

# multi_router 聚合健康用的模块级单例（构造不触发后端实例化/权重加载）。
_MULTI_ROUTER: Any = None


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


def _normalize_segmenter_info(info: dict[str, Any]) -> dict[str, Any]:
    """把注入分割器的 health_info() 转换为统一的健康信息结构。"""
    return _model_info(
        name=str(info.get("name", "segmenter")),
        type=str(info.get("type", "real")),
        provider=str(info.get("provider", "unknown")),
        available=bool(info.get("available", False)),
        ready=bool(info.get("ready", False)),
        loaded=bool(info.get("loaded", False)),
        version=info.get("version"),
        detail=str(info.get("detail", "分割器状态未知。")),
        model_path=info.get("model_path"),
    )


def _multi_router_health_info() -> dict[str, Any]:
    """multi_router 聚合健康：各路由后端 loaded/degraded/last_error。

    复用模块级单例路由（构造只建路由表，不实例化后端/不加载权重，
    对齐 aesthetic.py 单例缓存风格）；异常时返回 error 占位。
    """
    global _MULTI_ROUTER
    try:
        if _MULTI_ROUTER is None:
            from .segmenters.multi_router import MultiModelSegmenter

            _MULTI_ROUTER = MultiModelSegmenter()
        backends = _MULTI_ROUTER.health()
        last_degraded = list(backends.get("last_degraded", []))
        per_backend = {
            k: v for k, v in backends.items() if k != "last_degraded"
        }
        any_loaded = any(
            bool(e.get("loaded")) for e in per_backend.values())
        return {
            "name": "MultiModelSegmenter",
            "type": "real",
            "provider": "multi-router",
            "available": True,  # 聚合条目恒可查；各后端可用性见 backends
            "ready": any_loaded,
            "loaded": any_loaded,
            "version": None,
            "detail": (
                f"prompt 路由聚合（{len(per_backend)} 个后端条目，"
                f"{len(last_degraded)} 个最近降级）"
            ),
            "backends": per_backend,
            "last_degraded": last_degraded,
        }
    except Exception as exc:
        return {
            "name": "MultiModelSegmenter",
            "type": "real",
            "provider": "multi-router",
            "available": False,
            "ready": False,
            "loaded": False,
            "version": None,
            "detail": f"multi_router 健康信息获取失败：{exc}",
        }


def _render_degradation_info() -> dict[str, Any]:
    """render 侧关键路径降级汇总 (R22 F03, L2 暴露层)。

    惰性 import ``pixo.render.degradation`` (该模块仅依赖标准库, 但
    ``pixo.render.core`` 的包初始化会拉 numpy/cv2/rawpy, 故不在本模块顶层
    import —— 与本模块「不直接 import 重依赖」的既有约定一致)。import 失败
    (最小安装/裁剪环境) 时返回空汇总, 不影响 vision 侧任何状态。
    """
    try:
        from ..render.degradation import render_degradation_report

        return dict(render_degradation_report())
    except Exception as exc:
        return {
            "count": 0,
            "entries": [],
            "version_gate_count": 0,
            "version_gate_rejections": [],
            "error": f"render 降级汇总不可用：{exc}",
        }


def vision_health(
    segmenter: Any | None = None,
) -> dict[str, Any]:
    """返回各模型可用性、版本、加载状态。

    可通过 segmenter 参数注入测试/外部已加载的真实分割器实例
    （须提供 health_info()）；缺省以 multi_router 聚合状态作为真实
    分割栈信息。真实模型未就绪时整体返回 not_ready。

    R22 F03 追加 (纯增量, 不改既有 status/ready/available 语义):
      ``render_degraded``（list，含 source/kind/path/reason/detail/
      exception/count/first_seen/last_seen/timestamp）、
      ``render_degraded_count``、``render_status``（"degraded"|"ok"）、
      ``render_version_gate_rejections``（版本门**合法拒绝**独立通道,
      不计入 degraded, 见 render/degradation.py 判定依据）。
    """
    if segmenter is not None:
        try:
            real_info = _normalize_segmenter_info(segmenter.health_info())
        except Exception as exc:
            real_info = _model_info(
                name="segmenter",
                type="real",
                provider="unknown",
                available=False,
                ready=False,
                loaded=False,
                version=None,
                detail=f"获取真实分割器健康信息失败：{exc}",
            )
    else:
        real_info = _multi_router_health_info()

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
    multi_router_info = _safe_health(_multi_router_health_info)
    overall_ready = bool(real_info.get("ready", False))
    render_info = _render_degradation_info()
    render_extra: dict[str, Any] = {
        "render_degraded": list(render_info.get("entries", [])),
        "render_degraded_count": int(render_info.get("count", 0)),
        "render_status": "degraded" if render_info.get("count") else "ok",
        "render_version_gate_rejections": list(
            render_info.get("version_gate_rejections", [])),
        "render_version_gate_count": int(
            render_info.get("version_gate_count", 0)),
    }
    if render_info.get("error"):
        render_extra["render_degraded_error"] = render_info["error"]

    return {
        "status": "ready" if overall_ready else "not_ready",
        "ready": overall_ready,
        "available": overall_ready,
        "version": VISION_PACKAGE_VERSION,
        "segmenter": dict(real_info),
        "models": {
            "mock_segmenter": dict(mock_info),
            "mock": dict(mock_info),
            "segmenter": dict(real_info),
            "multi_router": dict(multi_router_info),
            "aesthetic": dict(aesthetic_info),
            "aesthetic_scorer": dict(aesthetic_info),
            "horizon": dict(horizon_info),
            "horizon_detector": dict(horizon_info),
        },
        "mock_segmenter": dict(mock_info),
        "mock": dict(mock_info),
        "multi_router": dict(multi_router_info),
        "aesthetic": dict(aesthetic_info),
        "horizon": dict(horizon_info),
        **render_extra,
    }


__all__ = [
    "vision_health",
    "VISION_PACKAGE_VERSION",
]
