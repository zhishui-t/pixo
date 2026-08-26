"""T16: RawPreviewSession 缓存增量 / generation / 编码输出测试。"""
from __future__ import annotations

import copy
import json
import os

import numpy as np
import pytest

import pixo.render.web.session as sess_mod
from pixo.render.web.session import RawPreviewSession
from pixo.render.pipeline.context import DOMAIN_GAMMA_RGB


class _FakeRaw:
    def close(self):
        pass


class _FakeStage:
    def __init__(self, name, calls, domain_out=DOMAIN_GAMMA_RGB):
        self.name = name
        self.calls = calls
        self.domain_out = domain_out

    def wants(self, ctx):
        return True

    def run(self, ctx):
        self.calls.append(self.name)
        # 保持输入分辨率：真实管线 stage 不改分辨率，raw48 sidecar 的
        # tier-shape 语义（sidecar 尺寸 == 渲染输出尺寸）才能在 fake 环境成立。
        ctx.image = np.full(ctx.image.shape, 0.5, dtype=np.float32)
        ctx.domain = self.domain_out


class _FakePipe:
    def __init__(self, stages):
        self.stages = stages


@pytest.fixture()
def session_env(monkeypatch):
    calls = []
    decode_calls = []
    seen_ctx = []

    monkeypatch.setattr(sess_mod.rawpy, "imread",
                        staticmethod(lambda path: _FakeRaw()))

    def fake_decode(raw, raw_path=None):
        decode_calls.append(1)
        return np.full((8, 8, 3), 0.2, dtype=np.float32)

    monkeypatch.setattr(sess_mod, "decode_cfa_half", fake_decode)

    stages = [_FakeStage("s1", calls), _FakeStage("s2", calls)]
    monkeypatch.setattr(sess_mod, "build_default_pipeline",
                        lambda prof=None, params=None: _FakePipe(stages))

    # 每次 stage.run 前把 ctx 交给用例检查（不改变现有缓存语义）。
    orig_run = None

    def wrap_run(ctx):
        seen_ctx.append(ctx)

    for stage in stages:
        orig_run = stage.run
        stage.run = lambda ctx, _orig=orig_run, _wrap=wrap_run: (
            _wrap(ctx), _orig(ctx))

    return {"calls": calls, "decode_calls": decode_calls,
            "stages": stages, "seen_ctx": seen_ctx}


def test_decode_once_and_stage_cache_hit(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    out1 = sess.render(long_edge=8)
    assert out1.dtype == np.uint8
    assert len(session_env["decode_calls"]) == 1
    assert session_env["calls"] == ["s1", "s2"]

    out2 = sess.render(long_edge=8)
    assert len(session_env["decode_calls"]) == 1
    assert session_env["calls"] == ["s1", "s2"]  # stage 缓存全部命中


def test_generation_increment_and_incremental_recompute(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    sess.render(long_edge=8)
    assert sess.generation == 0
    assert sess.update_params({"s2": {"x": 1}}) == 1
    sess.render(long_edge=8)
    # 缓存键含全 stage 参数指纹 (跨级参数依赖, 见
    # test_stage_cache_key_includes_all_stage_params): 任一 stage 参数变化
    # → 所有 stage 的键都变 → 全链重算 (正确性优先于增量)。
    assert session_env["calls"] == ["s1", "s2", "s1", "s2"]


def test_encode_cache_and_raw48_sidecar(session_env, tmp_path):
    sess = RawPreviewSession("x.nef", prof=object())
    data1 = sess.encode(long_edge=8, fmt="jpeg")
    data2 = sess.encode(long_edge=8, fmt="jpeg")
    assert data1 == data2

    path = sess.save_encoded(tmp_path, long_edge=8, fmt="raw48")
    assert path.exists()
    side = path.with_suffix(".json")
    assert side.exists()
    meta = json.loads(side.read_text(encoding="utf-8"))
    assert meta["format"] == "raw48"
    assert meta["channels"] == "RGB"
    assert meta["value_range"] == [0, 65535]


def test_encoding_cache_invalidates_on_generation_change(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    sess.encode(long_edge=8, fmt="jpeg")
    before = set(sess._encoding_cache)
    assert len(before) == 1

    assert sess.update_params({"s1": {"x": 1}}) == 1
    sess.encode(long_edge=8, fmt="jpeg")
    after = set(sess._encoding_cache)
    # generation 变化后必须生成新 key，不能复用旧 generation 的编码缓存
    assert after - before, "generation 变化后未新增编码缓存 key"


def test_generation_prevents_old_result_reuse(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    old_data = sess.encode(long_edge=8, fmt="jpeg")
    old_key = next(iter(sess._encoding_cache))

    # 模拟旧 generation 的异步结果在参数更新后才“写回”缓存
    sess.update_params({"s1": {"x": 2}})
    sess._encoding_cache[old_key] = b"stale-old-result"

    new_data = sess.encode(long_edge=8, fmt="jpeg")
    # 当前 generation 使用新 key，不应读到旧 key 的 stale 数据
    assert new_data != b"stale-old-result"
    assert old_key not in {k for k in sess._encoding_cache if k[4] == sess.generation}
    assert len(sess._encoding_cache) == 2


def test_camera_wb_injected_into_stage_context(session_env, monkeypatch):
    import pixo.render.core.io as core_io

    expected = np.array([1.6, 1.0, 1.4], dtype=np.float32)
    monkeypatch.setattr(core_io, "camera_neutral_wb_cached",
                        lambda raw, raw_path=None: expected.copy())

    sess = RawPreviewSession("x.nef", prof=object())
    sess.render(long_edge=8)
    for ctx in session_env["seen_ctx"]:
        np.testing.assert_array_equal(ctx.state["camera_wb"], expected)


def test_state_extras_injected_into_stage_context(session_env):
    """state_extras（归一化框）应注入每个 stage 的 StageContext.state。"""
    extras = {"face_boxes": [[0.1, 0.1, 0.4, 0.4]],
              "subject_boxes": [[0.3, 0.3, 0.8, 0.9]]}
    sess = RawPreviewSession("x.nef", prof=object())
    sess.render(long_edge=8, state_extras=extras)
    assert session_env["seen_ctx"], "应捕获至少一个 stage ctx"
    for ctx in session_env["seen_ctx"]:
        assert list(ctx.state.get("face_boxes")) == [[0.1, 0.1, 0.4, 0.4]]
        assert list(ctx.state.get("subject_boxes")) == [[0.3, 0.3, 0.8, 0.9]]


def test_state_extras_absent_or_empty_not_injected(session_env):
    """缺省 None / 空 dict 都不注入，保持旧行为。"""
    sess = RawPreviewSession("y.nef", prof=object())
    sess.render(long_edge=8)
    sess.render(long_edge=8, state_extras={})
    for ctx in session_env["seen_ctx"]:
        assert "face_boxes" not in ctx.state
        assert "subject_boxes" not in ctx.state


def test_16bit_formats_force_16bit_render(session_env):
    import cv2

    sess = RawPreviewSession("x.nef", prof=object())
    data = sess.encode(long_edge=8, fmt="png16")
    key = next(iter(sess._encoding_cache))
    assert key[3] == 16
    arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8),
                       cv2.IMREAD_UNCHANGED)
    assert arr.dtype == np.uint16
    assert int(arr[0, 0, 0]) == 32768


def test_raw48_sidecar_has_shape_and_endian(session_env, tmp_path):
    sess = RawPreviewSession("x.nef", prof=object())
    path = sess.save_encoded(tmp_path, long_edge=8, fmt="raw48")
    side = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    # sidecar 尺寸取自 tier（渲染输出与 tier 同分辨率），fake 解码 8x8
    assert side["width"] == 8 and side["height"] == 8
    assert side["endian"] == "big"
    assert side["bits_per_channel"] == 16
    assert side["value_range"] == [0, 65535]


def test_update_params_deep_merge_keeps_other_stage_params(session_env):
    sess = RawPreviewSession("x.nef", prof=object(),
                             params={"s2": {"x": 1, "y": 2}})
    sess.update_params({"s2": {"x": 9}})
    assert sess.params["s2"] == {"x": 9, "y": 2}


def test_encoding_cache_lru_eviction(session_env):
    sess = RawPreviewSession("x.nef", prof=object(), max_encoding_entries=2)
    for gen in range(3):
        sess.update_params({"s1": {"x": gen}})
        sess.encode(long_edge=8, fmt="jpeg")
    assert len(sess._encoding_cache) == 2
    assert next(iter(sess._encoding_cache))[4] == 2


def test_canonical_params_include_user_overrides(session_env):
    sess = RawPreviewSession("x.nef", prof=object(),
                             params={"s1": {"x": 1}, "s2": {"y": 2}})
    canonical = sess.canonical_params()
    assert canonical["s1"] == {"x": 1}
    assert canonical["s2"] == {"y": 2}


def test_raw_file_change_invalidates_decode_cache(session_env, tmp_path):
    raw_file = tmp_path / "x.nef"
    raw_file.write_bytes(b"a")
    sess = RawPreviewSession(raw_file, prof=object())
    sess.render(long_edge=8)
    assert len(session_env["decode_calls"]) == 1

    raw_file.write_bytes(b"bb")
    os.utime(raw_file, ns=(1_000_000_000, 2_000_000_000))
    assert sess._raw_version() != (1_000_000_000, 2)
    sess.render(long_edge=8)
    assert len(session_env["decode_calls"]) == 2



class _StatefulStage:
    """s1 写 state，s2 读 state；s1 输出图像保持不变以暴露 state 指纹缺失。"""

    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def wants(self, ctx):
        return True

    def run(self, ctx):
        self.calls.append(self.name)
        params = ctx.config["stages"].get(self.name, {})
        if self.name == "s1":
            ctx.state["wb"] = float(params.get("value", 1.0))
            ctx.image = np.full((4, 4, 3), 0.5, dtype=np.float32)
        else:
            wb = float(ctx.state.get("wb", 1.0))
            ctx.image = np.full((4, 4, 3), wb, dtype=np.float32)
        ctx.domain = DOMAIN_GAMMA_RGB


def test_stage_cache_state_fingerprint_invalidates(monkeypatch):
    calls = []
    stages = [_StatefulStage("s1", calls), _StatefulStage("s2", calls)]

    monkeypatch.setattr(sess_mod.rawpy, "imread",
                        staticmethod(lambda path: _FakeRaw()))
    monkeypatch.setattr(sess_mod, "decode_cfa_half",
                        lambda raw, raw_path=None: np.full(
                            (8, 8, 3), 0.2, dtype=np.float32))
    monkeypatch.setattr(sess_mod, "build_default_pipeline",
                        lambda prof=None, params=None: _FakePipe(stages))

    sess = RawPreviewSession("x.nef", prof=object(),
                             params={"s1": {"value": 0.25}})
    out1 = sess.render(long_edge=8)
    assert calls == ["s1", "s2"]
    assert float(out1[0, 0, 0]) == 64.0

    # 同参数第二次：应全部命中 stage 缓存
    sess.render(long_edge=8)
    assert calls == ["s1", "s2"]

    # 只改 s1 参数：s1 必须重算，s2 的 state 输入变化也必须重算
    sess.update_params({"s1": {"value": 0.5}})
    out2 = sess.render(long_edge=8)
    assert calls == ["s1", "s2", "s1", "s2"]
    assert float(out2[0, 0, 0]) == 128.0


# ---- t31: 异步 generation 防御 ----

def test_accept_async_result_discards_stale_generation(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    old = np.zeros((4, 4, 3), dtype=np.uint8)
    assert sess._accept_async_result(0, old) is True
    assert sess.latest_result is old

    sess.update_params({"s1": {"x": 1}})
    stale = np.full((4, 4, 3), 7, dtype=np.uint8)
    assert sess._accept_async_result(0, stale) is False
    # 旧 generation 结果不会成为当前 generation 的 latest_result
    assert sess.latest_result is None


def test_async_out_of_order_old_does_not_overwrite_new(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    old = np.full((4, 4, 3), 3, dtype=np.uint8)
    new = np.full((4, 4, 3), 9, dtype=np.uint8)

    sess._accept_async_result(0, old)
    sess.update_params({"s1": {"x": 1}})   # generation -> 1
    sess._accept_async_result(1, new)
    # 旧 gen0 迟到
    assert sess._accept_async_result(0, old) is False
    assert sess.latest_result is new


def test_render_snapshot_stale_before_work_returns_none(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    sess.update_params({"s1": {"x": 1}})   # generation -> 1
    result = sess._render_snapshot(
        0, copy.deepcopy(sess.params), 8, 8, "cfa_half_native")
    assert result is None
    assert sess.latest_result is None


def test_submit_render_async_completion(session_env):
    sess = RawPreviewSession("x.nef", prof=object())
    fut = sess.submit_render(long_edge=8)
    result = fut.result(timeout=5)
    assert result is not None
    assert result.dtype == np.uint8
    assert sess.latest_result is result
    sess.close()


# ---- 跨级参数依赖: 缓存键含全 stage 参数指纹 ----

class _CrossStageParamStage:
    """模拟 exposure 探针: 直接读**另一个** stage (whitebalance) 的参数决定输出。

    自身参数恒为空、输入图 (解码层) 恒不变、运行前 state 恒不变 —— 三指纹
    全部不变, 只有 whitebalance 参数在变, 用来暴露缓存键缺失跨级依赖的 bug。
    """

    def __init__(self, name, calls, reads):
        self.name = name
        self.calls = calls
        self.reads = reads   # 本 stage 输出依赖的其它 stage 参数名

    def wants(self, ctx):
        return True

    def run(self, ctx):
        self.calls.append(self.name)
        v = 0.5
        for dep in self.reads:
            dep_params = ctx.params_for(dep)
            # 模拟 modules/exposure.py 探针读 whitebalance 的 mode/temp/tint
            if dep_params.get("mode", "as_shot") == "manual":
                v *= 1.0 + float(dep_params.get("temp", 0.0)) / 100000.0
        ctx.image = np.full((4, 4, 3), v, dtype=np.float32)
        ctx.domain = DOMAIN_GAMMA_RGB


def test_stage_cache_key_includes_all_stage_params(monkeypatch):
    """改 whitebalance 参数后, 读它的 exposure 类 stage 必须重算 (不得命中旧缓存)。

    回归: 旧缓存键 (stage.name, 本 stage 参数指纹, 输入图指纹, state 指纹) 不含
    其它 stage 参数, 而 exposure 探针直接读 whitebalance 的 mode/temp/tint ——
    改 WB 后 exposure 三指纹不变命中旧缓存, EV 不随 WB 更新。
    """
    calls = []
    # 简单透传 stage (whitebalance 本体在真实链路里, 这里只需占位)
    class _Sink:
        name = "whitebalance"

        def wants(self, ctx):
            return True

        def run(self, ctx):
            calls.append(self.name)
            # 不改 image/domain: 只作为被读取参数的 stage 存在

    stages = [_CrossStageParamStage("exposure", calls, reads=["whitebalance"]),
              _Sink()]
    monkeypatch.setattr(sess_mod.rawpy, "imread",
                        staticmethod(lambda path: _FakeRaw()))
    monkeypatch.setattr(sess_mod, "decode_cfa_half",
                        lambda raw, raw_path=None: np.full(
                            (8, 8, 3), 0.2, dtype=np.float32))
    monkeypatch.setattr(sess_mod, "build_default_pipeline",
                        lambda prof=None, params=None: _FakePipe(stages))

    sess = RawPreviewSession("x.nef", prof=object())
    out1 = sess.render(long_edge=8)
    assert calls == ["exposure", "whitebalance"]
    v1 = float(out1[0, 0, 0])
    assert abs(v1 - (0.5 * 255.0 + 0.5)) < 1.0  # as_shot: 无 WB 修正

    # 同参数重复渲染: 全 stage 缓存命中 (键含全参数指纹不破坏命中)
    sess.render(long_edge=8)
    assert calls == ["exposure", "whitebalance"]

    # 改 whitebalance (manual/temp) —— exposure 必须重算, 输出随 WB 变化
    sess.update_params({"whitebalance": {"mode": "manual", "temp": 5200.0}})
    out2 = sess.render(long_edge=8)
    assert calls == ["exposure", "whitebalance", "exposure", "whitebalance"], (
        "改 whitebalance 参数后, 读 WB 参数的 exposure stage 命中了陈旧缓存")
    v2 = float(out2[0, 0, 0])
    expected2 = 0.5 * (1.0 + 5200.0 / 100000.0)
    assert abs(v2 - (expected2 * 255.0 + 0.5)) < 1.0, (
        f"第二次渲染未反映新 WB 参数: got {v2}, want ~{expected2 * 255.0}")
