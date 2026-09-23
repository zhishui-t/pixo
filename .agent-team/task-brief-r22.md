# 任务书（task-brief）— Pixo 第二十二轮（R22）：把 M0 之外的全部欠账清完

> 队长 2026-09-10 拟定；卡点①确认物。（R21 任务书已归档 `task-brief-r21.md`）
> 依据：`docs/R21_CHANGE_REQUESTS.md` 中**尚未开工的 9 条 CR** + `docs/tech_debt.md`。
> 用户指令原文：「继续把没修完的修完」。

## 目标

把 R21（M0 闭环插电）之外的剩余欠账**全部清完**，让三个产品目标「通透 / 干净 / 风格化」各自有完整落地路径：
- **干净** → CR-06 噪声指标入决策键宇宙 + CR-07 亮度降噪落地（唯一能力性缺口）
- **风格化** → CR-09 风格卡 LUT 生产注入 + CR-10 场景预设（含前端简约选择器）
- **验收与工程底座** → CR-11 多轴 QC、CR-08 静默降级可观测、CR-12 RP-CCM 裁决、CR-13 skin 金样本、CR-15 台账治理（含 #3 许可、#7 感知门禁、#12 公式守卫、#10 重编号、**#17 compose 跨分辨率**）

## 背景（R21 已交付的事实基线）

- 闭环已接生产：`POST /api/photos/{id}/auto-loop`（202+task）+ 11 条 `DEFAULT_RULES` 注入 + `pipeline/metrics.py` 公共指标 API + 美学 adapter 可调用契约 + F05 真 RAW 门禁。
- 全量回归基线（R21 终态）：**1574 passed / 0 failed**；金样本双路零漂移。
- `origin/master = a092d3a`（R21 四个提交已推）。
- 关键已知事实：
  - `DenoiseStage.wants()` 恒 `False`（`render/modules/reshape.py:113-134`）；真正在跑的是 `refine` 的色度降噪（无亮度降噪）。
  - `measure_sharpness` 已产 `noise_ratio`/`detail_score`（`vision/measure.py:298-306`），但未进决策键宇宙。
  - 风格卡唯一注入点 `apply_intents()`（`render/pipeline/intents.py:187`）在 `src/` 内零调用；`configs/styles/films/` 25 个 JSON；前端已有 `StyleAiPanel.tsx` 可复用。
  - native 链：源码 `src/pixo/render/native/src/*.cpp`，构建 `native/build.bat`，产物 `src/pixo/render/_native/pixo_render_native.dll`（620,886 B，DLL 1.6.0）。**新增内核须 DLL 版本 +1 并做新旧快照对拍**。
  - tech_debt **#17**：compose free 模式 x/y/width/height 为全画布像素 → 同参数跨分辨率取景不同、掩码落点错位可达 10% 画幅宽；现状由 `tests/unit/test_region_masks_channel.py::test_free_px_rect_cross_resolution_geometry_mismatch_recorded` **钉死失配行为**（清偿时该用例应**有意翻转重写**而非删除）。
  - 131 处 `except Exception`（`src/pixo`，R21 实测）。

## 范围（功能清单）

| F-ID | 功能 | 对应 CR | 优先级 | 备注 |
|------|------|---------|--------|------|
| F01 | 噪声/细节指标入决策键宇宙 + 噪声规则 | CR-06 | 必须 | `noise_ratio`/`detail_score` 展平 + 注册 |
| F02 | **亮度降噪落地**（native 内核 + Python 回退） | CR-07 | 必须 | **默认关**（A/B 裁决后才开）⇒ 不触发金样本漂移 |
| F03 | 关键路径静默降级可观测 | CR-08 | 必须 | 关键路径改 warning + 结构化 degraded 列表 |
| F04 | 风格卡 LUT 生产注入 + 前端选择器 | CR-09 | 必须 | 白名单限 `configs/styles/films`；前端**简约**（复用 StyleAiPanel） |
| F05 | 场景预设生产路径 | CR-10 | 应有 | `configs/styles/scenes.json` 6 预设 |
| F06 | 多轴 QC（软告警分级） | CR-11 | 必须 | 硬门禁仍只像素/溢出；美学不得作硬门禁 |
| F07 | RP-CCM 运行时切换或显式否决 | CR-12 | 应有 | 二选一，禁止悬置 |
| F08 | skin OKLab 一致性 + 金样本 | CR-13 | 应有 | 防双源失同步复发 |
| F09 | **compose 跨分辨率归一化** | CR-15/#17 | 必须* | *若用户在卡点①选择本轮做；含存量卡/参数迁移与 legacy 开关 |
| F10 | 台账治理（#3 许可、#7 提案、#12 维持、#10 重编号） | CR-15 | 应有 | #3 为发布前必收 |

## 非目标（本轮明确不做）

- 不重启架构、不改渲染既有算子的数值语义（除 F09 归一化与 F02 新增 stage 外）
- **不开启**任何新能力的生产默认值（降噪/LUT/场景/QС 新轴一律默认关或软告警，须数据裁决）
- 不做端到端 learned ISP；不改 `configs/color/calib_out/`（陈旧快照）
- 不引入新的第三方依赖（native 侧仅用既有 MinGW/CMake 链）

## 约束

- 技术栈：Python 3.12 / FastAPI / Vite+TS 前端 / MinGW C++ native（`native/build.bat`）
- 架构：`pipeline/` 不依赖 `service/`；native 内核须有 Python 等价位回退；DLL 版本门控
- 测试：新增代码必须有运行证据；**全量回归不得低于 1574 passed / 0 failed**；金样本 baseline 若需重生成**仅队长单点执行并留证**
- 纪律：小步快跑、改前先读现状、同一失败 2 次升级 `super-dev`、不提交 git（队长统一提交）
- 前端：简约、移动端优先（用户偏好；禁玻璃拟态/光斑/大量动画/列表式堆砌大卡片）

## 完成标准（可验证）

1. F01~F10（含用户卡点①选定的 F09 处置）全部交付，每条有「命令 → 输出 → 结论」证据
2. 降噪 A/B：≥20 张高 ISO 语料，`noise_ratio` 降 ≥30% 且 `detail_score` 降 ≤10%，且**默认关**下金样本零漂移
3. F09 若做：跨分辨率取景一致性有可判定断言（同一归一化参数在不同 tier 下相对裁剪窗一致），且 `test_free_px_rect_cross_resolution_geometry_mismatch_recorded` **有意翻转重写**
4. 台账 #3/#7/#10/#12 处置落 `docs/tech_debt.md`（#3 须给出可发布结论）
5. 全量回归 ≥ **1574 passed / 0 failed**；金样本 gate 零漂移（或按授权重生成后全绿）
6. `QA-checker` 总审签章 `.r22_ok`；`docs/changelog.md` 追加 R22 条目；`.agent-team/DELIVERY-R22.md`

## 用户确认

- 2026-09-10：用户指令「继续把没修完的修完」（R21 卡点③ 验收通过 + 要求继续清账）
- 2026-09-10：**卡点① 通过** —— 三项范围裁剪经用户在选项上确认：
  1. **范围 = 全要**，含 **F09（#17 compose px→相对坐标归一化）**，不另开一轮；
  2. **F02 降噪 = native 内核 + Python 等价位回退**（含 DLL 版本 +1 与新旧快照对拍）；
  3. **F04 = 后端注入 + 前端简约选择器**（复用 `StyleAiPanel`，不做列表式大卡片）。
- 2026-09-10：**执行机制确认** —— 用户问「是否官方内置小队」后决定「**不换，继续**」：R22 沿用
  `agent-team` skill + `~/.zcode/agents/` 角色库 + harness 原生 `subagent` 派单 + `.agent-team/` 黑板三卡点。
  事实澄清（队长核查）：本机 checkout（`D:\Program Files\deepseek`）**无 `packages/` 目录**（安装版），
  profile `web-fork` 的 `@deepseek-ai` 仅装 `dsh-toolkit`/`dsh-plugin-weave`/`dsh-client-*`/`dsh-host-apiproxy`
  —— **官方内置 agent-team 未安装**；已挂载的官方团队机制是 Weave 插件（`cordis.yml:530`，另一套）。
  机制切换问题留待 R23 专项处理（用户原有「下轮换官方内置」意向仍记录在案，未执行）。
