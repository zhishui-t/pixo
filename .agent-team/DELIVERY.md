# 交付报告（DELIVERY）— Pixo 第九轮战役

> 队长 2026-09-07；卡点③验收物。战役全景见 task-brief.md / qa-report.md。

## 任务回顾
一战清偿四大方向：**收口 9 月批次 + 彻底清债（FairFace/gsam 删除）× oklch 渐进切默认（第一批 hsl+split_tone）× M1 掩码驱动渲染落地 × 发布合规包**，外加 RAW 金样本团队重验关闭挂起两周的终审决策。全自主推进（用户 2026-09-07 plan 批准预授权卡点②）。

## 交付物清单
| F-ID | 交付内容 | 位置（commit） | 状态 |
|------|----------|------|------|
| F01 | changelog 补 08-27~09-05 历史批（31 commit/11 条目） | e02b91d | 完成 |
| F02 | 全量基线存证 1396 passed（qa 签认） | baseline-f02.md | 完成 |
| F03 | FairFace 彻底移除（82 passed/grep 零活引用/防复活断言） | 651f5d1 | 完成 |
| F04 | gsam 彻底移除（107 passed/兜底语义零掩码+warn/extras 保留） | 651f5d1 | 完成 |
| F05 | lr_baseline 处置=记债（生产零命中六证据/native 伪选项证明） | 0d5372a（tech_debt #16） | 完成 |
| F06 | RAW 金样本重验：基线过期裁决→重生成→qa 24/24 逐位→**挂起终审决策关闭** | b187d27 | 完成 |
| F07 | 23 存量卡钉 hsv 69 条（A1 卡级锚定，字节级逐位不变三方复核） | ef4473d | 完成 |
| F08 | gate 缺省分派 case+存量卡 golden（17→19，翻转实验双性质验证） | ce92c73 | 完成 |
| F09 | patch_protocol band 归属同源化（零字面量/parity 钉死）+canonical 确认 | ce92c73 | 完成 |
| F10 | **oklch 第一批切换**（hsl/split_tone 缺省翻转；A1 兑现/观测点兑现/RAW 零漂） | 3d2db90 | 完成 |
| F11 | skin/colorcal 意图级 A/B（72 张语料：skin 不劣于/colorcal 输出不劣但性能 15×） | .artifacts/skin_colorcal_oklch_ab.md | 完成 |
| F12 | region_adjust stage（order=57，默认零影响，343 passed） | 512bd0d | 完成 |
| F13 | 掩码通道 preview/export 双线注入（EV 漂移 0.0048/两设计陷阱机制级处置） | 35af288 | 完成 |
| F14 | decide region.* 接线（e2e 闭环+键宇宙完整注册+值域钳制） | b812061 | 完成 |
| F15 | M1 验收资产（gate 20 features/harness/README） | ce92c73 | 完成 |
| F16 | THIRD_PARTY_NOTICES.md 238 行（三警示置顶/四矛盾如实入档） | d25f70c | 完成 |
| F17 | PyYAML 升必装+scipy 可选 extras calib | 0d5372a | 完成 |
| F18 | DNG SDK 复审评估（286 行痕迹/高中低分级/**GPL 血缘新发现**） | research/dng-sdk-review.md | 完成 |
| F19 | 感知门禁提案（R3 双通道分期 2.5-3.5 人日/**JND 口径 1.0/2.3 两套并存发现**） | research/perceptual-gate-proposal.md | 完成 |
| F20 | changelog 本轮批 | 收尾 commit | 完成（writer） |
| 附 | M1 独立评审（0 阻断/4 重要/8 建议）+修复批 8 项 | fc2bfa8 | 完成 |

## 验证证据摘要
- **全量回归：1474 passed / 5 skipped / 1 xfailed / 0 failed**（开局基线 1396 → +78 全为本轮新增测试逐项对账；tester 与 qa 双跑逐数一致）
- 门禁链：.design_ok（9 修订）→ 7 份定向门禁 → .f10_ok（专项）→ **.qa_ok（总审 PASS，累计修复 10 处留档）**
- F10 三重证据：23 卡字节级三方全等 / gate 20 features v2 零漂 / RAW 24/24 max=0
- 前端 tsc 零错误 + unit 11 passed；bug 0（tester/test-report.md）
- 复现：`python -m pytest tests -q -m "not e2e"`；RAW 金样本 `gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512`

## 团队执行情况（角色库 2026-09-07 用户定稿版）
| 角色 | 模型/思考档位 | 实际生效 | 备注 |
|------|------|----------|------|
| dev-1 | GLM-5.3-Flash/max | ✅ | 清债流 F03/F04/F05 全交付 |
| dev-2 | GLM-5.3-Flash/max | ✅ | oklch 流 F07~F11 全交付（最高危 F10 一次通过） |
| dev-3 | GLM-5.3-Flash/max | ✅ | M1 流 F12/F14/F15+评审修复批；范围外追认 1 处（必要线） |
| super-dev | GLM-5.3/max | ✅ | F13 攻坚：spike 先行+两设计陷阱发现 |
| qa（QA-checker 本会话沿用旧注册名） | GLM-5.3/max | ✅ | 全程 10 轮任务：设计审核+6 门禁+F10 专项+总审；修复 10 处（含 1 断言弱化、1 红旗定位） |
| tester | GLM-5.3-Flash/max | ✅ | 测试计划+专项+全量，A1 三方独立复验 |
| researcher | GLM-5.3-Flash/max | ✅ | F18/F19/F16 素材（三项新发现） |
| writer | GLM-5.3-Flash/max | ✅ | F01/F16 成文/F17/F20 |
| reviewer | GLM-5.3-Flash（用户有意降档） | ✅ | M1 全链评审 0 阻断/4 重要/8 建议，全部处置 |

无兜底降级（qa 改名 QA-checker 未影响本会话派遣，沿用旧注册名）。

## 遗留问题（qa 分档 + 队长汇总）

### B. 待用户拍板（5 项）
1. **huesat RawTherapee GPL-3.0 血缘**（发布处置最高危）——`render/core/huesat.py:5-6` 自述移植；开源发布前必决（重写/隔离/许可调整），评估见 research/dng-sdk-review.md
2. **DNG SDK 痕迹的开源路径**——Adobe 许可实际允许衍生分发（原评审过严），阻断点收窄为不可再授权+SDK 衍生痕迹的声明口径
3. **台账矛盾修正时机（scorer.pt 部分撤案+缺陷已修）**——用户质询后队长实测：权重本就不进 git/包（部署期产物设计自洽）；初版「随 wheel 分发」为误报，**实情是 data-files 目录通配导致 wheel 构建直接失败**——已修复（e09053f：显式文件列表+补 films 卡进包+golden 移出打包，实测构建通过 0.66MB）；保留项：vision_models.json 过期冲突 / segformer 条目自相矛盾
4. **JND 口径统一**——仓内 1.0 与 2.3 两套并存（F19 发现），感知门禁提案落地前须定
5. **oklch 第二批 go/no-go**——skin/colorcal：输出质量不劣于，但 colorcal 性能 15×（4096px 外推 8.4s/图）+ skin 7% 图覆盖腰斩风险面；数据见 .artifacts/skin_colorcal_oklch_ab.md

### A. 记债已落（9 项）
tech_debt #16（lr_baseline）/ #17（free-px-rect 跨分辨率掩码几何失准，评审 I-2）/ S-4 限流器波及 / S-6 内存 / S-7 缓存 metrics / S-8 键别名 / 卡 stages 字段信息性 / region 规则保守不入默认包（激活开关）/ delta 累加 v1 限制

### C. 建议下轮（8 项，qa-report.md）
compose 相对坐标化（居首）/ region 规则激活评估 / 感知门禁 R3 落地（F19 提案）/ F19-第一期 ΔE 硬门 / skin A/B 风险面复核 / NOTICES 矛盾清理 / graphify 派生物刷新 / warm_sat spike 已取消（F05 伪选项证明）

## 后续建议
- oklch 第二批建议**先攻 colorcal 性能**（native oklch 路径或缓存策略）再谈切换——质量证据已备，卡在性能预算
- M1 下一步=region 规则激活的独立批准流程（需先跑真实语料的 region 效果评估）
- 发布合规三件（GPL 血缘/DCP 核验/台账矛盾）建议在开源发布决策时一并处置——按用户既定方针「发布后面说」挂起

## 用户验收
- 2026-09-07：待验收（卡点③）
