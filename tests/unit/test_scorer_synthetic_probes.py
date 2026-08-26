"""t98 合成/低纹理域探针的单元测试。

覆盖：
  - 合成探针生成可复跑（确定性、≥5 类、shape/dtype/finite 契约）
  - 退化阶梯生成（确定性、扰动强度随 σ 递增，与名义质量序一致）
  - Spearman 秩相关朴素实现（单调正/反/常量/短序列）
  - synthetic_tables：绝对分无跨域语义引用、分位表、阶梯结论
  - 结论分流：自洽（单调）→ 可用；不自洽（非单调）→ 不可靠
  - 表追加断言：docs/metrics/scorer_distribution.md 含 t98 合成域分位表
  - 脚本可复跑：导入 scripts/scorer_distribution.py 不触发 main
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "scorer_distribution.py"
DOC = ROOT / "docs" / "metrics" / "scorer_distribution.md"


def _load_sd():
    assert SCRIPT.is_file(), f"脚本缺失: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("sd_mod_t98", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sd_mod_t98"] = mod
    spec.loader.exec_module(mod)
    return mod


SD = _load_sd()


def test_synthetic_probes_rerunnable_and_complete():
    probes_a = SD.build_synthetic_probes(seed=0, size=256)
    probes_b = SD.build_synthetic_probes(seed=0, size=256)
    assert len(probes_a) >= 5
    # 确定性可复跑
    assert [n for n, _ in probes_a] == [n for n, _ in probes_b]
    for (n_a, img_a), (n_b, img_b) in zip(probes_a, probes_b):
        assert n_a == n_b
        assert img_a.shape == (256, 256, 3)
        assert np.isfinite(img_a).all()
        assert img_a.dtype in (np.uint8, np.float32)
        assert np.array_equal(img_a, img_b), f"非确定性探针: {n_a}"
    names = [n for n, _ in probes_a]
    for key in ("纯噪声", "平坦灰", "低对比渐变", "星点", "夜间黑场"):
        assert any(key in n for n in names), f"缺 {key} 类探针"


def test_degradation_ladder_deterministic_and_monotone_perturbation():
    ladder_a = SD.build_degradation_ladder(seed=0, size=256)
    ladder_b = SD.build_degradation_ladder(seed=0, size=256)
    assert len(ladder_a) == len(SD.DEGRADATION_SIGMAS) == 6
    base = SD._night_sky_base(size=256, seed=0)
    deltas = []
    for (n_a, img_a), (n_b, img_b) in zip(ladder_a, ladder_b):
        assert n_a == n_b
        assert np.array_equal(img_a, img_b), f"非确定性阶梯: {n_a}"
        # 扰动幅度随 σ 严格递增（加性高斯噪声方差单调）
        deltas.append(float(np.mean(np.abs(img_a - base))))
    assert all(deltas[i] < deltas[i + 1] for i in range(len(deltas) - 1))
    # 名义质量序标注
    assert "纯净" in ladder_a[0][0] and "坏点σ30" in ladder_a[-1][0]


def test_spearman_rho_basic():
    assert SD._spearman_rho([1, 2, 3, 4, 5], [1.0, 2.0, 3.0, 4.0, 5.0]) == 1.0
    assert SD._spearman_rho([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0
    assert SD._spearman_rho([1, 2, 3], [3, 3, 3]) == 0.0
    assert SD._spearman_rho([1], [2]) == 0.0


def _rows(names: list[str], overalls: list[float]):
    import time
    rows = []
    for n, o in zip(names, overalls):
        r = {"name": n, "elapsed_ms": 1, "overall": o}
        for k in SD.DIMS:
            r.setdefault(k, 0.0)
        rows.append(r)
    return rows


def test_synthetic_tables_emits_absolute_score_caveat():
    probe_rows = _rows(["纯噪声", "平坦灰", "渐变天空+星点"],
                       [0.3, -0.04, 0.04])
    ladder_rows = [{"name": "纯净", "overall": 0.5},
                   {"name": "轻噪声", "overall": 0.4}]
    lines, verdict = SD.synthetic_tables(probe_rows, ladder_rows)
    text = "\n".join(lines)
    assert "## 合成域分位表（t98 深化：≥5 探针）" in text
    assert "绝对分无跨域语义" in text
    assert "### 合成域分位汇总（探针内" in text
    assert "| p25 |" in text
    assert "### 域内自洽性：同一场景退化阶梯" in text
    assert isinstance(verdict, str) and verdict


def test_synthetic_tables_verdict_self_consistent_vs_not():
    # 自洽：打分随退化单调下降 → 可用
    probes = _rows(["a"], [0.0])
    ladder_ok = [{"name": f"s{i}", "overall": v}
                 for i, v in enumerate([1.0, 0.8, 0.6, 0.4, 0.2, 0.0])]
    _, v_ok = SD.synthetic_tables(probes, ladder_ok)
    assert "可用" in v_ok and "不可" not in v_ok
    # 不自洽：非单调（对应 t98 实测 ρ≈0.03）
    ladder_bad = [{"name": f"s{i}", "overall": v}
                  for i, v in enumerate([0.0, 0.5, 0.9, 0.6, 0.3, 0.1])]
    _, v_bad = SD.synthetic_tables(probes, ladder_bad)
    assert "不可靠" in v_bad or "仅有限可用" in v_bad


def test_doc_contains_t98_synthetic_section_appended():
    """表追加断言：scorer_distribution.md 必须已含 t98 合成域分位表。"""
    assert DOC.is_file(), f"文档缺失: {DOC}"
    doc = DOC.read_text(encoding="utf-8")
    assert "## 合成域分位表（t98 深化：≥5 探针）" in doc
    assert "绝对分无跨域语义" in doc
    # 实测结论（ρ≈0.03 不可靠）必须落档
    assert "Spearman ρ = **0.03**" in doc
    assert "不可靠" in doc
