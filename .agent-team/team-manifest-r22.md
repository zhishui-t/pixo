# 团队花名册（team-manifest）— Pixo 第二十二轮（R22）：清完剩余欠账

> 队长 2026-09-10 拟定；卡点①确认物。角色库 `~/.zcode/agents/`（注册名以 frontmatter `name` 为准）。
> （R21 花名册已归档 `team-manifest-r21.md`）

## 任务

清完 R21（M0）之外的 9 条 CR + 台账：#干净（CR-06/07）× 风格化（CR-09/10）× 验收底座（CR-11/08/12/13）× 几何正确性（#17）× 台账治理（CR-15）。

## 编制（9 席；满编理由：本轮跨「指标/渲染内核/前端/几何/文档」五个域，且含两项高危改动需独立评审）

| 位置 | 角色 | 数量 | 负责（F-ID） | 输入 | 输出 |
|------|------|------|--------------|------|------|
| 调研 | `researcher` | 1 | 探索（denoise 算法面/RP-CCM 证据/QC 内部/compose 几何/风格注入面） | task-brief.md | `.agent-team/exploration-r22.md` |
| Wave1 机制流 | `dev-1` | 1 | F01（CR-06 键宇宙）+ F06（CR-11 多轴 QC 软告警，独占 `pipeline/loop.py`） | design-r22.md | `.agent-team/streams/r22-stream-1.md` |
| Wave1 可观测流 | `dev-2` | 1 | F03（CR-08 静默降级可观测）+ F08（CR-13 skin 一致性/金样本） | design-r22.md | `.agent-team/streams/r22-stream-2.md` |
| Wave2 内核攻关 | `super-dev` | 1 | F02（**CR-07 亮度降噪**：spike → native 内核 + Python 回退 + A/B） | design-r22.md §降噪 | `.agent-team/streams/r22-hard.md` |
| Wave2 风格流 | `dev-3` | 1 | F04（CR-09 LUT 注入 + 前端简约选择器）+ F05（CR-10 场景预设） | design-r22.md | `.agent-team/streams/r22-stream-3.md` |
| Wave3 几何流 | `dev-1` | 1 | F09（**#17 compose px→相对坐标归一化** + legacy 开关 + 用例有意翻转） | design-r22.md §几何 | `.agent-team/streams/r22-stream-1b.md` |
| Wave3 裁决流 | `dev-2` | 1 | F07（CR-12 RP-CCM 切换或否决）+ F10（台账 #3/#7/#10/#12） | design-r22.md | `.agent-team/streams/r22-stream-2b.md` |
| 独立评审 | `reviewer` | 1 | F02 与 F09 的代码评审（只诊断不动刀） | 两流代码+报告 | `.agent-team/reviews/r22-review.md` |
| 测试 | `tester` | 1 | 各波定向 + 降噪 A/B（≥20 张高 ISO）+ 几何一致性门禁 + 全量回归 | 任务书+各流报告 | `.agent-team/test-plan-r22.md`、`test-report-r22.md` |
| 门禁/审核 | `QA-checker` | 1 | 设计审核 + 交付总审 + 门禁执笔 | 全部 | `design-review-r22.md`、`qa-report-r22.md`、`.design_ok`、`.qa_ok`、`.r22_ok` |

**未上场**：`writer`（用户文档由 dev-3 顺手写进 `docs/`；changelog 归队长）。
**模型档位**：角色库固化（dev-1/2/3 = GLM-5.3-Flash max；super-dev/QA-checker/reviewer = GLM-5.3 max；tester/researcher = GLM-5.3-Flash max）。实际生效情况记入 `DELIVERY-R22.md`。

## 工作流（与 dag.json 一致）

| # | 阶段 | 角色 | 串/并 | 输入 | 输出 | 完成判定 | 回流 |
|---|------|------|-------|------|------|----------|------|
| 1 | 卡点①确认 | 队长+用户 | 串行 | task-brief/manifest/DAG | 批准记录 | 用户点头 | 改席位/范围 → 重呈 |
| 2 | 探索 | `researcher` | 串行 | task-brief.md | exploration-r22.md | 结论可溯源（file:line / 命令） | 资料不足 → 补探 |
| 3 | 设计 | 队长 | 串行 | exploration-r22.md | design-r22.md | F01~F10 全覆盖 + 文件域冻结 | — |
| 4 | 设计审核+修复 | `QA-checker` | 串行 | design-r22.md | design-review-r22.md + `.design_ok` | 门禁落盘 | 架构级 → 队长（≤2 轮） |
| 5 | **卡点②** | 用户 | — | design-r22.md | 确认记录节 | 用户点头 | 修订 → QA 重审 → 再确认 |
| 6 | Wave1 开发 | `dev-1`/`dev-2` | 并行 | design + `.design_ok` | streams/r22-1 / -2 | 定向测试绿 | 卡死 2 次 → super-dev |
| 7 | Wave2 开发 | `super-dev`/`dev-3` | 并行 | Wave1 产出 + design | streams/r22-hard / -3 | spike 结论 + 定向绿 | 同上 |
| 8 | Wave3 开发 | `dev-1`/`dev-2` | 并行 | Wave2 产出 | streams/r22-1b / -2b | 定向绿（几何一致性断言） | 同上 |
| 9 | 独立评审 | `reviewer` | 串行 | Wave2/3 代码 | reviews/r22-review.md | 清单交付（无门禁权） | 问题 → 原流修 → 复评 |
| 10 | 测试 | `tester` | 串行 | 全部流报告 | test-plan/report-r22.md | 每条 F 有运行证据 + A/B + 全量 ≥1574 | bug → 原流 |
| 11 | 总审+签章 | `QA-checker` | 串行 | 全部 | qa-report-r22.md + `.qa_ok` + `.r22_ok` | 门禁落盘 | 超范围 → 返工（≤2 轮） |
| 12 | 提交+交付 | 队长+用户 | 串行 | `.r22_ok` | commit + changelog + DELIVERY-R22.md | 用户验收（卡点③） | — |

## 文件域仲裁（**设计阶段冻结为准**，以下为初版约束）

1. `src/pixo/pipeline/loop.py`：**Wave1 归 `dev-1` 独占**（键注册面 + QC 软告警面）；其他人的改动一律走队长仲裁。
2. Wave3 的 `src/pixo/render/modules/compose.py`、`render/pipeline/region_masks.py`、`render/geometry/**` 归 `dev-1`；`dev-2` 同时段只碰 `render/core/rp_ccm.py`、`render/dcp.py`、`docs/tech_debt.md`。
3. `src/pixo/render/native/**` + `_native/*.dll`（含版本号）+ `render/modules/reshape.py`（DenoiseStage）归 `super-dev`；**DLL 版本 +1 与快照对拍**由其执行，产物入库由队长确认。
4. 前端 `frontend/src/**` 归 `dev-3`（风格选择器）；**不得**改 `App.tsx` 路由结构以外的大件，遵循简约/移动优先。
5. `docs/` 中 `changelog.md` 归队长；`tech_debt.md` 由 `dev-2` 在 Wave3 按 design 条目化更新（队长终审）。
6. 测试文件：各开发流只新建自己的测试文件；`tests/regression/**` 归 `tester`（含 #17 用例的有意翻转须 tester 与 dev-1 在 design 指定下协同，串行执行）。
7. 交叉需求一律报队长仲裁，不得先斩后奏。

## 门禁定义

| 门禁文件 | 执笔 | 放行条件 |
|----------|------|----------|
| `.design_ok` | `QA-checker` | 设计覆盖 F01~F10、文件域冻结、风险识别；**另需卡点②用户确认** |
| `.qa_ok` | `QA-checker` | 需求逐条核对、证据齐全（命令+输出）、遗留分级处置 |
| `.r22_ok` | `QA-checker` | 全量 ≥1574 passed / 0 failed + 金样本零漂移（或授权重生成后全绿）+ 降噪 A/B 报告 + 几何一致性断言 |
| 降噪专项 | `QA-checker` | **默认关**下金样本零漂移；A/B ≥20 张满足 `noise_ratio`↓≥30% 且 `detail_score`↓≤10%；DLL 版本门控与新旧快照对拍 |
| 几何专项（#17） | `QA-checker` | 同归一化参数跨 tier 相对裁剪窗一致；原失配用例**有意翻转重写**并留有旧行为记录 |

## 返工上限

2 轮（超限三出口：降范围 / 记技术债 / 请示用户）

## 用户确认

- 2026-09-10：用户指令「继续把没修完的修完」
- 2026-09-10：**卡点① 通过**（用户选项确认）：范围=全要（含 F09 #17 几何归一化）；F02=native 内核 + Python 回退；F04=后端 + 前端简约选择器。随后派 `researcher` 进入第 2 阶段探索。
