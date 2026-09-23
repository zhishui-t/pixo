# r10-stream-1 报告（dev-1）— JND 口径单源化 + skin 7% 覆盖风险面复核

> 2026-09-07 · 第十轮 · 两任务顺序完成。

---

## 任务1：JND 口径单源化

### 做了什么

**盘点（全仓 grep JND/jnd + 2.3 上下文）**——两套口径并存：

| 口径 | 位置 | 性质 |
|---|---|---|
| **2.3（权威，转正/回归判据）** | `scripts/hsm_oklch_eval.py:57`（`JND = 2.3` 硬编码）、`scripts/illumination_est/eval_illum.py:62`（同，注「同阶段二口径」）、`scripts/README.md:28`、`.artifacts/` 评估报告 7 处（calib_run:67 / stage2_eval:73 / stage2_adopt_eval_A:73 / stage2_adopt_eval_prev:73 / stage2_qa_verdict:66 / stage3_first_verdict:84 / illumination_eval:37——「1 JND (2.3)」「≥1 JND = 2.3 ΔE00」） | 评估门/转正三证据判据 |
| **1.0（保守带）** | `src/pixo/pipeline/loop.py:695/:791` 注释（「默认 0.5，低于 1.0 JND 保守值」；实际早停阈值缺省 **0.5**，1.0 只是注释里的参照值）、`scripts/ab_intent_compare.py:19/:311/:531/:650`（p95 闸门地板 abs_eps=1.0 称「JND 地板」） | 早停/闸门的保守带口径 |

**落地**：
1. 权威常量 `JND_DELTA_E = 2.3` 落 **`src/pixo/pipeline/perceptual.py`**（单源点判断依据：该模块自 t47 起就是「JND 早停的 ΔE2000 底座」，loop 与 eval 脚本双方已有依赖，Sharma 2005 校验也在其测试内）；入 `__all__`，常量注释写明两套口径关系
2. `loop.py` 两处注释改为「低于 1.0 JND 保守值——保守带取 1.0，权威阈值 2.3 见 perceptual.JND_DELTA_E」；**行为零变化**（缺省 `jnd_threshold=0.5` / `jnd_window=2` 未动）
3. 两个评估脚本改引常量：`hsm_oklch_eval.py`、`eval_illum.py` 的 `JND = 2.3` → `from pixo.pipeline.perceptual import JND_DELTA_E as JND`（局部名不变，下游引用行零改动）
4. `ab_intent_compare.py` 四处注明口径：1.0 是 p95 闸门**保守带**（非转正判据），指回 JND_DELTA_E（行为零变化，报告文案措辞微调）
5. `scripts/README.md:28` 注明「JND 口径单源=perceptual.JND_DELTA_E」
6. `.artifacts/` 历史评估报告**不改写**（沿第九轮历史文档惯例），新报告经脚本常量自然统一

### 改了哪些文件

| 文件 | 变更 |
|---|---|
| `src/pixo/pipeline/perceptual.py` | +`JND_DELTA_E = 2.3`（+`__all__`+口径注释） |
| `src/pixo/pipeline/loop.py` | 两处注释（:695/:791 区）指回常量；行为零变化 |
| `scripts/hsm_oklch_eval.py` | 硬编码 → import 别名 |
| `scripts/illumination_est/eval_illum.py` | 同上 |
| `scripts/ab_intent_compare.py` | 4 处口径注明（docstring/注释/报告文案） |
| `scripts/README.md` | 1 处单源注明 |
| `tests/unit/test_perceptual_convergence.py` | +`test_jnd_caliber_single_source`（钉常量值=2.3、`__all__` 导出、loop 缺省 0.5/window 2 零变化） |

### 验证

```
python -m pytest tests/unit/test_perceptual_convergence.py tests/unit/test_loop_termination.py -q
→ 26 passed（含新钉死用例；早停行为/终止链全绿）
```
脚本接线冒烟：两脚本按各自 sys.path 引导 import 后 `m.JND == 2.3`（来自单源常量）；三脚本 `py_compile` 通过。

---

## 任务2：skin 7% 覆盖风险面复核（F11 遗留，第二批切换 skin 侧）

### 做了什么（纯评估，零代码改动）

1. **F11 JSON 逐行重挖**（`.artifacts/skin_colorcal_oklch_ab.json`，72 行 skin_rows）+ **主语料复跑**（`python .artifacts/_f11_skin_colorcal_ab.py`，44.9s，复跑值与原报告逐位一致——covA/covB/门控/分区 ΔE 全对上，确定性可复现）
2. **7% 定性到图**：5 行 = **4 张不同照片**（`golden_portrait_tele` 与 `X1_DSC_0466` 是同一张图的两个语料身份）：
   - `golden_portrait_tele`(=X1_DSC_0466)：covA 7.0%→covB 0.9%（**ratio 0.13，IoU 0.137**）——远超「腰斩」
   - `golden_high_contrast`：37.0%→7.7%（0.21）
   - `golden_high_key_bright`：25.9%→12.3%（0.48）
   - `DSC_5260_raw`（full_scan）：18.3%→9.0%（0.49）
3. **丢失带场景特征**（复用脚本函数逐图分析 A 独有带的亮度/饱和度）：四张图的丢失带高度一致——**低饱和**（HSV S 中位 0.09~0.15）+ 中暗部（Y 中位 54~107）。机理：两掩码都是 a-b 彩度平面椭圆（`core/skin.py`：cv2-Lab u8 椭圆 vs `SKIN_OKLAB_*` 固定椭圆），OKLab 椭圆在低彩度端更紧——**被丢的是去饱和/阴影侧肤色**（高对比图的 A 掩码大半是平坦低饱和背景误报，见下）
4. **意图影响逐图判定**（用 both/xor 分区作用量区分「真损失」与「假警报」）：

| 图 | A 掩码丢失占比 | 丢失带磨皮作用（ΔE 中位）| 判定 |
|---|---:|---:|---|
| portrait_tele/X1_DSC_0466 | **86.3%** | **0.639** | **真人像真损失**：tele 人像，A 掩码占比与人像构图一致；B 下仅剩 0.9% 受磨皮 |
| high_contrast | 83.6% | **0.000** | **假警报**：A 掩码自身作用为零（平坦低饱和区误报），B 收紧无行为差异——与 fit_skin_oklch「OKLab 误报更低」互证 |
| high_key_bright | 58.2% | 0.325 | 中度欠磨皮 |
| DSC_5260_raw | 45.4% | 0.388 | 中度欠磨皮 |
5. **3% 门控分叉**：F11 报告的 2/72 即上述同一张图（json 字段名 `gate3`=0.5% 门、`gate30`=3% 门，易混淆）；生产语义对照 `skin.py:36-37`（portrait 已分类 0.5% / 未分类 3%）：X1_DSC_0466 在 B 轨 covB=0.91%——**未分类时整段 skin 直通；即便分类为 portrait 过 0.5% 门，也只有 0.9% 面积受磨皮（A 为 7%）**。两条路都欠磨皮，区别只是「全无」与「剩一成」
6. **损失面全语料量化**：A 掩码总像素的 23.1% 落在 B 丢失带；covA≥2% 且丢失带作用 ≥0.1ΔE 的图 6 张（上表 4 张 + day_normal 0.571/wide_angle 0.561/night_lowlight 0.358——但这三张 A 掩码高达 41~79%，大概率本身是误报收紧，非真损失）。合成 GT 双图 P/R 两轨均 ≈1.0——**分歧集中在真实 RAW 的低饱和边界肤色**，与 F11 结论一致

### 结论：**需修（修后可切）**

- **不是「可切」**：唯一 probable 真人像（X1_DSC_0466）磨皮意图实质失效（86% 作用带丢失 + 3% 门直通风险），而磨皮恰是 skin stage 的存在目的；films 卡 22 张带 skin 键（17 张 enabled，F07 口径），切换后真实用户会撞上
- **不是「需缓」的模糊等待**：失败模式已定位到机制级——OKLab 椭圆（`SKIN_OKLAB_A/B/MAJOR/MINOR/ANGLE`，纯 a-b 平面、无 L 维）在低彩度端过紧，排除 S≲0.15 的去饱和/阴影侧肤色；修复杠杆明确
- **修什么**：沿 `scripts/fit_skin_oklch.py` 拟合管线重拟合 OKLab 椭圆的低彩度端（扩 MAJOR/minor 或加低彩度准入带），验收三条 = 合成 GT P/R 保持 ≈1.0 + X1_DSC_0466 类低饱和肤色召回恢复（丢失带占比降到 <30%）+ 全语料误伤闸门维持「不劣于(小值)」。修复工作量预估=一次重拟合 + F11 脚本复跑验证，一个定向小批次
- **降级路径**（若队长/产品接受披露切换）：风险方向恒为欠磨皮（B 足迹 ⊆ A 为主，零误伤），可「可切 + 观察期 + 文档披露 tele 人像欠磨皮」，但 3% 门控分叉须一并披露

### 改了哪些文件

零代码改动。评估产物：复跑刷新 `.artifacts/skin_colorcal_oklch_ab.json`（值逐位一致）；本节分析数据由脚本函数内联复算产生，未新增落盘文件。

### 遗留问题

1. X1_DSC_0466 在真实 loop 中的 scene 分类结果未验证（决定走 0.5% 门还是 3% 门）——修复验证时应连同 scene 路径一起过
2. `synthetic_portrait_warm` 行 xorEffA=2.110 但 xor 占比 0.0%（极小像素集的中位数抖动），无行为意义，记录避免误读
3. F11 md 报告由 `_f11_write_report.py` 生成，本次复跑只刷新 json；若 dev-2 需要新 md 需跑该生成器

---

# r10 追加：skin OKLab 椭圆低彩度端重拟合（承接本文件任务2 的「需修」）

> 2026-09-07 完成。结论：**修成，skin 侧翻转「可切」**；三门禁验收全过；
> 金样本 gate 20 feature 零漂移（无需基线再生）。

## 做了什么

### 1. 先证伪「纯阈值重拟合」，再定位可行杠杆

- 逐像素测量丢失带（X1_DSC_0466 / high_key_bright / DSC_5260）：OKLab
  **C≈0.007~0.017**（a≈0，b≈0.007~0.014），在 a-b 彩度平面与中性灰 (0,0)
  **统计不可分**——任何覆盖该带的椭圆必然同时覆盖中性灰。
- 实测色度核阈值放宽扫描（0.04→0.01，同点云 38 万正样本）：fp_bg
  0.2578→**0.7388** 爆炸（旧 Lab 轨 0.2705）——纯阈值重拟合破误伤闸门，
  证实原拟合注记「近中性带拽向中性」对包围拟合同样成立。**此路不通。**
- 可行杠杆 = 两个同为拟合产物的参数重定标：
  **覆盖分位 coverage 0.96→0.98**（同核 C>=0.04，把核分布尾端包进椭圆）
  + **软带 SOFT_BAND 0.25→0.31**（mask≥0.5 判定线 d=1.125→1.155 外推）。
  约束：中性灰不变量 `d0 > 1+band`（test_constants_sane）⇒ band ≤ d0−1。
  二维扫描 (coverage × band) 后定型 **(0.98, 0.31)**。

### 2. 落位（沿既有产物路径/登记方式）

| 文件 | 变更 |
|---|---|
| `src/pixo/render/core/skin.py` | 六常数回填（A 0.015127 / B 0.061263 / MAJOR 0.049594 / MINOR 0.047463 / ANGLE 0.196323 / SOFT_BAND 0.31）+ 注释块 r10 溯源 |
| `scripts/fit_skin_oklch.py` | 修正潜伏混淆：json 的 SKIN_OKLAB_SOFT_BAND 原误写旧掩码 SOFT_BAND → 改导入 SKIN_OKLAB_SOFT_BAND |
| `configs/color/skin_oklab.json` | 脚本 `--resume --coverage 0.98 --chroma-core 0.04` 正规重出（常数逐位一致，对照表 d≤1.0 口径更新：recall 0.8316→0.9226 / recall_core 0.9552→0.9751 / fp_bg 0.2578→0.3197） |
| `.artifacts/fit_skin_oklch.md` | 同步重出 + 追加 r10 溯源节；旧版 M-O2 报告存档 `.artifacts/fit_skin_oklch_mo2_20260904.md` |
| `.artifacts/skin_colorcal_oklch_ab.json/.md` | F11 修后全量复跑数据 + skin 结论翻转「可切」 |

### 3. F11 复跑验收（72 张全量，逐位可复现）

| 验收线 | 结果 | 判定 |
|---|---|---|
| ① 覆盖腰斩消除或缩到可接受 | 腰斩图 **5/72 → 0/72**；四张关键图 covB/covA：tele 0.13→**0.94**、high_contrast 0.21→0.93、high_key 0.48→0.95、DSC_5260 0.49→1.06；全语料 covB/covA median 0.847→**1.036**（min 0.137→0.921） | **PASS** |
| ② 门控分叉消除（含 scene 路径） | 0.5% 门分叉 0/72（持平）；3% 门分叉 **2/72 → 0/72**；X1_DSC_0466 covB 0.91%→**6.6%**——0.5%/3% **两门均过**，scene 分类路径不再敏感 | **PASS** |
| ③ 误伤闸门不破 | 双非肤区 B 与 A **逐位相同**（零新增害）；合成 GT P/R 双轨 **1.0000/1.0000**；双肤区强度 B/A **median 1.000** 入对齐带（尾部 9 张 0.85~1.41，绝对差 ≤0.13ΔE 亚 JND，记观察项）；d≤1.0 口径 fp_bg 0.2578→0.3197（量级与旧 Lab 轨 0.2705 同档，且软带外推的 ≥0.5 级 fp 变化 ±0.04，作用于近中性带——该带旧 Lab 轨本就覆盖） | **PASS** |

### 4. 测试与金样本

- 定向测试：`test_skin.py + test_skin_oklab.py + test_film_cards.py + test_film_cards_oklch.py` → **53 passed**（含 G-1 常数逐位锁 vs json、中性灰 d0>1+band 不变量、gray/green mask 严格 0、双域分歧探针 ≥0.02、hsv 域逐位回归）
- 金样本 gate：`test_gate_golden.py` **4 passed**；逐 feature 复测 **20/20 零漂移**（max diff 0.0）——skin_oklch case 补丁为饱和经典肤色 (210,155,130)，两代椭圆在其上均 mask≡1.0，软边带变化不进入输出。**无需队长再生基线。**
- fit 脚本数学测试（test_skin_oklab 内已知椭圆回收）随套通过。

### 5. 遗留/观察项

1. **双肤区强度尾部**：9 张（DSC_5268~5275 同场景连拍 + high_key）B/A 0.85~1.41——绝对差 ≤0.13 ΔE（亚 JND），方向磨皮增强，第二批切换后纳入观察。
2. **colorcal 计时口径**：本轮测得 native 9.2ms / python 24.4ms（2.6×），r9 首测 8.5/131（15×）——color_cal 算术未动，差异疑为测量环境/首载因素；dev-2 做 colorcal go/no-go 前建议统一计时口径复测。
3. **复合差 p95**：mask 足迹差带 p95 1.14（card）/2.89（strong）——两轨足迹对齐后 XOR 带进入更多有实差的色度肤像素，属足迹差带口径（非闸门），随 native OKLab 化议题一并观察。
4. 金样本 gate case 的 skin_oklch 补丁对软边带**零敏感性**（实心饱和肤色）——第二批切换后建议 gate_cases 为 skin_oklch 增补软边带敏感探针色（dev-2/tester 域，动议报队长）。
