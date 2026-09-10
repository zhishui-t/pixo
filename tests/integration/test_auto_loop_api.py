"""R21 F01/F02/F03（service 侧）定向测试：闭环生产入口 + 默认规则注入。

角色：dev-1（stream-1）文件域。覆盖：
  ① `_load_auto_loop_rules` 缺省非空；`PIXO_RULES=off`（及 0/false/no）为空；
  ② `run_auto_loop` 用**注入的假 render backend + MockSegmenter** 跑通
     （不跑 73s 真 RAW）：状态 / params / rule_ids（**全 decide 事件并集**，
     修订 R1）提取正确 + 每 photo 单飞；
  ③ FastAPI `TestClient` 真实 HTTP 往返：POST → 202 → GET → done
     （+ `sync=true` → 200 同构 + 内部异常落 status=failed 不裸抛 500）；
  ④ `decide_photo` 在 FakeSession（同 test_service_api.py:21-46 风格）下
     `decision.params` 非空（F03 分叉1 A2）；
  ⑤ `measure_session` 返回的 measurement **顶层**有 proxies 三键（F03）。

真 RAW 端到端门禁归 `tester`（F05），本文件永不读真 RAW。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pixo.pipeline.loop import SinglePhotoLoop, SyntheticRenderBackend
from pixo.service import PixoServiceRuntime, create_app
from pixo.service import runtime as runtime_mod
from pixo.vision import MockSegmenter


# ---------------------------------------------------------------------------
# 测试替身（对齐 tests/integration/test_service_api.py:21-46 的 FakeSession）
# ---------------------------------------------------------------------------

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


def _dark_image() -> np.ndarray:
    """低亮度合成图（影子裁切高 → 触发 shadow_open_rule_032）。"""
    img = np.full((64, 64, 3), 0.08, dtype=np.float32)
    img[16:48, 16:48] = 0.3
    return img


class _GatedBackend:
    """闸门包裹的假 backend：release 前阻塞渲染，用于确定性验证单飞。"""

    def __init__(self, backend, gate: threading.Event) -> None:
        self._backend = backend
        self._gate = gate

    def render_preview(self, params, long_edge: int = 1024) -> np.ndarray:
        self._gate.wait(15)
        return self._backend.render_preview(params, long_edge)

    def render_full(self, params) -> np.ndarray:
        self._gate.wait(15)
        return self._backend.render_full(params)

    def full_size(self):
        return self._backend.full_size()


class _FirstRoundThenHealthyBackend:
    """第 1 次 preview 返回异常图、其后返回健康图（构造收敛后的末轮 trace）。

    R21 修订 R1：tester 真 RAW 失败形态 = 首轮命中规则、末轮（终止轮）
    无规则可命中；本 backend 让逐轮测量真的收敛，从而复现该 trace 形态。
    """

    def __init__(self, first_image: np.ndarray,
                 later_image: np.ndarray) -> None:
        self._first = SyntheticRenderBackend(first_image)
        self._later = SyntheticRenderBackend(later_image)
        self.preview_calls = 0

    def render_preview(self, params, long_edge: int = 1024) -> np.ndarray:
        self.preview_calls += 1
        backend = self._first if self.preview_calls == 1 else self._later
        return backend.render_preview(params, long_edge)

    def render_full(self, params) -> np.ndarray:
        return self._later.render_full(params)

    def full_size(self):
        return self._later.full_size()


def _fake_backend_factory(gate: threading.Event | None = None):
    """替换 runtime.RawRenderBackend 的工厂（签名同 RawRenderBackend）。"""
    def _factory(raw_path, prof):
        del raw_path, prof
        backend = SyntheticRenderBackend(_dark_image())
        return backend if gate is None else _GatedBackend(backend, gate)
    return _factory


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def runtime(tmp_path: Path) -> PixoServiceRuntime:
    """构造注入 FakeSession 的测试运行时（同 test_service_api.py 风格）。"""
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


def _make_raw(tmp_path: Path, name: str = "DSC_0002.nef") -> Path:
    path = tmp_path / name
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


def _wait_task(rt: PixoServiceRuntime, task_id: str, timeout: float = 30.0):
    """轮询 runtime 任务表直到终态。"""
    deadline = time.monotonic() + timeout
    status = rt.auto_loop_status(task_id)
    while time.monotonic() < deadline:
        status = rt.auto_loop_status(task_id)
        if status["status"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"auto-loop 任务未在 {timeout}s 内终结: {status}")


def _poll_client(client: TestClient, task_id: str, timeout: float = 30.0):
    """HTTP 轮询 GET /api/auto-loop/{task_id} 直到终态。"""
    deadline = time.monotonic() + timeout
    task = client.get(f"/api/auto-loop/{task_id}").json()
    while time.monotonic() < deadline:
        resp = client.get(f"/api/auto-loop/{task_id}")
        assert resp.status_code == 200
        task = resp.json()
        if task["status"] in ("done", "failed"):
            return task
        time.sleep(0.02)
    raise AssertionError(f"auto-loop HTTP 任务未在 {timeout}s 内终结: {task}")


# ---------------------------------------------------------------------------
# ① F02：装配层默认规则注入
# ---------------------------------------------------------------------------

def test_load_auto_loop_rules_default_nonempty():
    """缺省（未设 PIXO_RULES）加载全部内置规则，显式传键宇宙不抛 DecideError。"""
    rules = runtime_mod._load_auto_loop_rules(("face", "sky", "plant"))
    assert rules, "默认规则包为空"
    assert all("rule_id" in r for r in rules)
    # region_rules.yaml 的 sky_*/plant_* 双引用必须能过 lint（显式 metric_keys）
    ids = {r["rule_id"] for r in rules}
    assert ids, f"rule_id 集合为空: {len(rules)} 条"


@pytest.mark.parametrize("value", ["off", "0", "false", "FALSE", "No", "OFF"])
def test_load_auto_loop_rules_env_disables(monkeypatch, value: str):
    """PIXO_RULES ∈ {0,false,off,no}（任意大小写）→ 装配层不注入规则。"""
    monkeypatch.setenv("PIXO_RULES", value)
    assert runtime_mod._load_auto_loop_rules(("face", "sky", "plant")) == []


def test_loop_layer_default_rules_stay_empty():
    """库层 SinglePhotoLoop(rules=None) 缺省保持空（F02 不变式）。"""
    from pixo.pipeline.loop import SinglePhotoLoop

    loop = SinglePhotoLoop()
    assert loop.rules == []


# ---------------------------------------------------------------------------
# ② F01：run_auto_loop（注入假 backend，不跑真 RAW）
# ---------------------------------------------------------------------------

def test_run_auto_loop_async_ok_and_single_flight(tmp_path, monkeypatch):
    """假 backend 跑通闭环；同 photo 二次提交返回既有 task_id（单飞）。"""
    gate = threading.Event()
    monkeypatch.setattr(
        runtime_mod, "RawRenderBackend", _fake_backend_factory(gate)
    )
    rt = PixoServiceRuntime(profile=object(),
                            work_dir=tmp_path / "exports",
                            session_factory=lambda p, sid: FakeSession(p, sid))
    photo = rt.create_photo(_make_raw(tmp_path))

    first = rt.run_auto_loop(
        photo.photo_id, max_iterations=2, preview_long_edge=64
    )
    assert first["status"] == "running"
    assert first["photo_id"] == photo.photo_id
    assert first["segmenter_type"] == "mock"
    assert first["degraded"] == ["mock_segmenter"]  # mock 掩码留痕

    dup = rt.run_auto_loop(
        photo.photo_id, max_iterations=2, preview_long_edge=64
    )
    assert dup["task_id"] == first["task_id"], "同 photo 单飞失效"

    gate.set()
    task = _wait_task(rt, first["task_id"])
    assert task["status"] == "done", task["error"]
    assert task["state"] in ("ACCEPTED", "MANUAL_REVIEW")
    assert task["params"], "闭环未落地任何参数"
    assert task["rule_ids"], "rule_ids 提取为空（应为全部 decide 事件并集）"
    assert task["rule_ids_by_iteration"], "缺逐轮规则分布"
    assert all(
        set(item) == {"iteration", "rule_ids"}
        and isinstance(item["iteration"], int)
        and isinstance(item["rule_ids"], list)
        for item in task["rule_ids_by_iteration"]
    )
    assert task["trace_event_count"] > 0
    assert task["error"] is None
    assert task["duration"] is not None and task["duration"] >= 0

    # 任务终结后清除单飞占位 → 再次提交得到新 task_id
    again = rt.run_auto_loop(
        photo.photo_id, max_iterations=1, preview_long_edge=64
    )
    assert again["task_id"] != first["task_id"]
    assert _wait_task(rt, again["task_id"])["status"] == "done"


def test_run_auto_loop_sync_matches_status(tmp_path, monkeypatch):
    """sync=True 阻塞返回终态结果，与 auto_loop_status 同构。"""
    monkeypatch.setattr(
        runtime_mod, "RawRenderBackend", _fake_backend_factory()
    )
    rt = PixoServiceRuntime(profile=object(),
                            work_dir=tmp_path / "exports",
                            session_factory=lambda p, sid: FakeSession(p, sid))
    photo = rt.create_photo(_make_raw(tmp_path))

    result = rt.run_auto_loop(
        photo.photo_id, max_iterations=2, preview_long_edge=64, sync=True
    )
    assert result["status"] == "done", result["error"]
    assert result == rt.auto_loop_status(result["task_id"])
    assert result["params"] and result["rule_ids"]
    assert result["rule_ids_by_iteration"], "sync 视图缺逐轮规则分布"


def test_auto_loop_rule_ids_union_across_decide_events():
    """rule_ids = 全部 decide 事件 rule_ids 的并集（首次出现顺序、去重）。

    R21 修订 R1：**不是**「最后一条 decide 事件」——末轮是否命中取决于该轮
    指标是否跨过阈值（D1 三样本实测：DSC_5236 末轮自然不命中、DSC_5237 末轮
    **命中**，两种形态都存在）。取「最后一条」会**静默丢掉早期命中**（在
    DSC_5236 这类形态下 `rule_ids` 即结构性为空）。
    **不得**把「末轮必空」写成不变量（末轮走 `last_iteration` 分支，规则照常
    评估，`engine.py:977-989`）。
    """

    class _FakeResult:
        decision = "ACCEPTED"          # ← 状态字符串，不是 rule_ids
        trace_events = [
            {"event_type": "meta_extracted", "value": {}},
            {"event_type": "decide", "value": {"iteration": 1,
                                               "rule_ids": ["a_rule"]}},
            {"event_type": "param_update", "value": {}},
            {"event_type": "decide", "value": {"iteration": 2,
                                               "rule_ids": []}},
            {"event_type": "decide", "value": {"iteration": 3,
                                               "rule_ids": ["b_rule",
                                                            "a_rule"]}},
        ]

    result = _FakeResult()
    assert PixoServiceRuntime._auto_loop_rule_ids(result) == [
        "a_rule", "b_rule"
    ]                                                    # 顺序 + 去重
    assert PixoServiceRuntime._auto_loop_rule_ids_by_iteration(result) == [
        {"iteration": 1, "rule_ids": ["a_rule"]},
        {"iteration": 2, "rule_ids": []},
        {"iteration": 3, "rule_ids": ["b_rule", "a_rule"]},
    ]


def test_auto_loop_rule_ids_nonempty_when_last_round_naturally_empty(
    tmp_path, monkeypatch
):
    """tester 真 RAW 失败形态：首轮命中过规则、末轮**自然不命中**。

    形态（QA/队长更正归因后的正确表述）：末轮**照常评估规则**，只是首轮命中
    并写入参数后指标已回到阈值内 ⇒ 该轮无命中、`rule_ids=[]`。这**不是**
    「终止轮必空」的不变量（`check_termination` 短路是另一条合法空路径）。

    用假 backend（第 1 次 preview 全黑 → 其后 0.5 灰）+ 单条确定规则构造出
    与真 RAW 同构的 trace（decide#1 命中、decide#2 自然空），钉死「并集非空 /
    逐轮末轮为空」。
    """
    crafted_rule = {
        "rule_id": "test_shadow_open_once",
        "priority": 10,
        "condition": {"metric": "shadow_clip_ratio", "op": "gte",
                      "value": 0.18},
        "action": {"param": "tone.shadows", "mode": "delta",
                   "formula": "0.05", "clamp": [-1.0, 1.0],
                   "conflict_policy": "high_priority_wins"},
    }
    healthy = np.full((64, 64, 3), 0.5, dtype=np.float32)
    # 首轮全黑：luminance < SHADOW_CLIP_THRESHOLD(5/255) → shadow_clip_ratio=1.0
    # → 命中；其后 0.5 灰 → shadow_clip_ratio≈0 → 末轮指标回落、自然不命中。
    backend = _FirstRoundThenHealthyBackend(
        np.zeros((64, 64, 3), dtype=np.float32), healthy
    )
    monkeypatch.setattr(
        runtime_mod, "RawRenderBackend", lambda raw_path, prof: backend
    )
    monkeypatch.setattr(
        runtime_mod, "_load_auto_loop_rules", lambda prompts=None: [crafted_rule]
    )
    rt = PixoServiceRuntime(profile=object(),
                            work_dir=tmp_path / "exports",
                            session_factory=lambda p, sid: FakeSession(p, sid))
    photo = rt.create_photo(_make_raw(tmp_path))

    task = rt.run_auto_loop(
        photo.photo_id, max_iterations=2, preview_long_edge=64, sync=True
    )
    assert task["status"] == "done", task["error"]
    assert task["iteration"] == 2

    by_iteration = task["rule_ids_by_iteration"]
    assert [item["iteration"] for item in by_iteration] == [1, 2]
    assert by_iteration[0]["rule_ids"] == ["test_shadow_open_once"]
    # 末轮规则照常评估过，只是自然不命中（旧「取最后一条」口径在此恒空）
    assert by_iteration[-1]["rule_ids"] == []
    # 并集口径：整轮闭环落地过的规则非空
    assert task["rule_ids"] == ["test_shadow_open_once"]
    assert task["params"], "首轮规则参数未落地"


def test_last_round_evaluates_rules_before_natural_miss():
    """末轮**不短路**：decide 事件带 `last_iteration=True` 且 decision 为
    `adjust_and_continue`（照常评估规则），只是该轮无命中。

    直接跑库层 `SinglePhotoLoop` 拿真 `LoopResult`，验证服务层并集提取在
    「末轮自然空」形态下仍非空。真 RAW 的指标是 `colorfulness_proxy`
    （6.19 → 5.8936），本用例用同构的 `shadow_clip_ratio`（1.0 → ≈0）。
    """
    crafted_rule = {
        "rule_id": "test_shadow_open_once",
        "priority": 10,
        "condition": {"metric": "shadow_clip_ratio", "op": "gte",
                      "value": 0.18},
        "action": {"param": "tone.shadows", "mode": "delta",
                   "formula": "0.05", "clamp": [-1.0, 1.0],
                   "conflict_policy": "high_priority_wins"},
    }
    backend = _FirstRoundThenHealthyBackend(
        np.zeros((64, 64, 3), dtype=np.float32),
        np.full((64, 64, 3), 0.5, dtype=np.float32),
    )
    loop = SinglePhotoLoop(
        render_backend=backend,
        segmenter=MockSegmenter(),
        rules=[crafted_rule],
        preview_long_edge=64,
        max_iterations=2,
        prompts=["face", "sky", "plant"],
        manual_on_unreliable=False,
    )
    result = loop.run("rev1-natural-miss")

    decide_values = [
        event["value"] for event in result.trace_events
        if event.get("event_type") == "decide"
    ]
    assert len(decide_values) == 2
    assert decide_values[0]["rule_ids"] == ["test_shadow_open_once"]
    last = decide_values[-1]
    assert last["iteration"] == 2
    # 末轮走 last_iteration 分支（should_stop=False）而非终止短路
    assert last["last_iteration"] is True
    assert last["decision"] == "adjust_and_continue"
    assert last["rule_ids"] == []          # 自然不命中

    # 服务层提取：并集保留首轮命中，逐轮分布忠实记录末轮为空
    assert PixoServiceRuntime._auto_loop_rule_ids(result) == [
        "test_shadow_open_once"
    ]
    assert PixoServiceRuntime._auto_loop_rule_ids_by_iteration(result) == [
        {"iteration": 1, "rule_ids": ["test_shadow_open_once"]},
        {"iteration": 2, "rule_ids": []},
    ]


def test_run_auto_loop_rejects_illegal_max_iterations_and_unknown_photo(
    tmp_path,
):
    """非法 max_iterations → ValueError；photo 不存在 → KeyError。"""
    rt = PixoServiceRuntime(profile=object(),
                            work_dir=tmp_path / "exports",
                            session_factory=lambda p, sid: FakeSession(p, sid))
    photo = rt.create_photo(_make_raw(tmp_path))

    for bad in (0, -1, 6, 2.5, "3", True):
        with pytest.raises(ValueError):
            rt.run_auto_loop(photo.photo_id, max_iterations=bad, sync=True)

    with pytest.raises(KeyError):
        rt.run_auto_loop("no-such-photo")


def test_auto_loop_env_overrides_default_iterations(monkeypatch):
    """env PIXO_LOOP_MAX_ITERATIONS 覆盖缺省；非法回退 3；超上限裁到 5。"""
    monkeypatch.setenv("PIXO_LOOP_MAX_ITERATIONS", "2")
    assert runtime_mod._auto_loop_default_iterations() == 2
    monkeypatch.setenv("PIXO_LOOP_MAX_ITERATIONS", "99")
    assert runtime_mod._auto_loop_default_iterations() == 5
    monkeypatch.setenv("PIXO_LOOP_MAX_ITERATIONS", "abc")
    assert runtime_mod._auto_loop_default_iterations() == 3
    monkeypatch.delenv("PIXO_LOOP_MAX_ITERATIONS")
    assert runtime_mod._auto_loop_default_iterations() == 3


# ---------------------------------------------------------------------------
# ③ F01：HTTP 真实往返（TestClient）
# ---------------------------------------------------------------------------

def test_auto_loop_http_post_202_then_get_done(client, monkeypatch, raw_file):
    """POST → 202（running）→ GET 轮询 → done；失败语义 404/400 同步生效。"""
    monkeypatch.setattr(
        runtime_mod, "RawRenderBackend", _fake_backend_factory()
    )
    photo_id = _create_photo(client, raw_file)

    resp = client.post(
        f"/api/photos/{photo_id}/auto-loop", json={"max_iterations": 2}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert set(body) >= {"task_id", "status", "photo_id", "segmenter_type"}
    assert body["status"] == "running"
    assert body["photo_id"] == photo_id
    assert body["segmenter_type"] == "mock"
    assert body["degraded"] == ["mock_segmenter"]

    task = _poll_client(client, body["task_id"])
    assert task["status"] == "done", task["error"]
    assert task["photo_id"] == photo_id
    assert task["params"] and task["rule_ids"]
    assert task["rule_ids_by_iteration"], "GET 视图缺逐轮规则分布"
    assert task["trace_event_count"] > 0
    assert task["error"] is None

    # 失败语义
    assert client.post("/api/photos/no-such-photo/auto-loop").status_code == 404
    bad = client.post(
        f"/api/photos/{photo_id}/auto-loop", json={"max_iterations": 0}
    )
    assert bad.status_code == 400
    assert client.get("/api/auto-loop/no-such-task").status_code == 404


def test_auto_loop_http_sync_true_returns_200_isomorphic(
    client, monkeypatch, raw_file
):
    """sync=true → HTTP 200 + 与 GET 同构的结果体（非 202）。"""
    monkeypatch.setattr(
        runtime_mod, "RawRenderBackend", _fake_backend_factory()
    )
    photo_id = _create_photo(client, raw_file)

    resp = client.post(
        f"/api/photos/{photo_id}/auto-loop",
        json={"sync": True, "max_iterations": 2},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "done", result["error"]
    assert result["params"] and result["rule_ids"]

    get_resp = client.get(f"/api/auto-loop/{result['task_id']}")
    assert get_resp.status_code == 200
    assert get_resp.json() == result  # 同构


def test_auto_loop_internal_error_no_500(client, monkeypatch, raw_file):
    """闭环内部异常 → status=failed + error（异步与 sync 两路都不裸抛 500）。"""

    def _boom(raw_path, prof):
        del raw_path, prof
        raise RuntimeError("boom-render\nsecond line must be dropped")

    monkeypatch.setattr(runtime_mod, "RawRenderBackend", _boom)
    photo_id = _create_photo(client, raw_file)

    async_resp = client.post(f"/api/photos/{photo_id}/auto-loop")
    assert async_resp.status_code == 202
    task = _poll_client(client, async_resp.json()["task_id"])
    assert task["status"] == "failed"
    assert task["error"].startswith("RuntimeError: boom-render")
    assert "\n" not in task["error"]

    sync_resp = client.post(
        f"/api/photos/{photo_id}/auto-loop", json={"sync": True}
    )
    assert sync_resp.status_code == 200
    failed = sync_resp.json()
    assert failed["status"] == "failed"
    assert failed["error"].startswith("RuntimeError: boom-render")


# ---------------------------------------------------------------------------
# ④ F03：decide_photo 展平 + 传 rules（响应字段集合不变）
# ---------------------------------------------------------------------------

def test_decide_photo_params_nonempty(client, raw_file):
    """FakeSession 全零渲染 → shadow_clip_ratio ≥ 阈值 → params 非空。"""
    photo_id = _create_photo(client, raw_file)
    _create_session(client, photo_id)

    resp = client.post(f"/api/photos/{photo_id}/decide")
    assert resp.status_code == 200
    body = resp.json()
    # 响应字段集合不变（仅 decision.params 由 {} 变非空）
    assert set(body) >= {
        "photo_id", "state", "iteration", "measurement", "decision"
    }
    assert body["decision"]["rule_ids"], "服务层 decide 仍零触发"
    assert body["decision"]["params"], "decision.params 仍为空"


# ---------------------------------------------------------------------------
# ⑤ F03：measure_session 顶层合并 proxies
# ---------------------------------------------------------------------------

def test_measure_session_merges_proxy_metrics_at_top_level(client, raw_file):
    """measurement 顶层有 proxies 三键；既有字段只增不改。"""
    photo_id = _create_photo(client, raw_file)
    session_id = _create_session(client, photo_id)

    resp = client.get(f"/api/sessions/{session_id}/measurements")
    assert resp.status_code == 200
    measurement = resp.json()["measurement"]
    for key in ("haze_proxy", "colorfulness_proxy", "tonal_range"):
        assert key in measurement, f"measurement 顶层缺 {key}"
    # 追加式：既有字段不变
    assert "global" in measurement
    assert "regions" in measurement
    assert measurement["mask_version"] == "mask_v0.1"
