# 总审报告（qa-final）— Pixo 第九轮战役

> 审核人：qa｜2026-09-07T03:32:03+08:00。被审版本：master @ **fc2bfa8**（12 笔战役提交：
> 651f5d1→fc2bfa8；工作树净，仅 .artifacts 未跟踪哈希存证）。
> 输入：task-brief.md（F01~F20 完成标准）+ design.md + tester test-report @ 03:14 + 各 stream/
> gate/review/research 报告 + 代码终态。
> 方法：逐 F 判定 + 文档事实抽验 + 设计-代码一致性终态抽查 + 全量独立复跑 + 遗留三级分档。

## 0. 放行结论

**PASS——.qa_ok 落盘。** F01~F19 全数达成完成标准（F20 为本门禁后收尾件，标待执行）；
全量回归 qa 独立复现 **1474 passed / 5 skipped / 1 xfailed / 0 failed**（基线 1396 不降，+78
逐项对账经 tester 表+qa 抽验）；阻断性缺陷 0；遗留全部落档分档（§3），其中 **2 项待用户
拍板为发布路径决策项**（非本轮工程缺口，任务书口径内）。

本轮总审修复：**0 处**（未发现代码级新问题）。战役全程 qa 修复累计 10 处（设计 9 + F07
断言弱化 1，均已在各门禁文件留三要素记录）。

---

## 1. 逐 F 判定

| F | 判定 | 依据（qa 独立核验路径） |
|---|---|---|
| F01 changelog 历史批 | **PASS** | 31 commit→11 条目全覆盖；抽验 3 项：t64 批（huesat_oklch 分派/缺省仍 hsv）与 f357b35 逐点吻合，验收数字 median 10.890/p95 16.070 与 hsm_oklch_eval.md:12 **逐位一致**；t66 批（styles 端点/双卡退役/client 清理）与 f4a51db stat 吻合；条目-提交覆盖核对通过 |
| F02 全量基线 | **PASS** | baseline-f02.md（1396/5/1 @ f357b35）qa 已签认（含 skip 第 5 项定位=learned_isolation 预铺门）；本轮全量 1474 对基线 +78 全为新增 |
| F03 FairFace 移除 | **PASS** | 门禁 gates/f03-f04-vision.md：src/configs 零活引用、防复活断言在位（test_vision_models_no_unused_entries）、终态 person.py 不在 git（qa 终验 ls-files=0） |
| F04 gsam 移除 | **PASS** | 同门禁：契约双边界（纯未知零掩码不上抛/真实全败仍上抛）测试钉死；extras 保留（qa 设计修订点被正确执行）；台账 15 在案 |
| F05 lr_baseline | **PASS(记债 c)** | 调查证据链（启用面 6 条）+ tech_debt 条目 16（commit 0d5372a 内）；零代码改动符合三选一裁决 |
| F06 RAW 金样本重验 | **PASS** | 双轮闭环：qa 首验 24/24 FAIL（基线 stale 定位+漂移源时间线）→ 队长重生成 b187d27 → 复验 24/24 逐位 PASS → F10 后 tester/qa 双复跑 24/24 max=0；manifest reviewer=`qa-reverified 2026-09-07 (regen@f357b35)`；挂起项（t108 待用户终审）关闭 |
| F07 存量卡钉 hsv | **PASS** | 门禁 f07-pin-hsv.md：69 条钉域（12/12/22/23 与设计口径对账）、diff 解析级纯度零违例、逐位证据三重复验（含 qa 独立重跑 23/23 字节复现）；门禁中修 1 处断言弱化（枚举外禁域恢复） |
| F08 gate 双 case | **PASS** | 门禁 f08-f09：翻转实验复现（case1 必变/case2 逐位不变）；manifest 外科式（17 旧条目字节未动+reviewer 保留）；--check 20 features 零漂移 |
| F09 patch 同源化 | **PASS** | 同门禁：_stage_default_color_domain 零字面量（STAGE_REGISTRY 同源）；翻转自证+parity 双测试钉死「F10 后自动成立」；11 红（F09 中途态）转绿复验 |
| F10 oklch 第一批切换 | **PASS** | .f10_ok 四条全过：落点纯度（两文件仅翻转+注释）/A1（23 卡字节级+card golden 零漂移）/RAW 24/24 max=0/v2 治理（仅 default_dispatch 变更，v2=b3352650 与预报一致）；断言修订 7 项零删除无净弱化 |
| F11 skin+colorcal A/B | **PASS** | tester 时点缺口已闭：.md 已落盘且结论 per 维度齐全——skin 伤害类不劣于+强度不劣于（B/A 0.935）；colorcal 质量不劣于、**性能劣于 ≈15×**（如实记录，下轮决策输入）；语料 72 张（54 全量超额完成）；纪律「只评估不切换」保持（缺省仍 hsv——qa 终验 hsl/split_tone oklch、skin/colorcal 未动） |
| F12 region_adjust | **PASS** | 门禁 f12-region：数值/零影响/羽化纪律全过；M1 评审批修复后 32 用例绿；order=57 终态在链 |
| F13 掩码双线注入 | **PASS** | 门禁 f13-mask-channel：双陷阱机制级成立；23 用例+邻域绿；M1 评审 S-2/I-3 修复已入 fc2bfa8 |
| F14 decide region.* | **PASS** | 门禁 f14-decide-wiring：闭环+像素局部性实证；21 用例（含 M1 评审 S-5/I-1 增补）；裁决=默认零变化（DEFAULT_RULES 未动终态核实） |
| F15 M1 验收资产 | **PASS** | gate region_adjust case（--check 含）+samples.py regions 展开（终态 grep）+README 模块清单（含 region_adjust）齐备 |
| F16 NOTICES | **PASS** | 与 license-inventory 逐项抽验忠实：GPL 最高危警示在位（:24-27）、3 处台账矛盾如实披露（aesthetic .pt 在仓随 wheel/segformer 自相矛盾标注「最大未决项」/vision_models 过期） |
| F17 依赖声明 | **PASS** | 终态实查：pyyaml 必装双文件（requirements:7/pyproject:17）、scipy 可选+用途注释（pyproject:32-35）——与 qa 复核结论（硬依赖论证）一致 |
| F18 DNG 复审评估 | **PASS** | 评估产出完整（286 命中/35 实质项/高中低分级/legal 检索/四路径风险结论/差异化处置选项）；**不做决策留用户**合任务书；高危发现（GPL 血缘/读源码文字证据）入 NOTICES 联动 |
| F19 感知门禁提案 | **PASS** | 提案产出（不实施）；硬约束推导成立（评分器仅真语料回归带，t98 ρ=0.03 禁绝对线） |
| F20 changelog 本轮批 | **待执行** | 时序=qa-final 后 writer 收尾件；放行后执行，DELIVERY 呈报时核对覆盖至 fc2bfa8 |

### 抽验记录（本轮 qa 独立执行的证据抽核）
1. **tester 全量复现**：`python -m pytest tests -q -m "not e2e" -rs` → **1474 passed / 5 skipped /
   1 xfailed，188.25s**——与 test-report 逐数一致；skip 5 项与基线 qa 清单**逐条相同**。
2. **A1 三方哈希**：f07_before = f10_after = qa 复跑（F07 门禁）= tester 复跑 23/23 全等
   （tester §4 B4 口径透明记录复核——元数据字段差异非渲染差异，判定正确）。
3. **RAW 金样本**：qa 于 F10 门禁复跑 24/24 max=0；tester 复跑同果——双证。
4. **F01 数字溯源**：changelog 验收数字 vs hsm_oklch_eval.md 逐位比对（见 F01 行）。
5. **F16 事实性**：NOTICES vs inventory 的 GPL/矛盾项/权威台账声明三面核对（见 F16 行）。
6. **设计-代码终态一致性**（4 项抽查）：F03 person.py 零残留 / F14 region 分支在 HEAD /
   F15 samples+README 在位 / F17 依赖双文件——全中。

## 2. 修复记录

本轮总审：**0 处**（无代码级新问题）。战役累计 qa 修复留档：design.md 修订 9 处
（design-review.md §7）+ F07 测试断言弱化修复 1 处（gates/f07-pin-hsv.md §4）。

## 3. 遗留问题分级

### A. 记债已落（台账/测试/注释钉住，无行动缺口）
| 项 | 落点 |
|---|---|
| F05 lr_baseline 启用面窄 | tech_debt #16（commit 0d5372a） |
| I-2 px-rect 跨分辨率失配 | tech_debt #17 + 钉现状测试（test_region_masks_channel）+ fc2bfa8 修复 I-1/I-3/I-4/S-1/2/3/5 |
| S-7 缓存命中 metrics 丢失 | m1-review 裁决记遗留（F14 闭环无影响） |
| S-8 preview_overflow_ratio 别名 | m1-review 记遗留（既有非 M1 引入） |
| 卡 JSON stages 信息性字段 | F07 遗留 1（observations 记录） |
| region_rules 未入 DEFAULT_RULES | 设计内保守选择；入包须独立批准（F14 门禁裁决） |
| S-4 限流器波及 region.* | yaml 注释留痕，引擎豁免随规则激活一起定（无生产影响） |
| S-6 export 线工作集内存 | v2 bbox 优化方向留档 |
| F14 region delta 累加基线 | v1 mode=set 规避，嵌套解析留档 |

### B. 待用户拍板（决策项，非工程缺口）
| 项 | 内容与建议 |
|---|---|
| **F18-GPL（最高）** | huesat.py:5-6 自述 RawTherapee（GPL-3.0）移植——代码衍生非依赖，NOTICES 不能化解；发布前必处置（重写/git 考古核实/隔离三选）；NOTICES 已如实披露 |
| **F18-SDK 痕迹** | color.py:587 引用 SDK 内部符号等 35 实质痕迹——内部研发低风险，开源发布路径阻断（与 PIXO_LICENSE_REVIEW §6 一致但理由修正） |
| 台账 3 矛盾修正时机 | aesthetic .pt 实际在仓随 wheel（README 过期）/vision_models 过期/segformer 自相矛盾——NOTICES 已如实记录为待修，修台账动作待用户/队长定 |
| F19 感知门禁口径 | 提案已成（真语料回归带/绝对线禁用约束），阈值最终口径用户定 |
| skin/colorcal 第二批切换 | F11 数据已备（skin 双不劣于/colorcal 质量↑性能↓15×），go/no-go 待观察期后用户定 |

### C. 建议下轮
compose 参数相对坐标化（I-2 根修，m1-review 建议升优先级）；F14 delta 嵌套解析；S-6 bbox
优化；S-4 引擎豁免；colorcal oklch 性能路径（15× 数据在 F11）；graphify 派生文档刷新
（PROJECT_GRAPH 残留 fairface/gsam 字样）；LLM env 三件套 e2e（用户提供 env 后）；tech_debt
既有 P3（#13.3/13.4 等）。

## 4. 完成标准对照（task-brief「完成标准」四条）
1. F01~F20 按表完成 ✅（应有/可选项均实做未降级：F05/F16/F17/F18/F19 全实做；F20 待收尾——
   收尾件不阻断门禁，DELIVERY 时核对）。
2. 全量回归 ≥1231 基线不降 ✅（1474 ≥ 1231 ≥ 1396 战役基线；金样本基线重生成由队长单点执行
   并留证：gate_defaults b187d27 + gate default_dispatch v2，均 qa 核验）。
3. qa 总审通过（.qa_ok 落盘）：需求逐条核对 ✅（§1）+测试证据 ✅（§1 抽验）+遗留分级 ✅（§3）。
4. 分批 commit（依赖序 12 笔）✅ + changelog 本轮批（F20 待收尾）+ DELIVERY.md 交付呈报
   （队长收尾件）。

## 5. 交接与后续
- .qa_ok 落盘后：writer 执行 F20（changelog 本轮批，覆盖至 fc2bfa8）→ 队长 DELIVERY.md →
  卡点③用户验收（含 §3-B 五项拍板清单建议随 DELIVERY 呈报）。
- 未跟踪 .artifacts 哈希存证（f07/f10/tester/ab 四组）是否入库由队长定（脚本身可复现）。

> 总审章：qa 2026-09-07T03:32:03+08:00 — F01~F19 全过，F20 待收尾，放行。
