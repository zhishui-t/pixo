# R26 · auto-loop 治理收口：tech_debt #20/#21 清偿 + 全量基线清绿

日期：2026-09-19 ｜ 上承：R21 auto-loop 生产入口（#20/#21 记债）→ R24/R25 引擎打磨

---

## 0. 结论速览

1. **#20（回写契约）清偿**：auto-loop 成功终局显式回写服务层三件事——状态机重放 +
   trace 导入 + last_decision 合成。跑完 auto-loop 后 `/timeline` 与 `/decide` 如实反映
   终态，"没生效"误判源消除。
2. **#21（任务治理）清偿**：queued 生命周期 + 迭代边界协作取消/截止 + cancel 端点 +
   任务表 TTL/容量淘汰。渲染本体仍无中断点——**协作粒度 = 迭代边界**是诚实边界，
   未越线承诺。
3. **全量基线清绿**：在册遗留 `test_llm_shadow` 断言精度清偿（trace round 6 位契约
   vs 默认 1.6e-7 容差），全量自此 0 failed。

## 1. #20 回写契约（`runtime._write_back_auto_loop`）

| 动作 | 语义 | 边界 |
|---|---|---|
| ① SM 重放 | service SM 停在 RAW_PENDING 时按 loop 转移事件序列重放（STATE_CHANGE/AGENT_ESCALATED/FINAL_QC_ACCEPT/REJECT/QC_ROLLBACK）⇒ `/timeline`/`photo.state` 全程轨迹 + 终态；iteration/current_params 对齐 | SM 已离开 RAW_PENDING（重跑）**不重放**（防非法转移），仅补 `auto_loop_summary` |
| ② 事件导入 | 非状态事件（decide/measure/param…）原样 `add_trace`，`source="auto_loop"` 与用户编辑轨迹可区分 | 重放转移自带新时戳的落痕；loop 原始历史仍在任务 trace 计数/payload 语义内 |
| ③ last_decision | decide 引擎同形 dict（decision/params/reasons/rule_ids/unreliable_regions/last_iteration）+ 扩展键 source/task_id/state；`decision`=loop 终态（ACCEPTED/MANUAL_REVIEW），与 decide 单轮动作词不同词汇表，消费方按 `source` 分派 | `decide_photo` 路径既有断言（test_service_runtime_fixes:164-173）不受影响 |
| 触发条件 | 仅 **done**（成功终局）；cancelled/failed 部分结果不回写（防半态污染缓存）；回写失败任务翻 `failed` + `write_back_failed:` 可见 | — |

## 2. #21 任务治理

- **库层**：`SinglePhotoLoop.run(stop_check=Callable[[], str|None])`——三边界询问
  （preview 迭代前 / 每轮迭代头 / FINAL_QC 全分辨率渲染前），真值即以当前状态早退，
  `metadata.stopped/stop_reason` 透出。库缺省 None = 行为与 R21 完全一致。
- **服务层**：任务生命周期 `queued→running→done|failed|cancelled`（提交即 queued；
  单飞口径含 queued）；`_AutoLoopControl`（threading.Event + monotonic 截止）。
- **HTTP**：`POST /api/auto-loop/{task_id}/cancel`——queued 即刻终态、running 置协作
  标记（响应 cancelling 语义）、终态幂等（cancel_requested=False）。
- **env**：`PIXO_AUTO_LOOP_TIMEOUT_S`（截止秒数，缺省 0 不设限保持 R21 行为；超限落
  `failed` + `timeout:` error）；`PIXO_AUTO_LOOP_TASK_TTL_S`（终态 TTL 秒，缺省 1800、
  下限 60）。
- **任务表治理**：提交时惰性 prune——终态任务 TTL 到期或总量超 200（最老先淘汰）；
  活跃任务永不淘汰。视图追加 created_at/started_at/finished_at/cancel_requested。

## 3. 基线清绿：test_llm_shadow

病灶：`loop.py` scores 字典面向 trace 可读性 `round(x, 6)`；测试从**舍入后**的 current
重推 threshold 却用 pytest.approx 默认容差 1.6e-7（差 5e-7 误红）。修复：测试侧
`abs=1e-6` 对齐 6 位舍入契约（R23 §7 判定"纯断言精度"，非产品缺陷）。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `src/pixo/pipeline/loop.py` | `run(stop_check=)` + `_run_preview_iterations(stop_check=)`（三个边界，缺省 None 行为不变） |
| `src/pixo/service/runtime.py` | `_AutoLoopControl` + env 助手；任务 queued 生命周期/时间戳/cancel_requested；`cancel_auto_loop` / `_prune_auto_loop_tasks` / `_write_back_auto_loop`；`_execute_auto_loop` 接 control + 停止分支 + 回写 |
| `src/pixo/service/app.py` | `POST /api/auto-loop/{task_id}/cancel`；status 端点 docstring 更新 |
| `tests/unit/test_llm_shadow.py` | 容差清绿 |
| `tests/integration/test_auto_loop_api.py` | +7 新用例；既有 2 处提交视图断言适配 queued/running 竞态；终态集纳 cancelled |
| `docs/tech_debt.md` | #20/#21 关闭条目 |

## 5. 回归

- auto-loop 专项：**27 passed**（假 backend，不读真 RAW；真 RAW 门禁
  `PIXO_GATE_AUTOLOOP_RAW` 用例维持 skip-or-run 契约未动）。
- 全量：**1706 passed / 0 failed / 6 skipped / 1 xfailed**
  （`.artifacts/_r26_full_suite.xml`）——自 R23 以来首次全绿（在册遗留清零）。
- 语义变化面：auto-loop 提交响应 status 可能是 `queued`（旧恒 running）——前端/
  调用方按集合判断即可；GET 视图为纯追加键。

## 6. 遗留与后续

- 渲染本体中断点（stage 级 cancellation）仍不可行——若未来需要，落点在 native
  kernel 的协作检查，另立项。
- auto-loop 重跑的 SM 不重放是**契约**（防非法转移）；若需要"重跑后完整轨迹"，
  需状态机支持 reset/replay-from-scratch，属 state 层演进，未在本轮范围。
