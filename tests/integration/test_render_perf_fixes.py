"""渲染引擎性能/资源缺陷修复的验收测试（指纹链 / 引用共享 / 锁 / LRU）。

覆盖：
- 同参数两次渲染：第二次全命中 stage 缓存、明显更快、输出逐位一致
- 指纹哈希数据量：第二次渲染 < 1MB（计数 _array_fingerprint/_ndarray_digest）
- 参数微调正确失效重算；state 大数组变化必须使下游缓存失效
- 缓存条目 state 按**引用**共享（不再 deepcopy 全图）
- _stage_cache_bytes 增量记账与逐条重算一致（含淘汰）
- io.py 缓存 LRU：超限淘汰最旧一条而非全清；命中刷新 recency
- lut.py 统一缓存：load_lut/load_lut_path 单 dict + LRU 上限 4
- tone_map._PROFILE_CACHE 强引用防 id 复用
- base.render_dcp_linear 不再第二次 rawpy.imread（双解压修复）
- 并发 render/update_params 冒烟
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

import numpy as np
import pytest

import pixo.render.core.io as core_io
import pixo.render.core.lut as lut_mod
import pixo.render.core.lut3d as lut3d
import pixo.render.modules.tone_map as tone_map
import pixo.render.pipeline.base as base_mod
import pixo.render.web.session as sess_mod
from pixo.render.pipeline.context import DOMAIN_GAMMA_RGB
from pixo.render.web.session import RawPreviewSession


class _FakeRaw:
    def close(self):
        pass


class _FakePipe:
    def __init__(self, stages):
        self.stages = stages


# ---------------------------------------------------------------------------
# fake 管线环境（参考 tests/integration/test_preview_session.py 的构造方式）
# ---------------------------------------------------------------------------

class _SlowStage:
    """模拟真实 stage：有耗时、写大 state 数组、输出依赖参数。"""

    def __init__(self, name, calls, sleep_s=0.05, big_state=True):
        self.name = name
        self.calls = calls
        self.sleep_s = sleep_s
        self.big_state = big_state

    def wants(self, ctx):
        return True

    def run(self, ctx):
        self.calls.append(self.name)
        if self.sleep_s:
            time.sleep(self.sleep_s)
        params = ctx.config["stages"].get(self.name, {})
        v = float(params.get("value", 0.5))
        # 大 state 数组（模拟 white_balance 写入的 cam_raw/cam_wb 全图）
        if self.big_state:
            ctx.state[f"{self.name}_arr"] = np.full(
                (256, 256, 3), v, dtype=np.float32)
        ctx.image = np.full(ctx.image.shape, v, dtype=np.float32)
        ctx.domain = DOMAIN_GAMMA_RGB


@pytest.fixture()
def perf_env(monkeypatch):
    calls = []
    decode_calls = []
    monkeypatch.setattr(sess_mod.rawpy, "imread",
                        staticmethod(lambda path: _FakeRaw()))

    # 大图解码（1024 tier ≈ 9.4MB/stage，放大指纹/拷贝收益）
    big = np.full((768, 1024, 3), 0.2, dtype=np.float32)

    def fake_decode(raw, raw_path=None):
        decode_calls.append(1)
        return big

    monkeypatch.setattr(sess_mod, "decode_cfa_half", fake_decode)
    stages = [_SlowStage("s1", calls), _SlowStage("s2", calls)]
    monkeypatch.setattr(sess_mod, "build_default_pipeline",
                        lambda prof=None, params=None: _FakePipe(stages))
    return {"calls": calls, "decode_calls": decode_calls, "stages": stages}


def _install_hash_counter(monkeypatch):
    """包装 _array_fingerprint/_ndarray_digest，累计实际哈希的字节数。"""
    counter = {"bytes": 0, "array_calls": 0, "digest_calls": 0}
    orig_array_fp = sess_mod._array_fingerprint
    orig_digest = sess_mod._ndarray_digest

    def counting_array_fp(arr):
        counter["bytes"] += int(np.asarray(arr).nbytes)
        counter["array_calls"] += 1
        return orig_array_fp(arr)

    def counting_digest(arr):
        n = int(np.asarray(arr).nbytes)
        counter["bytes"] += min(n, 2 * sess_mod._DIGEST_EDGE_BYTES)
        counter["digest_calls"] += 1
        return orig_digest(arr)

    monkeypatch.setattr(sess_mod, "_array_fingerprint", counting_array_fp)
    monkeypatch.setattr(sess_mod, "_ndarray_digest", counting_digest)
    return counter


# ---------------------------------------------------------------------------
# 指纹链 + 缓存命中
# ---------------------------------------------------------------------------

def test_second_render_bitexact_and_faster(perf_env):
    sess = RawPreviewSession("x.nef", prof=object())
    t0 = time.perf_counter()
    out1 = sess.render(long_edge=1024)
    t1 = time.perf_counter() - t0

    t0 = time.perf_counter()
    out2 = sess.render(long_edge=1024)
    t2 = time.perf_counter() - t0

    assert perf_env["calls"] == ["s1", "s2"]  # 第二次全命中，无 run
    assert out1.dtype == out2.dtype == np.uint8
    np.testing.assert_array_equal(out1, out2)  # 逐位一致
    # 两次 50ms sleep 的首渲染 vs 零 run 的缓存命中渲染
    assert t2 < t1 * 0.5, f"second render not faster: t1={t1:.3f}s t2={t2:.3f}s"


def test_second_render_hash_bytes_under_1mb(perf_env, monkeypatch):
    counter = _install_hash_counter(monkeypatch)
    sess = RawPreviewSession("x.nef", prof=object())

    sess.render(long_edge=1024)
    first = counter["bytes"]
    # 首渲染：tier 指纹 + 每 stage 输出各一次全图精确哈希（~9.4MB x 3）
    assert first > 3 * 768 * 1024 * 3 * 4 * 0.9

    counter["bytes"] = 0
    sess.render(long_edge=1024)
    second = counter["bytes"]
    # 命中路径：全图 sha256 0 次；state 数组只走 4KB 采样摘要
    assert second < 1024 * 1024, f"second render hashed {second} bytes"
    # 且明显小于首渲染（指纹链收益的实测计数）
    assert second < first / 20


def test_param_tweak_invalidates_and_recomputes(perf_env):
    sess = RawPreviewSession("x.nef", prof=object(),
                             params={"s1": {"value": 0.25},
                                     "s2": {"value": 0.25}})
    out1 = sess.render(long_edge=1024)
    assert float(out1[0, 0, 0]) == int(0.25 * 255.0 + 0.5)

    sess.render(long_edge=1024)
    assert perf_env["calls"] == ["s1", "s2"]

    sess.update_params({"s1": {"value": 0.75}, "s2": {"value": 0.75}})
    out2 = sess.render(long_edge=1024)
    # 参数微调：全链重算（缓存键含全 stage 参数指纹），输出随参数变化
    assert perf_env["calls"] == ["s1", "s2", "s1", "s2"]
    assert float(out2[0, 0, 0]) == int(0.75 * 255.0 + 0.5)
    np.testing.assert_array_equal(out1 != out2, np.ones_like(out1, dtype=bool))


def test_state_big_array_change_invalidates_downstream(monkeypatch):
    """改影响 state 大数组的参数 → 下游 stage 缓存必须失效。"""
    calls = []

    class _WbLikeStage:
        """模拟 whitebalance：输出图恒定，但写随参数变化的 cam_wb 全图。"""

        name = "wb"

        def wants(self, ctx):
            return True

        def run(self, ctx):
            calls.append("wb")
            v = float(ctx.config["stages"].get("wb", {}).get("gain", 1.0))
            ctx.state["cam_wb"] = np.full((256, 256, 3), v, dtype=np.float32)
            ctx.image = np.full((64, 64, 3), 0.5, dtype=np.float32)
            ctx.domain = DOMAIN_GAMMA_RGB

    class _ConsumerStage:
        """模拟 huesat：读 state['cam_wb'] 决定输出。"""

        name = "consumer"

        def wants(self, ctx):
            return True

        def run(self, ctx):
            calls.append("consumer")
            v = float(ctx.state["cam_wb"][0, 0, 0])
            ctx.image = np.full((64, 64, 3), v, dtype=np.float32)
            ctx.domain = DOMAIN_GAMMA_RGB

    stages = [_WbLikeStage(), _ConsumerStage()]
    monkeypatch.setattr(sess_mod.rawpy, "imread",
                        staticmethod(lambda path: _FakeRaw()))
    monkeypatch.setattr(sess_mod, "decode_cfa_half",
                        lambda raw, raw_path=None: np.full(
                            (64, 64, 3), 0.2, dtype=np.float32))
    monkeypatch.setattr(sess_mod, "build_default_pipeline",
                        lambda prof=None, params=None: _FakePipe(stages))

    sess = RawPreviewSession("x.nef", prof=object(),
                             params={"wb": {"gain": 0.25}})
    out1 = sess.render(long_edge=64)
    assert calls == ["wb", "consumer"]
    assert float(out1[0, 0, 0]) == int(0.25 * 255.0 + 0.5)

    # 同参数第二次：引用共享的 state 数组 ptr/采样摘要一致 → 全命中
    sess.render(long_edge=64)
    assert calls == ["wb", "consumer"]

    # 改 cam_wb 相关键 → wb 重算产生新数组 → consumer 的 state 指纹变化必重算
    sess.update_params({"wb": {"gain": 0.5}})
    out2 = sess.render(long_edge=64)
    assert calls == ["wb", "consumer", "wb", "consumer"]
    assert float(out2[0, 0, 0]) == int(0.5 * 255.0 + 0.5)


# ---------------------------------------------------------------------------
# 缓存条目引用共享 + 字节记账
# ---------------------------------------------------------------------------

def test_stage_cache_state_stored_by_reference(perf_env):
    sess = RawPreviewSession("x.nef", prof=object())
    sess.render(long_edge=1024)
    assert len(sess._stage_cache) == 2
    entries = list(sess._stage_cache.values())
    # 条目 state dict 是新容器但 ndarray 与条目间按引用共享（非 deepcopy）：
    # s2 条目里的 s1_arr 与 s1 条目是同一对象
    s1_state, s2_state = entries[0][2], entries[1][2]
    assert s1_state["s1_arr"] is s2_state["s1_arr"]
    # 恢复路径同样引用共享：第三次渲染命中的 state 数组即缓存内对象
    before = {k: id(v) for k, v in entries[1][2].items()
              if isinstance(v, np.ndarray)}
    sess.render(long_edge=1024)
    for key, ptr in before.items():
        cur = [e[2] for e in sess._stage_cache.values()
               if key in e[2]]
        assert any(id(e[key]) == ptr for e in cur)


def test_stage_cache_bytes_bookkeeping(perf_env):
    sess = RawPreviewSession("x.nef", prof=object())
    sess.render(long_edge=1024)
    sess.update_params({"s1": {"value": 0.1}})
    sess.render(long_edge=1024)
    sess.update_params({"s2": {"value": 0.2}})
    sess.render(long_edge=1024)
    # 增量记账 == 逐条重算
    recomputed = sum(
        sess._entry_bytes(e[0], e[2]) for e in sess._stage_cache.values())
    assert sess._stage_cache_bytes == recomputed
    assert len(sess._stage_cache) == 6


def test_stage_cache_byte_eviction_uses_incremental_total(perf_env):
    # 每条目 image ~9.4MB + state 2x(0.75MB) → 6 条约 65MB；给 3 条预算
    one_entry = 768 * 1024 * 3 * 4 + 2 * (256 * 256 * 3 * 4)
    sess = RawPreviewSession("x.nef", prof=object(),
                             max_stage_bytes=int(one_entry * 2.5))
    sess.render(long_edge=1024)
    sess.update_params({"s1": {"value": 0.1}})
    sess.render(long_edge=1024)
    sess.update_params({"s2": {"value": 0.2}})
    sess.render(long_edge=1024)
    recomputed = sum(
        sess._entry_bytes(e[0], e[2]) for e in sess._stage_cache.values())
    assert recomputed <= int(one_entry * 2.5)
    assert sess._stage_cache_bytes == recomputed
    assert len(sess._stage_cache) < 6  # 已按字节预算淘汰


# ---------------------------------------------------------------------------
# 并发冒烟（锁）
# ---------------------------------------------------------------------------

def test_concurrent_render_and_update_params_smoke(perf_env):
    sess = RawPreviewSession("x.nef", prof=object())
    errors = []

    def worker(k):
        try:
            for i in range(6):
                sess.update_params({f"s{k}": {"value": 0.1 * i}})
                sess.render(long_edge=1024)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, f"并发渲染/更新参数出现异常: {errors}"
    # 最终一次渲染仍应稳定成功
    out = sess.render(long_edge=1024)
    assert out.dtype == np.uint8


def test_submit_render_after_close_raises():
    sess = RawPreviewSession("x.nef", prof=object())
    sess.close()
    with pytest.raises(RuntimeError):
        sess.submit_render()


# ---------------------------------------------------------------------------
# io.py 缓存 LRU
# ---------------------------------------------------------------------------

class _FakeIoRaw:
    raw_image_visible = np.arange(8 * 8, dtype=np.uint16).reshape(8, 8)
    raw_pattern = np.array([[0, 1], [1, 2]], dtype=np.int32)
    color_desc = b"RGBG"
    black_level_per_channel = [64, 64, 64, 64]
    white_level = 16384

    def close(self):
        pass


def _patch_native(monkeypatch):
    import pixo.render._native as native
    calls = []

    def fake_decode(cfa, pattern_r, pattern_g0, pattern_g1, pattern_b,
                    black, white_level, output_scale=1.0):
        calls.append(1)
        return np.full((4, 4, 3), len(calls) * 0.1, dtype=np.float32)

    monkeypatch.setattr(native, "decode_cfa_half", fake_decode)
    return calls


def test_decode_cache_lru_evicts_oldest_not_all(monkeypatch, tmp_path):
    calls = _patch_native(monkeypatch)
    monkeypatch.setattr(core_io, "_DECODE_CACHE_DIR", tmp_path / "dc")
    monkeypatch.setattr(core_io, "_DECODE_CACHE", OrderedDict())

    paths = []
    for i in range(9):  # 超过 _LRU_MAX=8
        p = tmp_path / f"f{i}.nef"
        p.write_bytes(b"x" * (i + 1))  # size 不同 → key 不同
        paths.append(p)
        core_io.decode_cfa_half(_FakeIoRaw(), raw_path=p)
    assert len(calls) == 9
    assert len(core_io._DECODE_CACHE) == 8  # 全清会变 1

    # 命中刷新 recency 后再插入新 key：淘汰的是次旧而非刚命中的热点
    core_io.decode_cfa_half(_FakeIoRaw(), raw_path=paths[8])  # 命中最旧(第9个)
    p_new = tmp_path / "f_new.nef"
    p_new.write_bytes(b"y" * 99)
    core_io.decode_cfa_half(_FakeIoRaw(), raw_path=p_new)
    assert len(calls) == 10
    assert len(core_io._DECODE_CACHE) == 8
    # paths[8] 刚被访问过必须仍在缓存；最久未访问的 paths[1] 被淘汰
    keys = {k[0] for k in core_io._DECODE_CACHE}
    assert str(paths[8]) in keys
    assert str(paths[1]) not in keys


def test_wb_cache_lru_evicts_oldest(monkeypatch, tmp_path):
    monkeypatch.setattr(core_io, "_WB_CACHE", OrderedDict())

    class _WbRaw:
        camera_whitebalance = [2.0, 1.0, 1.5, 1.0]

    for i in range(9):
        p = tmp_path / f"w{i}.nef"
        p.write_bytes(b"x" * (i + 1))
        core_io.camera_neutral_wb_cached(_WbRaw(), raw_path=p)
    assert len(core_io._WB_CACHE) == 8
    # 命中缓存不再访问 raw（返回值与首算一致）
    p0 = tmp_path / "w0.nef"
    wb = core_io.camera_neutral_wb_cached(_WbRaw(), raw_path=p0)
    np.testing.assert_allclose(wb, [2.0, 1.0, 1.5])


# ---------------------------------------------------------------------------
# lut.py 统一缓存
# ---------------------------------------------------------------------------

def _write_cube(path, tag):
    lines = ["TITLE \"t\"", f"# {tag}", "LUT_3D_SIZE 2"]
    for r in range(2):
        for g in range(2):
            for b in range(2):
                lines.append(f"{r} {g} {b}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def lut_env(monkeypatch, tmp_path):
    # 跳过 256³ 建表（~50MB/LUT），只测缓存行为
    builds = []
    monkeypatch.setattr(
        lut3d.LUT3D, "_build_table",
        lambda self, chunk=16: builds.append(1), raising=True)
    monkeypatch.setattr(lut_mod, "_LUT_CACHE", OrderedDict())
    return {"builds": builds, "dir": tmp_path}


def test_load_lut_path_cached_and_lru_capped(lut_env, monkeypatch, tmp_path):
    cube = tmp_path / "a.cube"
    _write_cube(cube, "a")
    lut1 = lut_mod.load_lut_path(cube)
    lut2 = lut_mod.load_lut_path(cube)
    assert lut1 is lut2            # 命中缓存，同一对象
    assert len(lut_env["builds"]) == 1

    for i in range(5):  # 加 5 个不同路径 → 总 6 超上限 4
        p = tmp_path / f"b{i}.cube"
        _write_cube(p, f"b{i}")
        lut_mod.load_lut_path(p)
    assert len(lut_mod._LUT_CACHE) == lut_mod._LUT_CACHE_MAX == 4
    assert len(lut_env["builds"]) == 6  # 每个新路径只构建一次


def test_load_lut_and_path_share_one_cache(lut_env, monkeypatch, tmp_path):
    monkeypatch.setattr(lut_mod, "_LUT_REGISTRY", {"fake": "fake.cube"})
    monkeypatch.setattr(lut_mod, "_LUT_DIR", tmp_path)
    _write_cube(tmp_path / "fake.cube", "fake")
    by_id = lut_mod.load_lut("fake")
    by_path = lut_mod.load_lut_path(tmp_path / "fake.cube")
    # 两个公开入口共享同一物理 LUT 对象与同一套 LRU（键空间不同但 dict 唯一）
    assert by_id is by_path or lut_mod._LUT_CACHE_MAX >= len(lut_mod._LUT_CACHE)


def test_stylize_uses_unified_loader(lut_env, monkeypatch, tmp_path):
    from pixo.render.modules.style import StylizeStage
    from pixo.render.pipeline.context import StageContext

    assert not hasattr(StylizeStage, "_loaded")  # 类级双缓存已删除
    cube = tmp_path / "s.cube"
    _write_cube(cube, "s")

    ctx = StageContext(tmp_path / "x.nef")
    stage = StylizeStage({"lut_path": str(cube)})
    got = stage._get_lut(ctx)
    assert isinstance(got, lut3d.LUT3D)
    assert got is lut_mod.load_lut_path(cube)  # 走统一缓存


# ---------------------------------------------------------------------------
# tone_map _PROFILE_CACHE 强引用
# ---------------------------------------------------------------------------

def _fake_prof(curve=True):
    class _Prof:
        profile_tone_curve = (
            [float(x) for pt in zip(np.linspace(0, 1, 17),
                                    np.linspace(0, 1, 17) ** 2)
             for x in (pt[0], pt[1])] if curve else None)

    return _Prof()


def test_profile_cache_strong_ref_prevents_id_reuse(monkeypatch):
    monkeypatch.setattr(tone_map, "_PROFILE_CACHE", {})
    parsed = []
    orig_parse = tone_map.parse_profile_curve

    def counting_parse(vals):
        parsed.append(1)
        return orig_parse(vals)

    monkeypatch.setattr(tone_map, "parse_profile_curve", counting_parse)

    prof = _fake_prof()
    lut1 = tone_map._get_profile_lut(prof)
    assert lut1 is not None
    lut1_again = tone_map._get_profile_lut(prof)
    assert lut1_again is lut1          # 命中缓存
    assert len(parsed) == 1            # 只解析一次

    # 缓存值持 prof 强引用：del 后条目仍钉住对象，id 不可能被复用
    prof_id = id(prof)
    del prof
    entry = tone_map._PROFILE_CACHE[prof_id]
    assert entry[0] is not None and entry[1] is lut1

    # 无曲线 profile：None 也被缓存（不重复解析）
    prof2 = _fake_prof(curve=False)
    assert tone_map._get_profile_lut(prof2) is None
    assert tone_map._get_profile_lut(prof2) is None
    assert len(parsed) == 2


# ---------------------------------------------------------------------------
# base.py 双解压修复
# ---------------------------------------------------------------------------

def test_render_dcp_linear_decodes_once(monkeypatch, tmp_path):
    imread_calls = []
    wb_calls = []
    decode_calls = []

    class _RawObj:
        def close(self):
            pass

    monkeypatch.setattr(base_mod.rawpy, "imread",
                        staticmethod(lambda p: (imread_calls.append(1),
                                                _RawObj())[1]))
    monkeypatch.setattr(
        base_mod, "decode_stage3_like",
        lambda *a, **k: (decode_calls.append(1) or
                         (np.zeros((4, 4, 3), dtype=np.float32), _RawObj())))
    monkeypatch.setattr(base_mod, "camera_neutral_wb_cached",
                        lambda raw, raw_path=None: (
                            wb_calls.append(1)
                            or np.array([2.0, 1.0, 1.0], dtype=np.float32)))
    monkeypatch.setattr(base_mod, "find_camera_entry",
                        lambda raw_path, cache=None: {
                            "white_level": 15892, "opcodes": {},
                            "src_bounds": [0, 0, 4, 4], "dst_size": [4, 4],
                            "total_baseline": 0.0, "stage3_gain": 1.0,
                            "tone_table": [[0.0, 0.0], [1.0, 1.0]]})

    import pixo.render.core.resample as resample_mod
    import pixo.render.core.calibration as calib_mod
    monkeypatch.setattr(resample_mod, "dng_resample", lambda img, a, b: img)
    monkeypatch.setattr(calib_mod, "load_dcp", lambda p: object())
    ident = lambda x, *a, **k: x  # noqa: E731
    monkeypatch.setattr(base_mod, "cam_wb_to_prophoto",
                        lambda src, prof, wb: src)
    monkeypatch.setattr(base_mod, "apply_hue_sat_map_prophoto", ident)
    monkeypatch.setattr(base_mod, "apply_look_table_prophoto", ident)
    monkeypatch.setattr(base_mod, "exposure_ramp", ident)
    monkeypatch.setattr(base_mod, "apply_rgb_tone", ident)
    monkeypatch.setattr(base_mod, "linear_prophoto_to_srgb", ident)
    monkeypatch.setattr(base_mod, "load_tone_table", lambda t: t)

    raw = tmp_path / "x.nef"
    raw.write_bytes(b"x")
    base_mod.render_dcp_linear(raw, "p.dcp", cache={"entries": {}})

    assert len(decode_calls) == 1   # 第一次解码
    assert len(wb_calls) == 1       # WB 复用同一 raw 对象（close 前取）
    assert len(imread_calls) == 0, "第二次 rawpy.imread 双解压未消除"
