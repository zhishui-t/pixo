"""core.calibration_store 单测 (标定加载/缓存统一治理)。

覆盖:
  - 正常加载 + 缓存命中 (同对象直返, 不重读)
  - 缺失 → default + 负缓存 (中途落盘不被感知; reset 后可感知)
  - 损坏 → default + 每路径一次性 warning; 修复落盘后按 stat 态自动重读
  - 修改失效 (mtime+size 变化 → 重读) 与 refresh=True 强制重读
  - 线程并发 (含并发 reset) 无异常、结果一致
  - reset 钩子
  - 迁移对照: 直接读文件 vs 经 store 读内容相等; exposure/wb/tone 三个
    迁移加载器对同一文件产出与旧口径一致

运行: python -m pytest tests/unit/test_calibration_store.py -q
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from pixo.render.core import calibration_store


@pytest.fixture(autouse=True)
def _isolated_store():
    """每个用例独立的 store 状态 (全局缓存, 测试间必须清)。"""
    calibration_store.reset()
    yield
    calibration_store.reset()


# --- 正常 / 缓存命中 ---------------------------------------------------------

def test_load_normal_matches_direct_read(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text(json.dumps({"target_offset": -1.25, "cal_table": [[0, 1]]}),
                 encoding="utf-8")
    doc = calibration_store.load_json(f)
    assert doc == json.loads(f.read_text(encoding="utf-8"))


def test_cache_hit_returns_same_object_no_reread(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text(json.dumps({"a": 1}), encoding="utf-8")
    d1 = calibration_store.load_json(f)
    d2 = calibration_store.load_json(f)
    assert d1 is d2  # 同 stat 态 → 缓存对象直返 (约定: 调用方不得原地修改)


# --- 缺失 / 负缓存 -----------------------------------------------------------

def test_missing_returns_default_and_negative_caches(tmp_path):
    missing = tmp_path / "missing.json"
    sentinel = {"fallback": True}
    assert calibration_store.load_json(missing) is None          # default=None
    assert calibration_store.load_json(missing, sentinel) is sentinel
    # 负缓存: 缺失结果被缓存 —— 中途落盘不被自动感知 (不反复 stat 的代价)
    missing.write_text(json.dumps({"late": 1}), encoding="utf-8")
    assert calibration_store.load_json(missing) is None
    # reset 后重新感知
    calibration_store.reset()
    assert calibration_store.load_json(missing) == {"late": 1}


# --- 损坏: 一次性告警 + 修复自动重读 ------------------------------------------

def test_corrupt_returns_default_warns_once(tmp_path, caplog):
    f = tmp_path / "bad.json"
    f.write_text("{not json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert calibration_store.load_json(f, {"d": 1}) == {"d": 1}
        assert calibration_store.load_json(f, {"d": 1}) == {"d": 1}
    warns = [r for r in caplog.records if "标定文件损坏" in r.getMessage()]
    assert len(warns) == 1  # 一次性 (按路径)


def test_corrupt_top_level_non_object_warns(tmp_path, caplog):
    f = tmp_path / "list.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert calibration_store.load_json(f) is None
    assert any("损坏" in r.getMessage() for r in caplog.records)


def test_corrupt_recovers_after_rewrite(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text("{broken", encoding="utf-8")
    assert calibration_store.load_json(f) is None
    # 修复落盘 (mtime/size 变化) → 自动重读; 告警不重复 (同路径仅一次)
    f.write_text(json.dumps({"fixed": 2}) + " ", encoding="utf-8")
    assert calibration_store.load_json(f) == {"fixed": 2}


def test_warn_again_after_reset(tmp_path, caplog):
    f = tmp_path / "cal.json"
    for _ in range(2):
        f.write_text("{broken", encoding="utf-8")
        calibration_store.load_json(f)
    caplog.clear()  # 只计 reset 后的告警
    with caplog.at_level("WARNING"):
        calibration_store.reset()
        f.write_text("{broken-again!!", encoding="utf-8")
        calibration_store.load_json(f)
    assert sum("标定文件损坏" in r.getMessage() for r in caplog.records) == 1


# --- 修改失效 / refresh -------------------------------------------------------

def test_mtime_size_invalidation(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text(json.dumps({"v": 1}), encoding="utf-8")
    assert calibration_store.load_json(f) == {"v": 1}
    # 改写 (size 不同, 规避同毫秒 mtime 量子) → 立即生效 (wb 语义保留)
    f.write_text(json.dumps({"v": 2}) + "   ", encoding="utf-8")
    assert calibration_store.load_json(f) == {"v": 2}


def test_refresh_forces_disk_reread(tmp_path):
    f = tmp_path / "cal.json"
    f.write_text(json.dumps({"v": 1}), encoding="utf-8")
    assert calibration_store.load_json(f) == {"v": 1}
    # 同长度改写 (size 相同, mtime 可能同毫秒): refresh=True 绕过缓存强制读盘
    f.write_text(json.dumps({"v": 7}), encoding="utf-8")
    assert calibration_store.load_json(f, refresh=True) == {"v": 7}


# --- 线程并发 -----------------------------------------------------------------

def test_thread_concurrent_loads_consistent(tmp_path):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"k": [1, 2, 3]}), encoding="utf-8")
    miss = tmp_path / "miss.json"
    results = []
    lock = threading.Lock()

    def worker(i):
        # 混合 命中/缺失/reset, 任何交错下都不应异常且结果恒定
        r = (calibration_store.load_json(ok),
             calibration_store.load_json(miss, "def"),
             calibration_store.load_json(str(ok)))
        with lock:
            results.append(r)

    def resetter():
        for _ in range(20):
            calibration_store.reset()

    with ThreadPoolExecutor(max_workers=9) as ex:
        futs = [ex.submit(worker, i) for i in range(8 * 40)]
        futs.append(ex.submit(resetter))
        for fut in futs:
            fut.result()
    assert results and all(
        r[0] == {"k": [1, 2, 3]} and r[1] == "def" and r[2] == {"k": [1, 2, 3]}
        for r in results)


# --- 仓库根解析 ---------------------------------------------------------------

def test_resolve_repo_root_finds_pyproject():
    root = calibration_store.resolve_repo_root()
    assert root is not None
    assert (root / "pyproject.toml").is_file()
    assert (root / "configs").is_dir()


def test_resolve_repo_root_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "fake_root"
    fake.mkdir()
    (fake / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv(calibration_store.PIXO_CONFIG_ROOT_ENV, str(fake))
    assert calibration_store.resolve_repo_root() == fake.resolve()


# --- 迁移对照: 直接读文件 vs 经 store / 迁移加载器读 --------------------------

_RENDER = Path(__file__).resolve().parents[2] / "src" / "pixo" / "render"
_WARM_CAL = (Path(__file__).resolve().parents[2] / "configs" / "calibration"
             / "warmth_curve.json")


def test_store_matches_direct_read_for_repo_calibration_files():
    """验收: 真实标定文件 直接 json.loads 与 store.load_json 内容相等。"""
    for p in (_RENDER / "target_offset.json", _WARM_CAL):
        if not p.exists():
            pytest.skip(f"环境缺少标定文件: {p}")
        assert calibration_store.load_json(p) == json.loads(
            p.read_text(encoding="utf-8"))


def test_exposure_loader_matches_direct_read():
    """exposure._load_target_offset 与直接读文件的旧口径一致。"""
    import pixo.render.modules.exposure as exposure_mod
    exposure_mod._reset_caches()
    p = exposure_mod._CAL_FILE
    if not p.exists():
        pytest.skip(f"环境缺少标定文件: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert exposure_mod._load_target_offset() == pytest.approx(
        float(doc.get("target_offset", 0.0)))


def test_wb_loader_matches_direct_read(tmp_path):
    """white_balance._load_warm_cal 与直接读文件 + _check_warmth_curve 一致;
    改写文件后 mtime/size 失效即时生效 (旧 _WARM_CAL_CACHE 语义保留)。"""
    import pixo.render.modules.white_balance as wb_mod
    wb_mod._reset_caches()
    knots = [[1.0, 1.0, 1.0, 1.0], [3.0, 1.2, 0.9, 0.8]]
    f = tmp_path / "warmth_curve.json"
    f.write_text(json.dumps({"knots": knots, "_domain": {"wb_B": [1.0, 3.0]}}),
                 encoding="utf-8")
    got = wb_mod._load_warm_cal(f)
    assert got is not None
    assert np.allclose(got["curve"], wb_mod._check_warmth_curve(knots))
    assert got["domain"] == (1.0, 3.0)
    # 改写 (size 不同) → 新结点生效
    knots2 = [[1.0, 1.0, 1.0, 1.0], [3.0, 1.3, 0.95, 0.85]]
    f.write_text(json.dumps({"knots": knots2}) + " ", encoding="utf-8")
    got2 = wb_mod._load_warm_cal(f)
    assert np.allclose(got2["curve"], wb_mod._check_warmth_curve(knots2))
    assert got2["domain"] is None  # 新文件无 _domain
    # 缺失 → None (回退斜率模型)
    assert wb_mod._load_warm_cal(tmp_path / "nope.json") is None


def test_tone_lrfit_matches_direct_read(tmp_path, monkeypatch):
    """tone_map._get_lrfit 与直接读文件 + 旧公式 (gains, lut) 逐元素一致。"""
    import pixo.render.modules.tone_map as tone_mod
    curve = [round(v * 255) for v in np.linspace(0.0, 1.0, 1024)]
    gains = [1.01, 1.0, 0.99]
    f = tmp_path / "lr_tone_curve.json"
    f.write_text(json.dumps({"version": 3, "gains": gains, "curve": curve}),
                 encoding="utf-8")
    monkeypatch.setattr(tone_mod, "_LR_CAL_FILE", f)
    tone_mod._reset_caches()
    got = tone_mod._get_lrfit()
    assert got is not None
    # 旧公式复算 (迁移前 _get_lrfit 内联逻辑)
    c = np.asarray(curve, dtype=np.float64) / 255.0
    grid = np.linspace(0.0, 1.0, tone_mod._N_FAST, dtype=np.float64)
    lut = np.interp(grid, np.linspace(0.0, 1.0, len(c)), c).astype(np.float32)
    assert np.allclose(got[0], np.asarray(gains, dtype=np.float32))
    assert np.array_equal(got[1], lut)
    # 缺失文件 → None (负缓存: 重复调用不 stat)
    monkeypatch.setattr(tone_mod, "_LR_CAL_FILE", tmp_path / "missing.json")
    tone_mod._reset_caches()
    assert tone_mod._get_lrfit() is None
    assert tone_mod._get_lrfit() is None


# --- 模块 _reset_caches 钩子 ---------------------------------------------------

def test_module_reset_caches_hooks_exist_and_reset():
    """四模块 _reset_caches() 可调用且把模块缓存还原初始态。"""
    import pixo.render.modules.exposure as exposure_mod
    import pixo.render.modules.white_balance as wb_mod
    import pixo.render.modules.tone_map as tone_mod
    import pixo.render.pipeline.scene_apply as scene_apply

    for mod in (exposure_mod, wb_mod, tone_mod, scene_apply):
        assert callable(getattr(mod, "_reset_caches"))
        mod._reset_caches()  # 幂等可重复

    assert exposure_mod._cached_offset is None
    assert exposure_mod._cached_table is None
    assert wb_mod._WARM_CAL_CACHE == {}
    assert tone_mod._LRFIT_CACHE is None
    assert scene_apply._cache is None
    assert calibration_store._ENTRIES == {}
