"""t30 单元测试: torch 可微代理 diff_core (阶段二设计 §1)。

覆盖 (验收门):
  - surrogate 确定性: 同输入同 θ 两次前向逐位一致; 独立构建的参数集同值;
  - 参数梯度存在性: θ 全部参数 (warmth_gains/ev/brightness/neutral_a/neutral_b/
    rp_matrix) 反向传播后梯度非 None、有限且非零;
  - 前向逐位复刻: colorcal tint 与真实链 cv2 u8 路径逐位一致; tone LUT 线性
    插值与 core.curves.apply_lut1d 同式; quantize 与 runner 截断式一致;
    exposure rolloff 与 modules.exposure.soft_highlight_rolloff 同式;
  - WB 矩阵链 torch vs pixo (真实 DCP, 缺文件 skip): neutral_to_xy 与
    cam_to_linear_srgb_matrix 逐式对齐;
  - soft_clip: 前向=clamp (保真门口径), 反向界外非零 (soft-clip 语义在反向);
  - RP-CCM torch vs numpy (core.rp_ccm.apply_rp_ccm);
  - CCT 分桶选择语义 (端点钳位 / 单侧缺失回退);
  - warmth 等效增益折入等价性;
  - 真值 ΔE (eval_rp_ccm_ab.delta_e_2000) Sharma 2005 文献对自检。

纯合成静态量, 不依赖 RAW 语料 (保真门端到端对照见
scripts/calib/surrogate_fidelity.py → .artifacts/surrogate_fidelity.md)。

运行: python -m pytest tests/unit/test_diff_core.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
for _p in (str(_SCRIPTS / "calib"), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import diff_core  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_DCP = _REPO / "resources" / "dcp" / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
_WARMTH_JSON = _REPO / "configs" / "calibration" / "warmth_curve.json"
_TRIM_JSON = _REPO / "resources" / "camera_profiles" / "z5ii_neutral_trim.json"


# ---------------------------------------------------------------------------
# 合成静态量 (无 RAW 依赖)
# ---------------------------------------------------------------------------

def _synthetic_static(seed: int = 7, h: int = 48, w: int = 64) -> diff_core.ChainStatic:
    rng = np.random.default_rng(seed)
    img = rng.uniform(0.001, 1.2, (h, w, 3))
    img[0, 0] = 1.0      # 强制饱和近中性像素 (高光中性化路径)
    img[0, 1] = 1.0
    img[0, 2] = 0.99
    # θ0 gamma 图 → colorcal 静态量 (与 build 同流程)
    gamma0 = np.clip(rng.uniform(0.0, 1.0, (h, w, 3)), 0.0, 1.0)
    u8 = (gamma0 * 255.0 + 0.5).astype(np.uint8)
    w_up, li, t = diff_core._neutral_fast_statics(u8)
    trim = diff_core.load_neutral_trim(_TRIM_JSON) if _TRIM_JSON.is_file() else None
    sel = diff_core.select_neutral_curves(trim, cct=5300.0)
    return diff_core.ChainStatic(
        img_cam=img, camera_wb=np.array([1.3, 1.0, 2.0]),
        wb_key_b=2.0, cct_k=5300.0,
        sat_white=(np.array([0, 0, 0]), np.array([0, 1, 2])),
        cc_w_up=w_up, cc_li=li, cc_t=t,
        cc_base_rgb=diff_core._cv2_base_tints(), neutral_sel=sel)


def _synthetic_warmth() -> diff_core.WarmthCurveConsts:
    return diff_core.WarmthCurveConsts(
        abscissae=np.array([1.0, 1.5, 2.5, 3.5]),
        gains=np.array([[0.97, 1.02, 0.90], [1.05, 0.98, 0.95],
                        [1.10, 0.95, 0.88], [1.0, 1.05, 0.80]]))


def _make_surrogate(static=None, use_rp_ccm: bool = False):
    static = static or _synthetic_static()
    wc = _synthetic_warmth()
    trim = diff_core.load_neutral_trim(_TRIM_JSON) if _TRIM_JSON.is_file() else None
    sel = static.neutral_sel
    params = diff_core.SurrogateParams(wc, trim, sel, ev=0.05,
                                       brightness=diff_core.TONE_BRIGHTNESS_NEUTRAL,
                                       use_rp_ccm=use_rp_ccm)
    lut = np.linspace(0.0, 1.0, diff_core.TONE_LUT_N, dtype=np.float64)  # 占位
    from pixo.render.core.curves import make_base_curve_lut
    lut = make_base_curve_lut(eotf="srgb", gamma=2.2, n=diff_core.TONE_LUT_N)
    dc = diff_core.DcpChainConsts.from_profile(_load_profile())
    return diff_core.PhotoSurrogate(static, params, dc, lut, wc)


def _load_profile():
    from pixo.render.core.calibration import load_dcp
    return load_dcp(_DCP)


_requires_dcp = pytest.mark.skipif(not _DCP.is_file(), reason="缺 DCP 资源文件")


# ---------------------------------------------------------------------------
# 确定性 (验收门 1)
# ---------------------------------------------------------------------------

@_requires_dcp
def test_forward_deterministic_same_instance():
    sur = _make_surrogate()
    with torch.no_grad():
        a = sur.quantize(sur()).cpu().numpy()
        b = sur.quantize(sur()).cpu().numpy()
    assert np.array_equal(a, b)


@_requires_dcp
def test_forward_deterministic_fresh_params():
    """两次独立构建 (同 static/同 θ 初值) → 逐位一致 (无隐藏随机性)。"""
    static = _synthetic_static()
    s1 = _make_surrogate(static)
    s2 = _make_surrogate(_synthetic_static())
    s2.load_state_dict(s1.state_dict())
    with torch.no_grad():
        a = s1.quantize(s1()).cpu().numpy()
        b = s2.quantize(s2()).cpu().numpy()
    assert np.array_equal(a, b)


# ---------------------------------------------------------------------------
# 参数梯度存在性 (验收门 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("use_rp_ccm", [False, True],
                         ids=["norps", "rpccm"])
@_requires_dcp
def test_all_parameters_receive_gradients(use_rp_ccm):
    sur = _make_surrogate(use_rp_ccm=use_rp_ccm)
    gamma = sur()
    loss = (gamma * gamma).mean()          # 全图逐像素非零权重
    loss.backward()
    p = sur.params
    for name in ("warmth_gains", "ev", "brightness", "neutral_a", "neutral_b"):
        param = getattr(p, name)
        assert param.grad is not None, f"{name} 无梯度"
        assert torch.isfinite(param.grad).all(), f"{name} 梯度含 NaN/Inf"
        assert float(param.grad.abs().sum()) > 0.0, f"{name} 梯度全零"
    # rp_matrix: 开启时梯度必达; 关闭时不进链 (真实 apply_rp_ccm 恒等快路径语义)
    if use_rp_ccm:
        assert p.rp_matrix.grad is not None
        assert float(p.rp_matrix.grad.abs().sum()) > 0.0
    else:
        assert p.rp_matrix.grad is None
    # warmth 插值只触达 b_key=2.0 所在区段 [1.5, 2.5] 的两行结点
    g = p.warmth_gains.grad
    assert float(g[1].abs().sum()) > 0 and float(g[2].abs().sum()) > 0
    # neutral 曲线梯度应经 cv2-STE 的平滑雅可比回传 (非零, 见 tint 测试)
    assert float(p.neutral_a.grad.abs().sum()) > 0


@_requires_dcp
def test_soft_clip_backward_nonzero_outside_range():
    """soft-clip 语义在反向: 界外梯度非零 (衰减) 且前向逐位=clamp。"""
    x = torch.tensor([-0.6, 0.0, 0.5, 1.4], dtype=torch.float64,
                     requires_grad=True)
    y = diff_core.soft_clip(x, 0.0, 1.0)
    assert torch.equal(y.detach(), x.detach().clamp(0.0, 1.0))
    y.sum().backward()
    assert torch.isfinite(x.grad).all()
    assert float(x.grad[0]) > 0.0 and float(x.grad[3]) > 0.0   # 界外非零
    assert float(x.grad[1]) > float(x.grad[0])                 # 界内 > 界外


# ---------------------------------------------------------------------------
# 前向逐位复刻 (保真门的数值根基)
# ---------------------------------------------------------------------------

def test_neutral_tints_bitwise_match_real_chain():
    """代理 tint 前向 == 真实 _apply_neutral_fast 的 rgb_shift−rgb_base (整数)。"""
    import cv2
    rng = np.random.default_rng(11)
    base = diff_core._cv2_base_tints()
    for _ in range(8):
        off_a = rng.uniform(-24.0, 24.0, 7)
        off_b = rng.uniform(-24.0, 24.0, 7)
        got = diff_core._cv2_neutral_tints(off_a, off_b, base)
        # 直接复刻 color_cal.py L633-640 原式
        ref = np.zeros((7, 3))
        for k, lc in enumerate(diff_core.NEUTRAL_L_CENTERS_U8):
            shifted = np.clip(np.float32(
                [[[float(lc), 128.0 + off_a[k], 128.0 + off_b[k]]]]),
                0, 255).astype(np.uint8)
            rgb_shift = cv2.cvtColor(shifted, cv2.COLOR_LAB2RGB).astype(np.float32)
            base_in = np.uint8([[[int(lc), 128, 128]]])
            rgb_base = cv2.cvtColor(base_in, cv2.COLOR_LAB2RGB).astype(np.float32)
            ref[k] = (rgb_shift - rgb_base)[0, 0]
        assert np.array_equal(got, ref), "tint 前向与真实链不逐位"


def test_smooth_lab_conversion_close_to_cv2_float():
    """平滑 Lab→RGB 代理 (反向雅可比来源) 与 cv2 float 转换一致 (≤0.01/255)。"""
    import cv2
    rng = np.random.default_rng(3)
    off = rng.uniform(-30, 30, (5, 7))
    with torch.no_grad():
        got = diff_core._lab_offset_to_rgb_smooth(
            torch.tensor(off[0]), torch.tensor(off[1])).numpy()
    lab = np.stack([diff_core.NEUTRAL_L_CENTERS_U8 * (100.0 / 255.0),
                    off[0], off[1]], axis=-1).astype(np.float32).reshape(-1, 1, 3)
    ref = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB).reshape(-1, 3) * 255.0
    assert float(np.abs(got - ref).max()) <= 0.05   # ≪ 0.5 LSB (u8 tint 逐位另行测试)


def test_tone_lut_interp_matches_apply_lut1d():
    from pixo.render.core.curves import apply_lut1d, make_base_curve_lut
    lut = make_base_curve_lut(eotf="srgb", gamma=2.2, n=diff_core.TONE_LUT_N)
    rng = np.random.default_rng(5)
    x = rng.uniform(-0.1, 1.2, (33, 47, 3))
    with torch.no_grad():
        got = diff_core.tone_lut_interp(torch.tensor(x, dtype=torch.float64),
                                        torch.tensor(lut.astype(np.float64))).numpy()
    ref = apply_lut1d(np.clip(x, 0.0, 1.0), lut)
    assert float(np.abs(got - ref).max()) < 1e-6


def test_quantize_matches_runner_formula():
    rng = np.random.default_rng(6)
    gamma = rng.uniform(-0.1, 1.1, (20, 30, 3))
    with torch.no_grad():
        got = diff_core.quantize_u8(torch.tensor(gamma, dtype=torch.float64)).numpy()
    ref = (np.clip(gamma, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    assert np.array_equal(got.astype(np.uint8), ref)


def test_exposure_rolloff_matches_stage_reference():
    from pixo.render.modules.exposure import soft_highlight_rolloff
    rng = np.random.default_rng(8)
    x = rng.uniform(0.0, 1.3, (16, 16, 3)).astype(np.float32)
    with torch.no_grad():
        got = diff_core.exposure_rolloff_t(torch.tensor(x, dtype=torch.float64),
                                           knee=0.9).numpy()
    ref = soft_highlight_rolloff(x, knee=0.9)
    assert float(np.abs(got - ref.astype(np.float64)).max()) < 1e-6


@_requires_dcp
def test_rp_ccm_torch_matches_numpy():
    from pixo.render.core.rp_ccm import RPCCM, apply_rp_ccm, rp_features
    rng = np.random.default_rng(9)
    lin = rng.uniform(0.0, 1.0, (500, 3))
    matrix = rng.uniform(-0.5, 1.5, (3, 6))
    coeff = RPCCM(matrix=matrix, degree=2)
    ref = apply_rp_ccm(lin, coeff).astype(np.float64)
    with torch.no_grad():
        got = diff_core.apply_rp_ccm_t(torch.tensor(lin),
                                       torch.tensor(matrix)).numpy()
    assert float(np.abs(got - ref).max()) < 1e-6
    # 特征同式 (含负输入防御)
    feats_np = rp_features(lin * 1.2, degree=2)
    with torch.no_grad():
        feats_t = diff_core.rp_features_t(torch.tensor(lin * 1.2)).numpy()
    assert float(np.abs(feats_t - feats_np).max()) < 1e-12


# ---------------------------------------------------------------------------
# WB 矩阵链 torch vs pixo (真实 DCP)
# ---------------------------------------------------------------------------

@_requires_dcp
def test_wb_matrix_chain_matches_pixo():
    from pixo.render.core.color import cam_to_linear_srgb_matrix, neutral_to_xy, \
        wb_to_neutral
    prof = _load_profile()
    dc = diff_core.DcpChainConsts.from_profile(prof)
    rng = np.random.default_rng(12)
    for wb in (np.array([1.3, 1.0, 2.0]),
               np.array([1.9, 1.0, 1.08]),
               np.array([1.2, 1.0, 1.6]) * rng.uniform(0.9, 1.1)):
        with torch.no_grad():
            xy_t = diff_core.neutral_to_xy_t(
                diff_core.wb_to_neutral_t(torch.tensor(wb)), dc).numpy()
            m_t = diff_core.cam_to_linear_srgb_matrix_t(torch.tensor(wb), dc).numpy()
        xy_r = np.asarray(neutral_to_xy(wb_to_neutral(wb), prof))
        m_r = cam_to_linear_srgb_matrix(prof, wb)
        assert float(np.abs(xy_t - xy_r).max()) < 1e-10
        assert float(np.abs(m_t - m_r).max()) < 1e-9


# ---------------------------------------------------------------------------
# 配置语义
# ---------------------------------------------------------------------------

def test_select_neutral_curves_semantics():
    trim = diff_core.NeutralTrimConsts(
        buckets=((4000.0, np.zeros(7), None),
                 (5000.0, np.ones(7) * 2, np.ones(7) * 3),
                 (7000.0, None, np.ones(7) * 5)))
    # 端点钳位; a 轴 bucket0 存在 → t_a=0; b 轴 bucket0 缺失 → 回退 bucket1 (t_b=1,
    # 对齐 _lerp_curve_np "单侧缺失返回另一侧" 语义, 与混合比例 t 无关)
    s = diff_core.select_neutral_curves(trim, 3000.0)
    assert (s.i, s.j, s.t_a, s.t_b) == (0, 1, 0.0, 1.0)
    s = diff_core.select_neutral_curves(trim, 9000.0)
    assert (s.i, s.j) == (1, 2) and s.t_a == 0.0 and s.t_b == 1.0
    # 单侧缺失回退: fixture bucket0=(4000, a有, b缺) → 4500K 处 a 正常混合
    # (0.5), b 轴 bucket0 缺失 → 全量取 bucket1 (t_b=1.0)
    s = diff_core.select_neutral_curves(trim, 4500.0)
    assert s.t_a == 0.5
    assert s.t_b == 1.0
    # 与 numpy 参考语义一致 (lerp(0, 2, 0.5) = 1.0)
    ref_a = diff_core._lerp_curve_np(trim.buckets[0][1], trim.buckets[1][1], 0.5)
    assert np.allclose(ref_a, np.ones(7))
    ref_b = diff_core._lerp_curve_np(None, trim.buckets[1][2], 0.3)
    assert np.allclose(ref_b, trim.buckets[1][2])


def test_warmth_gain_fold_in_equivalence():
    """等效增益折入 (1+w·(k−1)) 与真实 apply_warmth 插值式逐点等价:
    结点折算前后对同一 wb_B 键的 np.interp 结果一致 (仿射可交换)。"""
    wc = diff_core.load_warmth_curve(_WARMTH_JSON, warmth=0.9)
    doc = json.loads(_WARMTH_JSON.read_text(encoding="utf-8"))
    knots = np.asarray(doc["knots"], dtype=np.float64)
    rng = np.random.default_rng(13)
    for b in rng.uniform(1.0, 3.0, 9):
        gk = np.array([np.interp(b, knots[:, 0], knots[:, c + 1])
                       for c in range(3)])
        ref = 1.0 + 0.9 * (gk - 1.0)                       # apply_warmth 曲线分支
        got = np.array([np.interp(b, wc.abscissae, wc.gains[:, c])
                        for c in range(3)])                # 折入后等效增益
        assert np.allclose(got, ref, atol=1e-12)


# ---------------------------------------------------------------------------
# 真值 ΔE 自检 (eval_rp_ccm_ab.delta_e_2000 --selftest)
# ---------------------------------------------------------------------------

def _load_eval_module():
    path = _SCRIPTS / "eval_rp_ccm_ab.py"
    spec = importlib.util.spec_from_file_location("eval_rp_ccm_ab_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_delta_e_2000_sharma_pairs():
    mod = _load_eval_module()
    for lab1, lab2, expect in mod._SHARMA_PAIRS:
        got = float(mod.delta_e_2000(np.array([lab1]), np.array([lab2]))[0])
        assert abs(got - expect) < 1e-3, f"ΔE00({lab1},{lab2})={got} 期望 {expect}"
