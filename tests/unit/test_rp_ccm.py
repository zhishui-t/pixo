"""M-O3 根多项式 CCM 单元测试 (OWN_PIPELINE_STAGE1_DESIGN §4)。

验证: 恒等系数逐位 no-op 快路径、合成色卡 (均匀网格调色板) 最小二乘精确恢复、
曝光不变性 (输入 ×k → 输出 ×k, 根多项式性质)、特征等比缩放、负输入/色域外
防御、JSON 往返、非法形状/度数/权重异常路径。

权威依据: Finlayson & Xu 2015 (CIC23) / Finlayson-Mackiewicz-Hurlbert 2015
(IEEE TIP) 根多项式项集与曝光不变性。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.core.rp_ccm import (RPCCM, apply_rp_ccm, fit_rp_ccm,
                                     identity_rp_ccm, load_rp_ccm, n_terms,
                                     rp_features, save_rp_ccm)


def _palette(n: int = 512, lo: float = 0.05, hi: float = 0.9,
             seed: int = 42) -> np.ndarray:
    """合成"色卡": [lo,hi]³ 均匀随机线性 RGB 调色板 (N,3), 避开裁剪区。"""
    rng = np.random.default_rng(seed)
    return (lo + (hi - lo) * rng.random((n, 3)))


def _positive_matrix(degree: int, scale: float = 0.3,
                     seed: int = 7) -> np.ndarray:
    """全正随机系数矩阵 (行和有界, 恒正映射便于构造无裁剪的合成目标)。"""
    rng = np.random.default_rng(seed)
    return scale * rng.random((3, n_terms(degree)))


# ---------------------------------------------------------------------------
# 恒等系数 no-op (核心纪律: 快路径逐位不变)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("degree", [1, 2])
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_identity_coeff_bitwise_noop(degree, dtype):
    """恒等系数: 任意形状/精度输入原样返回 (同一对象, 逐位不变, 连转换都不做)。"""
    rng = np.random.default_rng(1)
    for shape in [(4, 5, 3), (11, 3), (3,)]:
        img = (rng.random(shape) * dtype(1.0)).astype(dtype)
        out = apply_rp_ccm(img, identity_rp_ccm(degree))
        assert out is img, "恒等快路径必须原样返回输入对象 (零拷贝)"
        assert out.dtype == dtype


@pytest.mark.parametrize("degree", [1, 2])
def test_is_identity_detection(degree):
    """恒等判定: identity_rp_ccm 为恒等; 矩阵 [I|0] 手写亦然; 1e-9 扰动即非恒等。"""
    assert identity_rp_ccm(degree).is_identity
    m = np.zeros((3, n_terms(degree)))
    m[:, :3] = np.eye(3)
    assert RPCCM(matrix=m, degree=degree).is_identity
    m_pert = m.copy()
    m_pert[0, 0] += 1e-9
    assert not RPCCM(matrix=m_pert, degree=degree).is_identity


def test_identity_via_matrix_literal_noop():
    """非 identity_rp_ccm 构造、但矩阵恰为 [I|0] 的系数同样逐位 no-op。"""
    rng = np.random.default_rng(3)
    img = rng.random((6, 4, 3)).astype(np.float32)
    out = apply_rp_ccm(img, RPCCM(matrix=np.eye(3), degree=1))
    assert out is img
    m6 = np.hstack([np.eye(3), np.zeros((3, 3))])
    out6 = apply_rp_ccm(img, RPCCM(matrix=m6, degree=2))
    assert out6 is img


# ---------------------------------------------------------------------------
# 合成色卡恢复精度 (拟合为纯函数, 核心验收)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("degree", [1, 2])
def test_synthetic_chart_exact_recovery(degree):
    """均匀网格合成色卡上, 无噪最小二乘精确恢复真值矩阵 (≤1e-9),
    apply 复现目标 ≤1e-6 (float32 出口量化量级)。"""
    src = _palette()
    m_true = _positive_matrix(degree)
    dst = rp_features(src, degree) @ m_true.T           # 线性 RGB → 线性 RGB
    top = float(np.abs(dst).max())
    m_true = m_true * (0.95 / top)                      # 缩放使目标不触 [0,1] 裁剪
    dst = rp_features(src, degree) @ m_true.T

    coeff = fit_rp_ccm(src, dst, degree=degree)
    assert np.allclose(coeff.matrix, m_true, rtol=0, atol=1e-9), \
        "无噪精确观测下最小二乘应恢复真值矩阵"

    recovered = apply_rp_ccm(src, coeff)
    assert recovered.dtype == np.float32
    assert np.allclose(recovered.astype(np.float64), dst, rtol=0, atol=1e-6)


def test_synthetic_chart_noisy_fit_stable():
    """弱噪声 (σ=2e-3) 下恢复矩阵仍贴近真值 (≤0.05, 稳定性冒烟, 非精确解)。"""
    src = _palette()
    m_true = _positive_matrix(2)
    dst = rp_features(src, 2) @ m_true.T
    dst = dst * (0.95 / float(np.abs(dst).max()))
    rng = np.random.default_rng(5)
    noisy = np.clip(dst + rng.normal(0.0, 2e-3, dst.shape), 0.0, 1.0)

    coeff = fit_rp_ccm(src, noisy, degree=2)
    assert float(np.abs(coeff.matrix - m_true * (0.95 / float(np.abs(
        rp_features(src, 2) @ m_true.T).max()))).max()) < 0.05


def test_fit_sample_weights_equal_row_duplication():
    """权重 2 ≈ 样本行复制两份 (加权 LS 语义一致性)。"""
    src = _palette(64)
    m_true = _positive_matrix(2)
    dst = rp_features(src, 2) @ m_true.T
    w = np.ones(64)
    w[:16] = 2.0
    src_dup = np.vstack([src, src[:16]])
    dst_dup = np.vstack([dst, dst[:16]])
    a = fit_rp_ccm(src, dst, degree=2, weights=w)
    b = fit_rp_ccm(src_dup, dst_dup, degree=2)
    assert np.allclose(a.matrix, b.matrix, rtol=0, atol=1e-9)


def test_fit_rank_deficient_returns_min_norm_no_crash():
    """全灰样本 (特征秩亏) 不崩溃, 返回有限最小范数解。"""
    gray = np.full((32, 3), 0.25)
    coeff = fit_rp_ccm(gray, gray, degree=2)
    assert np.isfinite(coeff.matrix).all()


# ---------------------------------------------------------------------------
# 曝光不变性 (根多项式核心性质: 输入 ×k → 输出 ×k)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("k", [0.25, 0.5, 2.0, 4.0])
def test_features_scale_exactly_with_exposure(k):
    """特征等比缩放: f(k·x) = k·f(x) (根多项式性质的数值根基, ≤1e-12)。"""
    src = _palette(256)
    f0 = rp_features(src, 2)
    fk = rp_features(k * src, 2)
    assert np.allclose(fk, k * f0, rtol=0, atol=1e-12)


def test_apply_exposure_invariance():
    """apply 曝光不变: apply(k·x) ≈ k·apply(x) (系数取小幅度避免触发 [0,1] 裁剪)。"""
    rng = np.random.default_rng(9)
    m_small = (0.1 + 0.05 * rng.random((3, 6)))     # 行和 ≤0.45, 输出 ≤~0.12
    coeff = RPCCM(matrix=m_small, degree=2)
    src = 0.01 + 0.24 * rng.random((4096, 3))       # [0.01, 0.25]
    out = apply_rp_ccm(src, coeff).astype(np.float64)
    out_k = apply_rp_ccm(2.0 * src, coeff).astype(np.float64)
    assert out.max() < 0.5, "测试前提: 输出远低于裁剪区"
    ratio = out_k / out
    assert np.allclose(ratio, 2.0, rtol=1e-5), \
        f"曝光 2x 后输出应精确 2x, 实测比率偏差 {np.abs(ratio - 2.0).max():.3e}"


def test_zero_input_exact_zero():
    """黑端点: 0 输入特征全 0, 输出精确 0 (无 √0 噪声)。"""
    coeff = RPCCM(matrix=_positive_matrix(2), degree=2)
    out = apply_rp_ccm(np.zeros((3, 3)), coeff)
    assert np.array_equal(out, np.zeros((3, 3), dtype=np.float32))


# ---------------------------------------------------------------------------
# 值域 / 防御 / dtype 契约
# ---------------------------------------------------------------------------

def test_negative_input_clamped_no_nan():
    """契约外负输入按 0 处理: √ 项无 NaN, 输出有限且 [0,1]。"""
    coeff = RPCCM(matrix=_positive_matrix(2), degree=2)
    out = apply_rp_ccm(np.array([[-0.5, 0.2, 0.1],
                                 [0.3, -0.1, 0.0],
                                 [-1.0, -1.0, -1.0]]), coeff)
    assert np.isfinite(out).all()
    assert bool((out >= 0.0).all() and (out <= 1.0).all())


def test_out_of_gamut_clipped():
    """夸张系数导致色域外: 输出 clip [0,1], 无 NaN/Inf。"""
    big = np.full((3, 6), 50.0)
    out = apply_rp_ccm(_palette(64), RPCCM(matrix=big, degree=2))
    assert np.isfinite(out).all()
    assert bool((out == 0.0).all() or (out <= 1.0).all())
    assert float(out.max()) <= 1.0


def test_apply_dtype_contract():
    """非恒等路径出口 float32; float64/float32 输入均可。"""
    coeff = RPCCM(matrix=_positive_matrix(2), degree=2)
    src64 = _palette(16)
    assert apply_rp_ccm(src64, coeff).dtype == np.float32
    assert apply_rp_ccm(src64.astype(np.float32), coeff).dtype == np.float32


def test_apply_rejects_non_rpccm_coeff():
    """coeff 非 RPCCM → TypeError (防止裸矩阵误用绕过校验)。"""
    with pytest.raises(TypeError):
        apply_rp_ccm(_palette(4), np.eye(3))


# ---------------------------------------------------------------------------
# 形状 / 参数校验 (异常路径)
# ---------------------------------------------------------------------------

def test_features_shapes_and_invalid_degree():
    """特征形状随输入 (...,3)→(...,n); 非法 degree/形状报 ValueError。"""
    img = np.random.default_rng(11).random((4, 5, 3))
    assert rp_features(img, 1).shape == (4, 5, 3)
    assert rp_features(img, 2).shape == (4, 5, 6)
    with pytest.raises(ValueError):
        rp_features(img, 3)
    with pytest.raises(ValueError):
        rp_features(np.zeros(4))
    with pytest.raises(ValueError):
        rp_features(np.zeros((2, 2)), 2)


def test_rpccm_validation_errors():
    """RPCCM: 非法 degree / 矩阵形状 / NaN 均拒绝。"""
    with pytest.raises(ValueError):
        RPCCM(matrix=np.eye(3), degree=3)
    with pytest.raises(ValueError):
        RPCCM(matrix=np.eye(3), degree=2)          # (3,3) ≠ (3,6)
    bad = np.eye(3)
    bad[0, 0] = np.nan
    with pytest.raises(ValueError):
        RPCCM(matrix=bad, degree=1)


def test_fit_input_validation():
    """fit: 形状不匹配 / 空样本 / 权重长度或取值非法 → ValueError。"""
    src = _palette(16)
    with pytest.raises(ValueError):
        fit_rp_ccm(src, src[:15])
    with pytest.raises(ValueError):
        fit_rp_ccm(np.zeros((0, 3)), np.zeros((0, 3)))
    with pytest.raises(ValueError):
        fit_rp_ccm(src, src, weights=np.ones(15))
    with pytest.raises(ValueError):
        fit_rp_ccm(src, src, weights=-np.ones(16))
    with pytest.raises(ValueError):
        fit_rp_ccm(src, src, degree=5)


# ---------------------------------------------------------------------------
# JSON 往返
# ---------------------------------------------------------------------------

def test_json_roundtrip_bitwise(tmp_path):
    """save → load 矩阵逐位一致; 元数据保留。"""
    coeff = fit_rp_ccm(_palette(), rp_features(_palette(), 2) @ _positive_matrix(2).T,
                       degree=2, camera="nikon_z_5", source="test")
    path = save_rp_ccm(coeff, tmp_path / "rp_ccm_nikon_z_5.json")
    loaded = load_rp_ccm(path)
    assert np.array_equal(loaded.matrix, coeff.matrix)
    assert loaded.degree == coeff.degree
    assert loaded.camera == "nikon_z_5"
    assert loaded.source == coeff.source


def test_load_rejects_invalid(tmp_path):
    """load: 文件缺失 → FileNotFoundError; 非 RP-CCM JSON / 未知版本 → ValueError。"""
    import json
    with pytest.raises(FileNotFoundError):
        load_rp_ccm(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"type": "something_else"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_rp_ccm(bad)
    bad_v2 = tmp_path / "bad_v2.json"
    bad_v2.write_text(json.dumps({"type": "pixo_rp_ccm", "version": 99,
                                  "degree": 2, "matrix": [[0] * 6] * 3}),
                      encoding="utf-8")
    with pytest.raises(ValueError):
        load_rp_ccm(bad_v2)


def test_meta_passthrough():
    """拟合统计等元数据经 to_dict/from_dict 完整往返。"""
    coeff = identity_rp_ccm(degree=2, meta={"n_samples": 123, "n_photos": 3})
    d = coeff.to_dict()
    assert d["meta"]["n_samples"] == 123
    assert RPCCM.from_dict(d).meta["n_photos"] == 3
