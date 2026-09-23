# R21 stream-1 交付报告 — F01 服务层闭环入口 + F02 默认规则注入 + F03 service 侧接线（dev-1）

> 角色：`dev-1`｜阶段 6（开发，两流并行）｜产出时间 2026-09-10
> 上游：`.agent-team/design-r21.md`（**唯一实现依据**；§2.2 规则 1~8 / §2.3 / §3 / §4）+ `.agent-team/exploration-r21.md`（§1 / §2 / §5.8 / §6.1·6.3·6.11·6.12）+ `.agent-team/task-brief.md`
> 下游：`tester`（阶段 7）、`QA-checker`（阶段 8）
> **状态：F01/F02 与 F03 的 service 侧接线全部落地；本流定向测试 20 passed（含修订 R1 新增用例）；`tests/integration` 全目录 152 passed / 0 failed（R1 前基线，R1 后未复跑全目录）；邻居回归（`test_service_runtime_fixes.py`）21 passed / 0 failed。修订 R1（`rule_ids` 并集口径 + 归因更正）见文末。未提交 git（由队长提交）。**

---

## 0. 一句话结论

服务层现在有了闭环生产入口：`POST /api/photos/{id}/auto-loop`（202 + 任务表 + 轮询，或 `sync=true` → 200 同构结果）+ `runtime.run_auto_loop()`；装配层默认注入 11 条内置规则（`PIXO_RULES=off` 可关）；`measure_session` 顶层合并 proxies、`decide_photo` 展平指标并传 rules（响应字段集合不变，仅 `decision.params` 由 `{}` 变非空）。

---

## 1. 改动清单

| # | 文件（域内） | 改动量 | 关键内容 | 对应验收 |
|---|--------------|--------|----------|----------|
| 1 | `src/pixo/service/runtime.py` | +326 / −3 | ① 模块级 `_load_auto_loop_rules(prompts)` + `_auto_loop_default_iterations()` + `_validate_max_iterations()`；② `__init__` 加 auto-loop 任务表（`ThreadPoolExecutor(max_workers=1)` + `_auto_loop_tasks` + `_auto_loop_active` + `_auto_loop_lock`）；③ `run_auto_loop()` / `auto_loop_status()` / `_execute_auto_loop()` / `_auto_loop_rule_ids()` + 两个视图函数；④ `measure_session` 顶层合并 proxies；⑤ `decide_photo` 展平 + 传 rules | F01 / F02 / F03 |
| 2 | `src/pixo/service/app.py` | +47 / −1 | `POST /api/photos/{photo_id}/auto-loop`（缺省 202 / `sync=true` → 200）+ `GET /api/auto-loop/{task_id}`；`_not_found` / `_bad_request` 映射；`import json` + `JSONResponse` | F01 |
| 3 | `tests/integration/test_auto_loop_api.py`（**新建**，423 行 / 13 个测试函数 = 18 用例） | 全部新增 | ①F02 规则注入 ②闭环注入假 backend（含单飞）③HTTP 真实往返 + 失败语义 ④`decide_photo` params 非空 ⑤顶层 proxies | F01 / F02 / F03 |

### 1.1 关键 diff 摘要

**(a) F02 规则注入**（`runtime.py`，模块级，供单测直接断言）：

```python
_RULES_DISABLED = {"0", "false", "off", "no"}
_AUTO_LOOP_PROMPTS = ("face", "sky", "plant")
_AUTO_LOOP_DEFAULT_ITERATIONS = 3
_AUTO_LOOP_MAX_ITERATIONS_CAP = 5
_AUTO_LOOP_ITERATIONS_ENV = "PIXO_LOOP_MAX_ITERATIONS"

def _load_auto_loop_rules(prompts=None) -> list[dict[str, Any]]:
    if os.environ.get("PIXO_RULES", "").strip().lower() in _RULES_DISABLED:
        return []
    from pixo.pipeline.metrics import metric_universe     # ← 惰性 import（dev-2 并行交付）
    universe = metric_universe(tuple(prompts or _AUTO_LOOP_PROMPTS))
    rules = []
    for path in DEFAULT_RULES:
        rules.extend(load_rules(path, metric_keys=universe))   # ← 必须显式传键宇宙
    return rules
```

**(b) F01 闭环装配**（`_execute_auto_loop`，逐条对齐 design §2.2 规则 1~8）：

```python
loop = SinglePhotoLoop(
    render_backend=RawRenderBackend(raw_path, self.profile),   # 规则2：不读 preview session
    segmenter=self._segmenter,                                 # 规则3：显式传
    measurer=VisionMeasure(),
    rules=_load_auto_loop_rules(prompts),                      # 规则1
    preview_long_edge=int(preview_long_edge), max_iterations=int(max_iterations),
    prompts=list(prompts), targets={}, locked_params=[],
    manual_on_unreliable=False,                                # 规则4（P2 硬要求）
    aesthetic_scorer=None, agent_suggest=False, enable_style_cards=False,  # 规则5/6
)
result = loop.run(photo_id, raw_path=raw_path, max_iterations=int(max_iterations))
```

**(c) `rule_ids` 提取**（**不是** `LoopResult.decision`）：

```python
@staticmethod
def _auto_loop_rule_ids(result) -> list[str]:        # 最后一条 event_type=="decide" 覆盖前者
    rule_ids = []
    for event in result.trace_events or []:
        if isinstance(event, dict) and event.get("event_type") == "decide":
            value = event.get("value"); ids = value.get("rule_ids") if isinstance(value, dict) else None
            rule_ids = [str(r) for r in (ids or [])]
    return rule_ids
```

**(d) 每 photo 单飞**（规则 8，锁内判定）：

```python
with self._auto_loop_lock:
    active_id = self._auto_loop_active.get(photo_id)
    if active_id is not None:
        active = self._auto_loop_tasks.get(active_id)
        if active is not None and active["status"] == "running":
            return self._auto_loop_submit_view(active)     # 202 返回既有 task_id（幂等）
        self._auto_loop_active.pop(photo_id, None)
    ...创建任务并登记 _auto_loop_active[photo_id] = task_id
# 任务终结（done/failed）时在锁内清除 _auto_loop_active[photo_id]
```

**(e) F03 两处接线**（`runtime.py`）：

```diff
@@ measure_session：measure(...) 之后、写 photo.last_measurement（:625）之前
+        from pixo.pipeline.metrics import merge_proxy_metrics
+        merged = merge_proxy_metrics(measurement, image)
+        if isinstance(merged, dict):
+            measurement = merged
         if photo_id is not None and photo_id in self.photos:
             self.photos[photo_id].last_measurement = measurement
@@ decide_photo
+        from pixo.pipeline.metrics import metrics_for_decide
         result = decide({
-            "metrics": measurement,
+            "metrics": metrics_for_decide(measurement),
             "params": params,
             "iteration": max(1, iteration + 1),
+            "rules": _load_auto_loop_rules(_AUTO_LOOP_PROMPTS),
         })
```

**(f) app.py 两个路由**（照 `api_submit_export` / `api_decide` 风格）：

```python
@app.post("/api/photos/{photo_id}/auto-loop", status_code=202)
async def api_auto_loop(photo_id: str, request: Request):
    raw_body = await request.body(); body = json.loads(raw_body) if raw_body else {}
    ...                                                        # 空 body → {}; 非法 JSON → 400; 非对象 → 400
    sync = bool(body.get("sync", False))
    try:
        result = await run_in_threadpool(rt.run_auto_loop, photo_id,
                                         max_iterations=body.get("max_iterations"), sync=sync)
    except KeyError as exc: raise _not_found(str(exc)) from exc          # 404
    except ValueError as exc: raise _bad_request(str(exc)) from exc      # 400
    return JSONResponse(status_code=200 if sync else 202, content=result)

@app.get("/api/auto-loop/{task_id}")
def api_auto_loop_status(task_id: str) -> dict[str, Any]:
    try: return rt.auto_loop_status(task_id)
    except KeyError as exc: raise _not_found(str(exc)) from exc
```

---

## 2. 自测证据（命令 → 输出关键行 → 结论）

> 所有命令在 `K:\work\project\pixo` 下执行（`python -m pytest` 由 `tests/conftest.py` 保证 `src` 入 `sys.path`）。
> 探针脚本在仓库外：`D:\tmp\pixo_r21_dev1_probe.py`（`%TEMP%`，不落仓库产物）。

| # | 验收条目 | 命令 | 输出关键行 | 结论 |
|---|----------|------|------------|------|
| E1 | F02① 规则注入非空（11 条，含 `region_rules` 双引用键不抛 `DecideError`） | `python D:\tmp\pixo_r21_dev1_probe.py` | `"rules_count": 11`；`"rules_ids": [exposure_rule_001, highlight_protect_rule_002, crop_suggest_rule_003, dehaze_rule_030, clarity_flat_rule_031, shadow_open_rule_032, highlight_recover_rule_033, vibrance_low_rule, saturation_high_rule, region_sky_exposure_001, region_plant_exposure_002]` | ✅ 6 个规则文件 11 条全加载，显式 `metric_keys=metric_universe(...)` 生效 |
| E2 | F02② `PIXO_RULES=off`（及 0/false/no 任意大小写）→ 空 | `python -m pytest tests/integration/test_auto_loop_api.py -q -k "rules"` | `8 passed, 10 deselected`；探针 `"rules_off": []` | ✅ 开关生效 |
| E3 | F02③ 库层缺省保持空（不改 `loop.py`） | 同上 + 探针 | `"lib_default_rules": []`（`SinglePhotoLoop()` → `rules == []`） | ✅ 库层语义未动 |
| E4 | F01① 闭环跑通（注入假 backend + MockSegmenter，**不跑真 RAW**） | `python -m pytest tests/integration/test_auto_loop_api.py -q -k "run_auto_loop or auto_loop_rule_ids or env_overrides"` | `5 passed, 13 deselected`；探针任务体：`"status":"done"`,`"state":"ACCEPTED"`,`"iteration":2`,`"params":{"dehaze":{"strength":0.15,"enabled":true},"colorcal":{"vibrance":0.3}}`,`"rule_ids":["dehaze_rule_030","vibrance_low_rule"]`,`"trace_event_count":13`,`"error":null`,`"duration":0.484` | ✅ 状态/params/rule_ids 提取正确（`manual_on_unreliable=False` 生效：state=ACCEPTED 而非 MANUAL_REVIEW） |
| E5 | F01② `rule_ids` **必须**取最后一条 decide trace（反例锚定 `LoopResult.decision` 是状态串） | 同上 | `test_auto_loop_rule_ids_takes_last_decide_event` PASSED（两条 decide：`["old_rule"]` → `["r1","r2"]`，取后者） | ✅ 提取口径正确 |
| E6 | F01③ 每 photo 单飞（同 photo 二次提交 → 既有 task_id） | 同上 | 探针 `"single_flight_same_task": true`；测试用闸门 backend 确定性验证「任务终结后再提交得到新 task_id」 | ✅ 单飞 + 终结清除 |
| E7 | F01④ `max_iterations` 硬上限 5 / 非法 400；photo 404；env 覆盖 | 同上 | 探针 `"illegal_max_iterations": ["0:ValueError","-1:ValueError","6:ValueError","2.5:ValueError","'3':ValueError","True:ValueError"]`；`"unknown_photo":"KeyError"`；`"env_default_2":2`,`"env_default_99":5`,`"env_default_abc":3` | ✅ 参数校验/上限/env 覆盖齐备 |
| E8 | F01⑤ HTTP 真实往返 POST→202→GET→done + 失败语义（404/400/sync=200/内部异常不 500） | `python -m pytest tests/integration/test_auto_loop_api.py -q -k "http or internal_error"` | `3 passed, 15 deselected`；202 body：`{task_id,status:"running",photo_id,segmenter_type:"mock",degraded:["mock_segmenter"]}`；GET 到 `status=done`；`sync=true` → HTTP 200 且 `get.json() == post.json()`；坏 backend → 异步与 sync 两路均 `status=failed` + `error="RuntimeError: boom-render"`（无 500） | ✅ HTTP 层证据齐备（D5 要求） |
| E9 | F03① `decide_photo` 同 FakeSession fixture 下 `params` 非空、字段集合不变 | `python -m pytest tests/integration/test_auto_loop_api.py -q -k "decide_photo or proxy"` | `2 passed, 16 deselected`；探针 `"decide_field_set": [decision, iteration, measurement, photo_id, state]`；`"decide_rule_ids": [dehaze_rule_030, shadow_open_rule_032, vibrance_low_rule, region_plant_exposure_002]`；`"decide_params": {dehaze.strength:0.15, tone.shadows:0.05, vibrance.strength:0.3, region.plant.exposure:0.2}` | ✅ 服务层 decide 不再零触发，字段集合未变 |
| E10 | F03② `measurement` **顶层**有 proxies 三键（追加式） | 同上 | 探针 `"measure_top_keys": ["colorfulness_proxy","haze_proxy","tonal_range"]`；既有 `"global"`/`"regions"`/`mask_version=="mask_v0.1"` 仍在 | ✅ 顶层同层（非 `global` 下） |
| E11 | 本流定向测试全绿 | `python -m pytest tests/integration/test_auto_loop_api.py -q` | `18 passed, 1 warning in 29.74s` | ✅ |
| E12 | 邻居回归（服务层既有 8+ 用例 + `last_decision` 断言） | `python -m pytest tests/integration/test_service_api.py tests/unit/test_service_runtime_fixes.py -q` | `21 passed, 1 warning in 32.37s` | ✅ 既有契约未破（含 `photo.last_decision == result["decision"]`） |
| E13 | 集成目录整体（非全量回归，含本次新增 18 用例） | `python -m pytest tests/integration -q` | `152 passed, 12 warnings in 86.52s`（最终代码上复跑；另有 89.95s 一次同结果） | ✅ 集成面无回归 |

**关键实测数值（供 tester/QA 复核 F01 口径）**：注入假 backend 的闭环（64px 合成暗图 + MockSegmenter + 2 轮）`state=ACCEPTED, iteration=2, trace_event_count=13, duration≈0.34–0.48s`；命中 `dehaze_rule_030` + `vibrance_low_rule`（**proxy 驱动**，可证测量顶层 proxies 链路已通）。

---

## 3. 与 design 的偏差（逐条给理由）

| # | design 原文 | 实现 | 理由 |
|---|-------------|------|------|
| D1 | `run_auto_loop(..., max_iterations: int = 3, ...)` | `max_iterations: int \| None = None`（None → env `PIXO_LOOP_MAX_ITERATIONS` 或 3） | 字面默认值 3 无法区分「调用方未传」与「显式传 3」，而 env 覆盖只应作用于**缺省**。语义（缺省 3 / 硬上限 5 / 显式非法 ValueError）与 design 完全一致，仅签名默认值表达方式不同。 |
| D2 | env 覆盖缺省；显式非法 → `ValueError`（design 未规定 **env 本身**非法/超上限怎么办） | env 非整数 → 告警 + 回退 3（复用既有 `_env_int`）；env > 5 → 告警 + 裁剪到 5；显式实参仍严格 `ValueError` | env 是运维旋钮，抛异常会在服务运行期打断请求；裁剪/回退与既有 `PIXO_MAX_SESSIONS` 处置同风格。已实测：`2→2`、`99→5`、`abc→3`。 |
| D3 | GET 结果 8 键 + 响应带 `segmenter_type` | GET/sync 视图 = 设计 8 键 + `photo_id` + `segmenter_type` + `duration`；`segmenter_type=="mock"` 时附 `degraded:["mock_segmenter"]` | 全为**追加**键：`segmenter_type`/`degraded` 是 design §2.2 规则 3 明确要求；`duration` 对应 §7 D4「`max_iterations ≤ 5` + `duration` 落任务结果」。设计列出的 8 键一字未改。 |
| D4 | POST body 可选 `{"sync": true, "max_iterations": n}`（未规定解析方式） | `await request.body()` + `json.loads`：空 body → `{}`；非法 JSON → 400；非对象 → 400 | 仓库既有路由用 `await request.json()`，遇**空 body** 会抛 `JSONDecodeError` → 500，与「body 可选」冲突；本实现让「裸 POST」得到 202。已实测裸 POST 与 `{"max_iterations":0}`（400）两种路径。 |
| D5 | 闭环内部异常 → `status=failed` + `error`（异步与 sync 一致） | 额外把**结果提取**（`result.state/params/rule_ids/trace_event_count`）也放进同一 `try` | 鲁棒性：若提取环节异常而落在 `try` 外，任务会永久卡在 `running`（轮询永不终态）。行为对成功路径零差异。 |
| D6 | `merge_proxy_metrics(measurement, image)`「原地+返回」 | `merged = merge_proxy_metrics(...)`；`isinstance(merged, dict)` 才重新赋值 | 同时兼容原地与返回副本两种实现（dev-2 实际为原地+返回同对象，已读源码确认 `metrics.py:140-143`）。 |
| D7 | `metrics.py` 由 dev-2 并行交付 | `pixo.pipeline.metrics` 全部用**函数内惰性 import**；而 `RawRenderBackend` 在 `runtime.py` **模块顶层** import | 前者是任务书明确的等待策略（避免交付时序耦合）；后者是测试可注入性需要（`monkeypatch.setattr(pixo.service.runtime, "RawRenderBackend", ...)`），且 `service → pipeline` 依赖方向合规（exploration §6.5）。 |

> **不构成偏差的说明**：`PIXO_RULES` 解析用 `str.strip().lower()`，覆盖 design 的「任意大小写」；`decide_photo` 未读 preview session 变化（仍走既有 `sessions[-1]`）；auto-loop **不读 session / `canonical_params`**（§2.3/§6.12 已按要求）。

---

## 4. 遗留问题（范围外，仅登记，未处理）

1. **tech_debt #21（design D3 已裁决登记）**：auto-loop 不回写 `runtime.state_machines` / `photo.last_decision` ⇒ 跑完 `ACCEPTED` 后 `GET /api/photos/{id}/timeline` 仍显示 `RAW_PENDING`、`GET /decide` 缓存与 auto-loop 不联动。本轮按 design §2.3「不回写任何既有缓存」执行。
2. **tech_debt #22（design D4 已裁决登记）**：无任务级超时/取消。可控手段 = `max_iterations ≤ 5` + `preview_long_edge`；本流已在任务结果落 `duration` 供观测。
3. 任务表 `_auto_loop_tasks` **无淘汰**（与 `ExportManager._tasks` 同现状）：长跑服务下会无界增长；建议后续统一加清理/上限（本轮不改，跨流）。
4. **不同 photo 的任务共用 `max_workers=1` 队列**：第二个 photo 提交后状态即 `running`，但实际在排队（无 `queued` 态）。单飞只保证「同 photo 不重跑」，不保证「不同 photo 的排队可见性」；如需精确进度需引入排队态（本轮不做，设计未要求）。
5. 服务缺省 `PIXO_SEGMENTER=mock` ⇒ auto-loop 默认拿到**合成掩码**，结论不可信（已按 design §2.2 规则 3 在响应里带 `segmenter_type="mock"` + `degraded:["mock_segmenter"]` 留痕）。真路由需运维设 `PIXO_SEGMENTER=multi`；本流**未改**服务缺省（改缺省会影响既有 region 供给/测量线，属越界）。
6. 前端仍零改动：`frontend/src/api/client.ts:157` 的 `decidePhoto` 零调用，新端点未接前端（非目标）。
7. `tests/regression/conftest.py` 会把 gate 内 skip 转 fail（仅 `gate_e2e` 豁免）——F05 新门禁必须 `pytestmark = pytest.mark.gate` + 用例级 `@pytest.mark.gate_e2e` **两个都写**（design §4 已写明，此处复述给 tester）。
8. **边界提示（不是缺陷）**：`decide_photo` 在**无 session** 时走 `metrics_for_decide({})`（6 键全 `None`）+ 规则集非空；引擎对 `None` 指标短路不触发（`engine.py:360-362`），故 `test_evicted_photo_decide_no_keyerror` 仍绿（E12 已证）。
9. 任务书 §「现状」表里「`0711\raw` 下 765 个 NEF（brief 原写 3428）」的口径不符仍留在 `task-brief.md`，未修（文档属队长域）。

---

## 5. 给 tester / QA 的直接接口（避免二次摸索）

- 规则加载（F05 gate 装配可直接复用）：`from pixo.service.runtime import _load_auto_loop_rules` → `_load_auto_loop_rules(("face","sky","plant"))`（`PIXO_RULES=off` 时返回 `[]`）。
- 端点：`POST /api/photos/{photo_id}/auto-loop`（body 可空；`{"sync":true,"max_iterations":n}`）→ 202/200；`GET /api/auto-loop/{task_id}` → `status ∈ {running,done,failed}`。
- 任务结果字段：`task_id / status / photo_id / segmenter_type / state / iteration / params / rule_ids / rule_ids_by_iteration / trace_event_count / error / duration`（+ mock 时 `degraded`）。其中 `rule_ids` = 全 decide 事件并集（修订 R1），`rule_ids_by_iteration` = `[{"iteration": int, "rule_ids": [str,...]}, ...]` 诊断分布。
- 测试可注入点：`monkeypatch.setattr("pixo.service.runtime.RawRenderBackend", <factory(raw_path, prof) -> backend>)`，factory 返回的对象需实现 `render_preview(params, long_edge=)` / `render_full(params)` / `full_size()`（可包 `pixo.pipeline.loop.SyntheticRenderBackend`）。
- 复现证据：`python -m pytest tests/integration/test_auto_loop_api.py -q`（20 passed，含修订 R1 用例）。

---

# 修订 R1 — `rule_ids` 提取口径改并集（队长裁决，2026-09-10）

> **背景（归因已按队长/QA 更正，见 R1.4）**：tester 真 RAW 首跑 F05 门禁 FAILED（102.90s），根因 = 本流 `_auto_loop_rule_ids()` 逐条 decide 事件**覆盖赋值** ⇒ 取「最后一条」decide；而闭环收敛后**末轮规则自然不命中**（首轮 `saturation_high_rule` 命中后指标回落）⇒ 该轮 `rule_ids=[]` ⇒ 真 RAW 常规路径下取「最后一条」结构性为空。**末轮照常评估规则、不短路**（`last_iteration` 分支 `should_stop=False`，`engine.py:977-989`/`1165-1173`）；**engine 与 loop 一行未改**。
> **队长裁决**：只改服务层提取口径。**约束遵守**：未改 `src/pixo/pipeline/**`、`src/pixo/decide/**`、`tests/regression/**`、design 文档；未提交 git。

## R1.1 改动（增量）

| # | 文件（域内） | 改动 |
|---|--------------|------|
| 1 | `src/pixo/service/runtime.py` | `_auto_loop_rule_ids(result)` → **全部** `event_type=="decide"` 事件 `value["rule_ids"]` 的**并集**（首次出现顺序、去重），返回 `list[str]`；新增 `_auto_loop_decide_events(result)`（取 `(iteration, rule_ids)`，iteration 取 `value["iteration"]`，缺失回退 `metadata["iteration"]` 再回退序号）与 `_auto_loop_rule_ids_by_iteration(result)` |
| 2 | `src/pixo/service/runtime.py` | 任务记录 + GET/sync 视图**追加** `rule_ids_by_iteration: [{"iteration": int, "rule_ids": [str,...]}, ...]`（**纯追加**：设计列出的既有键一个不少、不改名） |
| 3 | `tests/integration/test_auto_loop_api.py` | 原「取最后一条」用例改为**并集口径**用例（含顺序/去重 + `rule_ids_by_iteration` 断言）；**新增** 1 条端到端用例（假 backend 状态化渲染 + 单条确定规则）复现 tester 的 trace 形态；既有 3 条用例补 `rule_ids_by_iteration` 断言 |

`_auto_loop_rule_ids()` 关键 diff：

```diff
-        rule_ids: list[str] = []
-        for event in result.trace_events or []:
-            if event.get("event_type") != "decide":
-                continue
-            value = event.get("value")
-            ids = value.get("rule_ids") if isinstance(value, dict) else None
-            rule_ids = [str(r) for r in (ids or [])]      # ← 覆盖赋值 = 只留最后一条
-        return rule_ids
+        merged: list[str] = []
+        seen: set[str] = set()
+        for _iteration, ids in cls._auto_loop_decide_events(result):
+            for rule_id in ids:
+                if rule_id not in seen:                    # 首次出现顺序 + 去重
+                    seen.add(rule_id)
+                    merged.append(rule_id)
+        return merged
```

## R1.2 自测证据（命令 → 输出关键行 → 结论）

> 按队长要求：输出重定向到文件再读，不接 `| Select-Object`。

| # | 项 | 命令 | 输出关键行 | 结论 |
|---|----|------|------------|------|
| R1-E1 | 定向测试全绿（20 passed，归因更正后最终口径） | `python -m pytest tests/integration/test_auto_loop_api.py -q > D:\tmp\r21_dev1_rev1_final.txt 2>&1` | `20 passed, 1 warning in 33.45s`（`exit=0`） | ✅ 15 个测试函数 / 20 用例（含 R1 新增 2 条）全绿 |
| R1-E2 | tester 真 RAW 失败形态**精确复现**（首轮命中、末轮自然空） | `python D:\tmp\pixo_r21_dev1_rev1_probe.py` | `"rule_ids_by_iteration": [{"iteration":1,"rule_ids":["test_shadow_open_once"]},{"iteration":2,"rule_ids":[]}]`；`"NEW_rule_ids_union": ["test_shadow_open_once"]`；`"OLD_rule_ids_last_only": []`；`state=ACCEPTED, iteration=2, params={"tone":{"shadows":0.05}}` | ✅ 同一 trace 上：旧口径空（= tester FAILED 现象）、新口径非空 |
| R1-E3 | 并集口径（顺序 + 去重） | 同 R1-E1（用例 `test_auto_loop_rule_ids_union_across_decide_events`） | trace = `decide#1["a_rule"] → decide#2[] → decide#3["b_rule","a_rule"]`；断言并集 `== ["a_rule","b_rule"]`、逐轮 `== [{1:["a_rule"]},{2:[]},{3:["b_rule","a_rule"]}]` | ✅ 首次出现顺序 + 去重 |
| R1-E4 | 端到端（假 backend）复现形态用例 | 同 R1-E1（用例 `test_auto_loop_rule_ids_nonempty_when_last_round_naturally_empty`） | 假 backend 第 1 次 preview 全黑（`shadow_clip_ratio=1.0 ≥ 0.18`）→ 命中 `test_shadow_open_once`；其后 0.5 灰 → 末轮指标回落、自然不命中；断言 `by_iteration[-1]["rule_ids"] == []` 且 `rule_ids == ["test_shadow_open_once"]` | ✅ 经 `run_auto_loop` 全链路复现（非纯桩） |
| R1-E5 | 新字段在 HTTP/GET 与 sync 视图可见 | 同 R1-E1（HTTP/sync 用例内断言） | GET 结果与 `sync=true` 200 结果均 `assert task["rule_ids_by_iteration"]` 通过 | ✅ 追加字段贯通两路 |
| R1-E6 | **末轮不短路**（归因更正的核心证据） | `python D:\tmp\pixo_r21_dev1_rev1_trace_probe.py` | `decide_events[1] = {"iteration":2,"decision":"adjust_and_continue","last_iteration":true,"rule_ids":[]}`；`decide_events[0] = {"iteration":1,"decision":"adjust_and_continue","last_iteration":null,"rule_ids":["test_shadow_open_once"]}`；`loop_state=ACCEPTED, loop_iteration=2` | ✅ 末轮 `decision=adjust_and_continue`（非 stopped/manual_review ⇒ 未走 `engine.py:1147-1163` 短路）+ `last_iteration=True`（`engine.py:977-989`）⇒ **规则照常评估后自然不命中** |
| R1-E7 | 库层用例钉死同一机制 | 同 R1-E1（用例 `test_last_round_evaluates_rules_before_natural_miss`） | 直跑 `SinglePhotoLoop` 取真 `LoopResult`：断言末轮 decide `last_iteration is True` 且 `decision == "adjust_and_continue"` 且 `rule_ids == []`，同时服务层并集 `== ["test_shadow_open_once"]` | ✅ 「末轮自然不命中 ≠ 终止轮必空」写进断言（不再把空值当不变量） |

**注**：R1 的失败/成功形态均由「假 backend + 单条确定规则」构造，**不跑真 RAW**（真 RAW 端到端归 tester 的 F05 门禁）。R1 早期一次 `19 passed`（`D:\tmp\r21_dev1_rev1_test.txt`，归因更正前）保留为过程记录；最终口径为 R1-E1 的 `20 passed`。

## R1.4 归因更正（队长/QA 更正 → 本流已对齐，行为未改）

| 项 | 更正前（**错误**） | 更正后（**正确**，已落地到注释与断言） |
|----|--------------------|----------------------------------------|
| 末轮为何 `rule_ids=[]` | 「`iteration >= max_iterations` 走到 `check_termination` 短路，`engine.py:1147-1163` 返回 `[]`」 | 「`iteration >= max_iterations` 走 `last_iteration` 分支且 **`should_stop=False`**（`engine.py:977-989`，t107 注释：末轮规则**必须**跑一次）⇒ `decide()` **不短路**，照常 `_apply_rules_internal`（`engine.py:1165-1173`）；末轮空是因为**规则自然不命中**（首轮 `saturation_high_rule` 由 `colorfulness_proxy` 6.19 ≥ 6.13 命中写入 `saturation=-0.15`，末轮降到 5.8936 < 6.13）」 |
| `engine.py:1147-1163` 短路 | 本次失败的原因 | **另一条**合法空路径（manual_review / stopped / targets_met 等判停），**本次真 RAW 未触发**；引擎语义正确，未改 |
| 结论 | —— | 并集口径修复方向不变；**「终止轮必空」不得写成不变量**（末轮照跑规则） |

- 代码注释对齐：`src/pixo/service/runtime.py` 的 `_auto_loop_rule_ids()` docstring 已改为上述正确表述（含 6.19→5.8936 实例与两条空路径的区分）；**行为零改动**（QA 复核点 `runtime.py:993-1054` 的并集实现未改）。
- 用例规格对齐：R1-E4 的 docstring/断言措辞由「终止轮必空」改为「末轮**自然不命中**」；新增 R1-E7 用 `last_iteration=True` + `decision=="adjust_and_continue"` 正面钉死「末轮不短路」。

## R1.5 给 tester 的复核提示（F05 断言口径）

- `rule_ids` 现在 = **整轮闭环落地过的规则并集**，真 RAW 上应为 `["saturation_high_rule", ...]` 这类非空集合；逐轮分布看 `rule_ids_by_iteration`（**末轮为空是正常收敛，不是失败**）。
- 若 F05 断言仍写「最后一条 decide 的 rule_ids 非空」，会在收敛样本上误报失败 —— 请改用任务结果里的 `rule_ids`（并集），或对 trace 自行取并集；**不要**把「末轮 rule_ids 必空」写成断言（末轮照常评估规则，若指标未回落仍会命中）。
- 其余交付面（端点/字段/404·400·failed 语义/单飞/`_load_auto_loop_rules`）未变，第 2 节 E1~E13 结论继续有效。


