"""P1-6 单元测试：pixo-service FastAPI 一期 API。

覆盖：
  - import 扫描候选 / photos 创建/列表/详情
  - session 创建、params patch + generation、canonical
  - image 编码、measurements、timeline、decide、health
  - exports 提交与状态查询
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pixo.service import PixoServiceRuntime, create_app


class FakeSession:
    """测试用预览会话替身。"""

    def __init__(self, photo, session_id: str) -> None:
        self.photo_id = photo.photo_id
        self.raw_path = Path(photo.path)
        self.session_id = session_id
        self.params: dict = {}
        self.generation = 0

    def update_params(self, patch: dict) -> int:
        self.params.update(dict(patch or {}))
        self.generation += 1
        return self.generation

    def canonical_params(self) -> dict:
        return dict(self.params)

    def render(self, long_edge: int = 1024) -> np.ndarray:
        del long_edge
        return np.zeros((16, 16, 3), dtype=np.uint8)

    def encode(self, long_edge: int = 1024, fmt: str = "jpeg",
               quality: int = 88) -> bytes:
        del long_edge, fmt, quality
        return b"fake-image-bytes"


@pytest.fixture()
def runtime(tmp_path: Path) -> PixoServiceRuntime:
    """构造注入 FakeSession 的测试运行时。"""
    return PixoServiceRuntime(
        profile=object(),
        work_dir=tmp_path / "exports",
        session_factory=lambda photo, sid: FakeSession(photo, sid),
    )


@pytest.fixture()
def client(runtime: PixoServiceRuntime):
    app = create_app(runtime)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def raw_file(tmp_path: Path) -> Path:
    path = tmp_path / "DSC_0001.nef"
    path.write_bytes(b"fake-raw")
    return path


def _create_photo(client: TestClient, raw_file: Path) -> str:
    resp = client.post("/api/photos", json={"path": str(raw_file)})
    assert resp.status_code == 201
    return resp.json()["photo"]["photo_id"]


def _create_session(client: TestClient, photo_id: str) -> str:
    resp = client.post(f"/api/photos/{photo_id}/sessions")
    assert resp.status_code == 201
    return resp.json()["session"]["session_id"]


def test_health(client: TestClient):
    """健康接口应返回服务与 vision 状态。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "pixo-service"
    assert data["vision"]["status"] == "not_ready"


def test_import_and_photo_lifecycle(client: TestClient, tmp_path: Path,
                                    raw_file: Path):
    """目录扫描、照片创建/列表/详情基本流。"""
    import_resp = client.post("/api/import",
                              json={"directory": str(tmp_path)})
    assert import_resp.status_code == 200
    candidates = import_resp.json()["candidates"]
    assert any(c["name"] == raw_file.name for c in candidates)

    photo_id = _create_photo(client, raw_file)
    list_resp = client.get("/api/photos")
    assert list_resp.status_code == 200
    assert any(p["photo_id"] == photo_id for p in list_resp.json()["photos"])

    detail_resp = client.get(f"/api/photos/{photo_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["photo"]["photo_id"] == photo_id
    assert detail_resp.json()["photo"]["state"] == "RAW_PENDING"


def test_session_params_generation_and_canonical(client: TestClient,
                                                 raw_file: Path):
    """params patch 应深合并并递增 generation。"""
    photo_id = _create_photo(client, raw_file)
    session_id = _create_session(client, photo_id)

    patch_resp = client.put(
        f"/api/sessions/{session_id}/params",
        json={"exposure": {"mode": 0.5}, "__source": "user"},
    )
    assert patch_resp.status_code == 200
    patch_data = patch_resp.json()
    assert patch_data["generation"] == 1
    assert patch_data["canonical"]["exposure"]["mode"] == 0.5

    canonical_resp = client.get(f"/api/sessions/{session_id}/canonical")
    assert canonical_resp.status_code == 200
    assert canonical_resp.json()["generation"] == 1
    assert canonical_resp.json()["canonical"]["exposure"]["mode"] == 0.5


def test_image_and_measurements(client: TestClient, raw_file: Path):
    """image 返回编码字节；measurements 返回完整 §5.4 测量。"""
    photo_id = _create_photo(client, raw_file)
    session_id = _create_session(client, photo_id)

    image_resp = client.get(
        f"/api/sessions/{session_id}/image?long_edge=64&fmt=jpeg"
    )
    assert image_resp.status_code == 200
    assert image_resp.content == b"fake-image-bytes"

    measure_resp = client.get(
        f"/api/sessions/{session_id}/measurements"
    )
    assert measure_resp.status_code == 200
    measure = measure_resp.json()["measurement"]
    assert "global" in measure
    assert "regions" in measure
    assert measure["mask_version"] == "mask_v0.1"
    assert "detail" in measure["global"]
    assert "zone_exposure" in measure["global"]["detail"]


def test_image_generation_mismatch_return_404(client: TestClient,
                                              raw_file: Path):
    """旧 generation 请求应返回 404，避免 UI 使用过期结果。"""
    photo_id = _create_photo(client, raw_file)
    session_id = _create_session(client, photo_id)
    client.put(f"/api/sessions/{session_id}/params", json={"exposure": {}})

    resp = client.get(f"/api/sessions/{session_id}/image?gen=0")
    assert resp.status_code == 404


def test_timeline_and_decide(client: TestClient, raw_file: Path):
    """timeline 返回状态与 trace；decide 返回决策结构。"""
    photo_id = _create_photo(client, raw_file)
    session_id = _create_session(client, photo_id)
    client.put(f"/api/sessions/{session_id}/params",
               json={"tone": {"highlights": -20}, "__source": "api"})

    timeline_resp = client.get(f"/api/photos/{photo_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()
    assert timeline["photo_id"] == photo_id
    assert timeline["state"] == "RAW_PENDING"
    assert any(e["event_type"] == "param_patch"
               for e in timeline["events"])

    decide_resp = client.get(f"/api/photos/{photo_id}/decide")
    assert decide_resp.status_code == 200
    decide = decide_resp.json()
    assert "decision" in decide
    assert "params" in decide["decision"]


def test_export_flow(client: TestClient, raw_file: Path, monkeypatch):
    """导出提交与状态查询基本流。"""
    import pixo.render.web.export as export_mod

    def fake_render(raw_path, prof, params, output_bps=8):
        del raw_path, prof, params, output_bps
        return np.full((8, 8, 3), 128, dtype=np.uint8)

    monkeypatch.setattr(export_mod, "_render_full_quality", fake_render)

    photo_id = _create_photo(client, raw_file)
    session_id = _create_session(client, photo_id)

    submit_resp = client.post(
        f"/api/sessions/{session_id}/exports",
        json={"fmt": "jpeg", "quality": 90},
    )
    assert submit_resp.status_code == 202
    task_id = submit_resp.json()["task_id"]

    for _ in range(50):
        status_resp = client.get(f"/api/exports/{task_id}")
        assert status_resp.status_code == 200
        task = status_resp.json()["task"]
        if task["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert task["status"] == "completed"
    assert Path(task["output_path"]).exists()
