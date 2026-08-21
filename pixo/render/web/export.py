"""pixo.render 最终全质量 export 层（t32）。

提供任务式导出接口：
- 复用 RawPreviewSession.canonical_params() 得到完整 stage 参数
- 走 full-quality 4s 主线（full-res decode + 完整 12 stage）
- 支持 8-bit JPEG/WebP 与 16-bit PNG-16/TIFF-16/raw48
- 任务状态查询与产物路径
"""
from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .encode import encode_image

_EXT = {
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "webp": ".webp",
    "png16": ".png",
    "tiff16": ".tiff",
    "raw48": ".raw48",
}


def _render_full_quality(raw_path, prof, params: dict, output_bps: int = 8):
    """Full-quality 4s 主线：full-res decode + 完整 12 stage。

    返回 uint8 (output_bps=8) 或 uint16 (output_bps=16)。
    """
    from pixo.render.core.io import camera_neutral_wb_cached, decode_raw
    from pixo.render.pipeline.context import (DOMAIN_GAMMA_RGB, DOMAIN_LINEAR_CAM,
                                         StageContext)
    from pixo.render.pipeline.presets import build_default_pipeline

    if output_bps not in (8, 16):
        raise ValueError("output_bps 只支持 8 或 16")

    img, raw = decode_raw(str(raw_path), half_size=False)
    try:
        pipe = build_default_pipeline(prof=prof, params=params)
        ctx = StageContext(
            raw_path, raw=raw, prof=prof,
            config={"stages": dict(params), "half_size": False, "preview": False})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["half_size"] = False
        try:
            ctx.state["camera_wb"] = camera_neutral_wb_cached(raw, raw_path)
        except Exception:
            pass
        pipe.run(ctx)
        if ctx.domain != DOMAIN_GAMMA_RGB:
            raise RuntimeError(
                f"导出管线最终域不是 {DOMAIN_GAMMA_RGB} 而是 {ctx.domain}")
        out = ctx.image
        if output_bps == 16:
            return (np.clip(out, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
        return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    finally:
        try:
            raw.close()
        except Exception:
            pass


class ExportManager:
    """进程内导出任务管理器（线程池执行 full-quality 渲染）。"""

    def __init__(self, prof, work_dir=None, max_workers: int = 1):
        self.prof = prof
        self.work_dir = Path(work_dir) if work_dir else Path.cwd() / "exports"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="render-export")

    def submit(self, session, fmt: str = "tiff16",
               quality: Optional[int] = None,
               output_dir: Optional[Path] = None) -> str:
        """提交导出任务，返回 task_id。

        session 需提供 raw_path / prof / canonical_params()。
        """
        fmt_l = fmt.lower()
        if fmt_l not in _EXT:
            raise ValueError(f"不支持的导出格式: {fmt}")
        canonical = session.canonical_params()
        task_id = uuid.uuid4().hex
        out_dir = Path(output_dir) if output_dir else self.work_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        task = {
            "task_id": task_id,
            "status": "pending",
            "raw_path": str(session.raw_path),
            "fmt": fmt_l,
            "quality": quality,
            "output_dir": str(out_dir),
            "output_path": None,
            "error": None,
        }
        with self._lock:
            self._tasks[task_id] = task
        self._executor.submit(self._run, task_id, session, fmt_l, quality,
                              out_dir)
        return task_id

    def status(self, task_id: str) -> dict[str, Any]:
        """查询任务状态。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"未知导出任务: {task_id}")
            return dict(task)

    def wait(self, task_id: str, timeout: Optional[float] = None) -> dict[str, Any]:
        """等待任务完成并返回最终状态。"""
        import time
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            st = self.status(task_id)
            if st["status"] in ("completed", "failed"):
                return st
            if deadline is not None and time.monotonic() >= deadline:
                return st
            time.sleep(0.02)

    def shutdown(self):
        self._executor.shutdown(wait=False)

    # ---- 内部 ----
    def _run(self, task_id, session, fmt, quality, out_dir):
        def set_status(**updates):
            with self._lock:
                self._tasks[task_id].update(updates)

        set_status(status="running")
        try:
            if fmt in ("png16", "tiff16", "raw48"):
                render_bps = 16
            else:
                render_bps = 8
            img = _render_full_quality(
                session.raw_path, self.prof, session.canonical_params(),
                output_bps=render_bps)
            data = encode_image(img, fmt, quality=quality)
            path = out_dir / f"{session.session_id}_{task_id}{_EXT[fmt]}"
            path.write_bytes(data)
            if fmt == "raw48":
                sidecar = {
                    "task_id": task_id,
                    "session_id": session.session_id,
                    "raw_path": str(session.raw_path),
                    "profile_path": str(getattr(self.prof, "path", "")
                                       or getattr(self.prof, "source", "") or ""),
                    "width": int(img.shape[1]),
                    "height": int(img.shape[0]),
                    "format": "raw48",
                    "channels": "RGB",
                    "channel_order": "RGB",
                    "endian": "big",
                    "bits_per_channel": 16,
                    "value_range": [0, 65535],
                }
                (path.with_suffix(".json")).write_text(
                    json.dumps(sidecar, ensure_ascii=False, indent=2),
                    encoding="utf-8")
            set_status(status="completed", output_path=str(path))
        except Exception as exc:  # noqa: BLE001 - 任务接口需把异常转为状态
            set_status(status="failed", error=f"{type(exc).__name__}: {exc}")


__all__ = ["ExportManager", "_render_full_quality"]
