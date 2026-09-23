# R21 队长收尾草稿（待 QA 总审签章后落地）

## A. docs/changelog.md 追加条目（插到 `# Changelog` 之后、R20 条目前）

```markdown
## 2026-09-10 — 第二十一轮：闭环插电（M0）—— SinglePhotoLoop 接入服务层

- **闭环生产入口（F01）**：新增 `PixoServiceRuntime.run_auto_loop()` 与
  `POST /api/photos/{id}/auto-loop`（202 + 任务表 + 每 photo 单飞，`sync=true` 直返 200）、
  `GET /api/auto-loop/{task_id}`；装配 `RawRenderBackend` + 显式 segmenter +
  `manual_on_unreliable=False`（库层缺省 True 会让有不可靠区域的首轮直接转 MANUAL_REVIEW）。
- **默认规则注入（F02）**：装配层 `_load_auto_loop_rules()` 加载 11 条 `DEFAULT_RULES`
  （`PIXO_RULES=off` 可关），库层 `SinglePhotoLoop(rules=None)` 语义不变。
- **指标口径单一来源（F03）**：新增 `pixo/pipeline/metrics.py`（`metrics_for_decide` /
  `METRIC_KEYS` / `metric_universe` / `merge_proxy_metrics`），`loop._metrics_for_decide` 改薄
  wrapper；service 侧 `measure_session` 顶层合并 proxies、`decide_photo` 展平并传 rules
  （响应字段集合不变，`decision.params` 由 `{}` 变非空）。清偿服务层规则**零触发**的三因叠加
  （没传 rules + 指标嵌套 + 无 proxies）。
- **评分器适配器签名（F04）**：`_PixoScorerAdapter.__call__` 返回 dict，一并修好 `loop` 与
  `smart_crop` 两个"按可调用对象"使用的契约（返回 `AestheticScore` 本体因 `float()` 在 try 外会 500）。
- **端到端门禁（F05）**：新增 `tests/regression/test_gate_auto_loop_e2e.py`（文件级 `gate` +
  用例级 `gate_e2e` 双 marker、独立 env `PIXO_GATE_AUTOLOOP_RAW`，**不复用** `RAW_PATH` 以免
  连带激活 30s 性能门禁）。真 RAW `DSC_5236` 跑通：`ACCEPTED` / `rule_ids=[saturation_high_rule]` /
  `params.colorcal.saturation=-0.15` / 与仅渲染基线像素差 56,293,263 / 高光溢出 2.59% ≤ 3%。
- **契约修订 R1（门禁首跑拦截）**：首跑 FAILED 暴露服务层 `rule_ids` 取「最后一条 decide 事件」
  的口径缺陷（末轮规则自然不命中时漏掉早期命中）⇒ 改为**全 trace decide 事件并集**（首现序去重）
  并追加 `rule_ids_by_iteration`。口径纪律：`iteration>=max_iterations` 的末轮**照跑规则**
  （`engine.py:977-989`），**不得**断言「终止轮必空」。
- **验收**：全量 **1574 passed / 0 failed**（6 skipped / 1 xfailed；R20 红线 1533，+41 全为新增用例）；
  F05 门禁 2 passed（122.12s）；金样本双路零漂移（合成 gate 7 passed + 真 RAW compare 24/24 逐位一致）。
```

## B. docs/tech_debt.md 追加条目（编号更正：现有最后一条是 **19**，故新增为 **20/21**，不是 21/22）

```markdown
20. **auto-loop 与 `/decide` 缓存、`/timeline` 不联动**（记债，2026-09-10 R21 D3）：
    `SinglePhotoLoop` 自建状态机（`loop.py:1783`）≠ `service.state_machines`（`runtime.py:302`），
    auto-loop 结果只落任务表，**不回写** `photo.last_decision` 与 `runtime.state_machines`
    （刻意避免双写不一致；`photo.last_decision` 是引擎决策缓存，`GET /api/photos/{id}/decide`
    按其 schema 原样透传，且 `tests/unit/test_service_runtime_fixes.py:164-173` 有断言）。
    后果：跑完 auto-loop 后 `/timeline` 仍显示 RAW_PENDING。清偿方向：共享 store 或显式回写契约。

21. **auto-loop 无任务级超时/取消**（记债，2026-09-10 R21 D4）：渲染无中断点，单次闭环实测
    43.95–107.4s（真 RAW `DSC_5236` 门禁 122s 含两次渲染）。当前可控手段只有
    `max_iterations`（缺省 3，硬上限 5）+ `preview_long_edge`，任务一旦启动只能等其结束。
    另：任务表无淘汰策略、跨 photo 排队无 `queued` 态。清偿方向：可取消渲染 + 任务表 TTL。
```

## C. 交付前待办（队长）
- [ ] QA 总审签章 `.qa_ok` + `.r21_ok` 后落地 A/B
- [ ] 提交（分批：① `src/pixo/pipeline/{metrics.py,loop.py,batch.py}` ② `src/pixo/service/{runtime.py,app.py}` ③ `tests/**` ④ `docs/**`）
- [ ] 写 `.agent-team/DELIVERY-R21.md`（含各角色模型/思考档位实际生效情况）
- [ ] 更新 `docs/R21_CHANGE_REQUESTS.md` §0 的更正记录（calib_out 结论已于本会话更正，无需再改）
