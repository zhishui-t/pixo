"""Gate: L2 golden 回归（FUNCTION_GATE_SPEC §6）。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gate

_GOLDEN_DIR = Path(__file__).resolve().parent / "goldens" / "gate"
_MANIFEST = _GOLDEN_DIR / "manifest.json"


def _load_cases():
    import sys
    if str(_GOLDEN_DIR.parent) not in sys.path:
        sys.path.insert(0, str(_GOLDEN_DIR.parent))
    import gate_cases
    import generate_gate_goldens
    return gate_cases, generate_gate_goldens


def test_manifest_schema_and_files():
    gate_cases, generate_gate_goldens = _load_cases()
    assert _MANIFEST.exists(), "gate golden manifest 不存在"
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    # 只认合成 golden 的 schema id；读到 render/tools 的 raw 版直接判失败。
    assert manifest.get("schema") == generate_gate_goldens.SCHEMA, (
        f"schema 应为 {generate_gate_goldens.SCHEMA}（合成 golden），"
        f"实际为 {manifest.get('schema')!r}；若为 {generate_gate_goldens.RAW_SCHEMA} "
        f"则说明混入了 render/tools 的真实 RAW manifest，两套条目结构互不兼容")
    features = manifest.get("features", {})
    assert len(features) == 21, f"golden feature 数量 {len(features)} != 21"
    # 20 = 前置 15 (纯函数+显式参数) + exposure_cal_auto/warmth_cal_auto
    # (t36 §5 门禁缺口关闭: 触达正式曝光表与 warmth 曲线的标定数据敏感 case)
    # + default_dispatch/card_portra_400 (F08, oklch 前置修补 b: 缺省分派
    # 观测点 + 存量卡 A1 金样本, 堵 t52 §3.1「翻转 default_params 后 gate
    # 零敏感性」盲区)
    # + region_adjust (F15, M1 验收: enabled=True + 合成软掩码经真实
    # DEFAULT_STAGES 链序快照, M1 stage 像素语义在金样本层可观测)
    # + skin_oklch_softband (r12 观察窗清偿: OKLab 椭圆软边带探针 ——
    # R10 重拟合改半轴+软带而 skin/skin_oklch 饱和肤色 case 零变化的盲区关闭)
    # reviewer 必须非空：golden 变更不得脱离复核静默合入。
    reviewer = str(manifest.get("reviewer") or "").strip()
    assert reviewer, "manifest.reviewer 为空：golden 基线必须由 reviewer 复核后合入"
    assert reviewer != "pending", "manifest.reviewer 仍为 pending，尚未完成复核"
    for feature, meta in features.items():
        assert meta.get("shape") and meta.get("dtype") and meta.get("sha256")
        assert (_GOLDEN_DIR / meta["file"]).exists(), f"golden 文件缺失: {feature}"


def test_baseline_files_match_manifest_sha256():
    """基线 .npy 文件自身 sha256 必须与 manifest 一致（防误替换/损坏）。"""
    gate_cases = _load_cases()[0]
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for feature, meta in manifest["features"].items():
        actual = gate_cases.sha256_file(_GOLDEN_DIR / meta["file"])
        assert actual == meta["sha256"], (
            f"{feature} 基线文件 sha256 与 manifest 不一致（manifest="
            f"{meta['sha256']} 实际={actual}），基线可能被误替换/损坏，"
            f"请重跑 generate_gate_goldens.py 并由 reviewer 复核")


def test_generator_check_mode_reports_no_drift():
    """--check 模式：当前实现与现有 manifest 应无漂移（退出码 0）。"""
    generate_gate_goldens = _load_cases()[1]
    rc = generate_gate_goldens.run_check(_GOLDEN_DIR)
    assert rc == 0, "当前实现与 gate golden manifest 存在漂移，--check 应返回 0"


def test_current_output_matches_goldens():
    gate_cases = _load_cases()[0]
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for feature, meta in manifest["features"].items():
        expected = np.load(_GOLDEN_DIR / meta["file"])
        current = np.asarray(gate_cases.compute(feature))
        assert current.shape == expected.shape, f"{feature} shape 变化"
        err = float(np.abs(current.astype(np.float64)
                           - expected.astype(np.float64)).max())
        assert err <= 1e-6, f"{feature} golden diff={err:.3e} > 1e-6"


def test_skin_oklch_softband_probe_not_blind(monkeypatch):
    """r12 观察窗清偿的验收镜像: 软边带探针对椭圆常数变更必须敏感（非盲）。

    R10 实证: 重拟合改半轴+软带, skin/skin_oklch 两 case（饱和肤色核内锚）
    输出零变化。本探针 case 的存在意义就是消除该盲区——半轴 +10% 平移后
    掩码输出必须变化（过渡带 16 行的 d 随半轴线性移动）。
    """
    gate_cases = _load_cases()[0]
    import pixo.render.core.skin as skin_mod

    base = np.asarray(gate_cases.compute("skin_oklch_softband"))
    monkeypatch.setattr(skin_mod, "SKIN_OKLAB_MAJOR",
                        skin_mod.SKIN_OKLAB_MAJOR * 1.10)
    shifted = np.asarray(gate_cases.compute("skin_oklch_softband"))
    assert not np.array_equal(base, shifted), (
        "软边带探针对椭圆常数变更零敏感 —— 探针设计失效, 无法守护软边带")


def test_skin_oklch_softband_band_width_observable():
    """软带宽度维度的敏感性镜像: SKIN_OKLAB_SOFT_BAND 0.31 → 0.25 (R10
    重拟合前旧值, 即 R10 原盲区的触发场景) 时探针输出必须变化。

    not_blind 测试 monkeypatch 的是 SKIN_OKLAB_MAJOR (函数体内引用); 而
    SKIN_OKLAB_SOFT_BAND 是 skin_mask_oklab 的**默认参数** (定义时绑定),
    运行时 monkeypatch 模块常数不触达 —— 真实 gate 场景是源码改常数后
    跨进程重跑 (默认参数重新求值), 显式传参与之数学等价, 故走此路径断言。
    """
    gate_cases = _load_cases()[0]
    from pixo.render.core.skin import skin_mask_oklab

    probe = gate_cases._skin_softband_probe()
    m_now = skin_mask_oklab(probe)                  # 现行软带 (源码常数)
    m_old = skin_mask_oklab(probe, soft_band=0.25)  # R10 前旧值
    assert not np.array_equal(m_now, m_old), (
        "软边带探针对 SKIN_OKLAB_SOFT_BAND 变更零敏感 —— R10 原盲区场景重现")
    # committed 金样本路径 (compute 走默认参数) 须与现行软带显式调用一致
    assert np.array_equal(
        np.asarray(gate_cases.compute("skin_oklch_softband")), m_now)


def test_skin_oklch_softband_covers_transition_band():
    """探针带须真实覆盖软过渡带: 当前常数下应有行落在 d∈[1, 1+band] 且
    掩码值介于 (0,1) 开区间（纯 0/1 行锁不住软带宽度）。"""
    gate_cases = _load_cases()[0]
    mask = np.asarray(gate_cases.compute("skin_oklch_softband"))
    row_max = mask.max(axis=1)
    transition_rows = int(((row_max > 0.0) & (row_max < 1.0)).sum())
    assert transition_rows >= 8, (
        f"过渡带行数 {transition_rows} < 8: 探针 C 范围与当前椭圆失配, "
        "软边带宽度变更不可观测")
