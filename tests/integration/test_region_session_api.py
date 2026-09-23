"""R14 集成测试：region 状态 API + patch 嵌套闭环 + preview e2e。

覆盖（M1 前端 region 控件的后端暴露）:
  - 掩码状态 API: GET /api/sessions/{id}/region（available/prompts/reason）——
    纯预览会话（无 loop 分割通道注入）显式报 "masks_not_injected"，避免
    "滑杆调了静默失效" 的 UI 陷阱; Route B 注入后 available=True + prompts
  - params patch 响应携带 region 状态节（每次 patch 后 UI 即可感知）
  - patch 嵌套闭环（真 RawPreviewSession 渲染）:
    PUT region_adjust.regions.<prompt>.<param> 深合并 → canonical 回读 →
    Route B 掩码注入 → 渲染生效（掩码区变暗、非掩码区逐位不变）

运行: python -m pytest tests/integration/test_region_session_api.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pixo.service import PixoServiceRuntime, create_app

from _corpus_paths import RAW_SKIP_REASON, REAL_A


class FakeSession:
    """测试用预览会话替身（镜像 RawPreviewSession 的 region_masks 属性面）。"""

    def __init__(self, photo, session_id: str) -> None:
        self.photo_id = photo.photo_id
        self.raw_path = Path(photo.path)
        self.session_id = session_id
        self.params: dict = {}
        self.generation = 0
        # F13 Route B: 默认 None（纯预览会话无掩码注入）
        self.region_masks = None

    def update_params(self, patch: dict) -> int:
        def merge(dst: dict, src: dict) -> None:
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    merge(dst[k], v)
                else:
                    dst[k] = v
        merge(self.params, dict(patch or {}))
        self.generation += 1
        return self.generation

    def canonical_params(self) -> dict:
        return dict(self.params)


# ---------------------------------------------------------------------------
# API 形状（FakeSession + TestClient）
# ---------------------------------------------------------------------------

class TestRegionStatusApi:
    @pytest.fixture()
    def runtime(self, tmp_path: Path) -> PixoServiceRuntime:
        return PixoServiceRuntime(
            profile=object(),
            work_dir=tmp_path / "exports",
            session_factory=lambda photo, sid: FakeSession(photo, sid),
        )

    @pytest.fixture()
    def client(self, runtime: PixoServiceRuntime):
        app = create_app(runtime)
        with TestClient(app) as test_client:
            yield test_client

    @pytest.fixture()
    def session_id(self, client: TestClient, tmp_path: Path) -> str:
        raw = tmp_path / "DSC_0001.nef"
        raw.write_bytes(b"fake-raw")
        resp = client.post("/api/photos", json={"path": str(raw)})
        assert resp.status_code == 201
        photo_id = resp.json()["photo"]["photo_id"]
        resp = client.post(f"/api/photos/{photo_id}/sessions")
        assert resp.status_code == 201
        return resp.json()["session"]["session_id"]

    def test_region_status_not_injected(self, client: TestClient,
                                        session_id: str):
        """纯预览会话（无掩码注入）: available=False + 原因显式化。"""
        resp = client.get(f"/api/sessions/{session_id}/region")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["prompts"] == []
        assert data["reason"] == "masks_not_injected"

    def test_region_status_available_after_route_b_injection(
            self, client: TestClient, runtime: PixoServiceRuntime,
            session_id: str):
        """Route B 注入（session.region_masks）后: available=True + prompts。"""
        session = runtime.get_session(session_id)
        session.region_masks = {"sky": np.ones((16, 16), np.float32),
                                "face": np.zeros((16, 16), np.float32)}
        resp = client.get(f"/api/sessions/{session_id}/region")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["prompts"] == ["face", "sky"]        # 排序稳定
        assert data["reason"] is None

    def test_params_patch_response_carries_region_status(
            self, client: TestClient, session_id: str):
        """每次 params patch 的响应携带 region 状态节（patch 后即感知）。"""
        resp = client.put(f"/api/sessions/{session_id}/params",
                          json={"tone": {"brightness": 0.1}})
        assert resp.status_code == 200
        region = resp.json()["region"]
        assert region["available"] is False
        assert region["reason"] == "masks_not_injected"

    def test_region_status_unknown_session_404(self, client: TestClient):
        resp = client.get("/api/sessions/no-such-session/region")
        assert resp.status_code == 404

    def test_region_nested_patch_deep_merges(self, client: TestClient,
                                             session_id: str):
        """嵌套 patch（region_adjust.regions.<p>.<param>）深合并不互相覆盖。"""
        resp = client.put(f"/api/sessions/{session_id}/params", json={
            "region_adjust": {"enabled": True,
                              "regions": {"sky": {"exposure": -0.5}}}})
        assert resp.status_code == 200
        resp = client.put(f"/api/sessions/{session_id}/params", json={
            "region_adjust": {"enabled": True,
                              "regions": {"sky": {"warmth": 0.4}}}})
        assert resp.status_code == 200
        regions = resp.json()["canonical"]["region_adjust"]["regions"]["sky"]
        assert regions["exposure"] == -0.5               # 首次 patch 未被覆盖
        assert regions["warmth"] == 0.4
        assert resp.json()["canonical"]["region_adjust"]["enabled"] is True


# ---------------------------------------------------------------------------
# patch 嵌套闭环 + preview e2e（真 RawPreviewSession 渲染, RAW skip 守卫）
# ---------------------------------------------------------------------------

# 语料路径集中解析（语料搬家 / env 覆盖见 tests/_corpus_paths.py）
_REAL_RAW = REAL_A

pytestmark_real = pytest.mark.skipif(
    _REAL_RAW is None,
    reason=RAW_SKIP_REASON,
)


def _real_raw() -> Path:
    assert _REAL_RAW is not None          # 由 pytestmark_real 保证
    return _REAL_RAW


@pytest.mark.skipif(
    _REAL_RAW is None,
    reason=RAW_SKIP_REASON,
)
class TestRegionPatchE2E:
    """端到端: Route B 掩码注入 → 嵌套 patch → canonical 回读 → 渲染生效。"""

    @pytest.fixture()
    def env(self):
        runtime = PixoServiceRuntime()          # 真实 DCP + 真渲染会话工厂
        photo = runtime.create_photo(str(_real_raw()))
        session = runtime.create_session(photo.photo_id)
        # Route B: 左半图掩码=1（受影响区）, 右半=0（对照区）
        session.region_masks = {
            "sky": np.concatenate(
                [np.ones((16, 8), np.float32),
                 np.zeros((16, 8), np.float32)], axis=1),
        }
        return runtime, session

    def test_patch_nesting_canonical_readback_and_render_effect(self, env):
        runtime, session = env
        base = session.render(long_edge=192)
        h, w = base.shape[:2]

        resp = runtime.update_params(session.session_id, {
            "region_adjust": {"enabled": True,
                              "regions": {"sky": {"exposure": -0.5}}}})
        # canonical 回读: 嵌套路径深合并正确
        regions = resp["canonical"]["region_adjust"]["regions"]["sky"]
        assert regions["exposure"] == -0.5
        assert resp["canonical"]["region_adjust"]["enabled"] is True
        # region 状态: 掩码已注入 → available
        assert resp["region"]["available"] is True
        assert resp["region"]["prompts"] == ["sky"]

        after = session.render(long_edge=192)

        # 掩码区（左半内部, 避开羽化边）: exposure -0.5 → 变暗
        gain = 2.0 ** (-0.5 / 2.2)
        li = slice(8, w // 2 - 40)
        d_left = (after[:, li].astype(np.float64)
                  - base[:, li].astype(np.float64)).mean()
        assert d_left < -0.005, f"掩码区未变暗: mean Δ={d_left:.5f}"
        # 量级 sanity: 亮度比例 ≈ gamma 域增益
        ratio = (after[:, li].mean() / max(base[:, li].mean(), 1e-9))
        assert ratio == pytest.approx(gain, rel=0.15)
        # 非掩码区（右远端内部）: 逐位不变。羽化注记: 掩码边界 x=96, 羽化
        # 过渡带实测至 ~x=107（region_masks 适配器入口羽化 + region_adjust
        # 二次羽化叠加）, 对照区取 x≥128 避开过渡带
        ri = slice(128, w - 8)
        assert np.array_equal(after[:, ri], base[:, ri]), (
            "非掩码区被意外修改（羽化越界或掩码适配错误）")
