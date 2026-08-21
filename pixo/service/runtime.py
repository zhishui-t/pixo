"""pixo.service.runtime —— Pixo 本地服务运行时。

持有照片、预览会话、状态机、导出任务与测量/决策入口，供 FastAPI
应用层调用。一期为进程内内存存储，不引入数据库/重型任务框架。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pixo.meta import extract
from pixo.render.decide import decide
from pixo.render.state import PhotoStateMachine
from pixo.render.web.export import ExportManager
from pixo.render.web.session import RawPreviewSession
from pixo.vision import MockSegmenter, VisionMeasure, vision_health

# 支持的相机 RAW 扩展名（一期扫描/导入）。
SUPPORTED_EXTENSIONS = {
    ".nef", ".nrw", ".dng", ".arw", ".cr2", ".cr3", ".orf", ".raf",
    ".rw2", ".pef", ".srw", ".raw", ".erf", ".mrw", ".x3f",
}

# 默认 DCP 路径：优先使用仓库内置 Nikon Z 5 基线。
_DEFAULT_DCP = (
    Path(__file__).resolve().parents[1]
    / "render"
    / "profiles"
    / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
)


def _now_iso() -> str:
    """生成带时区的 ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class PhotoRecord:
    """一张照片的服务端记录。"""

    photo_id: str
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    sessions: list[str] = field(default_factory=list)
    last_measurement: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "photo_id": self.photo_id,
            "path": str(self.path),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "sessions": list(self.sessions),
            "last_measurement": self.last_measurement,
        }


class PixoServiceRuntime:
    """Pixo 本地服务运行时，封装照片/会话/状态/导出/测量/决策。"""

    def __init__(
        self,
        profile: Any | None = None,
        profile_path: str | Path | None = None,
        work_dir: str | Path | None = None,
        session_factory: Callable[[PhotoRecord, str], Any] | None = None,
        export_manager: ExportManager | None = None,
    ) -> None:
        self.profile = profile
        if self.profile is None:
            from pixo.render.core.calibration import load_dcp

            dcp_path = Path(profile_path or _DEFAULT_DCP)
            self.profile = load_dcp(dcp_path)

        self.work_dir = Path(work_dir) if work_dir is not None else None
        self.export_manager = export_manager or ExportManager(
            self.profile, work_dir=self.work_dir
        )
        self.session_factory = session_factory or self._default_session_factory

        self.photos: dict[str, PhotoRecord] = {}
        self.sessions: dict[str, Any] = {}
        self.state_machines: dict[str, PhotoStateMachine] = {}

    # ---- 默认工厂 ----

    def _default_session_factory(
        self,
        photo: PhotoRecord,
        session_id: str,
    ) -> RawPreviewSession:
        """创建真实 RawPreviewSession。"""
        return RawPreviewSession(photo.path, self.profile, session_id=session_id)

    # ---- 导入 / 照片 ----

    def scan_directory(self, directory: str | Path) -> list[dict[str, Any]]:
        """扫描目录，返回 RAW 候选文件清单（不创建记录）。"""
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"目录不存在: {root}")
        candidates: list[dict[str, Any]] = []
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                candidates.append({
                    "path": str(path),
                    "name": path.name,
                    "size": path.stat().st_size,
                })
        return candidates

    def create_photo(
        self,
        raw_path: str | Path,
        photo_id: str | None = None,
    ) -> PhotoRecord:
        """创建照片记录；路径不存在或无法读取时抛 ValueError。"""
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"照片文件不存在: {path}")
        photo_id = photo_id or uuid.uuid4().hex[:12]
        if photo_id in self.photos:
            raise ValueError(f"photo_id 已存在: {photo_id}")

        try:
            metadata = extract(str(path))
        except Exception:  # noqa: BLE001 - 元数据失败不阻断导入
            metadata = {}

        photo = PhotoRecord(photo_id=photo_id, path=path, metadata=metadata)
        self.photos[photo_id] = photo
        self.state_machines[photo_id] = PhotoStateMachine(photo_id)
        return photo

    def get_photo(self, photo_id: str) -> PhotoRecord:
        """获取照片记录；不存在时抛 KeyError。"""
        if photo_id not in self.photos:
            raise KeyError(f"photo 不存在: {photo_id}")
        return self.photos[photo_id]

    def list_photos(self) -> list[PhotoRecord]:
        """按创建时间返回全部照片。"""
        return list(self.photos.values())

    def photo_dict(self, photo_id: str) -> dict[str, Any]:
        """返回含状态信息的照片详情。"""
        photo = self.get_photo(photo_id)
        data = photo.to_dict()
        sm = self.state_machines.get(photo_id)
        if sm is not None:
            data["state"] = sm.state
            data["iteration"] = sm.record.iteration
            data["next_action"] = sm.record.next_action
        return data

    # ---- 会话 ----

    def create_session(
        self,
        photo_id: str,
        session_id: str | None = None,
    ) -> Any:
        """为照片创建预览会话。"""
        photo = self.get_photo(photo_id)
        session_id = session_id or uuid.uuid4().hex[:16]
        if session_id in self.sessions:
            raise ValueError(f"session_id 已存在: {session_id}")
        session = self.session_factory(photo, session_id)
        self.sessions[session_id] = session
        photo.sessions.append(session_id)
        return session

    def get_session(self, session_id: str) -> Any:
        """获取会话；不存在时抛 KeyError。"""
        if session_id not in self.sessions:
            raise KeyError(f"session 不存在: {session_id}")
        return self.sessions[session_id]

    def session_dict(self, session_id: str) -> dict[str, Any]:
        """返回会话基础信息。"""
        session = self.get_session(session_id)
        return {
            "session_id": session.session_id,
            "photo_id": getattr(session, "photo_id", None),
            "generation": session.generation,
            "raw_path": str(session.raw_path),
        }

    def update_params(
        self,
        session_id: str,
        patch: dict[str, Any],
        source: str | None = None,
    ) -> dict[str, Any]:
        """深合并局部参数并递增 generation，同时记录 Trace。"""
        session = self.get_session(session_id)
        generation = session.update_params(dict(patch or {}))
        photo_id = self._photo_id_for_session(session_id)
        sm = self.state_machines.get(photo_id)
        if sm is not None:
            for key, value in (patch or {}).items():
                sm.add_trace(
                    event_type="param_patch",
                    param=str(key),
                    value=value,
                    new_value=value,
                    source=source or "api",
                )
        return {
            "session_id": session_id,
            "generation": generation,
            "params": dict(session.params),
            "canonical": session.canonical_params(),
        }

    def _photo_id_for_session(self, session_id: str) -> str | None:
        """从 session/photo 关联中倒推 photo_id。"""
        session = self.get_session(session_id)
        direct = getattr(session, "photo_id", None)
        if direct:
            return str(direct)
        for photo_id, photo in self.photos.items():
            if session_id in photo.sessions:
                return photo_id
        return None

    # ---- 测量 / 决策 ----

    def measure_session(
        self,
        session_id: str,
        long_edge: int = 1024,
    ) -> dict[str, Any]:
        """对当前会话渲染预览图并执行 Pixo Vision 整图测量。"""
        session = self.get_session(session_id)
        try:
            image = session.render(long_edge=int(long_edge))
        except Exception:  # noqa: BLE001 - 测量不应让 API 因渲染失败而中断
            image = None
        if image is None:
            return {
                "session_id": session_id,
                "generation": session.generation,
                "measurement": None,
                "error": "render_failed",
            }
        seg = MockSegmenter()
        masks = seg.segment(image, ["face", "sky", "plant"])
        measurement = VisionMeasure().measure(
            image,
            masks,
            image_id=getattr(session, "photo_id", None),
            render_version="0.1.0",
            detection_version="mock_v1",
            mask_version="mask_v0.1",
        )
        photo_id = self._photo_id_for_session(session_id)
        if photo_id is not None and photo_id in self.photos:
            self.photos[photo_id].last_measurement = measurement
        return {
            "session_id": session_id,
            "photo_id": photo_id,
            "generation": session.generation,
            "measurement": measurement,
        }

    def decide_photo(self, photo_id: str) -> dict[str, Any]:
        """获取照片当前状态并执行一轮 Decide（无规则时返回空调整）。"""
        photo = self.get_photo(photo_id)
        sm = self.state_machines.get(photo_id)
        session_id = photo.sessions[-1] if photo.sessions else None
        measurement: dict[str, Any] = {}
        params: dict[str, Any] = {}
        if session_id is not None:
            measure_result = self.measure_session(session_id)
            if measure_result.get("measurement") is not None:
                measurement = measure_result["measurement"]
            session = self.get_session(session_id)
            try:
                params = session.canonical_params()
            except Exception:  # noqa: BLE001
                params = dict(getattr(session, "params", {}))

        iteration = sm.record.iteration if sm is not None else 0
        result = decide({
            "metrics": measurement,
            "params": params,
            "iteration": max(1, iteration + 1),
        })
        return {
            "photo_id": photo_id,
            "state": sm.state if sm is not None else "UNKNOWN",
            "iteration": iteration,
            "measurement": measurement,
            "decision": result,
        }

    def timeline(self, photo_id: str) -> dict[str, Any]:
        """返回照片状态机当前状态与 Trace 事件流。"""
        photo = self.get_photo(photo_id)
        sm = self.state_machines.get(photo_id)
        events: list[dict[str, Any]] = []
        if sm is not None:
            events = [e.to_dict() for e in sm.history()]
        return {
            "photo_id": photo_id,
            "state": sm.state if sm is not None else "UNKNOWN",
            "iteration": sm.record.iteration if sm is not None else 0,
            "events": events,
        }

    # ---- 导出 ----

    def submit_export(
        self,
        session_id: str,
        fmt: str,
        quality: int | None = None,
        output_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """提交导出任务。"""
        session = self.get_session(session_id)
        task_id = self.export_manager.submit(
            session,
            fmt=fmt,
            quality=quality,
            output_dir=Path(output_dir) if output_dir is not None else None,
        )
        return {
            "task_id": task_id,
            "status": self.export_manager.status(task_id)["status"],
        }

    def export_status(self, task_id: str) -> dict[str, Any]:
        """查询导出任务状态。"""
        try:
            return self.export_manager.status(task_id)
        except KeyError as exc:
            raise KeyError(f"导出任务不存在: {task_id}") from exc

    # ---- 健康 ----

    def health(self) -> dict[str, Any]:
        """服务健康与依赖/模型状态。"""
        return {
            "status": "ok",
            "service": "pixo-service",
            "version": "0.1.0",
            "vision": vision_health(),
            "photos": len(self.photos),
            "sessions": len(self.sessions),
        }


__all__ = [
    "PixoServiceRuntime",
    "PhotoRecord",
    "SUPPORTED_EXTENSIONS",
]
