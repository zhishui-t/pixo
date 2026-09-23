# r20-stream-1 报告（dev-1）— warmth 曲线日光段补结点（#19 条件触发选项执行）

> 2026-09-08 · 用户批准执行。零标定加载代码改动（只换数据文件 configs/calibration/warmth_curve.json）。

## 做了什么

1. **拟合脚本** `.artifacts/_r20_fit_daylight_knots.py`：从 R19 checkpoint
   （54 照片 × 5 warmth 臂，真值=RAW 缩略图 Lab 均值）取 OOS-low 31 张的
   逐照片最优 warmth（抛物线细化），两结点按 R19 建议位置取分箱中位数：
   D1 @ wb_B=1.10 → w=0.5006（低 B 日光簇 n=12）、D2 @ wb_B=1.40 → w=0.0
   （过渡带 n=18，实测中位中性）；增益换算 g = 1+(w/0.9)·(g0−1)。
   `_check_warmth_curve` 校验通过；旧曲线备份
   `.artifacts/warmth_curve_pre_r20.json`。
2. **新曲线落位** `configs/calibration/warmth_curve.json`：7 结点（新增
   [1.10, 1.0966, 0.9547, 0.9382] 与 [1.40, 1, 1, 1]），拟合域 [1.7578,
   2.3984]→[1.10, 2.3984]，version 2 + r20_daylight_extension 溯源节。
3. **验证脚本** `.artifacts/_r20_warmth_daylight_verify.py`：域内不变性 +
   OOS-low 31 张改善 + 金样本漂移面，一体三检。
4. **台账 #19** 更新：已评估-记录接受 → **已清偿-日光段扩域落地（R20）**。

## 验证（完成标准三项）

| 项 | 结果 |
|---|---|
| 域内逐位不变 | ✅ [1.7578,2.3984] 2001 点增益逐位一致；apply_warmth 数组级逐位；`warmth_cal_auto` gate case 零漂移（域内不变性 gate 级证明） |
| 日光组改善 | ✅ OOS-low 31 张垫片偏差（生产−逐照片最优）median **+0.537 → +0.019** / p90 +1.117 → +0.109 / max 2.426 → 0.526；ΔE 绝对 6.14 → 5.29（最优 5.19，可恢复损失回收 ~85%）；方向性过暖消除 |
| 金样本漂移面 | RAW **24/24 漂移**（全部金样本 wb_B<1.6778 落新日光段=预期改善性漂移：ΔE76 2.34~9.91、max u8 24~65、方向=去暖回中性）；合成恰 **2/21**（default_dispatch max 0.030 / card_portra_400 max 0.016，合成相机 b=0.96 移入新插值段）；`warmth_cal_auto` 零漂移 |

定向测试：wiring/rules 域 41 passed（前轮）；gate_golden 现状 2 failed =
预期漂移面（default_dispatch/card_portra_400），待队长裁决基线重生成。

## 报队长裁决

1. **RAW gate_defaults 24 基线重生成**（u8+u16+manifest sha，方向=移除垫片
   过暖的预期改善性漂移；逐 case 量级见 `.artifacts/warmth_daylight_knots_r20.md` §4）。
2. **合成 gate 2 case 基线重生成**（default_dispatch/card_portra_400，
   generate_gate_goldens + reviewer 追加）。
3. 重生成后附带收益：日光样本的「超出暖度标定适用域」告警消失
   （domain [1.10,2.3984]）。

## 遗留

1. r19 评估报告（calib_domain_gap_eval.md）为历史记录不回写；R20 报告独立成文。
2. daylight 段 2 结点基于 R19 五臂网格最优（分辨率 0.405 warmth）；
   更细网格的逐照片再优化收益预计 <0.2 ΔE，不值得重跑。

## 文件

- `configs/calibration/warmth_curve.json`（数据文件，v2）/ 备份
  `.artifacts/warmth_curve_pre_r20.json`
- `.artifacts/_r20_fit_daylight_knots.py` / `_r20_warmth_daylight_verify.py`
- `.artifacts/warmth_daylight_knots_r20.md` / `r20_warmth_daylight_verify.json`
- `docs/tech_debt.md` #19（已清偿）
- 本文件
