# 第二轮外部架构评审处置表（5 维度 14 条）

- 日期：2026-09-04 · 执行：qa（长安）
- 核对基准：commit `3bcccd3` + 工作区在途批次（t46 影子模式 / t47 JND 早停 / t48 轨迹回放 / 前端滑杆与 huesat_oklch 批次——见文末时效注记，处置表内区分"已提交"与"在途"）
- 纪律：每条附代码行号/报告路径/测试名证据，逐条实证后修正预判；不凭印象判。
- 汇总：**已达成 4（①②⑪⑬-数据层）· 部分达成 4（③⑥⑩⑫）· 采纳-在途收口 3（⑧⑨⑬-回放）· backlog 3（⑤⑦⑭）· 驳回 1（④）**

| # | 维度 | 意见摘要 | 处置 |
|---|---|---|---|
| ① | 渲染管线 | DAG 增量缓存 | **已达成**（四级缓存超出建议） |
| ② | 渲染管线 | LOD 多分辨率预览 | **已达成**（两级+任意档） |
| ③ | 渲染管线 | LUT 预烘 / 与 CCM 合并 | **部分达成**（6x 已做；预烘历史实证否定；合并无对象） |
| ④ | 视觉轻量化 | 蒸馏小模型 | **驳回** |
| ⑤ | 视觉轻量化 | 评分器 INT8 量化 | **backlog P3**（条件触发） |
| ⑥ | 视觉轻量化 | 异步流水线 | **部分达成**（结构已缓解+预算门守卫） |
| ⑦ | 决策闭环 | 贝叶斯优化调参 | **backlog P3**（无收敛痛点） |
| ⑧ | 决策闭环 | LLM 影子模式 | **采纳**（t46 在途交付） |
| ⑨ | 决策闭环 | JND 早停 | **采纳**（t47 在途交付） |
| ⑩ | 知识 RAG | (Condition,ParamRange,Effect) 三元组 | **部分达成**（半形式化已有，全形式化 backlog） |
| ⑪ | 知识 RAG | 风格卡回归 | **已达成**（三层等价覆盖） |
| ⑫ | 工程测试 | 感知哈希回归门 | **部分驳回**（pHash 驳回；SSIM 条件保留） |
| ⑬ | 工程测试 | 优化轨迹可视化 | **部分达成**（数据层已达成；回放工具 t48 在途） |
| ⑭ | 工程测试 | tech-debt 转运行时断言 | **采纳**（backlog；首批断言已在途） |

---

## 维度一：渲染管线

### ① DAG 增量缓存 —— 已达成（实现超出评审建议）

四级缓存 + 内容指纹失效 + LRU 双预算 + 异步防过期，`src/pixo/render/web/session.py`：

- 四层缓存：`_decode_cache`（:139，键 decode_mode+raw_version）、`_tier_cache`（:141，按 long_edge INTER_AREA 建档 :224-238）、`_stage_cache`（:143，OrderedDict）、`_encoding_cache`（:145，键含 generation :469-471）；外加进程级 `core/io.py:28` `_DECODE_CACHE`（PIXO_DECODE_CACHE_MB 预算 LRU）与 `core/lut.py:49-51` LUT 对象缓存（上限 4 :66）；
- stage 缓存键 = `(stage.name, param_fp, input_fp, state_fp, all_stages_fp)`（:344-346）——**内容指纹失效**（参数/输入/state/全链任一变即 miss），`all_stages_fp` 专防跨级陈旧命中（:330-334 注释"改 WB 后 EV 不更新"问题）；`_raw_version`（mtime_ns+size，:176-182）使文件替换全链失效；
- LRU 双预算：条数 64 + 字节 512MiB 双重淘汰（`_evict_stage_cache` :260-271，`popitem(last=False)` :273-276），字节增量维护免 O(n)（:144）；
- 异步防过期：每 session 单线程池（:155-156）+ `submit_render` generation 快照（:396-413）+ 渲染前后双检（:415-425）+ `StaleGenerationError`（:108）；
- **覆盖度**：stage 缓存循环遍历 `pipe.stages` 全链（:341），`presets.py` DEFAULT_STAGES 14 级——**整个 DAG 已被 stage 级增量缓存覆盖，超出评审预期**。

附注（非差距，供后续优化参考）：stage 预算 512MiB 为硬编码（:129，非 env）；`submit_render` 防过期 API 在 src 无生产调用点（web 端走同步 `session.encode`，service/app.py:169）；`RawRenderBackend.render_preview` 每次新建 session（loop.py:377-383），优化循环内无跨迭代 stage 复用——缓存收益集中在长生命周期 web 会话（PIXO_MAX_SESSIONS LRU 治理，runtime.py:278-291）。

### ② LOD 多分辨率预览 —— 已达成（两级 + 任意档）

- 优化循环用 512 预览：`loop.py:627` `preview_long_edge=512` 缺省、:972-973 迭代内 `render_preview(long_edge=...)`、:977-993 评分/测量全部消费预览图；
- 全幅终检：FINAL_QC `render_full` 全幅 + mask 上采样（loop.py:1435/1284-1286；export.py:43 `decode_raw(half_size=False)`）——**"512 迭代 → 全幅终检"两级 LOD 成立**；
- 任意档 tier：web 端点 `long_edge` 可请求 16–4096（service/app.py:155），tier 缓存按档建档（session.py:224-238）——无固定阶梯但支持任意分辨率复用解码。

### ③ LUT 预烘 / 与 CCM 合并 —— 部分达成（性能已超；预烘方向被历史实证否定）

- **已达成部分**：native float 四面体插值内核（commit `4388f37`，2026-08-27："stylize 精度回收 + 预览提速 6x"，预览 87-95ms/全幅 333ms）——`native/src/lut3d.cpp:103` `ApplyLut3DF32`（Kasson 1993 四面体）、生产路径 `modules/style.py:55-58` `lut.apply_f32`（输入免 u8 量化）、numpy 参考实现逐位对齐（`core/lut3d.py:30/149`，`native/src/lut3d.h:8`）；评审的性能目标已被超出；
- **预烘驳回证据**：预烘曾被实现又被**主动移除**——`4388f37` message 明确"移除 load_lut/load_lut_path 的 256³ 表预热（每表 ~16s 建表成纯浪费）"；现设计为无状态内核 + Python 侧 LRU（lut3d.cpp:5，core/lut.py:72"仅解析 .cube（快）"）；
- **合并无对象**：`apply_rp_ccm`/`load_rp_ccm` 在 src/pixo/render **零运行时调用点**（.artifacts/gate_calibration_coverage.md:36-38——RP-CCM 并联只在 scripts/calib/diff_core 代理侧，G-5 从未切默认）——"LUT 与 CCM 合并"的 CCM 不在渲染链上，前提不成立；
- backlog 残项：若未来 rp_ccm 接线运行时且 profiling 显示 LUT+CCM 串行成热点，再评估合并（条件触发，与 rp 接线批次绑定）。

## 维度二：视觉轻量化

### ④ 蒸馏小模型 —— 驳回

- **无瓶颈证据**：全仓无蒸馏/量化代码（`distill|quantiz|int8|fp16` 零命中）；评分器稳态 ~20ms（aesthetic.py:253-254 实测注释"t58 冷启 ~15.8s vs 稳态 ~20ms"，warmup 已消冷启）；分割在预览图上仅首轮执行（loop.py:1086-1092 `if masks_cache is None`）；e2e 预算门在守（`src/pixo/render/bench/gate_e2e_loop_budget.json`：单张 ≤30s / 批量 ≥2 张/分）——评审未给任何延迟失守证据；
- **轻量化已有三层**：重依赖全懒加载（grounded_sam.py:44-45 / segformer_scenes.py:47-48 / sapiens_body.py:171-172 函数内 import；`test_vision_segmenter.py:203-235` AST 全量隔离门）+ 零掩码 best-effort 降级（multi_router.py:186-204，契约形状保持）+ 缺省 mock（runtime.py:129-131 `PIXO_SEGMENTER` 缺省 "mock"，避免意外加载 334MiB 模型）；
- **方法论违背**：蒸馏引入训练栈，违反本项目"确定性优先 + 权重不入仓"纪律（docs/LEARNED_BACKEND_GOVERNANCE.md 红线）；且 334MiB 是磁盘占用非延迟问题（aesthetic_scorer.pt 含 CLIP backbone，aesthetic.py:151-171）。

### ⑤ 评分器 INT8 量化 —— backlog P3（条件触发）

- 现状：torch+transformers fp32（aesthetic.py:296 provider 字段；334MiB 权重）；warmup 已有（`PIXO_SCORER_WARMUP` 缺省开，aesthetic.py:112-115/:253-283；服务启动线程池预热 app.py:51-58）；
- **预判修正**：评分结果**无 LRU**（`_probe_cache` 是权重探针布尔缓存 aesthetic.py:54，非评分缓存）——但稳态 20ms 使缓存/量化均无必要；
- backlog 触发条件：批量吞吐或端侧部署出现实测延迟证据（如 e2e 预算门逼近）时，先评估 ONNX/INT8 导出（注意 torch 出 src 的隔离纪律，量化推理放 vision adapter 层内）。

### ⑥ 异步流水线 —— 部分达成（结构已缓解，流水线化条件触发）

- 事实：分割与评分是**同步阻塞**调用（loop.py:1086-1092 首轮分割、:1131 每轮评分；batch.py:670-672 硬过滤分割；loop/batch 零 Thread/executor/asyncio——唯一线程化是启动 warmup app.py:51-58）；
- 但量级已被设计控制：分割仅首轮 + 512 预览图、评分预览图 + 稳态 20ms、LLM 调用有熔断（tools.py:98-105，3 次失败 60s 冷却，"最坏 ~20s/张"注释如实记录）；
- 现成守卫：e2e 预算门（30s/张）就是持续 profiling——失守即流水线化的触发信号；
- backlog 条件：预算门失守或批量化需求时，优先将 FINAL_QC 全幅渲染与分割/评分并行化（渲染与视觉无数据依赖点后置）。

## 维度三：决策闭环

### ⑦ 贝叶斯优化 —— backlog P3（无收敛痛点证据）

- 现状：规则驱动 + 可选几何步长衰减（`decide/engine.py:574-580` `step_decay ** (iteration-1)`）+ 四类终止（engine.py:859 `check_termination`：targets_met :897-909 / aesthetic_target_met :926-937 / aesthetic_stagnation :931-944 / low_improvement 缺省 0.1 :953-975，先于轮数上限判定）；
- **预判修正**：`max_iterations` 缺省 **3** 非 1（loop.py:645/:1057），且无"首轮短路"——engine.py:980-982 的 t107 修复反而保证 max_iter=1 时规则也触发一轮；搜索空间小（3 轮 × 规则动作），BO 的样本效率优势无处发挥；
- backlog 条件：若未来迭代轮数放开（>10）或参数维度扩张出现收敛慢的实测痛点，可衔接阶段二 diff_core 可微代理（scripts/calib/diff_core.py 已证明高保真代理可行性）做 BO——当前不动。

### ⑧ LLM 影子模式 —— 采纳（t46 在途交付）

已派单且产物已在工作区（未提交）：`tests/unit/test_llm_shadow.py`（新增）+ loop.py 影子事件链（`llm_shadow_skipped` :994/:1000/:1012/:1020、`llm_shadow_promote` :1035——影子建议记录/晋升判定已入 trace 事件体系）。闭环条件：该批次提交 + 全量绿。

### ⑨ JND 早停 —— 采纳（t47 在途交付）

采纳依据成立：此前 src 零 JND 语义（终止全靠美学分/改善阈值，无感知量纲）。t47 产物已在工作区（未提交）：`src/pixo/pipeline/perceptual.py`（新增——ΔE2000 从 scripts/eval_rp_ccm_ab.py 抽取为 src 单一实现防漂移 + `JndConvergenceTracker`）+ loop.py 接线（:32 import；`jnd_threshold=0.5` 缺省保守值 / `jnd_window=2`，:662-663/:698-699；`perceptual_convergence` 事件 :1399）+ `tests/unit/test_perceptual_convergence.py`（含 Sharma 2005 文献对校验）。闭环条件同上。

## 维度四：知识 RAG

### ⑩ (Condition, ParamRange, Effect) 三元组 —— 部分达成（半形式化已有）

- 已有结构化基础：知识包 nodes/edges 图（`know/graph.py:207` KnowledgeGraph；configs/knowledge/ 5 包 62 节点/51 边，registry 两阶段合并 :98-157 含跨包一致性核对）；**规则侧已是半形式化**——`configs/rules/exposure_rule_001.yaml:4-13` `condition:{metric,op,value}` + `action:{param,formula,clamp,step_decay}`（条件算子 7 种 + AND 组合，engine.py:341-426；clamp 即 ParamRange）；patch 协议参数带界（patch_protocol.py:74-83 schema 驱动 min/max，越界拒绝 :205-225）；
- 差距：知识节点语义为自由文本（`side_effect` 节点的 effect 是 prose，如 photography_post2.json 的 `post2_saturation_trap`）——**(Condition,ParamRange,Effect) 全形式化零命中**（全仓搜确认）；
- backlog（演进方向，P3）：把高价值 side_effect 节点形式化为三元组（condition 引规则算子语义 / param_range 引 Stage schema 界 / effect 引 ΔE 量纲），可先从与 patch 闸门 oklch 量纲文档（patch_protocol.py:96-101）同源的条目做起——收益是知识检索可执行化，代价是维护双轨（prose+结构），须有 LLM 建议质量痛点证据再动。

### ⑪ 风格卡回归 —— 已达成（三层等价覆盖）

评审若特指"风格卡级 A/B 快照工具"则不存在（run_ab_regression.py 是语料级渲染 A/B、ab_intent_compare.py 是意图级），但风格卡回归实质被三层覆盖：

1. **渲染内核金样本 17 case**：tests/regression/goldens/gate/manifest.json 17 features（含 hsl/split_tone/skin/stylize 全编辑域 + 新增 exposure_cal_auto/warmth_cal_auto 标定敏感 case），sha256 完整性 + 1e-6 数值门（test_gate_golden.py:35-37/:47-56/:66-75）；
2. **胶片卡零迁移守卫**：`test_film_cards_oklch.py:92-109` 存量 24 卡"无 color_domain 键 + bands 无 domain 键"逐卡断言（t21，阶段一域迁移零破坏的卡库层证明）+ :117/:141 oklch 域卡分派语义可见 + `test_oklch_preview_e2e.py` 卡参数经 preview 接口往返渲染；
3. **语料级 A/B 工具链**：run_ab_regression.py（全语料分层 ~40 张三层验收）/ ab_intent_compare.py（意图级 ΔE2000 + --selftest）/ ab_vs_camera_thumb.py / eval_rp_ccm_ab.py。

风格卡 = 配置数据，其视觉效果由渲染链决定——渲染链被 17 case 逐内核锁定 + 卡库被守卫测试锁定，卡级视觉快照属冗余层。

## 维度五：工程测试

### ⑫ 感知哈希回归门（pHash/SSIM）—— 部分驳回

- **pHash 驳回**：渲染链是确定性纯函数（seed 固定，gate_cases.py:69/:158），现有门 = 基线 sha256 完整性（防误替换 test_gate_golden.py:47-56）+ `max|Δ| ≤ 1e-6` 数值门（:66-75）——**严格强于任何感知哈希**（1e-6 容差对 float 中间量，感知哈希的汉明距离容差以数量级计）；降级到感知度量反而放宽门。loop 轨迹非 CI 快照对象（test_loop_replay/test_loop_termination/test_loop_e2e 全部是行为断言——mock/合成输入下的状态机行为，非输出金样本），无从加感知门；
- **SSIM 条件保留（不驳回也不做）**：SSIM 门仅对**非确定性渲染组件**有意义——当前渲染链零非确定性组件（torch 仅在 scripts/ 与 vision adapter，不产渲染输出）；若未来学习型渲染组件过三证据转正（LEARNED_BACKEND_PROMOTION），其金样本门须用 SSIM/感知度量替代逐位门（确定性 gone）——已作为该模板的隐含要求存在；
- 全仓 pHash/SSIM/LPIPS 零命中（搜 phash|ssim|lpips|perceptual，唯一感知度量 = perceptual.py 的 delta_e_median/JND，属决策环非回归门）。

### ⑬ 优化轨迹可视化 —— 部分达成（数据层已达成 + 回放工具在途）

- **数据层已达成**：`state/store.py:31-47` SQLite trace_events 全字段（param/old_value/new_value/reason/rule_id/formula/iteration/metadata…）；loop 侧 14 类事件统一写入口（`_add_trace` loop.py:894-938；param_update/decide/llm_shadow_*/agent_suggest_*/perceptual_convergence/qc_rollback/crop_*/meta_extracted 等）；查询 API `trace/query.py:36/:44`；web 端点 `GET /api/photos/{id}/timeline`（app.py:224-230）；
- **回放工具 t48 在途**：`scripts/loop_replay.py`（新增未提交——按 photo_id 查全序列渲染 markdown 时间线 + `--export-dir` 逐参数快照重渲 side-by-side 对照）+ `tests/unit/test_loop_replay.py`；其头注直接引用评审原话，即为本条意见的定点交付。闭环条件：提交 + 全量绿。

### ⑭ tech-debt 转运行时断言 —— 采纳，登记 backlog（首批已在途）

- 采纳理由：docs/tech_debt.md 的 P3 债项中"日落条款/触发条件"类（如公式守卫日落 §12、calib_prev 回退语义）本质是可执行不变量，测试固化优于文书约定（与 t42 治理门禁"测试固化不是文书约定"同哲学）；
- 首批已在途：`tests/unit/test_tech_debt_invariants.py`（新增未提交）+ docs/tech_debt.md 联动修改——该批次的落地形态即本条建议的第一次实践；
- backlog：t44 遗留清单与本处置表新增债项（③合并条件/⑤量化条件/⑥流水线条件/⑦BO 条件/⑩三元组）逐项评估"可否转监控断言"——大部分条件触发类债项的正确形态是**预算门/门禁测试**而非运行时断言（如⑥的 e2e 预算门已是该形态），逐项归位在下个维护批次。

---

## 时效注记

本表核对期间工作区有**多个并行批次在途**（均未提交，落盘时间 2026-09-04 23:31-23:35 前后）：t46（test_llm_shadow.py + loop.py 影子事件）、t47（perceptual.py + loop.py JND 接线 + test_perceptual_convergence.py + eval_rp_ccm_ab.py 改引共享实现）、t48（loop_replay.py + test_loop_replay.py）、前端滑杆与 huesat_oklch 批次（SliderParam/oklchScale/HslBandRow + core/huesat_oklch.py + UI_OKLCH_SPEC 更新——即首轮处置表 ③ backlog 的实施）、tech-debt 断言批次（test_tech_debt_invariants.py）。处置表对⑧⑨⑬⑭③ 的"在途"标注均引用上述工作区证据；**各批次提交 + 全量回归绿之前，在途项不计为已交付**。已提交核对基准：`3bcccd3`。

（过程注记：本审计两个并行搜证任务对"src 是否存在 JND"给出相反结论，经查为**时间差**——早查时 perceptual.py 尚未落盘、晚查时已存在。并行开发期的处置表必须以文件系统实时状态复核关键否定性结论。）

### 心跳 @ 2026-09-05 08:11:01

### 心跳v2 @ 2026-09-05 08:33:49

> 核验注记（t45 承接轮 @ 2026-09-05 08:38:36）：14 条处置正文已于 t45 本轮完整交付（汇总表 + 五维度逐条 + 时效注记），本次承接任务核验文件结构完整（138 行 / ①-⑭ 全在位），无缺补；心跳两行系 API 探针追加，非正文内容。
