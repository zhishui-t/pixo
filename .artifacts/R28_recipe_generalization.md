# R28 · recipe 泛化性三问 + decode_raw gamma 原生 bug（重大发现）

日期：2026-09-19 ｜ 上承：R24 recipe v1（preview tier 拟合, A_med=3.59）
探针：`.artifacts/_r28_recipe_generalization.py` → `_r28_recipe_generalization.json`

---

## 0. 结论速览

1. **Q1 抳出 `decode_raw` gamma 原生 bug（重大）**：export 主线的"线性"解码
   从 rawlab 迁移起就把 rawpy 缺省 gamma=(2.222, 4.5) 烘进输出 ⇒ export 全链
   （WB×矩阵→EOTF）在 gamma 污染域双重编码。**修复 = 显式钉 `gamma=(1,1)`**
   （io.py 一行 + 契约注释）：export recipe 臂 A 中位 **24.86 → 4.43**
   （preview 3.82, dA -0.61）⇒ recipe 跨 tier 成立。
2. **Q2 残差无白平衡结构 ⇒ recipe v2（按 WB 段细分）数据性关闭**（R18 先例）：
   n=47，wb_B 三分位分桶 A 中位 [3.52, 4.93, 3.39]（spread 1.54，非单调），
   Spearman ρ(A, wb_B) = **0.061** ≈ 无相关——残差尾部是逐片噪声级，
   无可细分结构。
3. **Q3 热路径等价**：R24 复合 LUT 渲染耗时与曲线基持平（median 0.072 vs
   0.069s）——预构单条 LUT 策略成立；recipe 臂 +0.02s（gains 全图乘本体开销）。

## 1. Q1 跨 tier 与 decode_raw gamma bug

**发现路径**：Q1 首跑 export 臂全线 A≈25（preview 3.8）→ 隔离复现 →
`decode_raw`（rawpy postprocess）与 `decode_cfa_half`（native，preview 主线）
同文件 half 解码统计对比：

| 解码 | median | 判定 |
|---|---:|---|
| decode_cfa_half（preview 主线） | 0.01425 | ✓ 线性 |
| decode_raw（export 主线，缺省 gamma） | 0.06404 | ✗ 带 dcraw 曲线 |
| rawpy 强制 gamma=(1,1) | 0.01309 | ✓ 回线性（残余=AHD vs 分箱去马赛克差） |

**受影响面**（`decode_raw` 四个消费方，全部假定线性）：
- `render/web/export.py:51`（**export 主线**——导出图全程双重编码）；
- `pipeline/graph.py run_file` 回退解码；
- `api.py Renderer.render`（标定流 render_file→线性 sRGB）；
- preview 的 native 回退路径（修复后回退预览与 native 预览域一致，
  顺带消掉一个静默分叉）。

**为什么一直没暴露**：F01/两分参照/风格卡审计全部跑 preview tier（native 线）；
export 侧门禁是自参照口径（R21 F05 与"仅渲染基线"比像素差）；两条解码线
此前**从未被逐像素对比**——Q1 是第一次。

**修复**：`io.py decode_raw` postprocess 显式 `gamma=(1.0, 1.0)` + 契约注释；
守卫单测 `test_decode_raw_pins_unit_gamma`（捕获 postprocess kwargs 断言
gamma/no_auto_bright/output_color 三契约，防默认值溜回）。

**修复后跨 tier（n=6）**：

| 项 | 修复前 | 修复后 |
|---|---:|---:|
| export A 中位 (vs 相机) | 24.86 | **4.43** |
| preview A 中位（不受影响） | 3.82 | 3.82 |
| tier 直接逐像素 ΔE 中位 | 28.05 | 9.78 |

残余 tier ΔE（1.6~34.5 逐片分散）= AHD 全分辨率 vs CFA 2×2 分箱的
去马赛克纹理差（DSC_5915 ≈1.6 即两线几乎重合的样张），整图系统差已消除。

## 2. Q2 残差结构（n=47 有效）→ v2 数据性关闭

wb_B 三分位桶 A 中位 [3.52, 4.93, 3.39]（非单调），ρ(A, wb_B)=0.061。
会话级亦无主导方向（json 详表）。**判定**：无可清偿结构，v2 不立项；
未来观感反馈指向具体场景时按 R19→R20 条件触发路径重启。

## 3. Q3 热路径（同 RAW 预热后 5 次中位）

| 臂 | median |
|---|---:|
| 曲线基（默认链） | 0.069s |
| 复合 profile_curve（R24） | 0.072s |
| recipe | 0.097s（gains 全图乘本体开销） |

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `src/pixo/render/core/io.py` | `decode_raw` 显式 `gamma=(1.0, 1.0)` + 契约注释（**export 输出全局变亮变正确**——语义修复预期后果） |
| `tests/unit/test_decode_cache.py` | `test_decode_raw_pins_unit_gamma` 契约守卫 |
| `.artifacts/_r28_recipe_generalization.py` / 本文件 | 探针 + 报告 |

## 5. 回归

- 金样本/gate：**零漂移**（gate 主线走 native 解码，不受影响；84 passed 实证）；
- 全量：见 `.artifacts/_r28_full_suite.xml`；
- 语义变化面：所有 `decode_raw` 路径的输出（export 主线、标定流 render_file、
  run_file 回退、preview native 回退）——修复前它们都偏暗（双重编码），
  修复后回到真线性。任何以旧输出为基准的外部对照需重造。

## 6. 待队长复核

- export 输出全局变化接受与否（gamma 污染修复的预期后果，如 R24 风格卡先例）；
- 建议后续：给 export 主线补一条"preview↔export 线性域一致性"门禁
  （Tier-1 同款思路），防两条解码线再静默分叉——本轮探针已具雏形。
