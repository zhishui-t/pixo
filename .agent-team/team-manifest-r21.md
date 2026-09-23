# 团队花名册（team-manifest）— Pixo 第二十一轮（R21）：闭环插电

> 队长 2026-09-08 拟定；卡点①确认物。角色库：`~/.zcode/agents/`（注册名以角色文件 frontmatter `name` 为准）。
> （R9 花名册已归档为 `team-manifest-r09.md`）

## 任务

把 `SinglePhotoLoop` 闭环接进服务层生产路径（F01~F05），让真 RAW 经 HTTP 入口走通「测量→决策→回写渲染→QC」，并落端到端门禁。

## 编制（5 席；缩编理由：M0 为接线类小步改造，无疑难攻关、无前端、无需成文报告）

| 位置 | 角色（注册名） | 数量 | 负责（F-ID） | 输入文件 | 输出文件 |
|------|----------------|------|--------------|----------|----------|
| 调研 | `researcher` | 1 | 前期探索（服务层装配面摸底） | task-brief.md | `.agent-team/exploration-r21.md` |
| 开发流1（服务层） | `dev-1` | 1 | F01 → F02 | task-brief.md, design.md | `.agent-team/streams/r21-stream-1.md` |
| 开发流2（口径/签名） | `dev-2` | 1 | F03 → F04 | task-brief.md, design.md | `.agent-team/streams/r21-stream-2.md` |
| 测试 | `tester` | 1 | F05（E2E 门禁）+ 全量回归 | 任务书 + 两流报告 | `.agent-team/test-plan-r21.md`, `.agent-team/test-report-r21.md` |
| 门禁/审核 | `QA-checker` | 1 | 设计审核 + 交付总审 + 门禁执笔 | 全部 | `.agent-team/design-review-r21.md`, `.agent-team/qa-report-r21.md`, `.design_ok`, `.qa_ok`, `.r21_ok` |

**未上场**：`super-dev`（无疑难题，卡死 2 次时随时补派）、`dev-3`、`reviewer`、`writer`（本轮 changelog 由队长收尾）。
**模型档位**：角色库固化（dev-1/dev-2/tester/researcher = GLM-5.3-Flash max；QA-checker = GLM-5.3 max）。实际生效情况记入 `DELIVERY-R21.md`。

## 工作流（与 dag.json 完全一致）

| # | 阶段 | 负责角色 | 串行/并行 | 输入 | 输出 | 完成判定 | 回流路径 |
|---|------|----------|-----------|------|------|----------|----------|
| 1 | 卡点①确认 | 队长 + 用户 | 串行 | task-brief / manifest / DAG | 批准记录 | 用户点头 | 增删席位 → 改 manifest 重呈 |
| 2 | 前期探索 | `researcher` | 串行 | task-brief.md | exploration-r21.md | 装配面/契约/语料路径结论落盘且有来源 | 资料不足 → researcher 补探 |
| 3 | 设计 | 队长 | 串行 | exploration-r21.md | design-r21.md | F01~F05 全覆盖 + 接口约定 + 风险 | — |
| 4 | 设计审核 + 修复 | `QA-checker` | 串行 | design-r21.md | design-review-r21.md + `.design_ok` | 门禁落盘 | 架构级/需求级问题 → 队长（≤2 轮） |
| 5 | 设计确认（**卡点②**） | 用户 | — | design-r21.md | design 确认记录节 | 用户点头 | 有问题 → 修订 → QA 重审 → 再确认 |
| 6 | 开发 | `dev-1` / `dev-2` | **并行**（2 流） | design-r21.md + `.design_ok` | streams/r21-stream-1.md / -2.md | 各流自验通过（定向测试绿） | 卡死 2 次 → `super-dev` |
| 7 | 测试 | `tester` | 串行（两流完成后） | 任务书 + 两流报告 | test-plan-r21.md + test-report-r21.md | F01~F05 均有**带命令输出**的运行证据；全量 ≥1533 绿 | bug → 退回原开发流 → 回归 |
| 8 | 总审 + 修复 | `QA-checker` | 串行 | 全部 | qa-report-r21.md + `.qa_ok` + `.r21_ok` | 门禁落盘 | 超修复范围 → 返工路由（≤2 轮） |
| 9 | 提交 + 交付（**卡点③**） | 队长 + 用户 | 串行 | `.qa_ok` + `.r21_ok` | commit + changelog + DELIVERY-R21.md | 用户验收 | — |

## 文件域仲裁（越界禁令配套，队长裁决）

1. **`src/pixo/service/**` 归 `dev-1`**（runtime.py / app.py）。`dev-2` **不得改 service 层**；F03 的公共 API 由 `dev-2` 在 `pipeline/` 侧提供，接线由 `dev-1` 调用。
2. **`src/pixo/pipeline/loop.py` 归 `dev-2`**（`_metrics_for_decide` 提公共、评分器签名适配）。`dev-1` 如需改动，先报队长仲裁。
3. **`src/pixo/pipeline/batch.py`、`src/pixo/render/geometry/smart_crop.py`、`src/pixo/vision/measure.py` 归 `dev-2`**（F03/F04 关联面）。
4. **新增测试文件各自建**：`dev-1` → `tests/integration/test_auto_loop_api.py`；`dev-2` → `tests/unit/test_metrics_for_decide_public.py`、`tests/unit/test_scorer_adapter_callable.py`；**谁都不改对方测试文件**。
5. **`tests/` 存量断言**：只有 `tester` 可在测试阶段做必要修订，且须在 test-report 中逐条说明理由。
6. `docs/`、`configs/`、`resources/`、`frontend/` 本轮**只读**（队长收尾时写 changelog）。
7. 交叉需求一律报队长仲裁，不得先斩后奏。

## 门禁定义

| 门禁文件 | 执笔 | 放行条件 |
|----------|------|----------|
| `.design_ok` | `QA-checker` | 设计覆盖 F01~F05、接口与契约明确、风险已识别；**另需用户卡点②确认后才进开发** |
| `.qa_ok` | `QA-checker` | 需求逐条核对、测试证据（命令+输出）齐全、遗留问题已分级处置 |
| `.r21_ok` | `QA-checker` | 全量回归 ≥1533 passed / 0 failed + 金样本 gate 零漂移 + 真 RAW 闭环实证；含审核人 / 覆盖 F-ID / ISO 时间戳 / 结论 |

## 返工上限

2 轮（超限三出口：降范围 / 记技术债 / 请示用户）

## 用户确认

- 2026-09-10：范围=M0（F01~F05）、人马=DSH 原生 agent-team 角色、CR-14 立即推送 —— 已确认（Clarify 轮）
- 2026-09-10：**花名册 + 工作流 + DAG 已批准（卡点①通过）**；随后派 `researcher` 进入第 2 阶段探索
