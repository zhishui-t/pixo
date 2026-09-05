# Oklab 域切默认专项评估 (t52, 设计 §1.2 "数据说话后再切默认" 的数据与成本)

- 生成时间: 2026-09-05
- 纪律: **只评估不执行** —— 本报告未修改任何 src/configs/金样本; "翻转实验"为进程内
  monkeypatch (`.artifacts/_flip_experiment.py`, 不落盘), 跑完即恢复。
- 结论速览: **收益侧数据充分 (hsl/split_tone), 但不可直接切** —— 切默认的真实作用面是
  **4 个 stage** (hsl/split_tone/skin/colorcal), 胶片卡 24 张中 12 (hsl) + 12 (split_tone)
  + 18 (skin) + 24 (colorcal, 其中 6 张含皮肤保护) 张的渲染语义会被静默改变 (违反 A1
  红线), skin 缺省开启更波及全部默认渲染的人像场景; 金样本 0 张需重生成
  (这本身是守卫盲区而非安全证明)。建议分 stage 渐进 + 先落三道前置修补 (§5)。

---

## 1. 收益复核: 三大根治指标回题

设计承诺与 A/B 实测对照 (A/B = `.artifacts/ab_intent_report.md`, 24 张语料, seed=20260904,
判定准则见其 :8 —— 不劣于闸门只放在口径良定的伤害类指标, 单侧 B/A ≤ 1.1, 绝对地板兜底):

| # | 设计根治点 (承诺) | A/B 指标 (回题) | A: hsv | B: oklch | B/A | 判定 |
|---|---|---|---:|---:|---:|:---:|
| 1 | HSV 饱和截断缺陷 → C_max(L) 软限幅 + 中性保护 (设计 :87 "HSV 饱和截断缺陷的根治点") | hsl 意图扇区外误伤 ΔE median (ab 报告 :28) | 0.000 | 0.000 | — | **不劣于(小值)** ✅ |
|   |  | hsl 意图扇区外误伤 ΔE p95 (ab 报告 :29, 两意图) | 0.101 / 0.046 | 0.001 / 0.438 | — | **不劣于** ✅ |
| 2 | 高光色相漂移缺陷 → OKLab 固定角染色 (设计 :99 "高光色相漂移缺陷的根治点") | 高光落点误差 median ° (ab 报告 :51) | 11.27 | 4.48 | 0.40 | **不劣于** ✅ |
|   |  | 高光落点误差 p95 ° (ab 报告 :52) | 48.78 | 21.81 | 0.45 | **不劣于** ✅ |
| 3 | 近白强加色度 → C_ref(L) 高光自然趋 0 (ab 报告 :56 注记 "设计 §2.3 根治点") | 近白 (Y≥0.95) 色度强加 median ΔC (ab 报告 :53) | 0.0756 | 0.0115 | 0.15 | **不劣于** ✅ |

- 总体判定 (ab 报告 :65): "全部通过 → oklch 域新内核不劣于 hsv 域旧内核"; 扇区内实现强度
  为量级对照非闸门 (I1 B/A 0.82 更弱 / I2 6.42 更强, 跨域数值语义不同, ab 报告 :62-63)。
- **收益边界**: A/B 覆盖的是 **hsl 与 split_tone 两个内核**、且两轨各自取域匹配参数
  (ab 报告 :6/:14-16)。**skin 与 colorcal 的 oklch 侧没有 A/B 闸门** —— skin 只有拟合
  证据 (.artifacts/fit_skin_oklch.md, 厦门/春节语料 42 张有效 / 38.1 万皮肤样本包围拟合,
  阶段一 QA G-1 过) 与色阶对照 (skin_oklch gate case, gate_cases.py:129-135), 没有
  "不劣于"口径的意图级对照。**"数据说话"对 4 个 stage 中的 2 个成立。**

## 2. 切默认的机制与确切落点

- 参数回退链: `Stage.p` = ctx config → 实例 params → 调用方缺省 (graph.py:62-67);
  `Stage.__init__` 把 `default_params()` 合入实例参数 (graph.py:46-48) —— 故实例参数
  恒含 `color_domain`, **运行时 `p(ctx, "color_domain", "hsv")` 里的硬编码字符串
  (hsl.py:51 / split_tone.py:50 / color_cal.py:221 / skin.py:86) 实际不可达**。
- **切默认的确切落点 = 4 个 stage 的 `default_params()`**:
  `HslStage` (hsl.py:34) · `SplitToneStage` (split_tone.py:43) · `ColorCalStage`
  (color_cal.py:218) · `SkinStage` (skin.py:67)。同枚举四段 schema:
  hsl.py:30 / split_tone.py:35 / color_cal.py:206 / skin.py:63。
- **A1 关键交互 (stage 级缺省 × band 级缺省)**: band 无 `domain` 键时按 **Stage 级
  color_domain** 归属内核 —— `_split_bands_by_domain` 的 `band.get("domain",
  default_domain)` (hsl.py:73) → hsv 组走 `hsl_adjust_rgb`、oklch 组走
  `oklch_adjust_rgb` (hsl.py:58-64)。**Stage 缺省翻转 ⇒ 所有无 domain 键的 band 整体
  改道 oklch 内核**。设计 §2.2 的 A1 承诺 ("无 domain 键按 hsv 旧语义走旧内核,
  存量卡零迁移、逐位不变", 设计 :90) 正是靠 Stage 缺省="hsv" (设计 :54) 兑现的。
- 四 stage 全部在默认渲染链中: DEFAULT_STAGES 含 hsl/split_tone/colorcal/skin
  (presets.py:14-16); 且 **SkinStage 缺省 enabled=True** (skin.py:67, wants 同缺省
  skin.py:70) —— skin/colorcal 的域翻转波及**一切默认渲染**, 不限于胶片卡。

## 3. 成本清单

### 3.1 金样本: 17 → 17, **0 张需重生成** (但这是守卫盲区)

gate 金样本 17 features = 前置 15 纯函数/显式参数 + exposure_cal_auto/warmth_cal_auto
(标定敏感) (gate_cases.py:24-31; test_gate_golden.py:24-28 断言恰 17)。逐 case 分析:

| case 组 | 参数形态 (行号) | 翻转后 |
|---|---|---|
| hsl (gate_cases.py:102-105) | **直调 hsv 内核** `hsl_adjust_rgb(bands)` —— bands 无 domain 键, 但不经 Stage 分派 | 不变 |
| hsl_oklch (:106-120) | 直调 `oklch_adjust_rgb`, DEFAULT_BANDS_OKLCH 骨架 (hsl_oklch.py:59) + 显式 oklch 参数 | 不变 |
| split_tone / split_tone_oklab (:121-126) | 直调两内核, 同参 (30/30/210/40) 供 reviewer 对照 | 不变 |
| 其余 11 个前置 case + 2 个 cal_auto (:73-101, :146-184) | 不触 color_domain (exposure_cal_auto 实例化的是 ExposureStage, 无域参数) | 不变 |

**实证**: 翻转实验 (4 个 default_params → oklch) 下 `tests/regression/test_gate_golden.py`
全绿 —— 金样本对切默认**零敏感性**。生成器只迭代 `gate_cases.compute()`
(generate_gate_goldens.py:64-65), 不经 Pipeline, 与标定新表对照档的结论同理:
金样本锁的是**内核**, 不是**分派**。

> 任务原文预期 "缺省参数 case 会变" —— 对 gate 家族不成立 (家族里**不存在**缺省分派
> case)。这恰是缺口: 翻转 Stage 缺省后, 真正改变的运行时路径在金样本层零观测。
> 修补建议见 §5-b。

### 3.2 胶片卡 24 张: 分 stage 语义变化矩阵

卡库盘点 (configs/styles/films/, 26 文件 = **24 存量** + 2 oklch_demo):

| stage | 受影响存量卡 | 语义变化机理 |
|---|---|---|
| hsl | **12 张** (agfa/cinestill/kodak 全系, 每卡 8 bands) | bands 均无 domain 键且卡无 color_domain (test_film_cards_oklch.py:92-106 的 A1 不变量即证) → 缺省翻转后经 hsl.py:73 改道 oklch 内核; **HSV 色相中心 0/30/…/300 被重新解释为 OKLCh 感知角** (两轮非均匀, ab 报告 :18: 绿区 HSV 30° ≈ OKLCh 9°) → 选段错位、强度失配 |
| split_tone | **12 张** (与 hsl 同一批卡) | 拨盘 highlights_hue=42 等 (如 kodak_portra_400 params.split_tone) 无域标注 → split_tone.py:50-59 改道 `split_tone_oklab_rgb`; ab 报告 :16 实证同一拨盘角两域落点差 45°→81.3° (UI 表 B 锚点) → **染色色相系统性偏移** |
| skin | **18 张** (skin.enabled) | 掩码从 cv2-Lab 椭圆换 OKLab 椭圆 (skin.py:40-51 `_mask_fn`) → 肤区/肤保护范围变化 → 平滑强度作用区变化 |
| colorcal | **24/24 张** (全部带非零调整参数) | ① 计算路径换轨: native 快路径**仅 hsv 域** (color_cal.py:384 `if … and domain == "hsv"`) → 全部 24 张改走 float 路径; ② 其中 **6 张** skin_protect>0 → 肤区软掩码换核 (color_cal.py:228-237), 保护权重变化 (skin_trim/scene_skin_trim 消费者 0 张, 不涉及); colorcal 缺省参数全零且无 wants 门控 (graph.py:52-53 默认 True) —— 零调整 × 掩码 = 默认管线经 colorcal 的像素影响 ≈ 0, 影响集中在卡与 decide 写入 colorcal 的渲染 |
| oklch_demo 2 张 | 不受影响 | 显式 `color_domain:"oklch"` + band 级 domain 戳 (test_film_cards_oklch.py:60-90 钉死) |

**判定: 切默认破坏 A1 红线** (设计 :90 "存量卡零迁移、逐位不变")。且翻转实验证明现有
测试对此**几乎沉默**: `test_film_cards_oklch.py` 全绿 (它守的是卡库不带域键, 不渲染存量
卡), 没有任何"存量卡渲染快照"级金样本 —— 12+12+17+26 张卡的输出变化**无测试报警**。

### 3.3 全局面 (不止胶片卡)

- **所有默认渲染**: skin 缺省 enabled (skin.py:67) + DEFAULT_STAGES (presets.py:14-16)
  → 翻转 skin 缺省后, 人像场景 (skin wants 按 scene 门控, skin.py:72-73) 的默认出图
  肤掩码换核。实证: `test_native_colorcal.py::test_full_path_float_precision_sentinel`
  在翻转下红 —— 全量路径 vs 纯 float 参考分歧 max=0.0757 (阈值 0.0025), 根因即
  colorcal 肤区掩码/路径域翻转; `test_perceptual_convergence.py` 3 项与
  `test_loop_termination.py::test_oscillation_without_target_counts_as_big_improvement`
  红 —— auto 闭环的收敛行为被预览变化扰动。
- **web canonical 参数面**: `session.py:443` 把每个 stage 的 `default_params()` 合入
  canonical 参数 → 翻转后 UI/service 拿到的规范参数携带 `color_domain:"oklch"`,
  参数面语义扩散。
- **agent 补丁校验背离**: `patch_protocol.py:105-111` 对无 domain 键 band 按**硬编码
  "hsv"** 归属校验; 运行时 (hsl.py:73) 却按 stage 缺省分派 → 翻转后校验假设与运行时
  分派**静默分叉** (hsv 量纲 band 被当成 oklch 执行, 却按 hsv 语义放行)。

### 3.4 测试成本 (翻转实验实测)

基线 **1360 passed / 5 skipped / 1 xfailed** (全绿, 2026-09-05 含在途 t36 gate 增补);
四缺省翻转后 **11 failed / 1369 passed**:

| 类别 | 失败项 |
|---|---|
| 缺省断言 (切默认需同步修订, 5) | test_skin.py::test_skin_stage_registered_order_and_domain (skin.py:243 实测 `{'color_domain':'oklch'} != {'color_domain':'hsv'}`) · test_hsl_oklch.py / test_split_tone_oklab.py 各 2-3 项 (default_hsv_bitwise / domain_dispatch / default_params_preserved) |
| 行为级 (切默认改变渲染/收敛的证据, 6) | test_native_colorcal 哨兵 (max 0.0757>0.0025) · test_perceptual_convergence ×3 · test_loop_termination ×1 · test_hsl_oklch 的 dispatch 项 |

## 4. 风险矩阵与回退路径

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 12 张 hsl 卡选段错位 (HSV 角当 OKLCh 角) | 必然 | 用户可见的胶片模拟走色 | 前置修补 a (卡级钉死 hsv) |
| 12 张 split_tone 卡染色色相偏移 (≤45° 量级, ab :16) | 必然 | 同上 | 前置修补 a |
| 18 张卡 skin 掩码换核 / 6 张卡皮肤保护权重变化 / 24 张卡 colorcal 换 float 算路 | 必然 | 肤色保护/平滑观感漂移 + colorcal 数值路径变化 | 前置修补 a 或 d 单列评估 |
| 全局默认渲染变化 (skin 缺省开启) | 必然 | auto 闭环/web 全量出图变化, 且无 A/B 闸门背书 | skin/colorcal 与 hsl/split_tone 拆开决策 (§5-c) |
| patch_protocol 校验与运行时分派分叉 | 必然 | agent 建议的域语义校验失效 | 前置修补 e |
| 测试哨兵长红掩盖新回归 | 必然 (11 项) | 回归信噪比下降 | 切换 PR 内同步修订缺省断言并逐项归因 |

**回退路径 (generation 回退即可, 设计 :55 "旧实现代码不删不改 (回退保证)")**:
翻转的代码面只有 4 个 `default_params()` 行 (hsl.py:34 / split_tone.py:43 /
color_cal.py:218 / skin.py:67) + 缺省断言测试修订; **金样本零重生成** → 回退 =
`git revert` 该提交即恢复逐位现状 (金样本/卡库均不动)。双轨内核与 band 级 domain
键 (hsl.py:69-78) 保持, 已显式钉域的 2 张 demo 卡与新卡不受回退影响。

## 5. 结论与建议 (只建议不执行)

**结论: 不可按"一次翻 4 个缺省"直接切。** 收益数据只覆盖 hsl/split_tone;
skin/colorcal 无 A/B 闸门且影响全局默认渲染; 胶片卡 A1 红线必破且测试对卡级变化
零报警 (守卫盲区)。若要在"数据说话"纪律内完成切换, 建议顺序:

- **a) 保 A1 的卡级锚定 (切 hsl/split_tone 的前置)**: 在卡加载层 (know/cards.py) 或
  24 张存量卡 JSON 显式补 `color_domain:"hsv"` (与 test_film_cards_oklch.py:92 的
  不变量测试同步改写), 使"存量卡逐位不变"不再依赖 Stage 缺省;
- **b) 补分派级守卫**: gate 金样本新增 1 个"缺省分派"case (走 Stage 缺省的 hsl/
  split_tone/skin/colorcal 合成图快照, 17→18) + 至少 1 张存量卡 (如 kodak_portra_400)
  的全管线渲染 golden —— 让下一次域缺省变化在金样本层可观测;
- **c) 分 stage 渐进**: ① 先切 **hsl + split_tone** (有 ab_intent_report.md 全过背书,
  a 完成后卡语义不动; 实测只剩 5 项缺省断言需同步修订); 观察一个周期后 ② 再评估
  **skin + colorcal** —— 切前需先补 skin 掩码域的意图级 A/B (现只有拟合报告) 并确认
  全局默认渲染变化可接受 (native 哨兵/收敛类测试的归因清单见 §3.4);
- **d) 同步项**: patch_protocol.py:111 的 band 归属假设改为与 Stage 缺省同源 (或读
  运行时常量); session.py canonical 参数面的 color_domain 透出与 UI 确认。
- **回退**: 任一步异常即 git revert 对应提交, 金样本零回滚成本 (§4)。

> 引用约定: 设计 = docs/OWN_PIPELINE_STAGE1_DESIGN.md; ab 报告 =
> .artifacts/ab_intent_report.md; 复现: `python .artifacts/_flip_experiment.py`
> (进程内翻转 + 全量 pytest, 勿与基线并行跑)。
