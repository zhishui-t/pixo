# 团队花名册（team-manifest）— Pixo 第九轮战役

> 队长 2026-09-07 拟定；卡点①确认物。角色库：`~/.zcode/agents/`（用户 2026-09-07 定稿版）。

## 任务
收口 9 月批次 + 清债（FairFace/gsam 删）× oklch 渐进切默认第一批 × M1 掩码驱动渲染落地 × 发布合规包 + 金样本重验。

## 编制（9 席，模型/思考档位按角色库固化）
| 位置 | 角色 | 数量 | 负责（F-ID/事项） | 输入文件 | 输出文件 |
|------|------|------|-------------------|----------|----------|
| 开发流1（清债流） | dev-1 | 1 | F03→F04→F05 | task-brief.md, design.md | streams/stream-1.md |
| 开发流2（oklch 流） | dev-2 | 1 | F07→F08→F09→F10→F11 | task-brief.md, design.md | streams/stream-2.md |
| 开发流3（M1 流） | dev-3 | 1 | F12→F14→F15 | task-brief.md, design.md | streams/stream-3.md |
| 疑难攻关 | super-dev | 1 | F13（掩码双线注入）+ warm_sat native spike | design.md §M1 | streams/hard-problems.md |
| 门禁/审核 | qa | 1 | F02 基线、F06 重验、设计审核、各批定向门禁、总审 | 全部 | design-review.md, golden-reverify.md, qa-report.md, .design_ok, .qa_ok |
| 测试 | tester | 1 | M1 测试、oklch 切换回归、全量执行 | 任务书+各 stream 报告 | test-plan.md, test-report.md |
| 调研 | researcher | 1 | F18 DNG 评估、F16 许可素材 | task-brief.md | research/dng-sdk-review.md, research/license-inventory.md |
| 文档 | writer | 1 | F01 changelog 历史批、F17 依赖声明、F20 本轮批 | git log + 各报告 | streams/writer.md（changelog 改动直接进 docs/changelog.md） |
| 评审 | reviewer | 1 | M1 region_adjust 独立代码评审 | streams/stream-3.md + 代码 | reviews/m1-review.md |

注：qa 席位角色库已更名 QA-checker，本会话派遣沿用注册名 `qa`（下会话生效新名）。reviewer 用户降档 Flash——M1 评审深度兜底由 qa 总审承担。

## 工作流（与 dag.json 完全一致）
| # | 阶段 | 负责角色 | 串行/并行 | 输入 | 输出 | 完成判定 | 回流路径 |
|---|------|----------|-----------|------|------|----------|----------|
| 1 | 卡点①确认 | 队长+用户 | 串行 | task-brief/manifest/DAG | 批准记录 | 用户点头 | — |
| 2 | design.md 起草 | 队长 | 串行 | 三份侦察结论 | design.md | F-ID 全覆盖 | — |
| 3 | 设计审核+修复 | qa | 串行 | design.md | design-review.md + .design_ok | 门禁落盘 | 架构级问题→队长 |
| 4 | 设计确认（卡点②） | 用户 | — | design.md | 确认记录节 | plan 批准=预授权（全自主） | 有问题→修订→QA 重审 |
| 5 | Wave1 开局 | qa/dev-1/dev-2/dev-3/super-dev/writer/researcher | 并行（7 路） | design.md + .design_ok | F02/F03/F07/F12/F13/F01/F18 | 各流自验通过+基线绿 | 卡死 2 次→super-dev |
| 6 | Wave2 推进 | qa/dev-1/dev-2 | 部分并行 | Wave1 产出 | F06→F04→F05；F08→F09→F10→F11 | 定向门禁过 | bug 退原流 |
| 7 | Wave3 合流 | dev-3/tester/reviewer/researcher/writer | 并行 | Wave1/2 产出 | F14→F15；M1 评审；F16/F17 | reviewer 清单+qa 裁决 | 评审问题→dev-3 修 |
| 8 | 总审+修复 | qa | 串行 | 全部 | qa-report.md + .qa_ok | 门禁落盘 | 超范围→返工路由（≤2 轮） |
| 9 | 回归+提交 | tester+队长 | 串行 | .qa_ok | test-report.md + 分批 commit | 全量≥基线 | 红→退回 |
| 10 | 交付（卡点③） | 队长+用户 | — | 全部 | DELIVERY.md | 用户验收 | — |

## 文件域仲裁（dev 越界禁令配套，队长裁决）
1. `tests/regression/goldens/gate_cases.py`：dev-2（F08，Wave2）先、dev-3（F15，Wave3）后——DAG 时序互斥，禁止并行
2. `src/pixo/pipeline/loop.py`：super-dev 拥有 backend/state_extras 掩码区域（F13，Wave1 先行）；dev-3 拥有 `_DOTTED_PARAM_REGISTRY`/`_apply_decide_params` 区域（F14，Wave3）
3. `src/pixo/vision/**` 归 dev-1（F03/F04）；`configs/styles/**` + `render/modules/{hsl,split_tone,skin,color_cal,huesat}.py` 归 dev-2；`render/modules/region_adjust.py` + `render/pipeline/presets.py` + `render/params.py` 归 dev-3
4. F05 若走 native 化碰 refine/native 域：super-dev spike 结论后队长单独派单
5. 交叉需求一律报队长仲裁，不得先斩后奏

## 门禁定义
| 门禁文件 | 执笔 | 放行条件 |
|----------|------|----------|
| .design_ok | qa | 设计覆盖全部 F-ID、可测、风险识别；plan 批准=用户确认（卡点②预授权） |
| .qa_ok | qa | 需求逐条核对、测试证据齐全、遗留分级处置 |
| F10 专项门禁 | qa | F08 金样本先行落位 + 存量卡逐位不变断言 + RAW 金样本复跑绿 + 5 缺省断言修订 |
| M1 专项门禁 | qa | 全 stage 指纹缓存正确 + preview/export 双线掩码有效 + 缓存失效测试 |

## 返工上限
2 轮（超限三出口：降范围 / 记技术债 / 请示用户）

## 用户确认
- 2026-09-07：花名册+工作流已批准（卡点①）；全自主推进预授权卡点②
