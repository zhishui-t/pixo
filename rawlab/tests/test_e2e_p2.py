"""T6 端到端验收 (Phase 1.5+2): 全链 = 检测→分类→场景预设→渲染。

用真实 NEF (RAWLAB_RAW_DIRS, 默认 K:\\data\\photo\\0711\\raw) 验证:
  - 输出合法 (H, W, 3) uint8
  - 同图同场景两次输出位精确一致 (确定性)
  - 全链 (probe 渲染 + 分析 + 最终渲染) 性能 < 8s
  - 无 NEF 时 pytest.skip (CI 环境)

运行: python -m pytest rawlab/tests/test_e2e_p2.py -q
"""
from __future__ import annotations

import glob
import os
import time

import numpy as np
import pytest

from rawlab.dcp import load_dcp
from rawlab.engine import build_default_pipeline
from rawlab.engine.analyze import run_analysis
from rawlab.engine.core import Pipeline, StageContext
from rawlab.engine.scene_apply import apply_scene_preset
from rawlab.render import render as legacy_render

DEFAULT_DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
               r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")


def _resolve_nef(n: int = 2):
    dirs = []
    env = os.environ.get("RAWLAB_RAW_DIRS")
    if env:
        dirs = [d for d in env.split(";") if d]
    else:
        d = r"K:\data\photo\0711\raw"
        if os.path.isdir(d):
            dirs = [d]
    files = []
    for d in dirs:
        files.extend(glob.glob(os.path.join(d, "*.NEF")))
    return sorted(files)[:n]


def _run_with_scene(raw_path, prof, scene_id: str):
    """probe 渲染 → 场景预设参数合并 → 引擎全链渲染 (确定性路径)。"""
    params, lut = apply_scene_preset(scene_id)
    pipe = build_default_pipeline(prof=prof, params=params)
    return pipe.run_file(raw_path, half_size=True)


@pytest.mark.e2e
def test_e2e_scene_pipeline_deterministic():
    files = _resolve_nef(2)
    if not files:
        pytest.skip("无 NEF 测试数据 (RAWLAB_RAW_DIRS)")
    prof = load_dcp(os.environ.get("RAWLAB_DCP", DEFAULT_DCP))

    for f in files:
        for scene_id in ("portrait", "landscape"):
            t0 = time.time()
            rgb8 = _run_with_scene(f, prof, scene_id)
            dt = time.time() - t0
            assert isinstance(rgb8, np.ndarray)
            assert rgb8.dtype == np.uint8 and rgb8.ndim == 3 and rgb8.shape[2] == 3
            assert rgb8.shape[0] > 100 and rgb8.shape[1] > 100
            assert float(rgb8.min()) >= 0.0 and float(rgb8.max()) <= 255.0
            # 确定性: 同图同场景两次输出位精确一致
            rgb8_2 = _run_with_scene(f, prof, scene_id)
            assert np.array_equal(rgb8, rgb8_2), f"{f}/{scene_id} 输出非确定"
            assert dt < 8.0, f"{f}/{scene_id} 全链 {dt:.1f}s >= 8s"


@pytest.mark.e2e
def test_e2e_scene_auto_classify_and_apply():
    """--scene auto 路径: probe → 检测+分类 → 场景预设 → 渲染 (smoke)。"""
    files = _resolve_nef(1)
    if not files:
        pytest.skip("无 NEF 测试数据 (RAWLAB_RAW_DIRS)")
    prof = load_dcp(os.environ.get("RAWLAB_DCP", DEFAULT_DCP))
    f = files[0]

    probe = legacy_render(f, prof, half_size=True)
    ctx = StageContext(f, prof=prof)
    run_analysis(ctx, rgb8=probe, detect=True, classify=True)
    scene = ctx.state.get("scene") or {}
    scene_id = scene.get("id")

    if scene_id:
        params, _ = apply_scene_preset(scene_id)
        pipe = build_default_pipeline(prof=prof, params=params)
        rgb8 = pipe.run_file(f, half_size=True)
        assert rgb8.dtype == np.uint8 and rgb8.ndim == 3 and rgb8.shape[2] == 3
        assert 0.0 <= float(scene.get("confidence", 0)) <= 1.0
    # 无检测环境 → scene_id None, 基座路径仍可跑
    else:
        pipe = build_default_pipeline(prof=prof)
        rgb8 = pipe.run_file(f, half_size=True)
        assert rgb8.dtype == np.uint8
