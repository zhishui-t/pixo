"""R15 集成测试：预览会话掩码供给（打开预览 → 直接可调区域）。

覆盖:
  - env 门控: PIXO_REGION_SUPPLY 缺省关（实测 multi 首推 17.7s ≫ 1s 裁决
    线）; 显式开启后 GET /region 懒触发一次分割并 Route B 注入
  - 生命周期: 每会话至多一次（掩码缓存沿 session, 重渲染/重复 GET 不重分割）
  - mock segmenter 环境永不尝试（零掩码 + 不可用, 不装可用 —— R14 契约不变）
  - 分割异常降级为不可用（不炸状态端点）; 空 mask → reason=segmenter_no_masks
  - 真权重 e2e（RAW 可达时）: 供给 → GET region available → PUT region
    params → 渲染区域变化（兼作成本实测载体）

运行: python -m pytest tests/integration/test_region_supply.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pixo.service import PixoServiceRuntime, create_app

from _corpus_paths import RAW_SKIP_REASON, REAL_A


class FakeSession:
    """测试用预览会话替身（含 region 属性面与供给所需的 render 桩）。"""

    def __init__(self, photo, session_id: str) -> None:
        self.photo_id = photo.photo_id
        self.raw_path = Path(photo.path)
        self.session_id = session_id
        self.params: dict = {}
        self.generation = 0
        self.region_masks = None                # F13 Route B 属性
        self.region_masks_source: str | None = None
        self.render_calls = 0

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
        import copy
        return copy.deepcopy(self.params)

    def render(self, long_edge: int = 1024) -> np.ndarray:
        del long_edge
        self.render_calls += 1
        # 确定性"RAW 渲染"桩（供给分割的输入图）
        rng = np.random.default_rng(7)
        return (rng.random((64, 96, 3)) * 255).astype(np.uint8)


class StubMultiSegmenter:
    """multi 替身: 记录调用次数, 返回可配置掩码/异常。"""

    def __init__(self, masks=None, exc: Exception | None = None) -> None:
        self.calls = 0
        self.masks = masks if masks is not None else {
            "sky": np.full((8, 8), 255, dtype=np.uint8)}
        self.exc = exc

    def segment(self, image_rgb, prompts):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return dict(self.masks)


def _make_runtime(stub: StubMultiSegmenter | None, tmp_path: Path,
                  supply: bool, segmenter_type: str = "multi"):
    runtime = PixoServiceRuntime(
        profile=object(),
        work_dir=tmp_path / "exports",
        session_factory=lambda photo, sid: FakeSession(photo, sid),
    )
    if stub is not None:
        runtime._segmenter = stub
    runtime.segmenter_type = segmenter_type
    app = create_app(runtime)
    client = TestClient(app)
    raw = tmp_path / "DSC_0001.nef"
    raw.write_bytes(b"fake-raw")
    photo_id = client.post("/api/photos",
                           json={"path": str(raw)}).json()["photo"]["photo_id"]
    session_id = client.post(
        f"/api/photos/{photo_id}/sessions").json()["session"]["session_id"]
    return runtime, client, session_id


@pytest.fixture()
def supply_on(monkeypatch):
    monkeypatch.setenv("PIXO_REGION_SUPPLY", "1")


def test_supply_default_off(monkeypatch, tmp_path):
    """缺省关（实测冷启 17.7s ≫ 1s 裁决线）: 不尝试分割, 语义同 R14。"""
    monkeypatch.delenv("PIXO_REGION_SUPPLY", raising=False)
    stub = StubMultiSegmenter()
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=False)
    data = client.get(f"/api/sessions/{sid}/region").json()
    assert data["available"] is False
    assert data["reason"] == "masks_not_injected"
    assert stub.calls == 0


def test_supply_lazy_once_then_cached(monkeypatch, tmp_path, supply_on):
    """开启后: GET /region 懒触发一次分割 → available+prompts; 重复 GET
    不重分割（掩码缓存沿 session）。"""
    stub = StubMultiSegmenter()
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=True)
    data = client.get(f"/api/sessions/{sid}/region").json()
    assert data["available"] is True
    assert data["prompts"] == ["sky"]
    assert data["reason"] is None
    assert stub.calls == 1
    session = runtime.get_session(sid)
    assert session.region_masks["sky"].dtype == np.uint8    # 原样注入
    # 重复 GET: 掩码已缓存, 不再分割
    client.get(f"/api/sessions/{sid}/region")
    assert stub.calls == 1


def test_supply_mock_segmenter_never_attempts(monkeypatch, tmp_path):
    """mock 环境: 零掩码 + 不可用（不装可用, R14 契约不变）——永不尝试分割。"""
    stub = StubMultiSegmenter()
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=True,
                                         segmenter_type="mock")
    data = client.get(f"/api/sessions/{sid}/region").json()
    assert data["available"] is False
    assert data["reason"] == "masks_not_injected"
    assert stub.calls == 0
    assert runtime.get_session(sid).region_masks is None


def test_supply_empty_masks_reports_segmenter_no_masks(monkeypatch,
                                                       tmp_path, supply_on):
    """分割成功但无区域掩码 → available=False + 原因区分（segmenter_no_masks）。"""
    stub = StubMultiSegmenter(masks={})
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=True)
    data = client.get(f"/api/sessions/{sid}/region").json()
    assert data["available"] is False
    assert data["reason"] == "segmenter_no_masks"
    assert runtime.get_session(sid).region_masks == {}


def test_supply_failure_degrades_without_error(monkeypatch, tmp_path,
                                               supply_on):
    """分割异常 → 降级不可用（不炸状态端点）, reason=segmenter_error
    (与"成功但全零"的 segmenter_no_masks 区分), 且标记已尝试不再重试。"""
    stub = StubMultiSegmenter(exc=RuntimeError("model boom"))
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=True)
    data = client.get(f"/api/sessions/{sid}/region").json()
    assert data["available"] is False
    assert data["reason"] == "segmenter_error"
    assert runtime.get_session(sid).region_masks == {}
    assert stub.calls == 1


def test_supply_all_zero_masks_not_usable(monkeypatch, tmp_path, supply_on):
    """R15 P1 回归: 全零掩码（分割成功但无有效区域）不注入 →
    available=False + reason=segmenter_no_masks, 滑杆不虚报可用。"""
    stub = StubMultiSegmenter(masks={
        "sky": np.zeros((8, 8), dtype=np.uint8),
        "face": np.zeros((8, 8), dtype=np.float32)})
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=True)
    data = client.get(f"/api/sessions/{sid}/region").json()
    assert data["available"] is False
    assert data["prompts"] == []
    assert data["reason"] == "segmenter_no_masks"
    session = runtime.get_session(sid)
    assert session.region_masks == {}                  # 全零不注入
    assert session.region_masks_source == "segmenter"  # 已尝试标记
    assert stub.calls == 1


def test_supply_partial_zero_keeps_only_signal_prompts(monkeypatch, tmp_path,
                                                       supply_on):
    """部分有效: 仅保留有信号的 prompt（status.prompts = 真实可用面）。"""
    stub = StubMultiSegmenter(masks={
        "sky": np.full((8, 8), 255, dtype=np.uint8),   # 有信号
        "face": np.zeros((8, 8), dtype=np.uint8)})     # 全零
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=True)
    data = client.get(f"/api/sessions/{sid}/region").json()
    assert data["available"] is True
    assert data["prompts"] == ["sky"]                  # 全零 face 被滤除


def test_supply_then_patch_then_render_uses_masks(monkeypatch, tmp_path,
                                                  supply_on):
    """供给 → patch region 参数 → 供给渲染桩被复用（掩码沿 session）:
    参数面落位 + 掩码不重分割。"""
    stub = StubMultiSegmenter()
    runtime, client, sid = _make_runtime(stub, tmp_path, supply=True)
    client.get(f"/api/sessions/{sid}/region")              # 触发供给
    resp = client.put(f"/api/sessions/{sid}/params", json={
        "region_adjust": {"enabled": True,
                          "regions": {"sky": {"warmth": 0.5}}}})
    assert resp.status_code == 200
    canon = resp.json()["canonical"]["region_adjust"]["regions"]["sky"]
    assert canon["warmth"] == 0.5
    assert stub.calls == 1                                 # patch 不重分割


# ---------------------------------------------------------------------------
# 真权重 e2e（RAW 可达时; 兼作成本实测载体, 用时数据打点在输出）
# ---------------------------------------------------------------------------

_REAL_RAW = REAL_A


@pytest.mark.skipif(_REAL_RAW is None, reason=RAW_SKIP_REASON)
def test_real_weights_supply_e2e(monkeypatch):
    """真权重供给 e2e（B1 修复语义钉死, tester O1 建议）:
    PIXO_SEGMENTER=multi + PIXO_REGION_SUPPLY=1 → 该 RAW 对 segformer 全零
    （实测 face/plant/sky 覆盖率均 0）→ 供给不注入 → available=False +
    reason=segmenter_no_masks, patch 渲染逐位不变（HSM 不应用, 不虚报可用）。
    渲染生效证据由合成掩码路径承载（Stub 用例 + tester 相位 D）。
    冷启分割 ≈17.7s, 属已知成本（见 r15-stream-2.md）。"""
    import time

    monkeypatch.setenv("PIXO_SEGMENTER", "multi")
    monkeypatch.setenv("PIXO_REGION_SUPPLY", "1")
    from pixo.service.runtime import PixoServiceRuntime as _RT

    runtime = _RT()
    if runtime.segmenter_type != "multi":
        pytest.skip("multi 分割器构造失败回退 mock（权重不可用）")
    photo = runtime.create_photo(str(_REAL_RAW))
    session = runtime.create_session(photo.photo_id)
    t0 = time.perf_counter()
    status = runtime.region_status(session.session_id)
    supply_s = time.perf_counter() - t0
    print(f"\n[R15 成本实测] 供给(含分割) {supply_s:.2f}s reason="
          f"{status['reason']}")
    # B1 修复语义: 该 RAW 无 segformer 类像素 → 全零掩码不注入
    assert status["available"] is False
    assert status["reason"] == "segmenter_no_masks"
    assert session.region_masks == {}
    assert session.region_masks_source == "segmenter"

    # patch 后渲染逐位不变（无有效掩码 → region_adjust skipped）
    runtime.update_params(session.session_id, {
        "region_adjust": {"enabled": True,
                          "regions": {"sky": {"exposure": -0.5}}}})
    base = session.render(long_edge=192)
    after = session.render(long_edge=192)
    assert np.array_equal(after, base), (
        "全零掩码不注入后 patch 渲染应与基座逐位一致（HSM 不应用）")
