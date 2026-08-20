"""T4.5 金样本回归 Harness。

固化 5 张 DNG 金样本为一键 pytest 回归:
  - 引擎渲染 vs SDK 参考: 5 张 full engine_mae <= 5e-5 (复用 dng_stage3_ablation 工具链);
  - 输入一致性: 5 张 stage3 input MAE <= 1e-5 (复用 decode_dng_stage3_like + replicate ref)。
数据存在时执行, 缺失时 pytest.skip (不红本地 CI)。
运行: PYTHONPATH=. python -m pytest rawlab/tests -q -m regression
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.regression

_VERIFY = Path(r"K:\dsh-share\dng_verify")
_REPLICATE = _VERIFY / "replicate"

# 复用 dng_stage3_ablation 的常量/函数 (不复制大段代码)
import rawlab.tools.dng_stage3_ablation as _abl
from rawlab.engine.decode import decode_dng_stage3_like

PHOTOS = [
    ("5236_fresh", r"K:\dsh-share\dng_verify\DSC_5236_fresh.dng"),
    ("5607", r"K:\dsh-share\dng_verify\DSC_5607.dng"),
    ("5603", r"K:\dsh-share\dng_verify\DSC_5603.dng"),
    ("0364", r"K:\dsh-share\dng_verify\DSC_0364.dng"),
    ("0479", r"K:\dsh-share\dng_verify\DSC_0479.dng"),
]
STEMS = [s for s, _ in PHOTOS]


def _data_available() -> bool:
    """数据目录/文件齐全才算可用; 缺任一 DNG 或 SDK stage3 参考即 skip。"""
    if not _VERIFY.is_dir():
        return False
    for _, dng in PHOTOS:
        if not Path(dng).exists():
            return False
    return all(cfg for cfg in [
        _verify_replicate_x(), _verify_dcp_x(), _verify_dng_x()])


def _verify_dng_x():
    return True


def _verify_dcp_x():
    return Path(_abl.ADOBE_DCP).exists()


def _verify_replicate_x():
    return all((_REPLICATE / f"{s}.stage3.raw").exists() for s in STEMS)


# 是否运行 (数据存在)
RUN = _data_available()


# ---------------------------------------------------------------------------
# input MAE (stage3 输入一致性) <= 1e-5
# ---------------------------------------------------------------------------
def _load_stage3_ref(stem: str) -> np.ndarray:
    p = _REPLICATE / f"{stem}.stage3.raw"
    hdr = np.fromfile(p, dtype="<u4", count=2)
    w, h = int(hdr[0]), int(hdr[1])
    arr = np.fromfile(p, dtype="<f4", offset=8, count=w * h * 3)
    return arr.reshape(h, w, 3)


def _compute_input_mae(stem: str, dng: str) -> float:
    img, raw = decode_dng_stage3_like(dng)
    raw.close()
    ref = _load_stage3_ref(stem)
    if img.shape != ref.shape:
        from rawlab.tools.dng_stage3_replicate import dng_resample
        H, W = img.shape[:2]
        img2 = dng_resample(img, (1, 1, H, W - 2), (ref.shape[1], ref.shape[0]))
        return float(np.abs(img2 - ref).mean())
    return float(np.abs(img - ref).mean())


# ---------------------------------------------------------------------------
# engine_mae (full 级) <= 5e-5
# ---------------------------------------------------------------------------
def _compute_engine_mae(stem: str, dng: str) -> float:
    """复用 dng_stage3_ablation 的 run/scaled_mae/OUT/ROOT/PY 跑 full 级并取 engine_mae。"""
    level = "full"
    dcp = _abl.ADOBE_DCP
    stage_raw = _abl.OUT / f"{stem}_{level}.stage3.raw"
    ref = _abl.OUT / f"{stem}_{level}.ref_linear.tif"
    tone = _abl.OUT / f"{stem}_{level}.tone.table"
    log = _abl.OUT / f"{stem}_{level}.engine.log"
    # replicate 工具生成 engine ref/log/tone/stage3
    rc, so, _ = _abl.run([
        sys.executable, str(_abl.ROOT / "rawlab/tools/dng_stage3_replicate.py"),
        "--dng", dng, "--dcp", dcp, "--out-dir", str(_abl.OUT),
        "--stem", f"{stem}_{level}"])
    assert rc == 0, f"replicate failed for {stem}"
    rc, so, se = _abl.run([
        sys.executable, str(_abl.ROOT / "rawlab/tools/dng_linear_probe.py"),
        "--dng", dng, "--dcp", dcp, "--ref", str(ref),
        "--stage3-raw", str(stage_raw), "--engine-log", str(log),
        "--tone-table", str(tone)])
    assert rc == 0, f"engine probe failed for {stem}: {se[-400:]}"
    eng = _abl.scaled_mae(so)
    assert eng is not None, f"no engine_mae parsed for {stem}"
    return float(eng)


@pytest.mark.skipif(not RUN, reason="金样本数据目录不存在 (K:/dsh-share/dng_verify)")
@pytest.mark.parametrize("stem,dng", PHOTOS, ids=[s for s, _ in PHOTOS])
def test_engine_full_mae_le_5e5(stem, dng):
    """引擎渲染 vs SDK: full 级 engine_mae <= 5e-5。"""
    mae = _compute_engine_mae(stem, dng)
    assert mae <= 5e-5, f"{stem} full engine_mae={mae:.3e} > 5e-5"


@pytest.mark.skipif(not RUN, reason="金样本数据目录不存在 (K:/dsh-share/dng_verify)")
@pytest.mark.parametrize("stem,dng", PHOTOS, ids=[s for s, _ in PHOTOS])
def test_input_stage3_mae_le_1e5(stem, dng):
    """输入一致性: decode_dng_stage3_like vs SDK 参考 stage3 input MAE <= 1e-5。"""
    mae = _compute_input_mae(stem, dng)
    assert mae <= 1e-5, f"{stem} input MAE={mae:.3e} > 1e-5"


def test_data_dir_skip_logic():
    """数据目录存在性检查: RUN 为 True 时数据就绪 (否则整个 parametrize 被 skip)。"""
    if RUN:
        assert _VERIFY.is_dir()
        assert all((_VERIFY / f"DSC_{s}.dng".replace("DSC_5236_fresh", "DSC_5236_fresh")).exists()
                   for s in STEMS if s != "5236_fresh")
        assert (_VERIFY / "DSC_5236_fresh.dng").exists()
        # replicate 参考与 Adobe DCP 就绪
        assert all((_REPLICATE / f"{s}.stage3.raw").exists() for s in STEMS)
        assert Path(_abl.ADOBE_DCP).exists()
        assert _verify_dcp_x()
    else:
        # 数据缺失时所有测例被 skip —— 本测试应直接通过(不失败)
        assert True
