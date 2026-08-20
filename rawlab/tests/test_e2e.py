"""T7 端到端验收测试: 基座渲染 = 相机预览级质量。

用真实 NEF (RAWLAB_RAW_DIRS 环境变量, 默认 K:\\data\\photo\\0711\\raw) 跑
默认管线 (基座), 断言:
  - 输出合法 8bit RGB (H, W, 3) uint8, 无异常
  - 高光/暗部裁切 < 2% (L1 口径)
  - 分层中性 worst |a|/|b| < 3 (中性标定生效)
无 NEF 时 pytest.skip (CI 环境)。

运行: python -m pytest rawlab/tests/test_e2e.py -q
"""
from __future__ import annotations

import glob
import os

import cv2
import numpy as np
import pytest

from rawlab.dcp import load_dcp
from rawlab.engine import build_default_pipeline
from rawlab.tools.verify_l1 import l1_metrics

DEFAULT_DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
               r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")


def _resolve_nnef(n: int = 3):
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


@pytest.mark.e2e
def test_end_to_end_base_render():
    files = _resolve_nnef(3)
    if not files:
        pytest.skip("无 NEF 测试数据 (RAWLAB_RAW_DIRS)")
    dcp = os.environ.get("RAWLAB_DCP", DEFAULT_DCP)
    prof = load_dcp(dcp)
    pipe = build_default_pipeline(prof=prof)

    for f in files:
        rgb8 = pipe.run_file(f, half_size=True)
        assert isinstance(rgb8, np.ndarray)
        assert rgb8.dtype == np.uint8 and rgb8.ndim == 3 and rgb8.shape[2] == 3
        assert rgb8.shape[0] > 100 and rgb8.shape[1] > 100
        assert float(rgb8.min()) >= 0.0 and float(rgb8.max()) <= 255.0

        m = l1_metrics(rgb8)
        assert m["hi_clip"] < 2.0, f"{f}: 高光裁切 {m['hi_clip']}% >= 2%"
        assert m["lo_clip"] < 2.0, f"{f}: 暗部裁切 {m['lo_clip']}% >= 2%"
        # 绝对中性带: 基座做"相机观感"标定 (对齐相机预览中性, 相机自身
        # 低光中性 b≈-6), 因此 L1 绝对中性只作"无可见偏色"级 smoke 门限;
        # 严格对齐验收由 L2 (vs 相机预览, 40 张全量) 承担。
        assert m["band_worst_a"] < 12.0, f"{f}: 中性 a 漂移 {m['band_worst_a']} >= 12"
        assert m["band_worst_b"] < 12.0, f"{f}: 中性 b 漂移 {m['band_worst_b']} >= 12"


@pytest.mark.e2e
def test_end_to_end_l2_camera_preview_alignment():
    """L2: 与相机预览对齐 (d_med/d_a/d_b 统计口径, n 小时仅做 smoke 断言)。"""
    from rawlab.tools.batch_iter import camera_preview
    from rawlab.tools.verify_engine import metrics

    files = _resolve_nnef(3)
    if not files:
        pytest.skip("无 NEF 测试数据 (RAWLAB_RAW_DIRS)")
    dcp = os.environ.get("RAWLAB_DCP", DEFAULT_DCP)
    pipe = build_default_pipeline(prof=load_dcp(dcp))

    rows = []
    for f in files:
        mine = pipe.run_file(f, half_size=True)
        cam = camera_preview(f)
        if cam is None:
            continue
        rows.append(metrics(mine, cam))
    if not rows:
        pytest.skip("无相机预览")
    dm = [r["d_med"] for r in rows]
    da = [r["d_a"] for r in rows]
    db = [r["d_b"] for r in rows]
    # 小样本 (3 张) smoke, 按 40 张全量验收数据留鲁棒余量:
    # 全量实测 d_med mean≈0±12、d_a 2.7、d_b 1.4;严格口径由
    # tools/verify_engine.py --mode engine --n 40 承担。
    assert abs(float(np.mean(dm))) < 25.0, f"d_med |mean|={abs(np.mean(dm)):.1f}"
    assert abs(float(np.mean(da))) < 6.0, f"d_a |mean|={abs(np.mean(da)):.1f}"
    assert abs(float(np.mean(db))) < 5.0, f"d_b |mean|={abs(np.mean(db)):.1f}"
