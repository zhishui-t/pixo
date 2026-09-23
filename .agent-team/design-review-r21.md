# 设计审核报告（design-review-r21）— Pixo 第二十一轮：闭环插电（M0）

> 审核人：QA-checker（2026-09-10）。被审对象：`.agent-team/design-r21.md`（队长 2026-09-10 起草，审核前 136 行 → 修订后 173 行）。
> 方法：任务书/花名册/探索报告/CR 四份上游逐条对照 + **回读源码核验设计的每一条事实引用**（抽查清单见 §8）。
> 处置：发现问题**当场在 design-r21.md 上做最小修订**（共 10 处，含 4 处"不修则开发必踩坑"的重要修订），逐处复验落位后签章。
> 范围边界：只审设计，未改 `src/`、`tests/`、`configs/`；架构级/需求级问题列 §7「需队长裁决」。

---

## 0. 审核范围

| 维度 | 覆盖 |
|---|---|
| 上游一致性 | `task-brief.md`（F01~F05 / 非目标 / 约束 / 完成标准 1-6）、`team-manifest.md`（文件域仲裁 / 门禁定义 / 返工上限）、`docs/R21_CHANGE_REQUESTS.md`（CR-01~05 原文与验收） |
| 设计事实核验 | design §0 六条前提（P1~P6）、§2 全部接口约定、§4 门禁断言、§5 风险行，逐条回读源码/测试确认 |
| 源码抽查（只读） | `service/runtime.py`、`service/app.py`、`pipeline/loop.py`、`pipeline/batch.py`、`pipeline/__init__.py`、`vision/measure.py`、`vision/__init__.py`、`decide/engine.py`、`decide/rules/*.yaml`、`decide/rules/__init__.py`、`render/geometry/smart_crop.py`、`render/web/export.py`、`state/machine.py`、`trace/recorder.py`、`tests/regression/conftest.py`、`tests/conftest.py`、`tests/regression/test_gate_e2e_perf.py`、`tests/integration/test_service_api.py`、`tests/unit/test_service_runtime_fixes.py`、`tests/unit/test_scorer_calibration.py`、`pyproject.toml` |
| 未独立复跑 | researcher 的 probe1~probe7（`%TEMP%` 已删/不可复现），只做**引用可信度抽查**：语料、模型缓存、坏 JSON、依赖行号均抽查一致（§8） |

---

## 1. 需求覆盖（F01~F05 × brief × CR-01~05）

| F-ID | design 落点 | CR 追溯 | 结论 |
|---|---|---|---|
| F01 | §1、§2.2、§3 | CR-01 | **覆盖**。新增 `run_auto_loop()` + 两个路由，保留 `decide_photo` 单轮语义与响应字段（`runtime.py:651-664`、`app.py:256-265` 未改）✓。缺口：CR-01 验收的 `iterations ≥ 2` 被漏 → **已修**（修订 2，F01 验收补 `iteration ≥ 2`，证据口径与 §4 断言 5 `measurements ≥ 2` 同源）。CR-01 的"curl 手测真 NEF"由 F05 gate（真 RAW 闭环）替代，取证更强 → 不要求裁决 |
| F02 | §1、§2.2 规则 1 | CR-02 | **覆盖**。`PIXO_RULES=off` 可关 + 库层 `SinglePhotoLoop(rules=None)` 保持空（`loop.py:770`）✓。缺口：验收"装配后 loop 实例 rules 非空"无可测接缝 → **已修**（修订 3+7：抽出模块级 `_load_auto_loop_rules(prompts)` 供单测直断） |
| F03 | §1、§2.1 | CR-03 | **覆盖且三件套齐**：①展平（`metrics_for_decide` 公共化）②补 proxies（`merge_proxy_metrics` 落 measurement 顶层）③传 rules（分叉1 A2）。缺口：`metric_keys=...` 未定值，**按现文字实现会直接 `DecideError`** → **已修**（修订 4+6+7，见本报告 §2.2） |
| F04 | §1、§2.4（新增） | CR-04 | **覆盖**。返回契约与两个消费者（`loop.py:907/912/924-932`、`smart_crop.py:194,199-208`）钉死；验收断言已从"非 fallback"改正为 `parts.scorer is not None`（CR-04 原文措辞不准，探索 §4.3 已证）✓；设计原本**缺 F04 接口小节** → **已修**（修订 5 新增 §2.4） |
| F05 | §1、§4 | CR-05 | **覆盖**。四要素（rule_ids/像素差/QC≤3%/trace 完整）齐；`.r21_ok` 执笔人=QA-checker ✓。缺口：断言 2 写了**不可运行**的 `decision.rule_ids`；marker 只写 `gate_e2e`（会掉出 `-m gate`）→ **已修**（修订 8） |

**非目标**（对照 brief §非目标、CR §4）：design §6 全文保留 CR-06/07、09/10、11、12/13、前端零改动、不动渲染算子/金样本/`calib_out/` ✓，无越界纳入。
**完成标准 6**（changelog + DELIVERY-R21）原设计未落点 → **已修**（修订 10 在 §4 补队长收尾项）。

结论：**F01~F05 全覆盖**（含 4 处补强），无 CR 要点丢失。

---

## 2. 可测性 / 误判风险（逐条）

| # | 检查 | 结论 |
|---|---|---|
| 2.1 | F01 轮询断言 `decision.rule_ids` | ❌→✅ **不可运行**。`LoopResult.decision` 是 `sm.state` 字符串（`loop.py:1959` 实测 `decision=sm.state`），rule_ids 只存在于 trace：`loop.py:1577-1595` 的 `decide` 事件 `value["rule_ids"]`，以及 `loop.py:1140` 的 `param_update.metadata.rule_ids`。原句会 `AttributeError` 或迫使 dev-1 造异形字段。**已修**：GET 响应字段改 `rule_ids`（= 最后一条 `decide` trace 的 `value["rule_ids"]`），F01/§4 同步改写 |
| 2.2 | F03 lint 的"键宇宙" | ❌→✅ **缺失定义**。原 §2.1 `METRIC_KEYS` 明写"不含区域键"，而 `region_rules.yaml:40-46,56,64-75,86` 的 condition 与 formula 同时引用 `sky_luminance`/`plant_luminance`；`load_rules` 在键宇宙非空时对 `condition.all[].metric` 与公式标识符**都**做严格校验（`engine.py:151-160,184-229`，`engine.py:270` 挂载）→ 只传 `METRIC_KEYS` 必抛 `DecideError`，F02 装配当场挂。**已修**：新增 `metric_universe(prompts)`，要求装配与 lint 都显式传 |
| 2.3 | F04 验收注入哪个 scorer | ⚠️ **误判风险**。CR-04 字面点名 `make_default_scorer()`，但真模型不可用时它回退 `MockAestheticScorer`（`batch.py:302-315`），后者只有 `.score()`、无 `__call__`（`batch.py:223-229`）⇒ 闭环仍"静默跳过"，断言 `measurement["aesthetic"]` 非空会 **fail（或被人为写成 skip 而假绿）**。**已修**：钉死确定性假内层 scorer 构造 `_PixoScorerAdapter`（对齐 `tests/unit/test_scorer_calibration.py:17-27`） |
| 2.4 | F05 像素差断言 | ⚠️ 原句"存在像素差"无判定式 → **已修**：`np.any(final != baseline)`（同 shape/dtype，baseline = 同 backend `render_full(base_params)`） |
| 2.5 | F05 QC ≤3% 断言 | ⚠️ 原句无取值路径 → **已修**：`result.final_measurement["global"]["highlight_clip_ratio"] <= 0.03`（阈值同源 `engine.py:81`；loop 读同键 `loop.py:1745-1749`） |
| 2.6 | F03 验收② `decide_photo` params 非空 | ⚠️ 原句"同 fixture"指代不明 → **已修**：钉到 `tests/integration/test_service_api.py:21-46` 的 FakeSession（`render` 返回全零图）；`_clip_ratio(lum≤5.0)=1.0 ≥ 0.18`（`measure.py:91-97`、阈值 `SHADOW_CLIP_THRESHOLD=5.0`）必触发 `shadow_open_rule_032`（`tone_clarity_rules.yaml:57-62`）——**该断言可达，不是碰运气** |
| 2.7 | F02"触发 ≥1 条" | ✅ 可测但需复用证据 → 已在修订中指向 F01 的 trace `decide` 事件，避免另造 fixture |
| 2.8 | `_metrics_for_decide` 别名是否破坏既有调用 | ✅ **不破坏**：全仓引用仅 `loop.py:521`(定义) / `:1393`(调用) / `:784`(注释) 与 `harness/goldens/samples.py:173`(注释串)，`tests/` 零引用；`build/lib/pixo/pipeline/loop.py:495` 为旧副本但 `tests/conftest.py:21-22` 把 `src` 插到 `sys.path[0]`，pytest 下不会取到 → 无风险（已写入 design §2.1 与 §8 证据） |

---

## 3. 边界与异常

| # | 检查 | 结论 |
|---|---|---|
| 3.1 | 404 / 400 语义 | ⚠️→✅ 原设计"无 sessions → 400"与自身装配规则矛盾：`run_auto_loop` 只用 `photo.path + self.profile`（§2.2 规则 2；探索 §6.12 明确"不依赖 session"）⇒ 该 400 是**死分支、不可测**。**已修**：404（photo/task 不存在）、400（`max_iterations` 非法/超硬上限 5）、显式声明"无 preview session 不是错误" |
| 3.2 | 内部异常不穿 500 | ⚠️→✅ 原句只覆盖"（异步路径）"，而 §2.2 同时定义了 `sync=true` 直返路径（测试要用）⇒ sync 路径裸抛 500 无人管。**已修**：两路统一 `status=failed + error`，sync 走 200+同构结果体 |
| 3.3 | 同 photo 并发单飞 | ⚠️→✅ 原来只写在 §5 风险表（非可执行约定）。**已修**：§2.2 规则 8 落成 `_active_by_photo` 幂等语义（同 photo 有 running → 202 返回既有 task_id） |
| 3.4 | segmenter 缺失/降级 | ⚠️→✅ 原来只说"响应暴露 `segmenter_type`"，未规定降级留痕。**已修**：`segmenter_type=="mock"` 时附 `degraded:["mock_segmenter"]`（对齐探索 §5.5 要求） |
| 3.5 | 超时上限 | ⚠️→✅ 原设计无时长口径，只有"600s 软上限"。**已修**：明确"不实现任务级超时/取消（渲染无中断点）"，可控手段 = `max_iterations`（硬上限 5）+ `preview_long_edge`，并给出实测区间（43.95–107.4s / probe6 73.09s） |
| 3.6 | MANUAL_REVIEW 处置 | ✅ §4 断言 1 要求"给理由与证据，不得放宽断言"，与 §5 掩码全零风险行一致 ✓ |
| 3.7 | task_id 未知 | ✅ 已在修订中显式补 404（对齐 `app.py:240-246` 导出任务风格） |

---

## 4. 接口合理性

- **环依赖**：`pipeline/metrics.py` 只 import `pixo.vision.measure`（`loop.py:37` 已有同向先例），`pixo.vision` 内**无**任何 `pixo.pipeline` 引用（grep 零命中）⇒ 无环；`pipeline/` 不反向依赖 service ✓（`grep -rn "service" src/pixo/pipeline/*.py` 仅 docstring）。
- **`_metrics_for_decide` 别名**：见 2.8，安全 ✓。
- **`decide_photo` 顺带修 rules 是否破坏字段集合**：核验 `tests/integration/test_service_api.py:185-189`（只断言 `"decision" in decide` / `"params" in decide["decision"]`）与 `:151-156`（只断言 `global`/`regions`/`mask_version`/`detail` 存在）⇒ `params` 空→非空、`measurement` 顶层**追加** 3 个 proxies 键均属追加式，不破坏；`tests/unit/test_service_runtime_fixes.py:164-173` 只约束 `photo.last_decision` 与 decide 结果一致（与 auto-loop 无关）。**已修**：§0 分叉1 补"追加式披露"，并在 §2.3 禁止 auto-loop 写 `photo.last_decision`（否则 `app.py:287-288` 会把异形结果当引擎 decision 透传）。
- **`_PixoScorerAdapter.__call__` 返回契约**：`dict`（含 overall）经 `loop.py:924-933` 得 `measurement["aesthetic"]` 且不触发 try 外的 `float(overall)`（`:932`）；经 `smart_crop._score_scalar:199-208` 走 dict 分支 → 两边同时满足 ✓。
- **F03 接线归属**：manifest 把 F03 派给 dev-2，而 F03 的 service 侧落点在 dev-1 文件域（`runtime.py`）⇒ 原设计未言明。**已修**（§3 末段按 `team-manifest.md:39` 重申：API 归 dev-2、接线归 dev-1，两流仍不共改一文件）。

---

## 5. 风险充分性（对照审核清单 5）

| 风险项 | 设计是否覆盖 | 备注 |
|---|---|---|
| 73s 耗时（全分辨率占 98%） | ✅ §0 P3 + §5 行 1 + §2.2 时长口径 | 已补实测区间与"无中断点"诚实口径 |
| 掩码全零 → MANUAL_REVIEW | ✅ §0 P2 + §5 行 2 | **已补强**：点明默认路由下 `face` 也零掩码，F05 的 `rule_ids` 非空实际压在 `saturation_high_rule` 1% 余量上（`color_rules.yaml:22-31`），落空即上报不得放宽 |
| mock segmenter | ✅ §2.2 规则 3 + §5 行 3 + P6 | 已补 `degraded` 留痕 |
| `register_metric_keys` 全局副作用 | ✅ §0/§2.1 + §5 行 5 | 已升级为"装配也显式传 universe"（原文字只管 lint 测试，仍会踩 2.2 的坑） |
| 双状态机回写策略 | ✅ §2.3 | 已从不破坏契约的方向收紧（不回写任何既有缓存） |
| PIXO_ALLOW_RESTRICTED/ sapiens 下载 | ✅ §0 P6 + §4 gate 装配 | 本机抽查：`~/.cache/huggingface/hub` 有 `segformer-b1`/`face-parsing`，`~/.roboflow/models/rf-detr-seg-xxlarge.pt` 154,851,262 B ⇒ P6 的"离线可用"抽查一致；sapiens 零权重结论采信探索报告 |

---

## 6. 交叉可执行性

- **文件域互斥**：stream-1 `runtime.py/app.py/tests-integration-new`；stream-2 `pipeline/metrics.py`(新)/`loop.py`/`batch.py`/两个 unit 测试(新)；tester `tests/regression/` 新文件 —— **无交集** ✓；补 F03 归属说明后仍无交集。
- **门禁可判定性**：`.design_ok`（覆盖+接口+风险，且注明仍需卡点②）/`.qa_ok`/`.r21_ok`（1533+金样本+真 RAW 实证）与 design §4 一致 ✓。
- **F05 env 与 marker vs conftest 事实**：`tests/regression/conftest.py:8-15` 仅对 `"gate_e2e" in item.keywords` 豁免 skip，其余 skip→failed ✓（P5 成立）；`pyproject.toml:70-74` 已注册 `gate`/`gate_e2e` marker ⇒ 无需新增注册 ✓。**但**原设计只写 `gate_e2e`：`pytest -m gate`（CR-05 的验收命令）**不会选中**该用例 ⇒ "验证过通"会假成立 → **已修**（两个 marker 都要 + 给出带 env 的运行命令；且提醒必须经 `python -m pytest`，因 `import pixo` 依赖 `tests/conftest.py:21-22` 插 `src`）。
- **不复用 `RAW_PATH`**：✅ `test_gate_e2e_perf.py:23,49-74` 证实复用会激活 30s 预算（probe6 73s 必 FAIL）。

---

## 7. 我做的修订（design-r21.md，最小改动 10 处）

> 全部为**就地修订**，未改 `src/`、`tests/`、`configs/`。复核方式：改后全文重读 + `grep` 确认问题句式零残留。

1. **§0 分叉1（重要）** — 原：`F03 顺带修好 decide_photo（给它传 rules）… 仅 decision.params 由 {} 变非空；现有断言只查字段存在`；新：明确 `decide({... "metrics": metrics_for_decide(measurement), "rules": _load_auto_loop_rules(prompts)})`，并**追加式披露** `measurement` 顶层多 3 键（证据 `app.py:198-212`、`test_service_api.py:151-156`）。
2. **§1 F01 验收** — 原：`轮询到 status=done 且 decision.rule_ids 非空`；新：`status=done、rule_ids 非空（= 最后一条 event_type=="decide" trace 的 value["rule_ids"]）、iteration ≥ 2`。
3. **§1 F02 验收** — 原：`同一 fixture：装配后 loop 实例 rules 非空且触发 ≥1 条`；新：`_load_auto_loop_rules(prompts) 返回值非空、PIXO_RULES=off 时为空；"触发≥1条"复用 F01 的 trace decide 证据；库层仍 rules == []（loop.py:770）`。
4. **§1 F03 验收（重要）** — 原：`①密钥宇宙 lint：DEFAULT_RULES 全部 condition 指标∈键宇宙 ②参数非空（同 fixture）`；新：`①显式 metric_keys=metric_universe(("face","sky","plant")) 后 6 个 DEFAULT_RULES 文件加载无 DecideError ②复用 test_service_api.py:21-46 的 FakeSession 全零图 → shadow_open_rule_032 必触发`。
5. **§1 F04 验收 + §2.4（新增，重要）** — 原：交付物`__call__ 返回 float/dict`、验收`注入 loop → 美学记录非空`；新：交付物钉成 **dict 契约**（`{"overall": s.overall, **s.dimensions, "source", "raw_overall", "domain_hint"}`），验收钉成确定性假内层 scorer（禁用 `make_default_scorer()` 真假分支），§2.4 给出代码与两侧消费者证据（`loop.py:906-932`、`smart_crop.py:199-208`）。
6. **§2.1 公共 API（重要）** — 原：`METRIC_KEYS: flatten 宇宙固定键…不含区域键`；新：显式列出 METRIC_KEYS 组成（6 global + 3 proxy + `crop_suggestion_applicable`）+ 新增 `metric_universe(prompts)` 定义与"必须显式传，否则 region_rules 的 sky_*/plant_* 抛 DecideError"证据；`merge_proxy_metrics` 补"须在写 `photo.last_measurement`（`runtime.py:625`）之前调用"；补公共 import 入口。
7. **§2.2 装配规则 1/3/7 + 新增 8（重要）** — 原：`load_rules(p, metric_keys=...)` / `segmenter 必须让调用方可见` / `仿 ExportManager`；新：`_load_auto_loop_rules(prompts)` 模块级函数 + `metric_universe(prompts)`；mock 时附 `degraded`；`max_workers=1`；新增规则 8 同 photo 单飞幂等语义。
8. **§2.2 HTTP + 失败语义 + 新增时长口径（重要）** — 原：`GET … {…, decision, params, …}`、`无 sessions → 400`、`异常不让 500 穿出（异步路径）`；新：GET 字段改 `rule_ids` 并给出 trace 取值路径（`loop.py:1577-1595`）+ 明示 `LoopResult.decision` 是字符串（`loop.py:1959`）；400 改为 `max_iterations` 非法、显式"无 session 不是错误"；异常两路统一；补时长/超时口径。
9. **§2.3 回写策略** — 原：`把 LoopResult.state/iteration/decision/params 写入 photo.last_decision 与任务结果`；新：**不回写任何既有缓存**（只落任务表；不写 `photo.last_decision`，证据 `app.py:287-288` + `test_service_runtime_fixes.py:164-173`）。
10. **§3 归属 + §4 门禁 + §5 风险** — 新增 F03 接线归属段（`team-manifest.md:39`）；§4 重写：双 marker（`gate`+`gate_e2e`）、gate 装配、运行命令、断言 2/3/4 判定式钉死、耗时口径、brief 完成标准 6 收尾项；§5 行 2 补 1% 余量裁决口径。

**复核结论**：修订后 `grep` 确认 `decision.rule_ids` 断言、`metric_keys=...`、`无 sessions → 400`、`float/dict`、`写入 photo.last_decision` 等原问题句式**零残留**；新增行号引用逐条回读源码一致（§8 清单）。

---

## 8. 源码核验清单（本次独立回读，file:line 已进 design 或本报告）

| 被核验事实 | 证据 | 结果 |
|---|---|---|
| decide 零触发成因③（没传 rules） | `service/runtime.py:651-655`；`decide/engine.py:1131` | ✅ 一致 |
| `manual_on_unreliable` 库层缺省 True | `pipeline/loop.py:751`；注入 `:1445,1465`；`engine.py:866-872,1147` | ✅ 一致 |
| 库层 rules 缺省空 | `pipeline/loop.py:770` | ✅ |
| `_metrics_for_decide` 定义/唯一调用点 | `pipeline/loop.py:521-551`、`:1393` | ✅ |
| 区域规则引用 sky_/plant_ | `decide/rules/region_rules.yaml:40-46,56,64-75,86` | ✅（关键修订依据） |
| lint 严格模式触发条件 | `engine.py:151-160`、`:184-229`、`:232`、`:270` | ✅ |
| proxies 合并层级 | `pipeline/loop.py:1352-1354`、`:1730-1732`；`vision/measure.py:548,574-581` | ✅ |
| `__call__` 崩溃链 | `pipeline/batch.py:71-86,318-410`；`pipeline/loop.py:906-932` | ✅（P4 成立） |
| `LoopResult.decision` 是状态字符串；rule_ids 只在 trace | `pipeline/loop.py:206-261`、`:1949-1965`；`state/machine.py` + `trace/recorder.py:18-60` | ✅（重要修订依据） |
| 服务测试断言面 | `tests/integration/test_service_api.py:151-156`、`:185-189`、`:214`；`tests/unit/test_service_runtime_fixes.py:164-173` | ✅ |
| skip→fail 规则与 marker 注册 | `tests/regression/conftest.py:8-15`；`pyproject.toml:70-74`；`tests/conftest.py:21-22` | ✅ |
| 30s 性能门禁连带 | `tests/regression/test_gate_e2e_perf.py:23,49-74`；`render/bench/gate_e2e_loop_budget.json` | ✅ |
| 导出先例（202+task） | `render/web/export.py:87-148`；`service/app.py:214-246` | ✅ |
| `compute_proxy_metrics` 未 re-export | `vision/__init__.py:37-45,48-72`；`vision/measure.py:584-594` | ✅ |
| 无环依赖 | `vision/` 内 `pixo.pipeline` 引用零命中；`pipeline/loop.py:31-37` 已有同向 import | ✅ |
| 离线权重抽查 | `~/.cache/huggingface/hub/{segformer-b1,face-parsing}`；`~/.roboflow/models/rf-detr-seg-xxlarge.pt`(154,851,262 B) | ✅ 与 P6 一致 |

---

## 9. 复核结论

**通过（修复后通过）**。design-r21.md 在 F01~F05 全覆盖、接口与契约明确、边界异常充分、文件域互斥、风险已识别且可执行这五项上均达标；10 处修订（4 处为"不修则开发必踩坑"：rule_ids 不可达断言 / lint 键宇宙缺失 / F04 契约缺节 / marker 掉出 `-m gate`）已全部落位并复核。据此签章 `.design_ok`。

**门禁语义声明**：`.design_ok` 只表示 **QA 的设计审核结论**；**不表示用户已确认**——卡点②由队长请用户确认（`team-manifest.md:51`），未获用户点头前不得进入第 6 阶段开发。

## 10. 需队长裁决清单（架构级/需求级，我不硬修）

| # | 事项 | 为什么需要裁决 | 我的建议 |
|---|---|---|---|
| D1 | **F05 的 `rule_ids` 非空可达性仅约 1% 余量**：默认不开 `PIXO_ALLOW_RESTRICTED` ⇒ `face` 掩码为零、`exposure_rule_001` 不参与，全靠 `saturation_high_rule`（`colorfulness_proxy` 6.1888 vs 阈值 6.13，`color_rules.yaml:22-31`）；渲染默认值微调即翻转 | 若 gate 实测 rule_ids 落空，是改语料/开受限后端/换断言，属需求级选择 | 首选：gate 实测后若落空，先查 `PIXO_ALLOW_RESTRICTED=1`（uniface 权重本机在）是否让 `exposure_rule_001` 稳定触发；**不得**放宽断言或静默换语料 |
| D2 | **CR-04 字面点名 `make_default_scorer()`**，而它在真模型不可用时回退无 `__call__` 的 `MockAestheticScorer` | 设计把验收改成"用固定假内层 scorer 构造 `_PixoScorerAdapter` 再注入"，属对 CR 验收措辞的偏离（可测性更好，但不再是 CR 原文口径） | 采纳设计的确定性断言；如需贴 CR 字面，另加一条"先断言返回值 **是** `_PixoScorerAdapter`，否则 skip 而非 fail"的用例 |
| D3 | **`/decide` 缓存与 auto-loop 结果的关系**：我按"不破坏引擎 schema"改成不回写 `photo.last_decision` ⇒ 跑完 auto-loop 后 `GET /api/photos/{id}/decide` 仍显示旧/空决策，`/timeline` 也仍是 `RAW_PENDING`（探索 §6.9） | 若产品上要求"闭环结果可经既有端点读到"，需新增字段/端点，属需求级 | 本轮按最小改动（登记 tech_debt #21）；若队长要求联动，请明确"新字段名 + 是否进 photo 详情响应" |
| D4 | **长耗时端点无任务级超时/取消**（渲染无中断点，`max_iterations ≤5` 仅软控，单任务可达数分钟） | 是否需要超时/取消能力属产品级约束 | 本轮接受现状并写入口径；若需取消，建议单开一轮（涉及渲染中断点） |
| D5 | **CR-01 的"curl 手测一次真 NEF"未单列**，由 F05 gate 替代 | 属验收形式选择 | 建议采纳 gate（可复跑、有输出），test-report 内附命令与输出即可 |

---

## 11. 增量复核（契约修订 R1：F05 真 RAW 首跑 FAILED 后）

> 审核人：QA-checker｜ISO 时间戳 `2026-09-10T22:15:28+08:00` (2026-09-10T14:15:28Z)｜被审 delta：design §7「契约修订 R1」+ §1 F01 + §2.2 GET/POST 契约 + §4 断言②（另 §2.3/§5 同步补字段与证据）。
> 范围不变：只审设计；本次**未改** `src/**`、`tests/**`（对 src/tests 只做只读回读取证）。原签章 `.design_ok` 保留，本次为追加复核条目。

### 11.1 触发与证据（读 tester 实跑产物，非转述）

- 首跑结果：`1 failed in 102.90s`（`.agent-team/tmp-r21-gate-run.txt:112`），失败点 = §4 断言②。
- 断言消息逐字证据（`tmp-r21-gate-run.txt:98`，末轮 decide 事件）：
  `{'iteration': 2, 'decision': 'adjust_and_continue', 'reasons': [], 'rule_ids': [], 'params': {'colorcal': {'saturation': -0.15}}, 'metrics': {... 'colorfulness_proxy': 5.8936 ...}, 'last_iteration': True}`
- 同跑其余证据（`:3`）：`state=ACCEPTED`、`params={'colorcal':{'saturation':-0.15}}`、`has_param_update=true`、`measurements=2`、`highlight_clip_ratio=0.025923`、`colorfulness_proxy(全分辨率 QC)=9.2987`、`rules_count=11`、`segmenter_last_degraded=[]`。

### 11.2 逐条复核结论（对队长四问）

**Q1 新口径「全 trace `decide` 事件 rule_ids 并集」是否可达、不误判、与 engine 语义自洽？→ 可达 ✅ / 不误判 ✅ / 自洽 ✅（但首版归因需纠正）**

- **可达（由证据可反推，且被其它断言蕴含）**：末轮 `params` 携带 `colorcal.saturation=-0.15` ⇒ 该参数只可能来自**规则轮**——本装配下 preview 轮 params 的唯一来源是 `decision["params"]`（`loop.py:1611-1617` → `_apply_decide_params`），而 `should_stop=True` 短路轮的 params 是"原样透传 context params"（`engine.py:1156-1163`）、`last_iteration` 轮也会跑规则（见下）⇒ 参数被写入 ⇒ 某轮 `applied` 非空 ⇒ 该轮 `rule_ids` 非空（`engine.py:1165-1173` 构造 → `_output` 第 4 位 `rule_ids`，`engine.py:1086-1092`）。**更强的蕴含**：断言⑤（trace 含 `param_update`）或断言③（与基线有像素差）任一成立 ⇒ 并集必非空（`param_update` 由 `_trace_param_updates` 仅在扁平参数真变化时写，`loop.py:1654-1660` + `1131-1142`）。故并集非空是**真 RAW 常规路径的可达事实**，不是碰运气。
- **不误判（不会伪造命中）**：`rule_ids` 只来自引擎实际 `applied` 列表，空 trace / 全空事件必然得到 `[]`；已把该性质写成负控（§4 断言 7）。
- **与 engine 语义自洽 —— 首版 R1 的归因错了，须纠正**：`iteration >= max_iterations` 走 `check_termination` 的 `last_iteration` 分支，返回 **`should_stop=False`**（`engine.py:977-989`，注释明写 t107 off-by-one："当前轮仍需计算并应用规则参数"）⇒ `decide()` **不短路**、照跑规则；loop 应用本轮参数后 break（`loop.py:1661-1664`）。实跑末轮事件正是 `decision='adjust_and_continue'` + `last_iteration=True`（`:98`），**不是**短路分支。本次空值的真因是**该轮规则自然不命中**：首轮 `saturation_high_rule` 命中（阈值 6.13，`color_rules.yaml:22-31`）并写入降饱和参数，末轮 `colorfulness_proxy` 已降到 **5.8936 < 6.13** ⇒ 无规则命中。`engine.py:1147-1163` 的"短路 → `rule_ids=[]`"是**另一条**合法空路径（`should_stop=True`，如 `low_improvement`/`targets_met`），本次未触发。两条路径都合法 ⇒ "取最后一条"必错、engine/loop 不改 —— **裁决方向不受影响，仅归因与用例规格需纠正**。

**Q2 裁决 B（不修 engine/loop）是否有反例（合法闭环但并集也恒空）？→ 无"假阴性"反例，B 不采纳正确 ✅**

- 存在"并集为空"的**合法运行**：`PIXO_RULES=off` ⇒ `rules=[]`；或所有轮次规则均不命中。但**不存在"其余四条断言全过而并集为空"的运行**：由 Q1 的蕴含关系，`params` 非空 / `param_update` 存在 / 像素差成立 ⇒ 至少一轮规则落地 ⇒ 并集非空。故并集口径**不会把失败运行伪装成通过**（无假阴性例外）。
- 也不存在"必须透传历史 rule_ids"的技术必要：透传会让终止轮 trace 谎报"该轮命中了规则"，B 的不采纳理由成立。

**Q3 追加字段 `rule_ids_by_iteration` 是否与既有响应契约冲突？→ 不冲突 ✅（既有键不减不改名）**

- `/api/auto-loop/*` 为 R21 新增端点，无既有消费者；实现层为**追加**：任务初始化键 `runtime.py:847-861`、POST 提交视图 `:887-897`、GET 视图 `:899-921`。既有键 `task_id/status/photo_id/segmenter_type/state/iteration/params/rule_ids/trace_event_count/error`（+ `duration`/条件 `degraded`）**无一删除或改名**。
- 形态与设计一致：`[{iteration: int, rule_ids: [str]}]`（`runtime.py:1043-1054`），且 iteration 有三级回退 `value["iteration"]` → `metadata["iteration"]` → 事件序号（`runtime.py:1000-1018`），不会因字段缺失而抛错。
- 已把设计 §2.2 的 GET 键集补全为与实现同集（原先漏列 `photo_id`/`segmenter_type`/`duration` 与条件 `degraded`）。

**Q4 是否需要 §4 负控？→ 需要；但队长提案的 `MAX_ITER=1` 形态无效，已改写并补进 §4 ✅**

- **`PIXO_GATE_AUTOLOOP_MAX_ITER=1` 不能充当负控**：该轮 `iteration(1) >= max_iterations(1)` ⇒ `last_iteration`（`should_stop=False`，`engine.py:977-989`）⇒ 规则照跑（`loop.py:1661-1664`），本语料首轮必命中 ⇒ 并集**非空**，用它当负控会得出"聚合伪造命中"的**错误结论**（与首版归因同源）。
- 已补入 §4（断言 6/7）：**正控** = `rule_ids == 并集(rule_ids_by_iteration)`（同序去重逐项相等；自洽、可判定、不依赖语料形态）；**负控**（单元级、无 RAW、必跑）= ① 全空/空 trace → `[]`；② 首轮命中 + 末轮空 → 返回首轮命中。

### 11.3 本次修订 diff 摘要（原句 → 新句）

| # | 位置 | 原句（要点） | 新句（要点） |
|---|---|---|---|
| 1 | §7 R1 根因（重要） | 「`decide()` 在 `check_termination` 命中末轮 `last_iteration` 时**先短路返回**，第 4 个位置参数（rule_ids）传 `[]`（`engine.py:1147-1163`），规则评估在其后**根本未执行**」；旧口径出处记 `runtime.py:984-1001` | 「两条**都合法**的空路径：①**实测触发**＝末轮 `last_iteration` **照跑规则**（`engine.py:977-989`）但该轮自然不命中（首轮命中后末轮 `colorfulness_proxy` 5.8936 < 6.13，`tmp-r21-gate-run.txt:98`）；②`should_stop=True` 短路（`engine.py:1147-1163`）透传 `[]`」；旧 `runtime.py:984-1001` 标注"修复前覆盖赋值"，并记为已落实现 `runtime.py:993-1054` |
| 2 | §7 R1 裁决 A | 承接方 = `dev-1`；用例「终止轮为空但首轮命中」 | 承接方 = **`dev-1`（service 提取+单测）+ `tester`（gate 侧同源口径复跑）**；用例改为「首轮命中、末轮**自然不命中**」并加禁止条款「**禁止**断言终止轮必空（错误不变量）」 |
| 3 | §7 R1 标题/末句 | 「QA 增量复核中」「等待 `QA-checker` 增量复核后生效」 | 「QA 增量复核**通过**」「已复核通过并生效（见 `design-review-r21.md §11`）」 |
| 4 | §4 断言② | 「`decide()` 命中 `last_iteration` 终止分支时先短路返回 `rule_ids=[]`…`loop.py:1959`」 | 双路径归因（①自然不命中 ②短路）+ 实跑数值 + `loop.py:1937`（行号随 dev-2 改动漂移，旧 1959 已失效） |
| 5 | §4 断言集（新增，重要） | 原仅 5 条 | 新增 **6 正控**（`rule_ids` == `rule_ids_by_iteration` 并集）与 **7 负控**（全空→`[]`；首轮命中+末轮空→首轮命中），并写明 MAX_ITER=1 禁作负控的理由 |
| 6 | §2.2 GET 契约 | 键集 `{…, state, iteration, params, rule_ids, rule_ids_by_iteration, trace_event_count, error}`；`loop.py:1959` | 补全为与实现同集（+`photo_id`/`segmenter_type`/`duration`；`degraded` 条件出现），注明"追加键，既有键不减/不改名"、iteration 三级回退；`loop.py:1937` |
| 7 | §2.2 POST 202 / §2.3 | `{task_id, status, photo_id, segmenter_type}`；任务表键 `state/iteration/params/rule_ids/trace_event_count` | POST 202 追加条件 `degraded`；任务表键补 `rule_ids_by_iteration`/`duration` |
| 8 | §5 风险行 2 | "1% 余量，若落空上报" | 追加首跑实测命中证据：迭代 1 命中并写入 `colorcal.saturation=-0.15` → 迭代 2 降到 5.8936（规则自熄火） |

### 11.4 复核结论

**通过（增量复核通过）**。R1 的修复方向（并集口径 + `rule_ids_by_iteration` 诊断字段）**正确、可达、不误判、与 engine 语义自洽**；裁决 A 维持、裁决 B（不修 engine/loop）维持。首版 R1 的两处**事实性错误**（把 `last_iteration` 说成短路；用 `MAX_ITER=1` 当负控）已就地纠正，并补入有效的正控/负控（§4 断言 6/7）。**未放宽任何断言、未改语料、未动 engine/loop/渲染路径。**

**对我上一轮结论的诚实修订**：review §7 修订 8 把断言从"不可运行"改成"从 trace 取**最后一条**"时，**保留了一个错误的选择口径**——合成/注入路径每轮都命中（dev-1 的 18 passed），掩盖了它；真 RAW 才暴露。教训：口径类断言必须与"何时会为空"的源码终止路径一起钉，不能只保证"能跑"。

**门禁**：`.design_ok` 追加本次增量复核条目（保留原签章内容不删）。

### 11.5 遗留提示（不阻塞、不在我文件域，仅提示 dev-1/tester 顺手对齐措辞）

- `src/pixo/service/runtime.py:1021-1029` docstring 仍把 `engine.py:1147-1163` 短路列为成因之一（**行为已正确**：并集实现见 `:993-1054`）；`tests/regression/test_gate_auto_loop_e2e.py:38-48`、`:79-85` 同样保留短路归因表述（**行为已正确**：`_decide_rule_ids_union` `:106-116` 已按并集）。措辞不影响放行，建议收口时对齐，不必单独返工。
- gate 侧已具备逐轮诊断打印（含 `decision`/`last_iteration`/`colorfulness_proxy`，`test_gate_auto_loop_e2e.py:96-102,209-213`）⇒ 复跑即可自证"早期轮命中、末轮空"的新形态，test-report 应附该输出（同时满足 §7 D1 要求的三样本 `colorfulness_proxy` 取数）。
