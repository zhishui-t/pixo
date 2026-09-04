"""t32 optimize.py 单测 —— loss/罚项/绑定/确定性/θ 导出 (阶段二设计 §3+§4)。

覆盖 (合成数据, 不依赖 RAW 语料):
  - cal_ev_weights 与运行时 exposure._cal_ev 逐位对齐 (真实表 + 合成表,
    含端点钳位 / 越界 / wb 邻域边界 / 邻域不足回退);
  - scene_constraints 罚项的方向逻辑与零点性质 (单调弱先验 / 二阶平滑 /
    2D TV / 轴正性 hinge θ0 恒 0);
  - proxy 基元 (Huber 分段 / torch Lab vs numpy / sRGB 解码表一致性);
  - 共享 θ 绑定: 梯度经 rebind 流向 SharedTheta 全部数据参数, 幂等, G-5
    轨道 (ev_override / use_rp=False) 不污染;
  - θ 导出: to_theta → theta_io 校验通过 + roundtrip 恒等 + warmth 钳界;
  - seed 确定性: 同构 mini 语料 2 步 Adam 的 loss 序列逐位一致。
"""
from __future__ import annotations

import importlib.util
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
import optimize  # noqa: E402
import theta_io  # noqa: E402
from diff_core import (ChainStatic, DcpChainConsts, NeutralSelect,
                       NeutralTrimConsts, PhotoSurrogate, SurrogateParams,
                       WarmthCurveConsts)  # noqa: E402
from pixo.render.modules.exposure import _cal_ev  # noqa: E402


# ---------------------------------------------------------------------------
# 构建基座: 假 DCP 常量 / 静态量 / 代理 (无 cv2 依赖路径, colorcal 静态手工构造)
# ---------------------------------------------------------------------------

def _fake_dc() -> DcpChainConsts:
    cm1 = np.array([[1.0, 0.10, 0.02],
                    [0.05, 1.0, 0.08],
                    [0.02, 0.06, 1.0]])
    return DcpChainConsts(cm1=cm1, cm2=None, cc1=np.eye(3), cc2=None,
                          t1=2850.0, t2=6500.0, name="fake")


def _fake_warmth() -> WarmthCurveConsts:
    return WarmthCurveConsts(
        abscissae=np.array([1.0, 1.5, 2.0, 2.5, 3.0]),
        gains=np.array([[1.0, 1.0, 1.0], [1.1, 0.95, 0.9], [1.05, 0.97, 0.95],
                        [1.08, 0.94, 0.92], [1.0, 1.05, 0.85]]))


def _fake_trim() -> NeutralTrimConsts:
    a = np.arange(7, dtype=np.float64) - 3.0
    b = np.linspace(0.0, 2.0, 7)
    return NeutralTrimConsts(
        buckets=((4500.0, a.copy(), b.copy()), (6500.0, a - 1.0, b - 0.5)),
        default_a=a.copy(), default_b=b.copy())


def _fake_static(rng: np.random.Generator, h: int = 24, w: int = 20
                 ) -> ChainStatic:
    img = rng.random((h, w, 3)) * 0.8 + 0.1
    wb = np.array([1.0, 1.0, 1.25])
    h2, w2 = h // 2, w // 2
    return ChainStatic(
        img_cam=img, camera_wb=wb, wb_key_b=float(wb[2] / wb[1]),
        cct_k=5200.0, sat_white=None,
        cc_w_up=rng.random((h, w, 1)) * 0.5,
        cc_li=rng.integers(0, 6, size=(h2, w2)),
        cc_t=rng.random((h2, w2)),
        cc_base_rgb=np.tile(np.array([128.0, 128.0, 128.0]), (7, 1)),
        neutral_sel=NeutralSelect("buckets", i=0, j=1, t_a=0.5, t_b=0.5))


def _make_surrogate(rng, use_rp: bool = True) -> PhotoSurrogate:
    static = _fake_static(rng)
    params = SurrogateParams(_fake_warmth(), _fake_trim(), static.neutral_sel,
                             use_rp_ccm=use_rp,
                             rp_matrix=np.eye(3, 6) * 0.9 + 0.1)
    lut = torch.linspace(0.0, 1.0, 64, dtype=torch.float64) ** 2.2
    return PhotoSurrogate(static, params, _fake_dc(), lut, _fake_warmth())


def _fake_theta() -> theta_io.Theta:
    """最小合法 θ (不读 configs, 测试自包含; 通过 theta_io 校验规则)。"""
    knots = np.array([[1.0, 1.0, 1.0, 1.0],
                      [1.5, 1.1, 0.95, 0.9],
                      [2.0, 1.05, 0.97, 0.95],
                      [2.5, 1.08, 0.94, 0.92],
                      [3.0, 1.0, 1.05, 0.85]])
    table = np.array([[-6.0, 1.2, 1.0], [-5.0, 1.4, 1.2], [-4.0, 1.7, 1.4],
                      [-3.0, 2.0, 1.5]])
    a = np.linspace(0.0, -1.0, 7)
    b = np.linspace(0.0, 1.0, 7)
    fake = theta_io.Theta(
        warmth_knots=knots, warmth_domain=(1.5, 2.5),
        exposure_table=table, probe_hi=None,
        neutral_default=np.stack([a, b]),
        neutral_cct=np.array([4500.0, 6500.0]),
        neutral_by_cct=np.stack([np.stack([a, b]),
                                 np.stack([a - 0.5, b - 0.25])]),
        rp_ccm_coeff=np.eye(3, 6) * 0.9 + 0.1, rp_ccm_degree=2,
        skin_ellipse=np.array([0.015, 0.06, 0.046, 0.045, 0.19]),
        docs={}, sources={})
    fake.docs = {   # 最小写回模板 (save 的 _apply_theta 需要的结构骨架)
        "warmth_knots": {"knots": [], "_domain": {}},
        "exposure_table": {},
        "neutral_curves": {},
        "rp_ccm_coeff": {"type": "pixo_rp_ccm", "version": 1},
        "skin_ellipse": {"constants": {}, "new_ellipse_fit": {}},
    }
    return fake


def _make_kit(rng, ev_weight_idx: int = 1) -> tuple[optimize.PhotoKit,
                                                    optimize.SharedTheta]:
    theta = _fake_theta()
    shared = optimize.SharedTheta(theta)
    sur = _make_surrogate(rng)
    h, w = sur.static.img_cam.shape[:2]
    idx = rng.choice(h * w, size=64, replace=False)
    ref_lab = rng.normal(50.0, 10.0, size=(64, 3))
    kit = optimize.PhotoKit(
        pid="t", raw="t.NEF", group="g", cam="c", sur=sur,
        med=-4.5, wb_b=1.3,
        ev_w=optimize.cal_ev_weights(
            np.asarray(theta.exposure_table)[:, 0],
            np.asarray(theta.exposure_table)[:, 1], -4.5, 1.3),
        ref_u8=(rng.random((h, w, 3)) * 255).astype(np.uint8),
        sample_idx=idx, ref_lab=ref_lab)
    optimize._tensorize([kit])
    return kit, shared


# ---------------------------------------------------------------------------
# cal_ev_weights vs 运行时 _cal_ev
# ---------------------------------------------------------------------------

class TestCalEvWeights:
    def test_real_table_bitwise(self):
        tbl = np.asarray(theta_io.load_theta().exposure_table, dtype=np.float64)
        xs, ws, ys = tbl[:, 0], tbl[:, 1], tbl[:, 2]
        rng = np.random.default_rng(7)
        for _ in range(120):
            m = float(rng.uniform(xs.min() - 1.0, xs.max() + 1.0))
            wb = float(rng.uniform(0.8, 2.8))
            w = optimize.cal_ev_weights(xs, ws, m, wb)
            assert float(w @ ys) == pytest.approx(_cal_ev(m, (xs, ws, ys), wb),
                                                  abs=1e-12)
            w0 = optimize.cal_ev_weights(xs, ws, m, None)
            assert float(w0 @ ys) == pytest.approx(
                _cal_ev(m, (xs, ws, ys), None), abs=1e-12)

    def test_synthetic_endpoints_and_nodes(self):
        xs = np.array([-6.0, -4.0, -2.0, 0.0])
        ws = np.array([1.2, 1.8, 1.5, 2.1])
        ys = np.array([1.0, 1.3, 1.1, 1.6])
        cases = [(-6.0, 1.2), (-7.0, 9.9), (0.0, 2.1), (1.0, 0.5),   # 端点/越界
                 (-4.0, 1.8), (-4.0, 1.3),                           # 结点上
                 (-3.0, 1.55), (-3.0, 1.0)]                          # 邻域内
        for m, wb in cases:
            w = optimize.cal_ev_weights(xs, ws, m, wb)
            assert float(w @ ys) == pytest.approx(
                _cal_ev(m, (xs, ws, ys), wb), abs=1e-12)

    def test_neighborhood_fallback_keeps_med_key(self):
        """wb 邻域结点 <2 → 回退 med 主键 (权重 = med 插值)。"""
        xs = np.array([-6.0, 0.0, 6.0])
        ws = np.array([1.2, 1.5, 1.8])
        ys = np.array([1.0, 1.2, 1.4])
        w = optimize.cal_ev_weights(xs, ws, 0.5, 1.33)   # 0.5 的邻域仅 1 结点
        ref = optimize.cal_ev_weights(xs, ws, 0.5, None)
        assert np.allclose(w, ref)

    def test_duplicate_wb_guard(self):
        """邻域内 wb 重复不产生除零, 且与运行时 _cal_ev 行为一致。"""
        xs = np.array([-1.0, -0.9, 1.0])
        ws = np.array([1.5, 1.5, 1.5])
        ys = np.array([1.0, 1.1, 1.2])
        w = optimize.cal_ev_weights(xs, ws, -0.95, 1.5)
        assert np.all(np.isfinite(w))
        assert float(w @ ys) == pytest.approx(
            _cal_ev(-0.95, (xs, ws, ys), 1.5), abs=1e-12)


# ---------------------------------------------------------------------------
# 罚项
# ---------------------------------------------------------------------------

class TestPenalties:
    def test_net_sign(self):
        assert optimize._net_sign([1.0, 2.0, 3.0]) == 1.0
        assert optimize._net_sign([3.0, 2.0, 0.0]) == -1.0
        assert optimize._net_sign([1.0, 2.0, 1.0]) == 0.0   # 净差分和为 0

    def test_warmth_monotone_direction(self):
        g = torch.tensor([[1.0], [1.1], [1.2]], dtype=torch.float64)
        s = torch.tensor([1.0])
        mono_up, _ = optimize.penalty_warmth(g, s)      # 纯递增 + 先验: 零罚
        mono_dn, _ = optimize.penalty_warmth(g, -s)     # 反方向先验: 受罚
        assert float(mono_up) == 0.0
        assert float(mono_dn) > 0.0

    def test_warmth_smooth_linear_is_zero(self):
        g = torch.linspace(1.0, 2.0, 5, dtype=torch.float64)[:, None] \
            * torch.ones(1, 3, dtype=torch.float64)
        _, smooth = optimize.penalty_warmth(g, torch.zeros(3))
        assert float(smooth) == pytest.approx(0.0, abs=1e-16)
        g2 = g.clone()
        g2[2, 0] += 0.1                                  # 中点鼓包
        _, smooth2 = optimize.penalty_warmth(g2, torch.zeros(3))
        assert float(smooth2) > 0.0

    def test_ev_tv(self):
        ev = torch.tensor([1.0, 1.2, 1.0, 1.2], dtype=torch.float64)
        tv_med, tv_wb = optimize.penalty_ev_tv(ev, torch.tensor([0, 1, 2, 3]))
        assert float(tv_med) == pytest.approx((0.04 + 0.04 + 0.04) / 3)
        tv_wb2, _ = optimize.penalty_ev_tv(ev, torch.tensor([3, 2, 1, 0]))
        assert float(tv_wb2) == float(tv_wb)             # 排序置换不变 (同差集)

    def test_skin_pos_hinge(self):
        ok = torch.tensor([0.01, 0.06, 0.046, 0.045, 0.19], dtype=torch.float64)
        assert float(optimize.penalty_skin_pos(ok)) == 0.0
        bad = ok.clone()
        bad[3] = -0.01
        assert float(optimize.penalty_skin_pos(bad)) > 0.0

    def test_shared_theta_theta0_finite_and_skin_zero(self):
        shared = optimize.SharedTheta(_fake_theta())
        cons = shared.constraints()
        assert set(cons) == {"warmth_mono", "warmth_smooth", "ev_tv_med",
                             "ev_tv_wb", "neutral_mono_a", "neutral_mono_b",
                             "skin_pos"}
        for v in cons.values():
            assert torch.isfinite(v)
        assert float(cons["skin_pos"]) == 0.0            # θ0 轴正 → hinge 零
        total = shared.penalty_total()
        assert torch.isfinite(total)
        assert float(total) > 0.0                        # 数据结构上非全零


# ---------------------------------------------------------------------------
# proxy 基元
# ---------------------------------------------------------------------------

class TestProxyPrimitives:
    def test_huber_piecewise(self):
        r = torch.tensor([0.0, 0.5, 2.0, 3.0], dtype=torch.float64)
        out = optimize.huber(r, 2.0)
        assert out.tolist() == pytest.approx([0.0, 0.125, 2.0, 4.0])

    def test_huber_gradient_bounded(self):
        r = torch.tensor([0.1, 5.0], dtype=torch.float64, requires_grad=True)
        optimize.huber(r, 2.0).sum().backward()
        assert r.grad.tolist() == pytest.approx([0.1, 2.0])

    def test_lab_torch_matches_numpy(self):
        lin = np.random.default_rng(1).random((37, 3))
        from eval_rp_ccm_ab import linear_srgb_to_lab
        got = optimize.linear_srgb_to_lab_t(torch.tensor(lin)).numpy()
        want = linear_srgb_to_lab(lin)
        np.testing.assert_allclose(got, want, atol=1e-9)

    def test_srgb_decode_table_consistency(self):
        x = np.linspace(0.0, 1.0, 33)
        got = optimize.srgb_decode_t(
            torch.tensor(x, dtype=torch.float64)).numpy()
        from pixo.render.core.tone import srgb_decode
        want = srgb_decode(x.astype(np.float32))
        np.testing.assert_allclose(got, want, atol=1e-6)

    def test_lab_dist_zero_safe(self):
        a = torch.zeros(4, 3, dtype=torch.float64, requires_grad=True)
        d = optimize.lab_dist(a, a)
        assert float(d.sum().detach()) == pytest.approx(0.0, abs=1e-8)
        d.sum().backward()                               # 不得 NaN
        assert torch.isfinite(a.grad).all()


# ---------------------------------------------------------------------------
# 共享 θ 绑定与梯度流
# ---------------------------------------------------------------------------

class TestBind:
    def test_gradients_reach_all_data_params(self):
        rng = np.random.default_rng(3)
        kit, shared = _make_kit(rng)
        optimize.bind(kit, shared)
        loss = optimize.proxy_loss(kit, 1.0)
        loss.backward()
        for name in ("warmth_knots_gain", "ev_table", "neutral_a",
                     "neutral_b", "rp_matrix"):
            p = getattr(shared, name)
            assert p.grad is not None, name
            assert torch.isfinite(p.grad).all(), name
            assert float(p.grad.abs().sum()) > 0.0, name
        # skin_ellipse 无数据项 → 无梯度 (仅罚项路径)
        assert shared.skin_ellipse.grad is None

    def test_bind_idempotent(self):
        rng = np.random.default_rng(4)
        kit, shared = _make_kit(rng)
        optimize.bind(kit, shared)
        g1 = kit.sur().detach().clone()
        optimize.bind(kit, shared)
        g2 = kit.sur().detach().clone()
        assert torch.equal(g1, g2)

    def test_bind_ev_path_matches_cal_ev(self):
        rng = np.random.default_rng(5)
        kit, shared = _make_kit(rng)
        optimize.bind(kit, shared)
        ev_bound = float(kit.sur.params.ev)
        want = _cal_ev(kit.med, (
            shared.ev_xs.numpy(), shared.ev_ws.numpy(),
            shared.ev_table.detach().numpy()), kit.wb_b)
        assert ev_bound == pytest.approx(want, abs=1e-12)

    def test_bind_g5_tracks_no_rp_no_table_ev(self):
        rng = np.random.default_rng(6)
        kit, shared = _make_kit(rng)
        optimize.bind(kit, shared, ev_override=0.0, use_rp=False)
        p = kit.sur.params
        assert float(p.ev) == 0.0
        assert p.use_rp_ccm is False
        # rp 不进链 → rp_matrix 梯度应无路径 (前向不消费)
        optimize.proxy_loss(kit, 1.0).backward()
        assert shared.rp_matrix.grad is None

    def test_ev_table_gradient_flows_through_weights(self):
        """ev = w @ ev_table: 改变 ev 列改变输出, 梯度经权重结构传导。"""
        rng = np.random.default_rng(7)
        kit, shared = _make_kit(rng)
        optimize.bind(kit, shared)
        kit.sur().sum().backward()
        w_nonzero = torch.tensor(kit.ev_w, dtype=torch.float64) != 0
        assert (shared.ev_table.grad[w_nonzero] != 0).all()

    def test_two_kits_shared_params_accumulate(self):
        rng = np.random.default_rng(8)
        kit1, shared = _make_kit(rng)
        kit2, _ = _make_kit(rng)
        shared.zero_grad()
        for k in (kit1, kit2):
            optimize.bind(k, shared)
            (optimize.proxy_loss(k, 2.0)).backward()
        assert float(shared.ev_table.grad.abs().sum()) > 0.0
        assert float(shared.warmth_knots_gain.grad.abs().sum()) > 0.0


# ---------------------------------------------------------------------------
# θ 导出
# ---------------------------------------------------------------------------

class TestThetaExport:
    def test_to_theta_validates_and_roundtrips(self, tmp_path):
        rng = np.random.default_rng(9)
        _, shared = _make_kit(rng)
        with torch.no_grad():                        # 模拟优化后的 θ*
            shared.ev_table += 0.05
            shared.rp_matrix += 0.01
            shared.warmth_knots_gain += 0.02
        theta_star, clip = optimize.to_theta(shared, _fake_theta())
        assert clip["warmth_clipped"] == 0
        theta_io._validate(theta_star)               # 运行时校验规则通过
        out = theta_io.save_theta(theta_star, tmp_path / "out")
        rt = theta_io.load_theta({k: out[k] for k in theta_io.SOURCE_KEYS})
        for name in ("warmth_knots", "exposure_table", "rp_ccm_coeff",
                     "skin_ellipse"):
            assert theta_io.bitwise_equal(getattr(theta_star, name),
                                          getattr(rt, name))
        assert theta_io.bitwise_equal(theta_star.neutral_by_cct,
                                      rt.neutral_by_cct)

    def test_to_theta_clamps_warmth_and_reports(self):
        rng = np.random.default_rng(10)
        _, shared = _make_kit(rng)
        with torch.no_grad():
            shared.warmth_knots_gain[0, 0] = 1.9     # 越上界
            shared.warmth_knots_gain[1, 2] = 0.2     # 越下界
        theta_star, clip = optimize.to_theta(shared, _fake_theta())
        assert clip["warmth_clipped"] == 2
        assert theta_star.warmth_knots[:, 1:].min() >= 0.5
        assert theta_star.warmth_knots[:, 1:].max() <= 1.5

    def test_to_theta_preserves_non_theta_fields(self):
        rng = np.random.default_rng(11)
        _, shared = _make_kit(rng)
        base = _fake_theta()
        base.probe_hi = np.array([[1.0, 2.0, 3.0]])
        theta_star, _ = optimize.to_theta(shared, base)
        assert theta_io.bitwise_equal(theta_star.probe_hi, base.probe_hi)
        assert theta_io.bitwise_equal(theta_star.neutral_default,
                                      base.neutral_default)


# ---------------------------------------------------------------------------
# 确定性 (seed → 同一训练轨迹)
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_adam_two_steps_bitwise(self):
        def run():
            rng = np.random.default_rng(12)
            kit, shared = _make_kit(rng)
            opt = torch.optim.Adam(shared.parameters(), lr=1e-3)
            losses = []
            for _ in range(2):
                opt.zero_grad()
                optimize.bind(kit, shared)
                loss = optimize.proxy_loss(kit, 1.0)
                loss.backward()
                pen = shared.penalty_total()
                pen.backward()
                opt.step()
                losses.append(float(loss) + float(pen))
            return losses, optimize.to_theta(shared, _fake_theta())[0]

        l1, t1 = run()
        l2, t2 = run()
        assert l1 == l2
        assert np.array_equal(t1.exposure_table, t2.exposure_table)
        assert np.array_equal(t1.rp_ccm_coeff, t2.rp_ccm_coeff)
        assert np.array_equal(t1.warmth_knots, t2.warmth_knots)

    def test_constraints_gradient_flow(self):
        shared = optimize.SharedTheta(_fake_theta())
        total = shared.penalty_total()
        total.backward()
        for name in ("warmth_knots_gain", "ev_table", "neutral_a",
                     "neutral_b"):
            p = getattr(shared, name)
            assert p.grad is not None and torch.isfinite(p.grad).all(), name


# ---------------------------------------------------------------------------
# G-5 门槛线判定
# ---------------------------------------------------------------------------

class TestG5Verdicts:
    def test_verdict_gates(self):
        res = optimize.G5Result()
        rng = np.random.default_rng(13)
        a = rng.gamma(5.0, 0.15, size=2000)            # median ~0.7
        res.a_pool = a
        res.b_pool = a * 0.7                            # 30% 改善
        res.rows = [{"a_median": 0.7, "b_median": 0.5}]
        v = res.verdicts(["camA", "camB"])
        assert v["gate_improve15"] and v["gate_no_regression"]
        assert v["gate_p95"] and v["gate_2cameras"]
        v1 = res.verdicts(["camA"])
        assert not v1["gate_2cameras"]                  # 单相机不满足门槛
        res2 = optimize.G5Result()
        res2.a_pool = a
        res2.b_pool = a * 1.1                           # 恶化
        res2.rows = [{"a_median": 0.7, "b_median": 0.9}]
        v2 = res2.verdicts(["camA", "camB"])
        assert not v2["gate_improve15"]
