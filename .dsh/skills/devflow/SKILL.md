---
name: devflow
description: DevFlow 双模型协同开发工作流:深度探索→可行性分析→预研→四份设计文档(固定模板)→任务规划(依赖图)→flash 并行开发→单元测试门与升级链→pro 审查。
whenToUse: 需要按规格驱动方式规划并开发一个功能或项目时。
---

# DevFlow 双模型协同开发工作流

你是主 Pro 调度模型,按以下阶段推进,不确定的技术点先派人预研,依赖未满足的任务不得派发。

## 阶段
1. 深度探索: devflow_explore 派多个 flash 子代理分域并行探查现有项目,pro 汇总。
2. 可行性分析: 按固定模板撰写 00-feasibility.md;不确定点用 devflow_research 派预研子代理。
3. 四份设计文档: 01-functional-design.md、02-software-design.md、03-specification.md、04-task-plan.md,必须遵循 planDir/templates/ 下的固定模板逐节填写;可用 devflow_design 派 pro 起草后审核定稿;定稿后经 plan 模式提交用户审批。
4. 任务规划校验: devflow_plan 校验任务图并生成拓扑分层 waves。
5. 派发开发: devflow_dispatch 按依赖调度(ready=就绪批 / all=整图逐波);flash 子代理并行实现,每个任务完成后由验证 agent 跑 testCommand 测试门;失败自动 flash 修复重试、仍失败升级 pro。
6. 审查: devflow_review 派 pro 子代理代码检视输出 findings,再派发修复任务。

## 模型分工
- pro: 探索汇总、可行性研判、设计定稿、调度、审查、困难任务与升级修复。
- flash: 探索/预研/开发/验证的并行子代理。

## 产物目录
- 规划产物在 planDir(默认工作区同级 dsh-plan-task);固定模板在 planDir/templates/。
- 开发与测试在 workdir(默认会话工作区)。

## 原则
- 依赖未满足禁止派发;任务需补写单元测试;测试门是验收依据。
