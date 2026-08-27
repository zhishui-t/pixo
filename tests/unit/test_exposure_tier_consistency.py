"""跨 tier 曝光决策一致性测试 (修复 tier 间曝光决策口径漂移)。

背景: 曝光 EV 决策依赖 _probe_linear_srgb 的中位/分位统计。旧实现在
**当前 tier 图**上 cam[::4,::4] 跨步取点, 采样网格随 tier 尺度变化 ——
同一 RAW 在 512/1024/2048/全尺寸档的取样物理位置与 resize 平均深度都
不同, 统计量随档漂移, EV 决策在 preview 与 export 间不一致。修复后
(_probe_sample) 探针规范到帧坐标固定 256 长边网格的 INTER_AREA 面积
均值块 (resize 不变量), 统计量 tier 无关。

口径与 epsilon (本机实测, DSC_5236/5237/5240 三张真实 RAW + 本文件合成图):
  - 修前: 合成图 (逐点噪声 σ=0.3) med 档间散度 0.078 log2 / EV 散度
    0.219 EV (p99 高光哨兵把 med 漂移放大为 EV 漂移); 真实 RAW med
    散度 0.005~0.015 log2。
  - 修后: 合成图 med 散度 0.0005 / EV 散度 0.0013; 真实 RAW med 散度
    0.0004~0.0015 / EV 散度 0.000 (默认 1024 档 EV 与修前一致)。
  - 断言阈值取修后实测的 ~10 倍余量 (统计噪声合理上界), 同时保证修前
    实测散度必然越界 (合成图是回归哨兵; 真实 RAW 用例是环境一致性巡检)。

真实 RAW 用例遵循仓库惯例: K:/data/photo/0711/raw/DSC_5236.NEF 存在才
运行, 缺失时 skip。

运行: python -m pytest tests/unit/test_exposure_tier_consistency.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import pixo.render.modules.exposure as exposure_mod
from pixo.render.core.calibration import DcpProfile
from pixo.render.modules.exposure import (
    ExposureStage,
    _probe_linear_srgb,
    _probe_sample,
)
from pixo.render.pipeline.graph import DOMAIN_LINEAR_CAM, StageContext

# EV / med 档间一致性阈值 (选择依据见模块 docstring)
_EV_EPS = 0.02    # 修后实测 ~0.0015 EV
_MED_EPS = 0.01   # 修后实测 ~0.0005 log2

_TIERS = (512, 1024, 2048)

# 真实 Nikon Z 5 II Camera Standard 矩阵 (与 tests/unit/test_exposure.py 一致)
_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]

_REAL_RAW = Path(r"K:\data\photo\0711\raw\DSC_5236.NEF")
_REAL_DCP = (Path(__file__).resolve().parents[2] / "resources" / "dcp"
             / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")


class _FakeRaw:
    def __init__(self, wb=(2.0, 1.0, 1.5)):
        self.camera_whitebalance = [wb[0], wb[1], wb[2], 1.0]


def _make_profile() -> DcpProfile:
    return DcpProfile(
        path=Path("test.dcp"),
        color_matrix1=_NIKON_CM1,
        color_matrix2=_NIKON_CM2,
        forward_matrix1=_NIKON_FM1,
        forward_matrix2=_NIKON_FM1,
        baseline_exposure_offset=0.0,
    )


@pytest.fixture()
def _no_cal_file(monkeypatch):
    """锚点模式: 屏蔽每机标定文件, EV 直接由探针中位驱动 (见 test_exposure.py)。"""
    monkeypatch.setattr(exposure_mod, "_CAL_FILE",
                        exposure_mod._CAL_FILE.parent / "__nonexistent_cal__.json")
    monkeypatch.setattr(exposure_mod, "_cached_table", None)
    monkeypatch.setattr(exposure_mod, "_cached_offset", None)


def _synthetic_decode(h: int = 1366, w: int = 2048, sigma: float = 0.3,
                      seed: int = 42) -> np.ndarray:
    """模拟 half decode 层: 平滑梯度 + 相机色偏 + 亮窗高光 + 逐点乘性噪声。

    逐点噪声是关键: 旧 ::4 跨步取样对"点样本 vs 块均值"的差异最敏感
    (低档位 tier 已被 INTER_AREA 平均过, 高档位保留全部噪声), 使修前
    档间漂移达到可断言的量级; σ=0.3 在 RAW 半解码的合理噪声范围内。
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = 0.03 + 0.20 * (xx / w) * 0.6 + 0.18 * (yy / h) * 0.4
    base = base[..., None] * np.array([1.25, 1.0, 1.75], np.float32)
    win = np.zeros((h, w), np.float32)
    win[int(0.20 * h):int(0.45 * h), int(0.60 * w):int(0.80 * w)] = 1.0
    base = base + win[..., None] * np.array([0.85, 0.8, 0.7], np.float32)
    noise = np.exp(rng.normal(0.0, sigma, (h, w, 1))).astype(np.float32)
    return (base * noise).astype(np.float32)


def _make_tier(img: np.ndarray, long_edge: int) -> np.ndarray:
    """decode → tier: 与 RawPreviewSession._get_tier 同款 INTER_AREA 缩放。"""
    h, w = img.shape[:2]
    scale = float(long_edge) / max(h, w)
    if abs(scale - 1.0) > 1e-6:
        import cv2
        img = cv2.resize(img, (max(1, int(round(w * scale))),
                               max(1, int(round(h * scale)))),
                         interpolation=cv2.INTER_AREA)
    return img


def _make_ctx(img: np.ndarray, prof) -> StageContext:
    """与 session._render_with_params 同口径的 ctx 组装 (camera_wb 入 state)。"""
    ctx = StageContext(
        "tier_consistency.nef", raw=_FakeRaw(), prof=prof,
        config={"stages": {"whitebalance": {"mode": "as_shot"},
                           "exposure": {"target_offset": 0.0}},
                "half_size": True, "long_edge": int(max(img.shape[:2]))},
    )
    ctx.set_image(np.ascontiguousarray(img, dtype=np.float32), DOMAIN_LINEAR_CAM)
    ctx.state["half_size"] = True
    ctx.state["camera_wb"] = np.array([1.244, 1.0, 1.791], dtype=np.float32)
    return ctx


def _tier_decisions(decode: np.ndarray, prof):
    """三档渲染 exposure 决策: 返回 [(long_edge, ev, med_log2, p99), ...]。"""
    rows = []
    for le in _TIERS:
        ctx = _make_ctx(_make_tier(decode, le), prof)
        ExposureStage().run(ctx)
        ev = float(ctx.state["ev"])
        assert ctx.results[-1].metrics["ev"] == ev  # state 与 trace 同源
        y = _probe_linear_srgb(ctx, ctx.image)
        med = float(np.median(np.log2(np.maximum(y, 1e-6))))
        p99 = float(np.percentile(y, 99.0))
        rows.append((le, ev, med, p99))
    return rows


def _assert_tier_consistent(rows, label: str) -> None:
    evs = [r[1] for r in rows]
    meds = [r[2] for r in rows]
    detail = " | ".join(f"le{le}: med={m:+.5f} p99={p:.4f} ev={e:+.6f}"
                        for le, e, m, p in rows)
    ev_spread = max(evs) - min(evs)
    med_spread = max(meds) - min(meds)
    assert ev_spread <= _EV_EPS, (
        f"{label}: 三档 EV 决策不一致 (spread={ev_spread:.6f} > {_EV_EPS}): {detail}")
    assert med_spread <= _MED_EPS, (
        f"{label}: 三档探针中位不一致 (spread={med_spread:.6f} > {_MED_EPS}): {detail}")


# ---------------------------------------------------------------------------
# 探针取样语义
# ---------------------------------------------------------------------------

def test_probe_sample_fixed_grid_and_small_image_fallback():
    """大图规范到固定 256 长边网格 (帧坐标锚定); 小图回退 ::4 跨步。"""
    big = np.zeros((1000, 1600, 3), np.float32)
    s = _probe_sample(big)
    assert max(s.shape[:2]) == 256, "探针网格应钉在固定 256 长边 (tier 无关基准)"
    small = np.zeros((64, 64, 3), np.float32)
    assert _probe_sample(small).shape == (16, 16, 3), "小图应保持 ::4 跨步回退"


def test_probe_sample_tier_images_share_statistics():
    """同一 decode 的三档 tier 图, 探针统计 (中位/p99) 应一致。"""
    decode = _synthetic_decode()
    meds, p99s = [], []
    for le in _TIERS:
        ctx = _make_ctx(_make_tier(decode, le), _make_profile())
        y = _probe_linear_srgb(ctx, ctx.image)
        meds.append(float(np.median(np.log2(np.maximum(y, 1e-6)))))
        p99s.append(float(np.percentile(y, 99.0)))
    assert max(meds) - min(meds) <= _MED_EPS
    assert max(p99s) - min(p99s) <= 0.02 * max(p99s), "高光哨兵分位也应 tier 一致"


# ---------------------------------------------------------------------------
# 端到端: 三档渲染的 EV 决策一致
# ---------------------------------------------------------------------------

def test_synthetic_raw_three_tiers_same_ev(_no_cal_file):
    """合成 decode: 512/1024/2048 三档的 EV 决策与探针统计一致 (回归哨兵)。

    修前 (::4 跨步): EV spread ~0.22 / med spread ~0.078, 必然越界。
    """
    rows = _tier_decisions(_synthetic_decode(), _make_profile())
    _assert_tier_consistent(rows, "合成 RAW")
    # 非平凡性: EV 不应钳到 max_ev 平台 (否则断言空转)
    assert all(abs(r[1]) < 2.0 for r in rows), f"EV 不应触到 max_ev 钳位: {rows}"


@pytest.mark.skipif(not _REAL_RAW.exists(), reason="真实 RAW 不在本机 (DSC_5236.NEF)")
def test_real_raw_three_tiers_same_ev():
    """真实 RAW (半解码 → 三档): EV 决策与探针统计一致。

    decode 用 RawPreviewSession 同款 decode_cfa_half (native), tier 用
    session 同款 INTER_AREA; 不屏蔽每机标定表 (走生产查表路径, EV 对
    med 的映射最多放大表斜率 ~1.7 倍, 阈值余量充足)。
    修前实测 med spread 0.0052; 修后 0.0015。
    """
    rawpy = pytest.importorskip("rawpy")
    if not _REAL_DCP.exists():
        pytest.skip("仓库 DCP 资源缺失")
    from pixo.render.core.calibration import load_dcp
    from pixo.render.core.io import camera_neutral_wb_cached, decode_cfa_half

    raw = rawpy.imread(str(_REAL_RAW))
    try:
        decode = decode_cfa_half(raw, raw_path=_REAL_RAW)
        wb = camera_neutral_wb_cached(raw, _REAL_RAW)
    finally:
        try:
            raw.close()
        except Exception:
            pass
    prof = load_dcp(_REAL_DCP)

    rows = []
    for le in _TIERS:
        ctx = _make_ctx(_make_tier(decode, le), prof)
        ctx.raw = None  # camera_wb 已在 state, 不需要 raw 对象
        if wb is not None:
            ctx.state["camera_wb"] = wb
        ExposureStage().run(ctx)
        ev = float(ctx.state["ev"])
        y = _probe_linear_srgb(ctx, ctx.image)
        med = float(np.median(np.log2(np.maximum(y, 1e-6))))
        rows.append((le, ev, med, float(np.percentile(y, 99.0))))
    _assert_tier_consistent(rows, f"真实 RAW {_REAL_RAW.name}")
