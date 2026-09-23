"""R16 集成测试：segmenter 启动预热（冷启 17.7s 优化）。

覆盖:
  - 门控: mock segmenter 跳过（无权重可预热, 不装可用）; env
    PIXO_SEGMENTER_WARMUP=0/false/off/no 跳过; 缺省开
  - 真预热: multi + env 开 → 后端加载 + 小图首推理（status=done, 计时,
    幂等——重复预热不再推理）; 推理异常 → status=failed（不炸）
  - 互斥: 预热与供给的 segment 调用经推理锁串行（预热中到达的供给等待,
    获锁即热态）
  - health: segmenter.warmup 状态/耗时暴露（沿 scorer health_info 惯例）
  - 真权重 e2e（RAW 可达时）: 预热吸收冷启 → 预热后首供给耗时降至秒级
    （对照 R15 冷启 17.7s）+ 预热中请求不阻塞

运行: python -m pytest tests/integration/test_segmenter_warmup.py -q
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from pixo.service import PixoServiceRuntime, create_app
from pixo.service.runtime import _segmenter_warmup_enabled

from _corpus_paths import RAW_SKIP_REASON, REAL_A


class FakeSession:
    """预览会话替身（供给路径所需的 render/params 桩）。"""

    def __init__(self, photo, session_id: str) -> None:
        self.photo_id = photo.photo_id
        self.raw_path = Path(photo.path)
        self.session_id = session_id
        self.params: dict = {}
        self.generation = 0
        self.region_masks = None
        self.region_masks_source: str | None = None

    def update_params(self, patch: dict) -> int:
        self.params.update(dict(patch or {}))
        self.generation += 1
        return self.generation

    def canonical_params(self) -> dict:
        return dict(self.params)

    def render(self, long_edge: int = 1024) -> np.ndarray:
        del long_edge
        return np.full((64, 96, 3), 128, dtype=np.uint8)


class StubSegmenter:
    """multi 替身: 记录调用与并发时间戳（互斥验证用）。"""

    def __init__(self, delay: float = 0.0,
                 exc: Exception | None = None) -> None:
        self.calls = 0
        self.delay = delay
        self.exc = exc
        self.spans: list[tuple[float, float]] = []   # (start, end) per call

    @property
    def route_table(self) -> dict[str, str]:
        return {"sky": "segformer", "plant": "segformer",
                "person": "rfdetr"}

    def segment(self, image_rgb, prompts):
        self.calls += 1
        t0 = time.perf_counter()
        if self.delay:
            time.sleep(self.delay)
        if self.exc is not None:
            self.spans.append((t0, time.perf_counter()))
            raise self.exc
        out = {p: np.ones((8, 8), np.float32) for p in prompts}
        self.spans.append((t0, time.perf_counter()))
        return out


def _make_runtime(tmp_path: Path, stub, segmenter_type: str = "multi"):
    runtime = PixoServiceRuntime(
        profile=object(),
        work_dir=tmp_path / "exports",
        session_factory=lambda photo, sid: FakeSession(photo, sid),
    )
    if stub is not None:
        runtime._segmenter = stub
    runtime.segmenter_type = segmenter_type
    return runtime


# ---------------------------------------------------------------------------
# 门控 / 状态机
# ---------------------------------------------------------------------------

def test_warmup_mock_segmenter_skipped(tmp_path):
    """mock 无权重可加载: 预热跳过（不装可用语义）, health 暴露。"""
    runtime = _make_runtime(tmp_path, None, segmenter_type="mock")
    info = runtime.warm_segmenter()
    assert info["status"] == "skipped"
    assert info["reason"] == "segmenter=mock"
    assert runtime.health()["segmenter"]["warmup"]["status"] == "skipped"


def test_warmup_env_off_skipped(monkeypatch, tmp_path):
    """PIXO_SEGMENTER_WARMUP=0/false/off/no → 跳过（沿 scorer 惯例, 缺省开）。"""
    stub = StubSegmenter()
    runtime = _make_runtime(tmp_path, stub, segmenter_type="multi")
    for val in ("0", "false", "off", "no"):
        monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", val)
        info = runtime.warm_segmenter()
        assert info["status"] == "skipped"
        assert info["reason"] == "env_off"
    assert stub.calls == 0
    monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", "1")
    assert _segmenter_warmup_enabled() is True     # 缺省开


def test_warmup_multi_done_idempotent(monkeypatch, tmp_path):
    """multi + 缺省开: done + 计时 + 暖 prompts; 幂等（重复预热不重推理）。"""
    monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", "1")
    stub = StubSegmenter()
    runtime = _make_runtime(tmp_path, stub, segmenter_type="multi")
    info = runtime.warm_segmenter()
    assert info["status"] == "done"
    assert info["duration_s"] >= 0
    assert info["prompts"] == ["sky", "plant", "person"]
    assert info["backends"] == ["rfdetr", "segformer"]
    assert stub.calls == 1
    info2 = runtime.warm_segmenter()
    assert info2["status"] == "done"
    assert stub.calls == 1                          # 幂等: 不重推理


def test_warmup_failure_marks_failed(monkeypatch, tmp_path):
    """预热推理异常 → status=failed + error 记录（不炸, 服务照常）。"""
    monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", "1")
    stub = StubSegmenter(exc=RuntimeError("weights missing"))
    runtime = _make_runtime(tmp_path, stub, segmenter_type="multi")
    info = runtime.warm_segmenter()
    assert info["status"] == "failed"
    assert "weights missing" in info["error"]


def test_health_reports_warmup_info(monkeypatch, tmp_path):
    monkeypatch.delenv("PIXO_SEGMENTER_WARMUP", raising=False)
    runtime = _make_runtime(tmp_path, StubSegmenter(), segmenter_type="multi")
    runtime.warm_segmenter()
    health = runtime.health()
    warm = health["segmenter"]["warmup"]
    assert warm["status"] == "done"
    assert "duration_s" in warm


# ---------------------------------------------------------------------------
# 互斥: 预热与供给的 segment 调用串行（推理锁）
# ---------------------------------------------------------------------------

def test_supply_nonblocking_during_warm_then_hot(monkeypatch, tmp_path):
    """R16 非阻塞语义: 预热持推理锁期间 GET /region 立即返回（reason=
    segmenter_warming, 不推理不阻塞）; 锁释放后重查 → 供给热态执行。"""
    monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", "1")
    monkeypatch.setenv("PIXO_REGION_SUPPLY", "1")
    stub = StubSegmenter(delay=0.3)
    runtime = _make_runtime(tmp_path, stub, segmenter_type="multi")
    # 直构 session（不经 RAW 校验）: PhotoRecord 最小路径 + 索引登记
    from pixo.service.runtime import PhotoRecord
    photo = PhotoRecord(photo_id="p1", path=Path("x.nef"))
    runtime.photos["p1"] = photo
    session = runtime.session_factory(photo, "s1")
    runtime.sessions["s1"] = session
    runtime._session_photo["s1"] = "p1"

    with runtime._segmenter_infer_lock:             # 模拟预热持锁
        t0 = time.perf_counter()
        status = runtime.region_status("s1")
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, f"预热持锁期间供给阻塞: {elapsed:.2f}s"
        assert status["available"] is False
        assert status["reason"] == "segmenter_warming"
    assert stub.calls == 0                          # 预热持锁期间未推理
    # 锁释放 → 重查: 供给热态执行
    status = runtime.region_status("s1")
    assert status["available"] is True
    assert status["reason"] is None
    assert stub.calls == 1


# ---------------------------------------------------------------------------
# 真权重 e2e（RAW 可达时）: 预热吸收冷启 + 预热中请求不阻塞
# ---------------------------------------------------------------------------

_REAL_RAW = REAL_A


@pytest.mark.skipif(_REAL_RAW is None, reason=RAW_SKIP_REASON)
def test_warmup_absorbs_cold_start_and_nonblocking(monkeypatch):
    """真权重: 预热耗时 ≈17s；预热后首供给 <3s（对照 R15 冷启 17.7s）；
    预热进行中 GET /region 立即响应（不阻塞）。"""
    monkeypatch.setenv("PIXO_SEGMENTER", "multi")
    monkeypatch.setenv("PIXO_REGION_SUPPLY", "1")
    monkeypatch.delenv("PIXO_SEGMENTER_WARMUP", raising=False)
    from pixo.service.runtime import PixoServiceRuntime as _RT

    runtime = _RT()
    if runtime.segmenter_type != "multi":
        pytest.skip("multi 分割器构造失败回退 mock（权重不可用）")
    photo = runtime.create_photo(str(_REAL_RAW))
    session = runtime.create_session(photo.photo_id)

    # 后台预热（模拟 app lifespan 的 daemon 线程启动方式）
    t_warm = threading.Thread(target=runtime.warm_segmenter, daemon=True)
    t0 = time.perf_counter()
    t_warm.start()

    # 预热进行中: GET /region 非阻塞快速返回（warming/未注入均属不挡请求）
    st = runtime.region_status(session.session_id)
    t_status = time.perf_counter() - t0
    assert t_status < 3.0, f"预热中状态请求被阻塞: {t_status:.2f}s"
    assert st["available"] is False                 # 掩码未注入（等待后端热）

    t_warm.join(timeout=60)
    info = runtime.segmenter_warmup_info
    print(f"\n[R16 成本实测] 预热耗时 {info.get('duration_s')}s "
          f"backends={info.get('backends')}")
    assert info["status"] == "done"
    # NC 门控: 预热后端 ⊆ 非受限路由（缺省 PIXO_ALLOW_RESTRICTED 未放行）
    assert set(info.get("backends", [])) <= {"segformer", "rfdetr"}

    # 预热后首供给: 秒级（对照 R15 冷启 17.7s）。本 RAW 对 segformer 全零
    # → 供给后 segmenter_no_masks（B1 修复语义, 该 RAW 的真实可用面为空）
    t0 = time.perf_counter()
    status = runtime.region_status(session.session_id)
    supply_s = time.perf_counter() - t0
    print(f"[R16 成本实测] 预热后首供给 {supply_s:.2f}s reason="
          f"{status.get('reason')} prompts={status.get('prompts')}")
    assert supply_s < 3.0, f"预热后首供给仍慢: {supply_s:.2f}s"
    assert status["reason"] == "segmenter_no_masks"
    # patch 后渲染逐位不变（无有效掩码 → HSM 不应用）
    runtime.update_params(session.session_id, {
        "region_adjust": {"enabled": True,
                          "regions": {"sky": {"exposure": -0.5}}}})
    base = session.render(long_edge=192)
    after = session.render(long_edge=192)
    assert np.array_equal(after, base)
