# 花名册 + 工作流 · R32 RT 组件移植战役（卡点②确认物，v2 串行版）

编制（5 位；frontend-dev/tester-blackbox 不需要——纯引擎/native 线）：

| 岗位 | 引擎 | 职责 |
|---|---|---|
| 队长 | 主会话 | 需求/设计 T1/仲裁/验收 |
| dev-1 | WorkBuddy | **串行主攻**：T1 RCD/AMaZE 移植 → T2 DCP 对照 → T3 胶片接入（同一实例/会话贯穿，上下文不丢） |
| junior-dev | 宿主原生 | RT 源码 clone（K:/work/project/rawtherapee）+ native 工具链 bring-up（先用 D:\code 工具链重编现有 DLL 验证链路）+ 报告 |
| reviewer | WorkBuddy（复用 R31 会话 wbdy-651119f0-3ba） | 每步设计/代码双门禁（.design_ok / 检视），GPL 出处标注核查 |
| tester-whitebox | 宿主原生 | 每步回归（全量+金样本零漂移）+ T1 A/B 数据复算 |

工作流（每步循环）：队长设计 → reviewer 门禁 → dev-1 实现+自测 → reviewer 检视 →
tester 回归 → 推送分支 → 下一步。T1→T2→T3 串行；返工上限 2 轮/步。
门禁：.design_ok 前不动码；.qa_ok 前不进下一步；master 不动（全在 render-core-integration）。
