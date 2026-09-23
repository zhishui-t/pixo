# 花名册 + 工作流 · R31 RAW 打开色彩对齐 DNG 渲染（卡点②确认物）

日期：2026-09-22 ｜ 来源：Prism delivery 模板（用户点名）+ skill 流水线合并 ｜ 适配：数据/测量轮裁剪

## 编制（模板 7 位 → 本轮 5 位）

| 岗位 | 承担角色 | 来源 | 核心契约 | 负责 F-ID | 输入 | 输出 |
|---|---|---|---|---|---|---|
| 队长 | 主会话 | — | 需求/仲裁/整合/验收，不代工 | 全局 | task-brief.md | design.md / DELIVERY |
| dev-1 | `dev`（WorkBuddy 引擎） | 模板 | **DNG SDK 参照发生器**：修编译、出 dng_validate 渲染 CLI 壳（口径可复现：WB/profile/输出空间参数化） | F1 | design.md | dng_validate.exe + 渲染脚本 + 自测报告 |
| dev-2 | `dev`（WorkBuddy 引擎） | 模板 | **RT-cli 参照臂 + 测量管线 + 矫正执行**：三臂对照 harness、判据裁决、超阈重拟合 default_look | F3/F4 | design.md | 测量报告 + 矫正 diff + 自测报告 |
| junior-dev | `junior-dev`（宿主原生） | 模板 | **环境与批转**：winget 装 DNG Converter、NEF→DNG 子样本批转、GPLv3 许可证落地（LICENSE + pyproject）、报告排版推送 | F2 + 前置 | design.md | 批转产物 + LICENSE + 报告草稿 |
| reviewer | `reviewer`（WorkBuddy 引擎） | 模板 | **两道门禁**：design 审核（.design_ok）+ 代码/数据 diff 检视（含测量口径公平性） | 门禁 | design.md / 各 diff | .design_ok + 检视意见清单 |
| tester-whitebox | `tester-whitebox`（宿主原生） | 模板 | **回归与复现**：全量 pytest + gate 金样本零漂移 + 测量结果抽片复现 | F5 | 矫正 diff + 报告 | .qa_ok + 白盒测试证据 |

**裁剪说明**（呈用户）：frontend-dev 裁（零界面任务）；tester-blackbox 裁（无 E2E/视觉面；需求侧验证由三臂测量本身+reviewer 口径检视承担）。如需保留请卡点②提出。

## 工作流（模板九阶段 × skill 四卡点合并；执行口径=用户 2026-09-17 裁定：卡点③设计确认已取消，.design_ok 即进开发）

| # | 阶段 | 负责角色 | 串/并 | 输入 | 输出 | 完成判定 | 回流 | 来源 |
|---|---|---|---|---|---|---|---|---|
| 1 | 需求收集/定稿 | 队长 | 串行 | 用户输入+现状 | task-brief.md | **用户批准（✅ 2026-09-22）** | — | 模板=skill |
| 2 | 设计 | 队长 | 串行 | task-brief | design.md（测量口径/判据/接口/风险预案） | 覆盖全部 F-ID | 歧义回卡点① | 模板 |
| 3 | 设计审核 | reviewer | 串行 | design.md | 意见清单 → .design_ok | 无 blocker（≤2 轮） | 驳回→队长改 | 模板；skill 卡点③按用户裁定取消用户确认环节 |
| 4a | GPLv3 落地 + Converter 安装批转 | junior-dev | 并行① | design.md | LICENSE/pyproject/批转产物 | 批转子样本可被 dng_validate 消费 | 失败→备选路径 | skill 开发段 |
| 4b | DNG SDK 编译 | dev-1 | 并行① | design.md | dng_validate.exe+渲染壳 | 首张 DNG 参照图渲染成功 | 卡住→最小渲染壳备选 | 模板阶段5 |
| 4c | RT-cli 参照臂 | dev-2 | 并行① | design.md | RT 臂脚本+口径记录 | n=3 试跑出数 | — | 模板阶段5 |
| 5 | 三臂测量 n=48 | dev-2 | 串行 | 4a+4b+4c | 对照分布报告 | 分位数表齐+口径记录 | 样本故障→跳片留痕 | 本轮核心 |
| 6 | 矫正裁决执行 | dev-2 | 串行 | 阶段5 | 重拟合 diff（或达标结论） | 判据裁决落地+回归绿 | 超判据争议→队长仲裁 | 预授权 |
| 7 | 代码/数据检视 | reviewer | 串行 | 全部 diff | 检视意见 | 无 blocker；≤5 行小修当场改 | blocker→对应 dev | 模板阶段6 |
| 8 | 回归与复现 | tester-whitebox | 串行 | diff+报告 | .qa_ok+测试证据 | 全量 0 failed+金样本零漂移+抽片复现一致 | 缺陷→dev | 模板阶段7/8 合并（白盒轨） |
| 9 | 报告推送 | junior-dev | 串行 | 全产物 | R31 报告+changelog+push | 用户仓库更新 | — | 模板阶段9 前置 |
| 10 | **交付验收（卡点④）** | 队长+用户 | 串行 | 全产物 | DELIVERY-R31.md | **用户确认交付** | 遗留→下轮/技术债 | 模板=skill |

**门禁**：.design_ok 前 dev/junior 不动工；.qa_ok 前不出 DELIVERY；返工上限 2 轮/节点。
**风险预案**（design.md 详述）：Converter 静默装失败→GUI/缩样本；dng_validate 残余编译错→自写最小渲染壳；渲染过慢→小尺寸口径。
