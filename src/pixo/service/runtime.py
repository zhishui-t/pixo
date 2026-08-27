"""pixo.service.runtime —— Pixo 本地服务运行时。

持有照片、预览会话、状态机、导出任务与测量/决策入口，供 FastAPI
应用层调用。一期为进程内内存存储，不引入数据库/重型任务框架。
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pixo.meta import extract
from pixo.decide import decide
from pixo.state import PhotoStateMachine
from pixo.render.web.export import ExportManager
from pixo.render.web.session import RawPreviewSession
from pixo.vision import MockSegmenter, VisionMeasure, vision_health

_LOGGER = logging.getLogger(__name__)

# 支持的相机 RAW 扩展名（一期扫描/导入）。
SUPPORTED_EXTENSIONS = {
    ".nef", ".nrw", ".dng", ".arw", ".cr2", ".cr3", ".orf", ".raf",
    ".rw2", ".pef", ".srw", ".raw", ".erf", ".mrw", ".x3f",
}

# 默认 DCP 路径：优先使用仓库内置 Nikon Z 5 基线。
_DEFAULT_DCP = (
    Path(__file__).resolve().parents[3]
    / "resources"
    / "dcp"
    / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
)

# 会话 LRU 上限缺省值（env PIXO_MAX_SESSIONS 可调）。
_DEFAULT_MAX_SESSIONS = 8

# 分割器类型 → 测量标记 detection_version（mock 时响应里明确可见）。
_DETECTION_VERSIONS = {
    "mock": "mock_v1",
    "multi": "multi_v1",
}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """读 env 整型配置；缺失/非法时回退缺省值。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        _LOGGER.warning("env %s=%r 非法，回退缺省 %d", name, raw, default)
        return default


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
    last_decision: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "photo_id": self.photo_id,
            "path": str(self.path),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "sessions": list(self.sessions),
            "last_measurement": self.last_measurement,
            "last_decision": self.last_decision,
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
        # OrderedDict 维护 LRU 访问序：命中 move_to_end，逐出 popitem(last=False)。
        self.sessions: OrderedDict[str, Any] = OrderedDict()
        self.state_machines: dict[str, PhotoStateMachine] = {}
        # 会话 LRU 治理：上限 + session→photo 索引（避免线性反查）。
        self.max_sessions = _env_int("PIXO_MAX_SESSIONS", _DEFAULT_MAX_SESSIONS)
        self._session_photo: dict[str, str] = {}
        # FastAPI 线程池化路由下的 photos/sessions 并发变更锁。
        self._lock = threading.Lock()

        # 测量分割器：env PIXO_SEGMENTER（mock|multi），缺省 mock
        # 保持现行为（避免意外下载/加载真实模型）。
        self._segmenter_requested = (
            os.environ.get("PIXO_SEGMENTER", "mock").strip().lower() or "mock"
        )
        self.segmenter_type = self._segmenter_requested
        self._segmenter = self._build_segmenter(self._segmenter_requested)

    # ---- 默认工厂 ----

    def _build_segmenter(self, requested: str) -> Any:
        """按类型构造分割器；multi 懒 import，不可用回退 mock 并告警。"""
        if requested == "mock":
            return MockSegmenter()
        try:
            if requested == "multi":
                from pixo.vision.segmenters.multi_router import (
                    MultiModelSegmenter,
                )

                seg = MultiModelSegmenter()
            else:
                raise ValueError(
                    f"未知 PIXO_SEGMENTER: {requested!r}（可选 mock|multi）"
                )
            self.segmenter_type = requested
            return seg
        except ImportError as exc:  # 仅捕获依赖缺失回退 mock，真实构造错误上抛
            self.segmenter_type = "mock"
            _LOGGER.warning(
                "PIXO_SEGMENTER=%s 构造失败(%s)，回退 MockSegmenter 假测量",
                requested, exc,
            )
            return MockSegmenter()

    def _default_session_factory(
        self,
        photo: PhotoRecord,
        session_id: str,
    ) -> RawPreviewSession:
        """创建真实 RawPreviewSession。"""
        return RawPreviewSession(photo.path, self.profile, session_id=session_id)

    # ---- 导入 / 照片 ----

    def _data_roots(self) -> list[Path]:
        """解析 PIXO_DATA_ROOT 白名单根目录（pathsep 分隔）。

        未显式配置时返回 [] 表示不限制（保持默认开发/测试行为）；
        显式配置后严格生效，拒绝白名单外的任意目录枚举。
        """
        raw = os.environ.get("PIXO_DATA_ROOT", "").strip()
        if not raw:
            return []
        return [
            Path(part).expanduser().resolve()
            for part in raw.split(os.pathsep) if part.strip()
        ]

    def _ensure_scannable(self, root: Path) -> None:
        """目录枚举白名单校验：显式配置 PIXO_DATA_ROOT 时拒绝白名单外路径。"""
        allowed = self._data_roots()
        if not allowed:                       # 未显式配置：不限制
            return
        for base in allowed:
            if root == base or base in root.parents:
                return
        raise ValueError(
            f"目录 {root} 不在 PIXO_DATA_ROOT 白名单内 "
            f"（允许: {[str(a) for a in allowed]}），拒绝枚举任意路径"
        )

    def scan_directory(self, directory: str | Path) -> list[dict[str, Any]]:
        """扫描白名单内目录，返回 RAW 候选文件清单（不创建记录）。"""
        root = Path(directory).expanduser().resolve()
        self._ensure_scannable(root)
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
        # 与 scan_directory 同一套白名单：配置 PIXO_DATA_ROOT 后拒绝
        # 白名单外路径（未配置时不限制），避免枚举面收窄、读取面全开。
        self._ensure_scannable(path)
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
        with self._lock:
            if session_id in self.sessions:
                raise ValueError(f"session_id 已存在: {session_id}")
        session = self.session_factory(photo, session_id)
        evicted: list[tuple[str, Any]] = []
        with self._lock:
            self.sessions[session_id] = session
            self._session_photo[session_id] = photo_id
            photo.sessions.append(session_id)
            # 会话 LRU 治理（t107）：超上限逐出访问序最旧会话，同步清理
            # session→photo 索引与 photo.sessions，避免残留死 id 导致
            # decide_photo 取 sessions[-1] 后 get_session KeyError。
            while len(self.sessions) > self.max_sessions:
                old_id, old = self.sessions.popitem(last=False)
                old_photo_id = self._session_photo.pop(old_id, None)
                old_photo = (
                    self.photos.get(old_photo_id) if old_photo_id else None
                )
                if old_photo is not None and old_id in old_photo.sessions:
                    old_photo.sessions.remove(old_id)
                evicted.append((old_id, old))
        # 被逐出会话防御式 close()：释放 RawPreviewSession 的多级缓存与
        # 线程池，避免服务形态内存无界增长；放锁外避免持锁做 IO。
        for old_id, old in evicted:
            close = getattr(old, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - 关闭失败不阻断创建
                    _LOGGER.warning(
                        "[pixo.runtime] 会话 close 失败: %s", old_id)
        return session

    def get_session(self, session_id: str) -> Any:
        """获取会话并 LRU touch；不存在时抛 KeyError。"""
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError(f"session 不存在: {session_id}")
            self.sessions.move_to_end(session_id)
            return session

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
        """反查 photo_id：优先 session→photo 索引（O(1)），miss 再兜底扫描。"""
        photo_id = self._session_photo.get(session_id)
        if photo_id:
            return photo_id
        direct = getattr(self.sessions.get(session_id), "photo_id", None)
        if direct:
            return str(direct)
        for pid, photo in self.photos.items():
            if session_id in photo.sessions:
                return pid
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
        photo_id = self._photo_id_for_session(session_id)
        # 使用注入的分割器（env PIXO_SEGMENTER 构造），detection_version
        # 随实际生效的分割器类型标记，避免装饰性接线。
        masks = self._segmenter.segment(image, ["face", "sky", "plant"])
        measurement = VisionMeasure().measure(
            image,
            masks,
            image_id=photo_id,
            render_version="0.1.0",
            detection_version=_DETECTION_VERSIONS.get(
                self.segmenter_type, "mock_v1"
            ),
            mask_version="mask_v0.1",
        )
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
        # 记录最近一次决策，供照片详情/后续规则读取（字段此前从不写入）。
        photo.last_decision = result
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
            "segmenter": {
                # t91：报告当前实际生效的分割器路由（构造失败回退后为 mock）。
                "router": self.segmenter_type,
                "part_prompts": ["hair", "skin", "clothes", "body"],
            },
            "photos": len(self.photos),
            "sessions": len(self.sessions),
        }


__all__ = [
    "PixoServiceRuntime",
    "PhotoRecord",
    "SUPPORTED_EXTENSIONS",
]
