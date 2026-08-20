# 长安小队 v2 配置单（照抄进 Agents Team GUI）

## 为什么会失败（三分钟版）
1. **主会话工具失活**：`list_agents`/`agent_teams_*` 报 agents service inactive，我这边派不了任务；这是插件注入问题，不是小队问题。
2. **一轮塞了四件事**：计划+审核+实现+QA 一个 run 做完，范围过大；实现还没开始 run 就被 cancel。
3. **Planner failed validation**：GUI 自动落到 deterministic workflow，任务被平铺给每个成员，拆解失败。
4. **没有启用质量门**：上一轮 GUI 显示的小队没有 qualityGate（reviewer/maxRounds），所以审核不是“只审 1 轮”，而是成员自由发挥 + stop error。
5. **门禁太重**：QA 一上来跑 3 分钟全量测试，执行窗口被浪费；迁移起点只需 29 个相关用例。
6. 方案本身没问题，且已修好：`rawlab/docs/RAWLUX_NATIVE_MIGRATION_PLAN.md` v2（commit de1d20e）。

## GUI 里要做的配置（按顺序）
### A. 会话预设（所有成员 max 思考）
- 发起小队 run 前，把当前会话的预设切到 max reasoning（插件 schema 没有 per-agent effort 字段；成员由预设/父会话继承）。
- 成员模型全部 opencode-go / deepseek-v4-flash（你之前定的 v4-flash）。

### B. 新增 1 个审核成员
- 成员名：`审核员·严`
- provider: `opencode-go`
- model: `deepseek-v4-pro` **(审核者例外: 用 v4-pro; 其余成员仍 v4-flash)**
- 角色提示词（直接粘）：
  “你是长安小队的质量审核员。只读审核，不改实现代码。每次审核只做 1 轮：
   1) 按验收门逐条真实运行测试命令；2) 只输出 PASS/FAIL + 证据数据 + 修复建议；
   3) FAIL 时把建议交给修复成员，不要自己修；4) 不重复审已 PASS 的项；5) 用最大思考量。”
- toolScope：deny: `["str_replace_editor", "bash"]` 会连验证都做不了；**建议 allow: `["bash"]`, deny: 编辑类工具**（按 GUI 快捷目录实际名称勾选；审核员需要跑 pytest 但不需要写文件）。

### C. 小队「长安」设置
- 成员：保留现有成员 + 新加 `审核员·严`。
- executionMode: `serial`
- memberSelectionMode: `all`
- failurePolicy: `stop`
- activationMode: `manual`（不要 always，避免又自动重复派发）
- responseMode: `foreground`
- planningContext: `full`
- plannerMaxTokens: `4000`

### D. 质量门（关键）
- enableQuality: ON
- reviewerAgentId: `审核员·严`
- repairAgentId: `十九`（backend/实现成员；若你希望修复的是小鑫，就选小鑫）
- maxRounds: **1**
- criteria（直接粘）：
  “审核只跑 1 轮。按当前 run 的任务验收门检查：相关 pytest 子集全绿、grep rawlab in rawlux==0、
   旧 import 恒等可用、无未提交的越权改动。FAIL 时写明单条根因与最小修复范围。”

### E. 不要再派“整个迁移”
按下面 5 个 run 派（每个 run 只一件事、一个门）：
| run | 范围 | 验收门 |
|---|---|---|
| R1 | A2+A3+A4: rawlux/core/{curves,color,tone,warp,io,lut3d} 原生 | test_curves/test_color_math/test_lut 全过；grep rawlab in rawlux==0 |
| R2 | A4.5: rawlab dcp/engine 叶子模块反向 shim | 逐 shim 旧名 import 可用 + is 恒等 + 29 相关测试 |
| R3 | B: core/pipeline/stages → rawlux/pipeline + rawlux/modules | test_pipeline/test_pipeline_config/test_intents 全过 |
| R4 | C: render_base/api/intents → rawlux/pipeline + rawlux/api | test_renderer_adjust 全过；render_preview 指向 rawlux/presets |
| D | 终验四件套 | 全量 ≥597；regression 11；ablation 5≤5e-5；原生冒烟 |

每个 run 通过后 git commit；失败就停在该 run，修复后再往下。

## 当前稳定基线
- HEAD `de1d20e`（计划 v2），工作树有未提交的 `rawlux/__init__.py` 惰性修复 + `rawlux/core/calibration.py` 原生草稿 + `rawlux/calibration_data/`。
- 全量基线：597 passed, 7 deselected。
