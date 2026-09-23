# 任务书（task-brief）— Pixo 第九轮战役

> 队长 2026-09-07 拟定；卡点①确认物。用户已批准（见文末确认记录）。

## 目标
一战清偿四大方向：**收口 9 月批次 + 彻底清债（FairFace/gsam 删除）× oklch 渐进切默认（第一批 hsl+split_tone）× M1 掩码驱动渲染落地（region_adjust）× 发布合规包**，外加 RAW 金样本团队重验关闭挂起决策。全程全自主推进（用户预授权卡点②）。

## 背景与现有材料
- 仓库 `K:\work\project\pixo`，工作树干净（master 与 origin 同步），最后活动 2026-09-05 上午（t64 HSM→OKLCh 接线收口）。
- 自研渲染路线图三阶段已全部兑现（阶段一 QA GO / 阶段二终审 GO / 阶三首块交付）。
- 最新全量测试存证：09-04 QA 终审 **1231 passed / 4 skipped / 1 xfailed**；09-05 后 4 个提交无全量存证。
- 关键评估报告（设计输入）：
  - `.artifacts/oklch_default_eval.md`（t52）— oklch 切默认"三道前置修补 + 分 stage 渐进"结论
  - `.artifacts/hsm_oklch_eval.md` — t64 验收报告（54 张语料，两域分歧 median 10.89 ΔE）
  - `.artifacts/gate_report.md` — gate 17 features 现状
- 技术债台账 `docs/tech_debt.md`（挂起：#2/#3/#4/#7/#12/#13.2-13.4）。
- RAW 语料：本机 `D:\tmp\pixo_t108\samples.json`（6 样本，不入库）。
- 侦察报告三份（队长探索阶段产出）：oklch 链路 / M1 接线点 / 清债调用点——结论已融入 design.md。

## 范围（功能清单）
| F-ID | 功能 | 优先级 | 备注 |
|------|------|--------|------|
| F01 | changelog 补写 08-27~09-05 历史批（约 29 commit） | 必须 | writer；格式沿 docs/changelog.md 惯例 |
| F02 | 09-05 提交后全量测试基线存证 | 必须 | qa；结果落 .agent-team/ 与 .artifacts/ |
| F03 | FairFace 彻底移除 | 必须 | dev-1；删除面：person.py/health.py/__init__/manifest+3 测试 |
| F04 | gsam 彻底移除 | 必须 | dev-1；DEFAULT_ROUTE 兜底改零掩码降级+warning；torch extras 视引用收缩 |
| F05 | lr_baseline float 化处置 | 应有 | dev-1 调查启用面→float/native/记债三选一给证据 |
| F06 | RAW 金样本团队重验 | 必须 | qa；gate_golden compare 4 默认路径×6 样本，出独立报告；**在 F10 之前完成** |
| F07 | oklch 前置修补 a：存量 23 卡显式钉 hsv | 必须 | dev-2；含 test_film_cards_oklch 不变量改写 |
| F08 | oklch 前置修补 b：gate 缺省分派 case（17→18）+ 存量卡全管线 golden | 必须 | dev-2；gate_cases.py |
| F09 | oklch 前置修补 d：patch_protocol band 归属同源化 + canonical 透出确认 | 必须 | dev-2 |
| F10 | oklch 第一批切换：hsl+split_tone default_params→oklch | 必须 | dev-2；最高危项；5 缺省断言修订+存量卡逐位不变+RAW 金样本复跑 |
| F11 | skin+colorcal 意图级 A/B 证据 | 应有 | dev-2；只出证据不切换（观察周期） |
| F12 | region_adjust stage 模块 | 必须 | dev-3；order 56-59，DOMAIN_GAMMA_RGB，默认 enabled=False |
| F13 | 掩码通道 preview/export 双线注入 | 必须 | super-dev；spike 先行；堵 RawRenderBackend.render_full/export 无 state_extras 缺口 |
| F14 | decide region.* 接线 | 必须 | dev-3；_DOTTED_PARAM_REGISTRY+enabled 联动+指标键注册+首版规则 |
| F15 | M1 验收资产 | 必须 | dev-3+tester；gate case（时序在 F08 后）、harness、README |
| F16 | THIRD_PARTY_NOTICES.md 编制 | 应有 | researcher 素材+writer 成文 |
| F17 | scipy/PyYAML 可选依赖声明 | 应有 | writer；pyproject/requirements |
| F18 | DNG SDK clean-room 复审评估 | 应有 | researcher；产出评估+处置建议（法律判断，不重写代码） |
| F19 | 感知质量门禁（#7）评估+提案 | 可选 | 只出评估与提案，不实施 |
| F20 | changelog 本轮批次 | 必须 | writer；收尾 |

## 非目标（本次明确不做）
- skin/colorcal 的 oklch 缺省切换（等意图级 A/B + 观察周期）
- 感知质量门禁的实施（#7 只出提案）
- DNG SDK clean-room 重写（#2 只出评估）
- tech_debt #13.3 ±1EV 压力实验 / #13.4 低频加权（P3 不动）
- LLM env 三件套相关 e2e（用户未提供）

## 约束
- 技术栈：Python（src/pixo src-layout）+ FastAPI + 前端 Vite/TS；native MinGW DLL（build.bat）
- 风格/规范：沿用仓库既有约定（stage 注册制/金样本 gate/tech_debt 台账/changelog 惯例）
- 平台/环境：Windows Git Bash；MinGW `D:\code\mingw64`；测试入口 `python -m pytest tests -q -m "not e2e"`
- 额度纪律：dev/tester/researcher/writer = Flash；只跑定向测试，全量回归队长统一执行
- 文件域互斥：见 team-manifest.md「文件域仲裁」节

## 完成标准（可验证）
- F01~F20 按上表完成（应有/可选项允许降级为记债，须在 DELIVERY.md 说明）
- 全量回归 ≥1231 passed 基线不降（F10 若涉金样本基线重生成由队长单点执行并留证）
- qa 总审通过（.qa_ok 落盘）：需求逐条核对+测试证据+遗留分级
- 分批 commit（依赖序）+ changelog 本轮批 + DELIVERY.md 交付呈报

## 用户确认
- 2026-09-07：任务书+花名册+工作流+DGM 计划已批准（卡点①，ExitPlanMode 通过）
- 2026-09-07：执行节奏=全自主推进（本次 plan 批准即预授权卡点②；卡点②呈报留档 design.md「用户确认记录」节）
- 2026-09-07：金样本 reviewer 终审=本轮团队重验（F06）
- 2026-09-07：本轮方向=四方向全选（收口清债/oklch/M1/合规包）
