# 阶段一（OWN PIPELINE STAGE 1）QA 终审报告

- 审查人: 质量审核（t25）
- 日期: 2026-09-04
- 依据: `docs/OWN_PIPELINE_STAGE1_DESIGN.md` §0-§9（含 §8 收口追加）、t22/t23 交付报告、t24 检视报告（第 1 轮）、t1/t2/t3/t7/t14/t15/t16-t21 各批次交付记录
- 终审判定: **GO（有条件放行）**

> 判定依据概述：§6 验收红线三要素（全量测试全绿 / hsv 既有 gate 基线逐位不变 / oklch 新基线 reviewer 签注）全部满足，t24 集中检视零 blocker，盲点 A1-A4 全部闭环。唯一未满足项为 §6 操作手册表第 3 行「skin oklch → skin case 双域」的金样本要求（详见 §1 缺口 G-1）——该项位于非缺省路径（skin oklch 域需显式开启）、有 16 项单测覆盖行为语义，不构成红线违背，作为 P1 条件项放行。

---

## 1. §6 质量门操作手册逐行核对

| §6 行 | 验收要求 | 交付对应与证据 | 状态 |
|---|---|---|---|
| oklab.py 内核 | 金样本不涉及（纯新模块） | t1（§8.1 已验收）：`test_oklab.py` 23 用例，网格 1/32 往返实测 1.8e-10（线 1e-7） | ✅ 按设计 N/A |
| hsl/split_tone oklch 域 · 金样本 | 新增 2 case + 旧 12 case 不动 | t22：`hsl_oklch` + `split_tone_oklab` 入 `gate_cases.py`（14 features），新基线生成 + `--check` 重算一致 + reviewer 签注。**QA 复核**：manifest diff 仅 +2 条目 + reviewer 行重签，旧 12 个 .npy 零字节改动（git 跟踪文件未修改即逐位一致），数量守卫 12→14 已同步 | ✅ |
| hsl/split_tone oklch 域 · native 等价 | hsv 旧内核不动即安全 | t24 检视：`core/hsl.py`、`core/split_tone.py` 零 diff；四 Stage 缺省 hsv 路径逐行等价 + bit-identical 测试锁定 | ✅ |
| hsl/split_tone oklch 域 · 语料 A/B | `ab_intent_compare.py` | t23：交付 + `.artifacts/ab_intent_report.{md,json}`（24 张、双跑逐位可复现）。不劣于闸门（误伤 median/p95×2、高光色相落点误差、近白色度强加）全过；HSV 已知缺陷量化证实（落点误差 median 11.27°→4.48°、近白 C 强加 0.0756→0.0115，6.6×） | ✅ |
| **skin oklch · 金样本** | **skin case 双域** | **缺口 G-1**：t22 按 §2.5（仅列 hsl_oklch/split_tone_oklab 两 case）交付，gate 的 `skin` feature 仍只锁旧 cv2-Lab 掩码（`skin_mask(_skin_patch())`），**无 `skin_mask_oklab` 域 case**；且 `SKIN_OKLAB_*` 拟合常数无任何精确锁定（`test_constants_sane` 仅 sanity 范围断言，core/skin.py 与 configs/color/skin_oklab.json 之间无一致性测试） | ❌ → 遗留 G-1（P1） |
| skin oklch · native 等价 | 不涉及 | oklch 域显式旁路 native（`_native_available() and domain=="hsv"`），hsv 缺省 native 路径不变（t24 核） | ✅ N/A |
| skin oklch · 语料 A/B | 召回/误报对照 | t18：`.artifacts/fit_skin_oklch.md` + `configs/color/skin_oklab.json`——核内召回 0.955 / 全体 0.832 / 背景误报 0.258（旧 0.271），诚实口径下首次全面占优；两域 d 分位数交叉验证旧椭圆几何 | ✅ |
| native oklab · native 等价 | **逐位等价强制** | t19：`test_native_oklab.py` 10/10——uint 位型视图比较（非 allclose），随机 100 万像素双向 + 网格双向 + 边界 + 越域；DLL 1.4.0 实际加载。t24 复核零 skip；C++ 立方 `std::pow(x,3.0)` 与 numpy `x**3` CRT 对齐 + 「禁止改写」注释在位 | ✅ |
| RP-CCM · 语料 A/B | ΔE2000 报告强制（不切默认） | t2：`.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md`（54 张全扫描，median -7.7%）；configs 默认未被修改（t24 复核 + 本轮 git 佐证） | ✅（转默认建议见 §3） |
| 前端 · e2e 冒烟 | e2e 冒烟 | t20：smoke 8/8 + oklch 交互检查 9/9 + hsv 域像素级取证（视口 0/1,296,000 差异，全面板差异仅 2 处规格内 toggle）；typecheck/build 过（t24 复跑 typecheck ✓） | ✅ |
| **验收红线 ①** | `pytest tests/unit tests/regression` 全绿 | t22 报告 1231 passed / 4 skipped / 1 xfailed；**QA 终审独立复跑同口径 1231/4/1（171s）**，4 skip 均为 RAW_PATH 未设的 gate_e2e 既有豁免 | ✅ |
| **验收红线 ②** | hsv 既有 gate 基线逐位不变 | t22 三方核验（磁盘 ↔ manifest ↔ git HEAD）+ QA git 佐证（旧 .npy 零修改） | ✅ |
| **验收红线 ③** | oklch 新基线 reviewer 通过 | t22 签注入库。**程序瑕疵备注**：生成器约定基线改动需双签，本次为 QA 单方执行记录；t22 已注明脚本确定性已证、可 `--check` 直接复现，本终审接受该签注并留痕 | ✅（带备注） |

## 2. 审核盲点 A1-A4 闭环核对

| 盲点 | 要求 | 闭环证据 | 状态 |
|---|---|---|---|
| **A1** 存量胶片卡 | band 语义迁移零破坏，13→24 张存量卡逐位不变 | t21 守卫测试（24 卡「无 color_domain 键 + bands 无 domain 键」+ film_portra_400 锁定）+ t21 集成 e2e（卡参数经 preview 接口渲染）+ t24 检视复核 + t22 内核层旧 12 gate 基线逐位不变（覆盖 hsl/split_tone 旧内核行为） | ✅ 闭环 |
| **A2** 知识包语义 | LLM 副驾层量纲描述同步 | t21：photography_hue +2 节点 3 边（OKLCh 色相量纲/色度量纲）、post2 +1 节点 2 边（color_domain 双轨说明），全部合规（≤80 字/keywords 3-6/受控 relation/包内边）、registry 合并零新增告警、新节点可检索；t24 复核 | ✅ 闭环 |
| **A3** skin 白点口径 | 以 cv2 实现语义为准，不照抄文档 "Lab(D65)" | t18 拟合脚本头显式声明（"以 cv2 实现语义为准, 不照抄文档"，含 OKLab 与管线同源说明）；t24 检视确认。（注：终审任务书原文写「t17 skin」系批次号笔误——skin 重拟合为 t18/原 t5，以内容核对为准） | ✅ 闭环 |
| **A4** loop 色彩桥 | `loop.py:54 _COLOR_PARAM_ALIASES` 桥接排查 | **上游批次未交付此项，由本终审亲自排查闭环**：①`_COLOR_PARAM_ALIASES` 仅映射 `vibrance.strength`/`saturation.adjust` → **colorcal** stage（vibrance/saturation 为 Lab 域增益，与 hsl `color_domain` 无关）；②`_DOTTED_PARAM_REGISTRY`（t107 注册表）无任何 hsl/split_tone 键——规则侧不存在会受域迁移影响的执行位；③规则 yaml 中 split_tone 仅**注释模板**（`split_tone_neutral_rule` 预留，参数为 `split_tone.strength`——strength 是双域同义的混合权重）；④`reshape.py` VibranceStage 为已废弃占位，消费注释明确指向 colorcal。**结论：hsl/split_tone 域变更不影响 decide 环路，A4 无需代码改动。** 注意事项：阶段二若激活 split_tone 规则模板或新增 hue/sat 语义规则键，必须过 color_domain 语义审查（hue 语义跨域不可换算） | ✅ 闭环（QA 排查） |

## 3. RP-CCM ΔE2000 汇总与转默认初步建议（只建议，不决策）

**报告数据**（`.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md`，54 张 full_scan，CIEDE2000 D65，逐照片曝光增益对齐）：

- 总体：A（DCP 现行）median 6.151 / p95 16.732；B（DCP+RP-CCM）median **5.675**（**-7.7%**）/ p95 16.239（-2.9%）；B 优照片 45/54。
- 回归簇：**9/54 张 B 轨变差**，其中 DSC_5250（+2.607）、DSC_5243（+2.205）、DSC_5238（+1.614）、DSC_5239（+1.584）、DSC_5237（+1.489）等成簇集中在 523x-5250 拍摄段；部分照片 p95 同步变差（如 5236: 11.038→11.624）。

**初步建议：未达转默认门槛，维持并联 opt-in、作为阶段二（M-D1）输入消化。** 理由：

1. **绝对误差仍大、收益不可感知**：两轨 median ΔE2000（6.15 vs 5.68）均远超 JND（≈1.0），-0.475 的改善在整体观感上不构成用户可感知的质变；
2. **回归簇未治理**：9/54 成簇回归（最大 +2.6 median）说明单一全局矩阵对该光照/场景簇失效，直接切默认会牺牲这批照片；应先按 pixo.meta 分组拟合或分簇门控（t18 的 skin 拟合已示范 per-group 组间漂移的存在）；
3. **验证面窄**：仅 nikon_z5_2 单相机 + 单 DCP 基线；
4. **门槛未立**：设计 §4 只规定「只报告不切默认」，未定义转默认的量化验收线。建议先立线再谈切换，例如：median 改善 ≥15%、无单照片 median 回归 > 1 JND、总体 p95 不劣化、≥2 相机复验通过。

## 4. 遗留项清单

| # | 级别 | 内容 | 建议责任方 |
|---|---|---|---|
| G-1 | **P1**（GO 条件项） | skin oklch 双域金样本缺失（§6 表行 3）：gate 无 `skin_mask_oklab` case，且 `SKIN_OKLAB_*` 常数无精确锁定。建议补法（二选一或都做）：① gate 增 `skin_oklch` feature = `skin_mask_oklab(_skin_patch()/255)` 走 reviewer 流程入库；② 增 core/skin.py ↔ configs/color/skin_oklab.json 常数逐位一致性测试。完成前 skin oklch 域保持非缺省（现即如此） | 测试线（t22 后续小批次），阶段二首批前关闭 |
| G-2 | P2 | t24 三条 minor 未修复（本轮核实仍原样）：①`modules/split_tone.py`/`modules/hsl.py` 的 `color_domain` schema 缺 `choices`（行为等价、风格不一）；②`modules/skin.py wants()` except 静默吞 oklch 掩码异常无留痕；③前端 3 处过时批次号注释（types.ts:240 / DomainToggle.tsx:7 / AdjustmentsPanel.tsx:205，"t18 合入前"实为 t17 已合入）。择机清理，不阻塞 | t17/t18/t20 对应成员 |
| G-3 | P2 | 项目图谱重生成（§8.5 已记录）：`--check` 守卫实测报漂移（图谱生成于 f48d453，其后阶段一改动未入图）；需重跑 `build_project_graph.py --merge docs/project_graph_frontend.json`；前端图谱生成脚本 `gen_project_graph_frontend.py` 从 `.artifacts/` 归位 `scripts/`。t24 已抽样 11 边验证图谱真实性（11/11 命中），漂移仅为时效性 | 维护批次 |
| G-4 | P3 | golden 生成器 `--out` 默认值仍是历史路径 `tests/goldens/gate`（实际 `tests/regression/goldens/gate`），需显式传参 + `PYTHONPATH=src` 运行（t22 报告遗留）；RAW_PATH 就绪后补跑 4 个豁免的 gate_e2e L3 项 | 维护批次 |
| G-5 | P3 | RP-CCM 维持不切默认（见 §3 建议）；阶段二先立量化门槛、做分组拟合/分簇门控后再评估 | 队长决策 + 阶段二 |
| G-6 | P3 | 阶段二规则侧提醒：激活 split_tone 规则模板或新增 hue/sat 语义键时须过 color_domain 语义审查（A4 排查结论的边界条件） | 阶段二规则线 |

## 5. 重组批次 t17-t25 ↔ 原设计 t4-t13 映射与终审状态

（映射依据设计 §9；「原号先行」批次 t1/t2/t3/t7 与 DAG 追加 t14/t15/t16 一并列出供完整追溯）

| 重组批次 | 承接原任务 | 内容 | 终审状态 |
|---|---|---|---|
| t17 | t4 | `core/split_tone_oklab.py` 分离色调 OKLab 迁移 | ✅ 交付 + t24 检视通过（2 minor 待清） |
| t18 | t5 | skin OKLab 椭圆重拟合 + `skin_mask_oklab` | ✅ 交付 + t24 检视通过（1 minor 待清；金样本缺口见 G-1） |
| t19 | t6 | native `oklab.cpp` 逐位等价 + t1 复核表述修正 | ✅ 交付 + t24 检视零问题（t16 复核 §5.1/§5.2 修正已落实） |
| t20 | t8 | 前端 HSL/split_tone 面板 `color_domain` | ✅ 交付 + t24 检视通过（1 minor 待清） |
| t21 | t9 | 胶片卡/知识包 OKLCh 语义同步（A1/A2） | ✅ 交付 + t24 检视零问题 |
| t22 | t10 | 金样本 oklch case + gate 回归 | ✅ 交付（§6 行 3 skin 双域缺口 → G-1；签注单方执行留痕） |
| t23 | t11 | `ab_intent_compare.py` 意图级 A/B 对照 | ✅ 交付，不劣于闸门全过 |
| t24 | t12 | 代码检视（≤2 轮） | ✅ 第 1 轮完成：六维零 blocker、4 minor（3 未修复 → G-2）；因无 blocker 无需第二轮 |
| t25 | t13 | QA 终审 | ✅ 本报告 |
| （原号）t1 | — | oklab 内核 | ✅ §8.1 已验收 + t16 独立复核通过 |
| （原号）t2 | — | RP-CCM 线 | ✅ §8.2 已验收（转默认建议见 §3） |
| （原号）t3 | — | hsl_oklch + HslStage 分派 | ✅ §8.1 已验收 + t24 抽检通过 |
| （原号）t7 | — | UI 规范 | ✅ §8.4 已验收 |
| t14/t15 | — | 项目图谱（后端/前端） | ✅ §8.3 已验收 + t24 抽样验证（重生成待办 → G-3） |
| t16 | — | t1 独立复核 | ✅ §8.1（2 处表述修正由 t19 落实，t24 核对闭环） |

## 6. QA 独立复验记录（非转述交付报告的亲验项）

1. 全量 `pytest tests/unit tests/regression tests/integration` → **1231 passed / 4 skipped / 1 xfailed**（171s，与 t22 报告同口径一致）；
2. 旧 12 gate 基线：git 佐证逐位不变（旧 .npy 跟踪文件零修改；manifest diff 仅 +2 条目 + reviewer 行）；
3. `build_project_graph.py --check` 守卫实测触发（漂移符合 §8.5 记录）；
4. A4 桥接逐点排查（§2 表内四条证据）；
5. t24 三条 minor 修复状态核实（均未修复，列入 G-2）；
6. RP-CCM 报告逐行复读（含 9 张回归照片分簇核对）；
7. native DLL 1.4.0 加载 + oklab 面 85 项零 skip（t24 轮验证，本轮全量套件含之）；前端 typecheck（t24 轮复跑通过）。

---

**最终判定：GO（有条件放行）。** 阶段一六项质量门红线全部满足、四个审核盲点全部闭环、t24 集中检视零 blocker。条件项 G-1（skin oklch 双域金样本 + 常数锁定）须在阶段二首批消费 skin oklch 域之前关闭；其余 P2/P3 遗留按清单择机处理。oklch 域继续保持非缺省（设计 §1.2「数据说话后再切默认」留待阶段二金样本与 A/B 数据积累后另行决策）。
