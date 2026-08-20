"""test_fit_camera_profile —— fit_camera_profile 升级 (T4) 的纯函数单测。

覆盖 (不依赖真实 RAW/Adobe DCP, 全部合成数据):
  - staged 拟合: split_neutral_warm 按 wb_B≤1.79 分集; fit_trim 仅中性样本
    (暖样本大增益不污染 trim); full 模式奇异回退对角
  - 暖度: b0/b1 硬冻结 (无网格搜索); 斜率回归复现真值; 越界钳位到带界;
    样本不足回退内置常数
  - 曲线肩部锚定 (1,1): y(1.0)==1.0、单调、x≤0.95 可靠区与原始一致
  - 四口径: 恒等图全零; 偏色图中性区/全帧检出; 聚合中位
  - --force 覆盖保护: 产物存在且无 --force → SystemExit
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rawlab.dcp import DcpProfile
from rawlab.tools.fit_camera_profile import (
    HSM_DIMS, TRIM_RATIO_MIN, TRIM_RATIO_MAX,
    WARMTH_B0, WARMTH_B1, WARMTH_SLOPE_BOUNDS,
    ACCEPT_THRESHOLDS, BAND_ACCEPT, CALIBER_THRESHOLDS,
    HIGHLIGHT_ACCEPT, NEUTRAL_ACCEPT,
    _active_crop_oriented, anchor_curve_shoulder,
    aggregate_calibers, attach_hsm,
    build_validation_report, ensure_overwrite_ok, fit_trim,
    fit_warmth_slopes, four_caliber_stats, hsm_write_enabled,
    pass_four_calibers, select_lr_rows, select_preview_rows,
    select_stratified, split_lr_holdout, split_neutral_warm,
    trim_diag_out_of_range,
)


def _pair(seed: int, wb_b: float, gain=(1.0, 1.0, 1.0), size=8):
    rng = np.random.default_rng(seed)
    ours = rng.uniform(0.05, 0.8, (size, size, 3)).astype(np.float32)
    target = ours * np.asarray(gain, np.float32)
    return {"linear8": ours, "linear_m8": ours,
            "target_lin8": target, "target8": target, "wb_b": wb_b}


# ---------------------------------------------------------------------------
# staged 拟合: trim 仅中性样本
# ---------------------------------------------------------------------------

def test_split_neutral_warm():
    pairs = [{"wb_b": 1.5}, {"wb_b": 1.79}, {"wb_b": 1.8001}, {"wb_b": 2.287}]
    neutral, warm = split_neutral_warm(pairs)
    assert [p["wb_b"] for p in neutral] == [1.5, 1.79]      # s=0 边界含 1.79
    assert [p["wb_b"] for p in warm] == [1.8001, 2.287]


def test_fit_trim_uses_only_neutral():
    # 2 中性 (恒等) + 2 暖 (大增益 b 通道 0.8) —— 若混入暖样本 trim 会被拉偏
    neutral = [_pair(i, 1.3 + 0.1 * i) for i in range(2)]
    warm = [_pair(100 + i, 2.2 + 0.1 * i, gain=(1.0, 1.12, 0.8)) for i in range(2)]
    trim, _, trim_out = fit_trim(neutral, "diag")
    assert np.allclose(trim, 1.0, atol=1e-3)                # 中性恒等 → 1
    assert len(trim_out) == 3
    # 对照: 全体混入暖样本 → b 通道明显偏离 1 (证明 staged 门控的必要性)
    trim_all, _, _ = fit_trim(neutral + warm, "diag")
    assert abs(float(trim_all[2]) - 1.0) > 0.02


def test_fit_trim_full_mode_identity():
    neutral = [_pair(i, 1.4) for i in range(4)]             # 恒等
    trim, apply_trim, trim_out = fit_trim(neutral, "full")
    assert np.allclose(trim, np.eye(3), atol=1e-3)
    assert len(trim_out) == 9
    p = neutral[0]
    assert np.allclose(apply_trim(p["linear8"]), p["linear8"], atol=1e-4)


def test_fit_trim_full_singular_falls_back_diag():
    # 常量灰度图 → O 列线性相关 → 3×3 正规方程奇异 → 回退对角 (仍返回可用 trim)
    def const_pair(v):
        ours = np.full((4, 4, 3), v, np.float32)
        return {"linear8": ours, "target_lin8": ours.copy(), "wb_b": 1.5}
    neutral = [const_pair(0.2), const_pair(0.4), const_pair(0.6)]
    trim, _, trim_out = fit_trim(neutral, "full")
    assert len(trim_out) == 3
    assert np.allclose(trim, 1.0, atol=1e-3)


# ---------------------------------------------------------------------------
# medium#3: trim 分段 LSQ (每亮度段独立拟合 + 中段权重) 收敛中间调偏色
# ---------------------------------------------------------------------------

def _srgb_encode(v):
    """线性 → gamma sRGB 编码 (target8 域, 用于亮度分段掩码)。"""
    v = np.clip(np.asarray(v, np.float32), 0.0, 1.0)
    return np.where(v <= 0.0031308, 12.92 * v,
                    1.055 * v ** (1.0 / 2.4) - 0.055).astype(np.float32)


def test_band_balanced_trim_prefers_mid_band():
    # 亮像素 o² 主导的普通全像素 LSQ 会忽略暗-中段 (cv2 L∈[50,100)) 的增益
    # 需求; 分段 LSQ (默认 luma_weights) 让中段增益参与加权平均 → 显著抬高 R。
    # 线性 0.0509 → gamma ≈0.262 → cv2 L≈71 ∈ [50,100) (暗-中段);
    # 线性 0.4477 → gamma ≈0.700 → cv2 L≈185 ∈ [160,256) (高光段)。
    mid_lin, hi_lin = 0.0509, 0.4477
    size = 64
    ours = np.empty((size, size, 3), np.float32)
    ours[:size // 2] = mid_lin
    ours[size // 2:] = hi_lin
    target = ours.copy()
    target[:size // 2, :, 0] *= 1.10          # 中段目标 R 更红 (gain 1.10)
    pair = {"linear8": ours, "target_lin8": target,
            "target8": _srgb_encode(target), "wb_b": 1.4}
    trim_bal, _, _ = fit_trim([pair] * 3, "diag", estimator="median")   # 段中位比值加权
    trim_eq, _, _ = fit_trim([pair] * 3, "diag", luma_weights=None)
    # 等权: 亮像素 o² 主导 → R 被拉回 ≈1.0 (中段需求 1.10 被淹没)
    assert float(trim_eq[0]) < 1.02
    # 段中位比值: 中段 (w=2) 与高光段 (w=0.5) 加权平均 → R = (2*1.10+0.5*1.0)/2.5 ≈ 1.08
    assert float(trim_bal[0]) > 1.03
    assert abs(float(trim_bal[0]) - 1.10) < abs(float(trim_eq[0]) - 1.10)
    # 空权重表 = 各段等权 (R=(1.10+1.0)/2≈1.05), 介于等权 LSQ 与中段加权之间
    trim_off, _, _ = fit_trim([pair] * 3, "diag", luma_weights=(),
                              estimator="median")
    assert 1.02 < float(trim_off[0]) < float(trim_bal[0])


def test_band_balanced_trim_full_mode_weights():
    # full (3×3) 模式同样按亮度分段加权: 中段 R 增益 1.10 抬高 M[0,0]
    rng = np.random.default_rng(42)
    size = 64
    ours = np.empty((size, size, 3), np.float32)
    ours[:size // 2] = rng.uniform(0.05, 0.11, (size // 2, size, 3))   # 暗-中段
    ours[size // 2:] = rng.uniform(0.35, 0.60, (size // 2, size, 3))   # 高光段
    target = ours.copy()
    target[:size // 2, :, 0] *= 1.10
    pair = {"linear8": ours, "target_lin8": target,
            "target8": _srgb_encode(target), "wb_b": 1.4}
    trim_bal, _, _ = fit_trim([pair] * 3, "full")
    trim_eq, _, _ = fit_trim([pair] * 3, "full", luma_weights=None)
    assert float(trim_bal[0, 0]) > float(trim_eq[0, 0]) + 0.03
    assert float(trim_bal[0, 0]) > 1.03


# ---------------------------------------------------------------------------
# 暖度: 冻结锚点 + 斜率带界
# ---------------------------------------------------------------------------

def _warm_pair(seed: int, wb_b: float, gain):
    p = _pair(seed, wb_b)
    p["linear_m8"] = p["linear8"]                           # trim 固定后 (恒等)
    p["target_lin8"] = p["linear8"] * np.asarray(gain, np.float32)
    return p


def test_fit_warmth_slopes_frozen_anchors():
    # 真值斜率 r=0.00, g=0.10, b=0.26 (带内); 应被精确复现, 锚点冻结
    pairs = []
    for i in range(8):
        wb_b = WARMTH_B0 + 0.05 + (WARMTH_B1 - WARMTH_B0 - 0.05) * i / 7.0
        s = (wb_b - WARMTH_B0) / (WARMTH_B1 - WARMTH_B0)
        pairs.append(_warm_pair(i, wb_b, (1.0 + 0.0 * s,
                                          1.0 + 0.10 * s, 1.0 - 0.26 * s)))
    cal = fit_warmth_slopes(pairs)
    assert cal["b0"] == round(WARMTH_B0, 3) and cal["b1"] == round(WARMTH_B1, 3)
    assert abs(cal["g_slope"] - 0.10) < 0.01
    assert abs(cal["b_slope"] - 0.26) < 0.01
    assert abs(cal["r_slope"]) < 0.01
    for k in ("r_slope", "g_slope", "b_slope"):
        lo, hi = WARMTH_SLOPE_BOUNDS[k]
        assert lo <= cal[k] <= hi


def test_fit_warmth_slopes_clamps_bounds(capsys):
    # 大幅越界增益 → 斜率钳位到带界 (保证 preset 渲染不触发 Stage 越界报错)
    # r/g 增益 0.9 → 钳到上界; b 增益 +0.9 (模型不可表达) → 钳到下界 0.20
    pairs = []
    for i in range(8):
        wb_b = WARMTH_B0 + 0.1 + (WARMTH_B1 - WARMTH_B0) * i / 7.0
        s = (wb_b - WARMTH_B0) / (WARMTH_B1 - WARMTH_B0)
        pairs.append(_warm_pair(i, wb_b, (1.0 + 0.9 * s, 1.0 + 0.9 * s,
                                          1.0 + 0.9 * s)))
    cal = fit_warmth_slopes(pairs)
    assert cal["r_slope"] == WARMTH_SLOPE_BOUNDS["r_slope"][1]   # 0.05
    assert cal["g_slope"] == WARMTH_SLOPE_BOUNDS["g_slope"][1]   # 0.15
    assert cal["b_slope"] == WARMTH_SLOPE_BOUNDS["b_slope"][0]   # 0.20
    # medium#1: 越界不再静默 —— ERROR 级告警 + out_of_bounds 标记 (--validate fail)
    assert cal["out_of_bounds"] is True
    out = capsys.readouterr().out
    assert "ERROR" in out and "越界" in out


def test_fit_warmth_slopes_in_bounds_not_flagged(capsys):
    # 带内斜率 (0.0/0.10/0.26) → 无越界标记、无 ERROR 输出
    pairs = []
    for i in range(8):
        wb_b = WARMTH_B0 + 0.05 + (WARMTH_B1 - WARMTH_B0 - 0.05) * i / 7.0
        s = (wb_b - WARMTH_B0) / (WARMTH_B1 - WARMTH_B0)
        pairs.append(_warm_pair(i, wb_b, (1.0 + 0.0 * s,
                                          1.0 + 0.10 * s, 1.0 - 0.26 * s)))
    cal = fit_warmth_slopes(pairs)
    assert cal["out_of_bounds"] is False
    assert "ERROR" not in capsys.readouterr().out


def test_fit_warmth_slopes_fallback_when_few():
    # 样本 <6 → 回退内置常数 (0.0/0.10/0.26), 锚点仍冻结
    pairs = [_warm_pair(i, WARMTH_B0 + 0.2 + 0.1 * i,
                        (1.0, 1.5, 0.5)) for i in range(3)]
    cal = fit_warmth_slopes(pairs)
    assert cal["b0"] == round(WARMTH_B0, 3) and cal["b1"] == round(WARMTH_B1, 3)
    assert cal["r_slope"] == 0.0 and cal["g_slope"] == 0.10 and cal["b_slope"] == 0.26


# ---------------------------------------------------------------------------
# 曲线肩部锚定 (1,1)
# ---------------------------------------------------------------------------

def _raw_curve_no_shoulder():
    grid = np.linspace(0.0, 1.0, 1024)
    raw = np.clip(np.power(grid, 0.75) * 0.93, 0.0, 1.0)     # 峰值 0.93 < 1
    return grid, raw


def test_anchor_curve_shoulder_endpoint_and_monotone():
    grid, raw = _raw_curve_no_shoulder()
    curve = anchor_curve_shoulder(raw, grid)
    assert abs(float(curve[-1]) - 1.0) < 1e-9                 # y(1.0)==1.0
    assert np.all(np.diff(curve) >= -1e-12)                   # 单调
    assert np.all(curve <= 1.0 + 1e-12)
    # x≤0.95 可靠区与原始一致 (maximum.accumulate 头部)
    k = int(np.searchsorted(grid, 0.95, side="right")) - 1
    expected = np.clip(np.maximum.accumulate(raw[:k + 1]), 0.0, 1.0)
    assert np.allclose(curve[:k + 1], expected, atol=1e-12)
    # 肩部从可靠点平滑上升收敛到 1
    assert curve[k + 1] >= curve[k] - 1e-12
    assert 0.93 <= curve[-1] <= 1.0


def test_anchor_curve_shoulder_already_at_one():
    grid = np.linspace(0.0, 1.0, 1024)
    raw = np.clip(np.maximum.accumulate(grid), 0.0, 1.0)      # 直线到 (1,1)
    curve = anchor_curve_shoulder(raw, grid)
    assert abs(float(curve[-1]) - 1.0) < 1e-9
    assert np.all(np.diff(curve) >= -1e-12)


def test_anchor_curve_shoulder_dip_repaired():
    # 原始曲线上尾抖动下探 → maximum.accumulate 修复, 仍单调且端点 (1,1)
    grid = np.linspace(0.0, 1.0, 1024)
    raw = np.clip(np.power(grid, 0.8), 0.0, 1.0)
    raw[900:950] = 0.4                                        # 人为下探
    curve = anchor_curve_shoulder(raw, grid)
    assert abs(float(curve[-1]) - 1.0) < 1e-9
    assert np.all(np.diff(curve) >= -1e-12)


# ---------------------------------------------------------------------------
# 四口径验证
# ---------------------------------------------------------------------------

def _img(seed: int, size=64):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (size, size, 3), dtype=np.uint8)


def test_four_caliber_identity():
    img = _img(7)
    s = four_caliber_stats(img, img)
    assert s["full"]["da"] == 0.0 and s["full"]["db"] == 0.0
    assert s["full"]["dS"] == 0.0 and s["full"]["dp50"] == 0.0
    assert s["neutral"]["da"] == 0.0
    assert len(s["bands"]) == 4
    for b in s["bands"]:
        if b is not None:                                    # 空掩码段为 None, 跳过
            assert b["da"] == 0.0 and b["db"] == 0.0
    assert s["highlight"]["da"] == 0.0


def test_four_caliber_detects_shift():
    gray = np.full((32, 32, 3), 128, np.uint8)
    shifted = gray.copy()
    shifted[..., 0] = 150
    shifted[..., 1] = 120
    shifted[..., 2] = 100
    s = four_caliber_stats(shifted, gray)
    assert s["neutral"]["da"] > 1.0                            # 中性区检出偏色
    assert s["neutral"]["db"] > 1.0
    assert s["full"]["da"] > 1.0
    assert s["full"]["db"] > 1.0


def test_four_caliber_empty_highlight_mask():
    # 全黑图: L=0, 高光区 L>160 掩码空 → None (聚合跳过)
    black = np.zeros((16, 16, 3), np.uint8)
    s = four_caliber_stats(black, black)
    assert s["highlight"] is None
    assert s["neutral"] is not None


def test_aggregate_calibers_median():
    rng = np.random.default_rng(1)
    reports = []
    for i in range(3):
        img = _img(10 + i)
        stats = four_caliber_stats(img, img)                  # 全零
        reports.append({**stats, "photo": f"p{i}"})
    summary = aggregate_calibers(reports)
    assert summary["full"]["da"] == 0.0
    assert summary["neutral"]["da"] == 0.0
    assert len(summary["bands"]) == 4
    assert summary["highlight"]["da"] == 0.0
    # 3 张同一偏色图 → 聚合中位非零 (检出偏色)
    gray = np.full((32, 32, 3), 128, np.uint8)
    shifted = gray.copy()
    shifted[..., 2] = 90
    shift_reports = [four_caliber_stats(shifted, gray) for _ in range(3)]
    summary2 = aggregate_calibers(shift_reports)
    assert summary2["neutral"]["da"] > 0.0 or summary2["neutral"]["db"] > 0.0
    assert summary2["full"]["da"] > 0.0 or summary2["full"]["db"] > 0.0


# ---------------------------------------------------------------------------
# --force 覆盖保护
# ---------------------------------------------------------------------------

def test_ensure_overwrite_ok(tmp_path):
    out = tmp_path / "x.dcp"
    assert ensure_overwrite_ok([out], force=False) is None    # 不存在 → 通过
    out.write_bytes(b"x")
    with pytest.raises(SystemExit):
        ensure_overwrite_ok([out], force=False)               # 存在且无 --force → 报错
    ensure_overwrite_ok([out], force=True)                    # --force → 覆盖
    p2 = tmp_path / "p.json"
    p2.write_bytes(b"{}")
    with pytest.raises(SystemExit):
        ensure_overwrite_ok([out, p2], force=False)


# ---------------------------------------------------------------------------
# medium#1: trim 对角异常值告警 (G>1.5 或 B<0.7 → ERROR, 不再静默)
# ---------------------------------------------------------------------------

def test_trim_diag_out_of_range_detection():
    # 通道比判定: R/G 与 B/G 必须在 [0.5, 1.6] (WB 级修整物理可信域)
    assert trim_diag_out_of_range(np.array([1.0, 1.0, 0.45]))            # B/G=0.45
    assert trim_diag_out_of_range(np.array([1.7, 1.0, 1.0]))             # R/G=1.7
    assert trim_diag_out_of_range(np.array([1.2, 1.0, 0.8])) is False    # 正常
    # 3×3 模式看主对角 [0,0]/[1,1]/[2,2] 的通道比
    assert trim_diag_out_of_range(np.diag([1.7, 1.0, 1.0])) is True
    assert trim_diag_out_of_range(np.diag([1.2, 1.0, 0.8])) is False
    assert trim_diag_out_of_range(None) is False
    assert trim_diag_out_of_range(np.array([])) is False


def test_fit_trim_warns_on_diag_b_below_min(capsys):
    # 目标增益 B=0.45 (G=1) → B/G=0.45 < 0.5 → ERROR 告警 (不再静默)
    pairs = [_pair(i, 1.4, gain=(1.0, 1.0, 0.45)) for i in range(3)]
    trim, _, _ = fit_trim(pairs, "diag")
    assert float(trim[2]) / float(trim[1]) < TRIM_RATIO_MIN
    out = capsys.readouterr().out
    assert "ERROR" in out and "异常" in out


def test_fit_trim_warns_on_diag_g_over_max(capsys):
    # 目标增益 R=1.7 (G=1) → R/G=1.7 > 1.6 → ERROR 告警
    pairs = [_pair(i, 1.4, gain=(1.7, 1.0, 1.0)) for i in range(3)]
    trim, _, _ = fit_trim(pairs, "diag")
    assert float(trim[0]) / float(trim[1]) > TRIM_RATIO_MAX
    assert "ERROR" in capsys.readouterr().out


def test_fit_trim_full_warns_on_diag_anomaly(capsys):
    # 3×3 模式主对角通道比越界同样告警
    pairs = [_pair(i, 1.4, gain=(1.7, 1.0, 1.0)) for i in range(4)]
    trim, _, trim_out = fit_trim(pairs, "full")
    assert len(trim_out) == 9
    assert float(trim[0, 0]) / float(trim[1, 1]) > TRIM_RATIO_MAX
    assert "ERROR" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# medium#2: select_stratified 去重 + 无放回; LR 模式按 wb_B 分层
# ---------------------------------------------------------------------------

def _row(path: str, wb_b: float) -> dict:
    return {"path": path, "wb": [1.0, 1.0, wb_b], "wb_b": wb_b,
            "raw_mean": 0.1}


def test_select_stratified_more_than_available_no_duplicates():
    # n > len(rows): np.linspace(dtype=int) 会产生重复索引 → 必须全部唯一
    rows = [_row(f"K:\\a\\DSC_{i}.NEF", wb)
            for i, wb in enumerate([1.2, 1.6, 2.2])]
    sel = select_stratified(rows, n=10)
    assert len(sel) == 3
    assert {r["wb_b"] for r in sel} == {1.2, 1.6, 2.2}
    assert len({id(r) for r in sel}) == 3                     # 无重复对象


def test_select_stratified_dedup_fill_without_replacement():
    # n < len(rows) 时 linspace 去重 + 从剩余无放回补齐; 确定性; 覆盖两端
    rows = [_row(f"K:\\a\\DSC_{i:02d}.NEF", round(1.1 + 0.2 * i, 2))
            for i in range(10)]
    sel1 = select_stratified(rows, n=6)
    sel2 = select_stratified(rows, n=6)
    assert len(sel1) == 6
    assert len({id(r) for r in sel1}) == 6                    # 去重 + 无放回
    assert [r["wb_b"] for r in sel1] == [r["wb_b"] for r in sel2]  # 确定性 (seed)
    wbs = [r["wb_b"] for r in sel1]
    assert min(wbs) == min(r["wb_b"] for r in rows)           # 分层覆盖两端
    assert max(wbs) == max(r["wb_b"] for r in rows)


def test_select_lr_rows_stratified_not_head(tmp_path):
    # LR 模式: selected 不再等于 rows[:n] 顺序取前 n, 而是按 wb_B 分层;
    # 且先按 wb_B 分层留出 2 中性 + 2 暖 (medium#4), 选中集 ⊆ 拟合池。
    lr = tmp_path / "lr"
    lr.mkdir()
    rows = [_row(f"K:\\data\\photo\\DSC_{i:04d}.NEF", wb)
            for i, wb in enumerate([2.5, 1.3, 2.0, 1.1, 2.8, 1.7, 2.3, 1.5,
                                    2.6, 1.2])]
    for r in rows:
        (lr / f"{Path(r['path']).stem}.jpg").write_bytes(b"\xff\xd8")
    fit_rows, holdout, selected = select_lr_rows(rows, str(lr), n=4)
    # 留出集: 中性 2 + 暖 2, 与拟合集不重叠
    assert len(holdout) == 4
    assert sum(1 for r in holdout if r["wb_b"] <= WARMTH_B0) == 2
    assert sum(1 for r in holdout if r["wb_b"] > WARMTH_B0) == 2
    fit_ids = {id(r) for r in fit_rows}
    assert all(id(r) in fit_ids for r in selected)            # 选中 ⊆ 拟合池
    assert not ({id(r) for r in holdout} & {id(r) for r in selected})
    # 分层覆盖而非顺序取前 n (旧 rows[:n] 只会取 [2.5, 1.3, 2.0, 1.1])
    sel_wbs = [r["wb_b"] for r in selected]
    assert sel_wbs != [r["wb_b"] for r in rows[:4]]
    assert min(sel_wbs) <= 1.3 and max(sel_wbs) >= 2.3       # 冷/暖两端都有


# ---------------------------------------------------------------------------
# medium#4: LR 语料分层留出集 (中性 2 + 暖 2) + validation JSON n_photos
# ---------------------------------------------------------------------------

def test_split_lr_holdout_stratified_and_disjoint():
    # 6 中性 (1.2..1.7) + 6 暖 (1.8..2.3): 留出 2 中性 + 2 暖, 其余进拟合池
    rows = [_row(f"K:\\a\\DSC_{i:02d}.NEF", round(1.2 + 0.1 * i, 2))
            for i in range(12)]
    fit_rows, holdout = split_lr_holdout(rows)
    assert len(holdout) == 4
    assert sum(1 for r in holdout if r["wb_b"] <= WARMTH_B0) == 2
    assert sum(1 for r in holdout if r["wb_b"] > WARMTH_B0) == 2
    assert len(fit_rows) == len(rows) - 4
    assert not ({id(r) for r in fit_rows} & {id(r) for r in holdout})
    # 确定性 (seed): 两次调用留出集一致
    _, h2 = split_lr_holdout(rows)
    assert [r["path"] for r in holdout] == [r["path"] for r in h2]


def test_build_validation_report_records_n_photos():
    # --validate 落盘 JSON: n_photos = 留出集有效张数; holdout_photos 明细
    holdout = [_row("K:\\a\\DSC_0001.NEF", 1.4),
               _row("K:\\a\\DSC_0002.NEF", 2.2)]
    rep = build_validation_report("lr", ok=2, holdout_rows=holdout,
                                  fit_errors=[], summary={"pass": True},
                                  reports=[])
    assert rep["n_photos"] == 2
    assert rep["target"] == "lr" and rep["fit_errors"] == []
    assert rep["holdout_photos"] == [{"path": r["path"], "wb_b": r["wb_b"]}
                                     for r in holdout]
    # medium#3: 默认 thresholds = 四口径完整阈值表 (full/neutral/band/highlight)
    assert rep["thresholds"] == CALIBER_THRESHOLDS
    assert set(CALIBER_THRESHOLDS) == {"full", "neutral", "band", "highlight"}
    assert CALIBER_THRESHOLDS["full"] == ACCEPT_THRESHOLDS
    assert CALIBER_THRESHOLDS["neutral"] == NEUTRAL_ACCEPT
    assert CALIBER_THRESHOLDS["band"] == BAND_ACCEPT
    assert CALIBER_THRESHOLDS["highlight"] == HIGHLIGHT_ACCEPT


# ---------------------------------------------------------------------------
# medium#3: 四口径 pass 判定 (full/neutral/bands/highlight 全部纳入)
# ---------------------------------------------------------------------------

def _ok_stats():
    return {
        "full": {"da": 1.0, "db": 1.0, "dS": 9.6, "dp50": 9.5},
        "neutral": {"da": 1.0, "db": 1.0},
        "bands": [
            {"range": [0.0, 50.0], "da": 2.5, "db": 1.0},
            {"range": [50.0, 100.0], "da": 2.5, "db": 2.0},
            {"range": [100.0, 160.0], "da": 2.5, "db": 2.0},
            {"range": [160.0, 256.0], "da": 2.0, "db": 3.0},
        ],
        "highlight": {"da": 2.0, "db": 3.0},
    }


def test_pass_four_calibers_all_ok():
    ok, failures = pass_four_calibers(_ok_stats())
    assert ok is True and failures == []


def test_pass_four_calibers_band_mid_overshoot_fails():
    # 审查 medium#3 原始场景: full 全达标但 band L[50,100) |Δa|=6.5 → FAIL
    stats = _ok_stats()
    stats["bands"][1] = {"range": [50.0, 100.0], "da": 6.5, "db": 2.0}
    ok, failures = pass_four_calibers(stats)
    assert ok is False
    assert any("band" in f and "da" in f and "6.5" in f for f in failures)
    assert any("full" not in f for f in failures)   # 不是 full 导致的


def test_pass_four_calibers_each_caliber_enforced():
    # 逐口径验证: 任何一个超阈值 → FAIL, 且 failures 指名口径与数值
    cases = [
        ("full", {"da": 3.5}),
        ("full", {"db": 4.5}),
        ("full", {"dS": 12.5}),
        ("full", {"dp50": 20.5}),
        ("neutral", {"db": 3.5}),
        ("highlight", {"da": 3.5}),
        ("highlight", {"db": 4.5}),
        ("band", {"db": 4.5}),
    ]
    for caliber, over in cases:
        stats = _ok_stats()
        if caliber == "full":
            stats["full"].update(over)
        elif caliber == "neutral":
            stats["neutral"].update(over)
        elif caliber == "highlight":
            stats["highlight"].update(over)
        else:
            stats["bands"][2].update(over)
        ok, failures = pass_four_calibers(stats)
        assert ok is False, caliber
        assert len(failures) >= 1 and caliber in failures[0], (caliber, failures)


def test_pass_four_calibers_skips_empty_calibers():
    # 掩码空的口径 (None) 无数据可判 → 跳过, 不误报 (也不谎报)
    stats = _ok_stats()
    stats["neutral"] = None
    stats["highlight"] = None
    stats["bands"][0] = None
    stats["bands"][3] = None
    ok, failures = pass_four_calibers(stats)
    assert ok is True and failures == []
    # 有数据但超限 → 即使其余 None 也 FAIL
    stats["bands"][1]["da"] = 5.0
    ok, failures = pass_four_calibers(stats)
    assert ok is False


def test_pass_four_calibers_boundary_exact_ok():
    # 恰好等于阈值 (≤) 算达标
    stats = _ok_stats()
    stats["full"] = {"da": 3.0, "db": 4.0, "dS": 12.0, "dp50": 20.0}
    stats["neutral"] = {"da": 3.0, "db": 3.0}
    stats["highlight"] = {"da": 3.0, "db": 4.0}
    for b in stats["bands"]:
        b["da"], b["db"] = 3.0, 4.0
    ok, failures = pass_four_calibers(stats)
    assert ok is True and failures == []


# ---------------------------------------------------------------------------
# low#4: preview 目标不写 HSM 表, LR 目标保留
# ---------------------------------------------------------------------------

def test_hsm_write_enabled_per_target():
    assert hsm_write_enabled("preview") is False     # preview: huesat.enabled=false
    assert hsm_write_enabled("lr") is True


def test_attach_hsm_skips_for_preview_target():
    prof = DcpProfile(path=Path("x.dcp"))
    hue_sat_map = [0.0, 1.0, 1.0] * (90 * 16 * 16)
    attach_hsm(prof, hue_sat_map, HSM_DIMS, 1, "preview")
    assert prof.hue_sat_map is None
    assert prof.hue_sat_dims is None


def test_attach_hsm_writes_for_lr_target():
    prof = DcpProfile(path=Path("x.dcp"))
    hue_sat_map = [0.0, 1.0, 1.0] * (90 * 16 * 16)
    attach_hsm(prof, hue_sat_map, HSM_DIMS, 1, "lr")
    assert prof.hue_sat_map == hue_sat_map
    assert prof.hue_sat_dims == HSM_DIMS
    assert prof.hue_sat_encoding == 1


def test_select_preview_rows_warm_all():
    """--warm-all: 暖尾全进拟合, 其余名额从冷/中性分层补齐。"""
    rows = [{"path": f"p{i}", "wb_b": wb_b} for i, wb_b in enumerate(
        [1.2, 1.4, 1.6, 1.79, 1.8, 2.0, 2.2, 2.4, 2.5, 2.6])]
    sel = select_preview_rows(rows, n=6, warm_all=True)
    warm = [r["wb_b"] for r in sel if r["wb_b"] > 1.79]
    assert warm == [1.8, 2.0, 2.2, 2.4, 2.5, 2.6][:0] + [1.8, 2.0, 2.2, 2.4, 2.5, 2.6]
    # 10 个里暖尾 6 个, n=6 → 暖尾全进, 但 trim 保护强制补 2 张中性
    assert len([r for r in sel if r["wb_b"] > 1.79]) == 6
    assert len([r for r in sel if r["wb_b"] <= 1.79]) == 4
    # trim 保护会保留全部 4 张中性, 即使 n 被暖尾占满
    sel8 = select_preview_rows(rows, n=8, warm_all=True)
    assert len([r for r in sel8 if r["wb_b"] > 1.79]) == 6
    assert len(sel8) == 10
    # 关闭 warm-all 与旧分层一致
    sel_old = select_preview_rows(rows, n=6, warm_all=False)
    assert [r["wb_b"] for r in sel_old] == [r["wb_b"] for r in select_stratified(rows, 6)]


def test_active_crop_oriented_flip6():
    """flip=6 (90CW): crop rect 必须旋到输出坐标; 旧直裁会裁错/越界。"""
    from types import SimpleNamespace
    img = np.zeros((6064, 4040, 3), np.uint8)
    raw = SimpleNamespace(sizes=SimpleNamespace(
        crop_left_margin=8, crop_top_margin=4,
        crop_width=6048, crop_height=4032,
        raw_width=6064, raw_height=4040, flip=6))
    out = _active_crop_oriented(img, raw)
    assert out.shape == (6048, 4032, 3)

