"""Gate: 守门员覆盖矩阵自检（FUNCTION_GATE_SPEC §8.4）。

防漏测：新增 stage / 缺失门禁层时，本文件让 gate 收集或运行失败，
而不是让“现有测试都绿”掩盖覆盖缺口。
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

_GATE_DIR = Path(__file__).resolve().parent
_GOLDEN_MANIFEST = _GATE_DIR.parent / "goldens" / "gate" / "manifest.json"

# 13 个调整 feature 的 L0 门禁文件（文件名必须与矩阵一致）。
_L0_FILES = {
    "exposure": "test_gate_exposure.py",
    "whitebalance": "test_gate_whitebalance.py",
    "compose": "test_gate_compose.py",
    "curves/tone": "test_gate_curves.py",
    "huesat": "test_gate_huesat.py",
    "clarity": "test_gate_clarity.py",
    "colorcal": "test_gate_colorcal.py",
    "calibration": "test_gate_calibration.py",
    "hsl": "test_gate_hsl.py",
    "split_tone": "test_gate_split_tone.py",
    "skin": "test_gate_skin.py",
    "stylize": "test_gate_stylize.py",
    "refine": "test_gate_refine.py",
}

# 已导出 native 内核必须在 L1 等价文件中出现（防只注册不验）。
_NATIVE_KERNELS = (
    "decode_cfa_half",
    "apply_local_warm_sat_native",
    "colorcal_apply_lab",
    "refine_apply",
    "refine_sat_protection",
    "exposure_apply",
    "matrix_apply3",
    "tone_apply_lut1d",
    "clarity_apply",
)


def test_all_features_have_l0_file():
    missing = [name for name, file in _L0_FILES.items()
               if not (_GATE_DIR / file).exists()]
    assert not missing, f"L0 门禁文件缺失: {missing}"


def test_native_equivalence_covers_exported_kernels():
    text = "\n".join(path.read_text(encoding="utf-8")
                     for path in sorted(_GATE_DIR.glob("test_gate_*.py")))
    missing = [k for k in _NATIVE_KERNELS if k not in text]
    assert not missing, f"L1 未覆盖 native 内核: {missing}"


def test_l2_golden_manifest_exists():
    assert _GOLDEN_MANIFEST.exists(), (
        "L2 golden 未建立（缺 render/tests/goldens/gate/manifest.json）；"
        "按 FUNCTION_GATE_SPEC §6 阻塞合并")


def test_p1_7_perf_gate_file_exists():
    assert (_GATE_DIR / "test_gate_e2e_perf.py").exists(), "P1-7 性能门禁文件缺失"


def test_l3_e2e_ab_file_exists():
    assert (_GATE_DIR / "test_gate_e2e_ab.py").exists(), "L3 A-B 门禁文件缺失"


def test_run_all_tests_blocks_on_gate_and_bench():
    script = _GATE_DIR.parents[1] / "run_all_tests.bat"
    assert script.exists(), "render/run_all_tests.bat 不存在"
    text = script.read_text(encoding="utf-8", errors="replace")
    for tag in ("[4/6 FAIL]", "[5/6 FAIL]", "[6/6 FAIL]"):
        assert tag in text, f"run_all_tests.bat 缺少阻塞分支 {tag}"
