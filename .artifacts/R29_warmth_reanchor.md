# R29 · lr_* 卡暖度域清偿——LR 双锚点复验驱动的旧底补偿退役

日期：2026-09-19 ｜ 触发：队长质疑"拟合出来的准确吗"+"拟合 ngb（暖光白）……之前做过"
探针：本报告 §1 双锚点复验 + n=24 语料验证（内联脚本，同 f01 口径）

---

## 0. 结论速览

1. **"拟合准不准"的答案（LR 域）：不准——2026-08 的暖度标定已被底层演化作废。**
   用 white_balance.py docstring 冻存的双 LR 锚点（0376: a+6/b+12；5236: a0/b−1）
   复验：**今天的中性链色度天然命中双锚点**（5236 逐值精确），而 lr_* 卡的
   warmth/warmth_curve/trim 在 0376 上过冲黄偏 **+46b***。
2. **根因**：暖度系统是给**旧色底**（R12 clean-room 色彩重写 + R23 中性化之前）
   打的"到 LR 的补偿增量"；底重写后增量变纯过冲。与 R24 发现的 profile_curve
   槽位、R28 发现的 decode_raw gamma 同族——**旧标定 × 新底 = 系统性失配**，
   本轮是第三次在同一根因家族里清偿。
3. **清偿**：lr_* 三张卡白平衡暖度域 → 纯 `as_shot`（130 行旧补偿退役）；
   lr_adobe_standard 另关 huesat（其 DCP LookTable max=2.0，0376 贡献 +21b*，
   同属旧底增量；LR 参照已删无法重拟合，按锚点证据退役）。
   **修后**：双锚点 0376 a+4/b+15（was a−2/b+58）、5236 **a0/b−1 逐值命中**。

## 1. 双锚点复验（white_balance.py:185-188 冻存的 LR 实测）

| 渲染 | 0376 (wb_B 2.287) | 5236 (wb_B 1.791) |
|---|---|---|
| LR 实测锚点（2026-08 记录） | a+6 / b+12 | a0 / b−1 |
| 中性链（今天） | **a+4 / b+12 ✓** | **a+0 / b−1 ✓✓** |
| lr_adobe 卡（修前） | a−2 / **b+58 ✗** | a−1 / b+2 |
| lr_adobe 卡（修后） | **a+4 / b+15** | **a+0 / b−1 ✓✓** |
| lr_baseline 卡（修后） | a+6 / b+19 | a+0 / b−1 ✓✓ |

暖源分解（0376）：whitebalance 暖度域 +25b*（warmth 0.9 + curve 在 wb_B=2.287
处 B−18%/G+9% + trim G+5%/B−10%）；huesat LookTable +21b*；refine/colorcal 微量。

## 2. 语料级验证（n=24 vs 相机 JPEG，median）

| 卡 | A 修前 (R27) | A 修后 |
|---|---:|---:|
| lr_baseline / lr_camera_standard | 19.19 | 17.04 |
| lr_adobe_standard_baseline | 12.73 | 12.35 |

中位改善温和的原因：语料以日光片为主（wb_B 低于暖度域，修前暖度也不触发）；
**修复的主战场是钨丝灯/暖光域**（锚点 b+58→+15），语料中位读数弱化了该效应。

## 3. 改动清单

| 文件 | 改动 |
|---|---|
| `configs/styles/lr_baseline.json` | whitebalance 暖度域（8-9 键）→ `{"mode":"as_shot"}` |
| `configs/styles/lr_camera_standard_baseline.json` | 同上 |
| `configs/styles/lr_adobe_standard_baseline.json` | 同上 + huesat → disabled（LookTable 旧底增量退役） |

渲染代码零改动；引擎默认链不动（R23 后默认 warmth 本就 0）。

## 4. 残差与遗留

- lr_baseline 系仍带 refine/colorcal 的 wb_B 微曲线（warm_hue_curve ±6、
  scene_trim ±14 量级）——同族旧底补偿但幅度小（0376 残差 b+19 vs 锚 +12），
  本轮**不动**（证据仅双锚点，动 look 微曲线需更多参照）；锚点级残差 +3~+7b。
- LookTable（hsm_oklch 表）如需复活须**在新底上重拟合**（需 LR 参照重建，
  guanlan LRClient 桥 + Lightroom 安装，另立项）。
- "打开≈LR"的**亮度/影调域**缺口仍在（0376: 卡 L180 vs LR 196）——归
  recipe 域（R24 方法论），同样等 LR 参照或改用相机参照。

## 5. 回归

风格卡/服务/金样本相关 **112 passed / 3 skipped**；渲染默认链零改动。
