"""pixo.service.app —— FastAPI 本地服务应用。

实现 docs/PIXO_FRONTEND_DESIGN.md §5.4 的一期 REST API，包装
vision/meta/render/decide/state/trace。不实现 DSH 工具插件（P2）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from .runtime import PixoServiceRuntime

_API_DESCRIPTION = "Pixo 本地服务：照片管理、渲染预览、测量、决策、导出。"

_LOGGER = logging.getLogger(__name__)


def _media_type(fmt: str) -> str:
    """根据输出格式返回 Content-Type。"""
    mapping = {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "webp": "image/webp",
        "png16": "image/png",
        "tiff16": "image/tiff",
        "raw48": "application/octet-stream",
    }
    return mapping.get(fmt.lower(), "application/octet-stream")


def _not_found(message: str) -> HTTPException:
    """构造统一 404。"""
    return HTTPException(status_code=404, detail=message)


def _bad_request(message: str) -> HTTPException:
    """构造统一 400。"""
    return HTTPException(status_code=400, detail=message)


def warm_aesthetic_scorer() -> dict[str, Any]:
    """t67：启动期预热评分器，消除首轮推理冷启（PIXO_SCORER_WARMUP 可关）。"""
    from pixo.vision.aesthetic import warm_default_scorer

    return warm_default_scorer()


@asynccontextmanager
async def scorer_warmup_lifespan(app: FastAPI):
    """启动期预热评分器；预热在线程池执行避免阻塞事件循环。"""
    try:
        info = await run_in_threadpool(warm_aesthetic_scorer)
        _LOGGER.info("[pixo.service] 评分器预热: %s", info)
    except Exception:  # noqa: BLE001 - 预热失败不阻断服务启动
        _LOGGER.exception("[pixo.service] 评分器预热失败(不影响启动)")
    yield


def create_app(runtime: PixoServiceRuntime | None = None) -> FastAPI:
    """创建 FastAPI 应用；可注入自定义 runtime 便于测试。"""
    app = FastAPI(title="pixo-service", description=_API_DESCRIPTION,
                  version="0.1.0", lifespan=scorer_warmup_lifespan)
    rt = runtime or PixoServiceRuntime()
    app.state.runtime = rt

    @app.post("/api/import")
    async def api_import(request: Request) -> dict[str, Any]:
        """扫描目录，返回 RAW 候选清单（目录遍历在线程池执行）。"""
        body = await request.json()
        directory = body.get("directory") if isinstance(body, dict) else None
        if not directory:
            raise _bad_request("缺少 directory 参数")
        try:
            candidates = await run_in_threadpool(rt.scan_directory, directory)
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc
        return {"directory": directory, "candidates": candidates}

    @app.post("/api/photos", status_code=201)
    async def api_create_photo(request: Request) -> dict[str, Any]:
        """确认导入，创建 photo 记录（EXIF 读取 RAW 在线程池执行）。"""
        body = await request.json()
        if not isinstance(body, dict) or not body.get("path"):
            raise _bad_request("缺少 path 参数")
        try:
            photo = await run_in_threadpool(
                rt.create_photo, body["path"], body.get("photo_id")
            )
            return {"photo": rt.photo_dict(photo.photo_id)}
        except (ValueError, KeyError) as exc:
            raise _bad_request(str(exc)) from exc

    @app.get("/api/photos")
    def api_list_photos() -> dict[str, Any]:
        """图库照片列表。"""
        return {"photos": [rt.photo_dict(p.photo_id) for p in rt.list_photos()]}

    @app.get("/api/photos/{photo_id}")
    def api_get_photo(photo_id: str) -> dict[str, Any]:
        """照片详情 + 当前状态。"""
        try:
            return {"photo": rt.photo_dict(photo_id)}
        except KeyError as exc:
            raise _not_found(str(exc)) from exc

    @app.post("/api/photos/{photo_id}/sessions", status_code=201)
    def api_create_session(photo_id: str) -> dict[str, Any]:
        """为照片创建 RawPreviewSession。"""
        try:
            session = rt.create_session(photo_id)
            return {"session": rt.session_dict(session.session_id)}
        except KeyError as exc:
            raise _not_found(str(exc)) from exc
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc

    @app.put("/api/sessions/{session_id}/params")
    async def api_update_params(session_id: str,
                                request: Request) -> dict[str, Any]:
        """局部 patch 参数，深合并并递增 generation（canonical 构建在线程池执行）。"""
        body = await request.json()
        if not isinstance(body, dict):
            raise _bad_request("请求体必须是 JSON 对象")
        patch = {k: v for k, v in body.items() if k != "__source"}
        source = body.get("__source")
        try:
            return await run_in_threadpool(
                rt.update_params, session_id, patch, source=source
            )
        except KeyError as exc:
            raise _not_found(str(exc)) from exc

    @app.get("/api/sessions/{session_id}/canonical")
    def api_canonical(session_id: str) -> dict[str, Any]:
        """返回 canonical_params。"""
        try:
            session = rt.get_session(session_id)
            return {
                "session_id": session_id,
                "generation": session.generation,
                "canonical": session.canonical_params(),
            }
        except KeyError as exc:
            raise _not_found(str(exc)) from exc

    @app.get("/api/sessions/{session_id}/image")
    def api_image(
        session_id: str,
        gen: int | None = Query(default=None),
        long_edge: int = Query(default=1024, ge=16, le=4096),
        fmt: str = Query(default="jpeg"),
        quality: int = Query(default=88, ge=1, le=100),
    ) -> Response:
        """渲染并返回当前 generation 的预览编码图。"""
        try:
            session = rt.get_session(session_id)
        except KeyError as exc:
            raise _not_found(str(exc)) from exc
        if gen is not None and gen != session.generation:
            raise _not_found(
                f"generation 已过期: 请求={gen}, 当前={session.generation}"
            )
        try:
            data = session.encode(long_edge=long_edge, fmt=fmt, quality=quality)
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc
        return Response(content=data, media_type=_media_type(fmt))

    @app.get("/api/sessions/{session_id}/measurements")
    def api_measurements(
        session_id: str,
        gen: int | None = Query(default=None),
    ) -> dict[str, Any]:
        """返回当前会话的 Vision 测量报告。"""
        try:
            session = rt.get_session(session_id)
        except KeyError as exc:
            raise _not_found(str(exc)) from exc
        if gen is not None and gen != session.generation:
            raise _not_found(
                f"generation 已过期: 请求={gen}, 当前={session.generation}"
            )
        return rt.measure_session(session_id)

    @app.post("/api/sessions/{session_id}/exports", status_code=202)
    async def api_submit_export(
        session_id: str,
        request: Request,
    ) -> dict[str, Any]:
        """提交导出任务（canonical_params 全管线构建在线程池执行）。"""
        body = await request.json()
        if not isinstance(body, dict):
            raise _bad_request("请求体必须是 JSON 对象")
        fmt = body.get("fmt", "jpeg")
        quality = body.get("quality")
        output_dir = body.get("output_dir")
        try:
            result = await run_in_threadpool(
                rt.submit_export,
                session_id,
                fmt=str(fmt),
                quality=int(quality) if quality is not None else None,
                output_dir=output_dir,
            )
            return result
        except KeyError as exc:
            raise _not_found(str(exc)) from exc
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc

    @app.get("/api/exports/{task_id}")
    def api_export_status(task_id: str) -> dict[str, Any]:
        """查询导出任务状态。"""
        try:
            return {"task": rt.export_status(task_id)}
        except KeyError as exc:
            raise _not_found(str(exc)) from exc

    @app.get("/api/photos/{photo_id}/timeline")
    def api_timeline(photo_id: str) -> dict[str, Any]:
        """返回照片状态机事件流 + Trace。"""
        try:
            return rt.timeline(photo_id)
        except KeyError as exc:
            raise _not_found(str(exc)) from exc

    @app.post("/api/photos/{photo_id}/decide")
    def api_decide(photo_id: str) -> dict[str, Any]:
        """触发一轮 Decide：渲染 + 测量 + 规则决策，结果缓存到照片。

        整条链路同步阻塞（渲染/测量），sync def 让 FastAPI 自动进线程池。
        """
        try:
            return rt.decide_photo(photo_id)
        except KeyError as exc:
            raise _not_found(str(exc)) from exc

    @app.get("/api/photos/{photo_id}/decide")
    def api_decide_cached(photo_id: str) -> dict[str, Any]:
        """只读返回最近一次 Decide 缓存；无缓存时 404 提示先 POST。

        GET 不触发渲染/测量等副作用，避免缓存击穿与重复计算。
        """
        try:
            photo = rt.get_photo(photo_id)
        except KeyError as exc:
            raise _not_found(str(exc)) from exc
        if not (photo.last_measurement or photo.last_decision):
            raise _not_found(
                f"photo {photo_id} 尚无 Decide 结果缓存，"
                f"请先 POST /api/photos/{photo_id}/decide 触发计算"
            )
        sm = rt.state_machines.get(photo_id)
        return {
            "photo_id": photo_id,
            "state": sm.state if sm is not None else "UNKNOWN",
            "iteration": sm.record.iteration if sm is not None else 0,
            "measurement": photo.last_measurement,
            "decision": photo.last_decision,
            "cached": True,
        }

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        """服务健康检查。"""
        return rt.health()

    return app


__all__ = ["create_app"]
