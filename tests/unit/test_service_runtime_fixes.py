"""runtime 装饰性接线修复回归测试。

覆盖：
  - PIXO_SEGMENTER=multi 时 measure_session 走注入 segmenter 且
    detection_version 标记 multi_v1（不再硬编码 MockSegmenter/mock_v1）
  - health 报告真实 segmenter_type
  - 会话真 LRU：超限逐出最旧、命中 touch 保护、逐出同步清理
    photo.sessions 死 id（decide_photo 不再 KeyError）
  - decide_photo 写入 photo.last_decision
  - create_photo 白名单：配置 PIXO_DATA_ROOT 后拒绝白名单外路径
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pixo.service import PixoServiceRuntime


class FakeSession:
    """测试用预览会话替身（带 close 记录，便于断言逐出释放）。"""

    def __init__(self, photo, session_id: str) -> None:
        self.photo_id = photo.photo_id
        self.raw_path = Path(photo.path)
        self.session_id = session_id
        self.params: dict = {}
        self.generation = 0
        self.closed = 0

    def update_params(self, patch: dict) -> int:
        self.params.update(dict(patch or {}))
        self.generation += 1
        return self.generation

    def canonical_params(self) -> dict:
        return dict(self.params)

    def render(self, long_edge: int = 1024) -> np.ndarray:
        del long_edge
        return np.zeros((16, 16, 3), dtype=np.uint8)

    def close(self) -> None:
        self.closed += 1


def _make_runtime(tmp_path: Path) -> PixoServiceRuntime:
    """构造注入 FakeSession 的测试运行时。"""
    return PixoServiceRuntime(
        profile=object(),
        work_dir=tmp_path / "exports",
        session_factory=lambda photo, sid: FakeSession(photo, sid),
    )


def _make_raw(root: Path, name: str = "DSC_0001.nef") -> Path:
    path = root / name
    path.write_bytes(b"fake-raw")
    return path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔离 env 白名单/分割器配置，避免本机环境影响断言。"""
    monkeypatch.delenv("PIXO_DATA_ROOT", raising=False)
    monkeypatch.delenv("PIXO_SEGMENTER", raising=False)


# ---- a) PIXO_SEGMENTER 接线 ----

def test_measure_uses_injected_segmenter_and_multi_version(
    tmp_path, monkeypatch
):
    """PIXO_SEGMENTER=multi：用注入 segmenter，detection_version=multi_v1。"""
    monkeypatch.setenv("PIXO_SEGMENTER", "multi")
    rt = _make_runtime(tmp_path)
    assert rt.segmenter_type == "multi"

    calls = {"n": 0}

    class _FakeSeg:
        def segment(self, image_rgb, prompts):
            calls["n"] += 1
            return {p: np.zeros(image_rgb.shape[:2], dtype=np.uint8)
                    for p in prompts}

    rt._segmenter = _FakeSeg()  # type: ignore[assignment]

    photo = rt.create_photo(_make_raw(tmp_path))
    session = rt.create_session(photo.photo_id)
    result = rt.measure_session(session.session_id)

    assert calls["n"] == 1
    assert result["measurement"]["detection_version"] == "multi_v1"
    assert result["measurement"]["image_id"] == photo.photo_id


def test_health_reports_real_segmenter_type(tmp_path):
    """health 的 router 字段应报真实生效的分割器类型而非硬编码 multi。"""
    rt = _make_runtime(tmp_path)
    assert rt.health()["segmenter"]["router"] == rt.segmenter_type == "mock"


# ---- b) 会话真 LRU ----

def test_lru_evicts_oldest_and_cleans_photo_sessions(tmp_path, monkeypatch):
    """超上限逐出访问序最旧会话；photo.sessions 不残留死 id。"""
    monkeypatch.setenv("PIXO_MAX_SESSIONS", "2")
    rt = _make_runtime(tmp_path)
    photo = rt.create_photo(_make_raw(tmp_path))

    s1 = rt.create_session(photo.photo_id)
    s2 = rt.create_session(photo.photo_id)
    s3 = rt.create_session(photo.photo_id)  # 触发逐出 s1

    assert s1.session_id not in rt.sessions
    assert s2.session_id in rt.sessions and s3.session_id in rt.sessions
    assert s1.closed == 1  # 被逐出会话防御式 close
    assert photo.sessions == [s2.session_id, s3.session_id]
    with pytest.raises(KeyError):
        rt.get_session(s1.session_id)


def test_lru_touch_protects_recently_used(tmp_path, monkeypatch):
    """命中 get_session 会 touch：最旧者改为未被访问的 s2 被逐出。"""
    monkeypatch.setenv("PIXO_MAX_SESSIONS", "2")
    rt = _make_runtime(tmp_path)
    photo = rt.create_photo(_make_raw(tmp_path))

    s1 = rt.create_session(photo.photo_id)
    s2 = rt.create_session(photo.photo_id)
    rt.get_session(s1.session_id)  # touch s1
    s3 = rt.create_session(photo.photo_id)

    assert s1.session_id in rt.sessions
    assert s2.session_id not in rt.sessions
    assert s3.session_id in rt.sessions


def test_evicted_photo_decide_no_keyerror(tmp_path, monkeypatch):
    """逐出清理死 id 后，旧照片 decide 不再因 sessions[-1] KeyError。"""
    monkeypatch.setenv("PIXO_MAX_SESSIONS", "2")
    rt = _make_runtime(tmp_path)
    p1 = rt.create_photo(_make_raw(tmp_path, "a.nef"))
    p2 = rt.create_photo(_make_raw(tmp_path, "b.nef"))
    p3 = rt.create_photo(_make_raw(tmp_path, "c.nef"))

    rt.create_session(p1.photo_id)          # s1（将最旧）
    rt.create_session(p2.photo_id)          # s2
    rt.create_session(p3.photo_id)          # s3 → 逐出 s1

    # 修复前 p1.sessions 残留死 id [s1]，decide 取 sessions[-1] 后
    # get_session(s1) 抛 KeyError（API 表现为"照片不存在"无法自愈）。
    assert p1.sessions == []
    result = rt.decide_photo(p1.photo_id)
    assert result["photo_id"] == p1.photo_id
    assert "decision" in result


# ---- c) last_decision 写入 ----

def test_decide_photo_writes_last_decision(tmp_path):
    """decide 成功后应把决策写入 photo.last_decision 字段。"""
    rt = _make_runtime(tmp_path)
    photo = rt.create_photo(_make_raw(tmp_path))
    rt.create_session(photo.photo_id)

    result = rt.decide_photo(photo.photo_id)

    assert photo.last_decision == result["decision"]
    assert rt.photo_dict(photo.photo_id)["last_decision"] == result["decision"]


# ---- d) create_photo 白名单 ----

def test_create_photo_rejects_path_outside_data_root(tmp_path, monkeypatch):
    """配置 PIXO_DATA_ROOT 后 create_photo 拒绝白名单外路径。"""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("PIXO_DATA_ROOT", str(allowed))
    rt = _make_runtime(tmp_path)

    inside = rt.create_photo(_make_raw(allowed, "in.nef"))
    assert inside.path == (allowed / "in.nef").resolve()

    outside = _make_raw(tmp_path, "out.nef")
    with pytest.raises(ValueError, match="PIXO_DATA_ROOT"):
        rt.create_photo(outside)


def test_create_photo_unrestricted_without_data_root(tmp_path):
    """未配置 PIXO_DATA_ROOT 时 create_photo 不限制路径（默认行为保持）。"""
    rt = _make_runtime(tmp_path)
    photo = rt.create_photo(_make_raw(tmp_path))  # tmp_path 本身不在任何白名单
    assert photo.photo_id in rt.photos
