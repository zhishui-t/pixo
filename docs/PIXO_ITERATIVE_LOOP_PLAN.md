# Pixo 迭代式修图重构计划（Loop-Centric Refactor)

> 北极星: 修图是一个 **loop**, 所有模块参与其中 ——
> measure(vision+美学) -> decide(rules+LLM建议) -> render(core) -> qc -> 反馈再入环,
> 直到美学达标或触发终止; 不允许任何"一次渲染定终身"的单发路径。

## 依赖排序原则
零风险地基先行(B/E) -> 渲染单点化(A/D) -> 参数方言统一(C) ->
评分器接线(P1, 为规则提供触发指标) -> 规则包扩容(P2) -> LLM 转正(P3)。
**A 完成前不启动 P2 大规模规则**(否则每条规则需在 3 条渲染路径上验证)。

## Phase 0 地基清障 (~1 天)
| 项 | 动作 | 验证 |
|---|---|---|
| B 清退 shim | 全仓 grep 引用改直连后删除 16 个 <=8 行转发壳(decide×5/render.decide×2/render.state×4/meta×3/state×1) | import 图无转发层; 673 pass |
| E 规则单源 | configs/rules 为唯一源, 包内副本由脚本生成; 加 sha 一致性门禁测试 | 改 configs 未同步时测试红 |

## Phase 1 渲染内核收敛 (~2-3 天)
| 项 | 动作 | 验证 |
|---|---|---|
| A render_core | 抽单一 ctx 工厂(解码/state装配/缩放); api.render_preview_full / web.session / web.export 瘦身为缓存壳与编码壳 | 新 gate: 三入口同 RAW+params 输出逐位一致 |
| D native 可观测 | 统一 _native loader, 降级事件写 trace/metrics; PIXO_NATIVE=strict 下 CI bench 强制 native | strict 模式 bench 通过 |

## Phase 2 全模块进环 (~3-4 天) ★核心
| 项 | 动作 | 验证 |
|---|---|---|
| C ParamRef 统一 | 规则 YAML 直写 stage.param; 映射集中单模块+锁定单测(消灭 exposure_ev 方言与子串匹配) | 规则->参数端到端单测 |
| P1 评分器接线 | loop.measure 每轮附 7 维美学分(overall/lighting/color/quality); batch 选片换真评分器(Mock 仅作无 torch 回退) | trace 含每轮分数; batch TopN 不再来自 Mock |
| 终止/QC 升级 | check_termination 增美学达标/停滞判定; FINAL_QC = clip + dE预算 + aesthetic>=阈值 | 真实 NEF 多轮迭代轨迹可回放 |

## Phase 2.5 知识库充实·摄影四域 (已完成)
- 落地现状: configs/knowledge/ 四包 50 节点 37 边 (capture_post 12n4e / hue 14n11e / post2 9n9e / tone 15n13e);
  schema={nodes,edges}, node=id/type/label/keywords(3-6)/content(≤80字), edge=id/from/to/relation(策略|副作用|配套)/weight/content。
- registry 自动合并: pixo.know.registry 初始化即合并包内 data/ 与仓库 configs/knowledge/ 全部 *.json 入图谱
  (实测合并后 64 节点 46 边 = 内置 14 + 四包 50),
  query/suggest/agent_suggestion 及 to_decide_rules/to_decide_context 开箱可用, 新增知识包零代码接入。
- 接线规划: decide 规则命中时按关键词 query 图谱, strategy/side_effect 写进 reasons 让决策可解释;
  loop trace 记录引用的 node id 供回放审计; P3 时 RAG 检索结果注入 LLM prompt 作为决策上下文。
- 长期管道: 感知门禁 A/B 结论(达标与翻车参数对)自动沉淀为 evidence 边回写知识包, 知识库随闭环自增长。

## Phase 3 规则包扩容·体现"全参与" (~3 天)
- 通透包: haze 估计 -> dehaze/clarity; 色彩包: color 维低分 -> vibrance/split_tone;
  影调包: lighting 维 -> shadows/highlights/whites/blacks; 质感包: quality 维 -> denoise/sharpen。
- 遗留清偿: warmth_curve 分桶标定(0355 偏色)、曝光标定表升维 (med, wb_B)、高光 cap 与查表 EV 联合策略。
- 验证: 每条规则配最小样本 A/B(ab_vs_camera_thumb 纳入 harness, dE/裁切/美学分三预算)。

## Phase 4 AI 副驾转正 (~3-5 天)
- dsh.chat 占位 -> 真实 DSH 调用; LLM 读 metrics+评分轨迹, 按 prompts 既定协议输出参数补丁。
- decide 引擎转为护栏: 锁定/限幅/终止不可绕过; LLM 补丁必须通过 RuleEngine 校验方可 apply。
- 验证: 补丁校验失败率统计; 人工抽样复核协议落地。

## 风险与回滚
每 Phase 独立提交组; 金样本(像素回归)+感知门禁(ΔE/美学)双保险;
Phase1 的逐位一致性测试是后续一切重构的安全网。

## 总量估算 ~2 周(单人)
