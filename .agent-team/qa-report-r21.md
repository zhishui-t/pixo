# QA 总审报告（qa-report-r21.md）— Pixo 第二十一轮（R21）闭环插电 M0

> 角色：`QA-checker`（阶段 8：交付总审 + 门禁执笔）｜产出时间 2026-09-10｜工作目录 `K:\work\project\pixo`（Windows / PowerShell）
> 依据：`.agent-team/design-r21.md`（含 §7 契约修订 R1，唯一实现依据）、`task-brief.md`、`docs/R21_CHANGE_REQUESTS.md`（CR-01~05）、`team-manifest.md`（门禁定义）、`.agent-team/test-report-r21.md`、`streams/r21-stream-1.md`/`-2.md`
> 方法：**全部结论来自本会话独立复跑与只读回读**（不采信任何报告结论本身）；命令输出一律经 `cmd /c "set PYTHONIOENCODING=utf-8&& python … > 文件 2>&1"` 落 UTF-8 再读（规避 PS 5.1 `*>` 写 UTF-16 与本机 `| Select-Object` 假 exit 1 两个陷阱）；真 RAW 全分辨率渲染全程**串行**（无并发 pytest/探针）。
> 范围：只审交付物；本轮 QA **未改产品代码**（`src/**` 零改动），仅做 2 处测试 docstring 措辞修复 + 1 处证据脚本勘误（§6）。

---

## 0. 一句话结论

**通过（修复后通过），0 阻塞项。** F01~F05 对 CR-01~05 与 brief 完成标准 1~6 全部满足且有用例/运行证据；**全量回归 1574 passed / 0 failed**（红线 1533）、**金样本零漂移**（合成 gate 7 passed + 真 RAW 24 case 逐位一致 `u8_max=0/u16_max=0`）、**F05 真 RAW 门禁 2 passed**；QA 独立复现了 D1 反例样本与 D2 观测，并揪出 1 处**证据脚本误标**（已勘误，结论不变）。

---

## 1. 审核范围与独立取证方式

| 类别 | 内容 |
|---|---|
| 被审代码（4 个改动文件） | `src/pixo/service/runtime.py`（+394/-3）、`src/pixo/service/app.py`（+48/-1）、`src/pixo/pipeline/loop.py`（+8/-30）、`src/pixo/pipeline/batch.py`（+30/-0）、`src/pixo/pipeline/metrics.py`（新建 153 行） |
| 被审测试（4 个新文件） | `tests/integration/test_auto_loop_api.py`（20 用例 / 594 行）、`tests/unit/test_metrics_for_decide_public.py`（14）、`tests/unit/test_scorer_adapter_callable.py`（6）、`tests/regression/test_gate_auto_loop_e2e.py`（2，367 行） |
| 独立复跑 ① 全量 | `python -m pytest tests -q -m "not e2e"` → **1574 passed / 0 failed**（跑两次：251.99s、212.66s） |
| 独立复跑 ② 门禁 | `$env:PIXO_GATE_AUTOLOOP_RAW='K:\data\photo\0711\raw\DSC_5236.NEF'; python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate -s -rA --durations=5` → **2 passed in 124.06s** |
| 独立复跑 ③ 金样本 | `python -m pytest tests/regression/test_gate_golden.py -q` → **7 passed in 26.94s**；`python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512` → **RESULT: PASS（24/24 case，u8_max=0/u16_max=0）**，且 `git status -- data` 零改动 |
| 独立复跑 ④ 定向 | `python -m pytest tests/integration/test_auto_loop_api.py tests/unit/test_metrics_for_decide_public.py tests/unit/test_scorer_adapter_callable.py -q` → **40 passed in 26.69s** |
| 独立复算 ⑤ D1 反例 | 自写只读探针 `tmp-qa-r21-d1-recheck.py` 复算 DSC_5237 / DSC_5238（与门禁同装配）→ 见 §5.1 |
| 独立复算 ⑥ D2 观测 | 自写只读探针 `tmp-qa-r21-d2-probe.py` → 见 §5.2 |
| 未独立复跑（据实声明） | ① tester 的 DSC_5236 完整 3 样本探针（我用门禁 + 自算 5237/5238 覆盖其结论）；② 单 RAW gate manifest（8 features）compare —— 其 `raw` 指向已消失的 `K:\data\photo\corpus_a\...`（遗留 §7.6，本轮不可复跑） |

---

## 2. 代码检视结论（逐文件，重点项已逐条核验）

### 2.1 `src/pixo/service/runtime.py`（dev-1）

| 检查项 | 结论 | 证据 |
|---|---|---|
| `_load_auto_loop_rules` 装配层规则注入 + `PIXO_RULES` 关 | ✅ | 定义 `runtime.py:152-175`：`strip().lower() ∈ {0,false,off,no}` → `[]`；否则 `metric_universe(prompts)` + 逐文件 `load_rules(path, metric_keys=universe)`（**显式键宇宙**，design §2.2 规则 1） |
| 库层 `SinglePhotoLoop(rules=None)` 保持空（F02 硬约束） | ✅ | 未触碰 `loop.py:770`；`test_loop_layer_default_rules_stay_empty` 20 passed 内 |
| `manual_on_unreliable=False` 真落地 | ✅ | `runtime.py:416`（`SinglePhotoLoop(... manual_on_unreliable=False ...)`）；门禁真 RAW 实测 `state=ACCEPTED`（若为缺省 True，sky/plant/face 三区域不可靠会首轮 MANUAL_REVIEW） |
| `render_backend=RawRenderBackend(photo.path, self.profile)` 且不依赖 session | ✅ | `runtime.py:407`；`run_auto_loop` 只用 `photo.path`，不读 `sessions`/`canonical_params`（对齐 exploration §6.12） |
| 每 photo 单飞 | ✅ | `runtime.py:299-307` 锁内查 `_auto_loop_active[photo_id]`，running → 返回既有 task_id；终结时锁内清除 `:453-454`；`test_run_auto_loop_async_ok_and_single_flight` 用闸门 backend 确定性验证（含"终结后再提交得新 task_id"） |
| `rule_ids` 并集口径 + 首现序 + 去重 | ✅ | `runtime.py:1021-1041`（`merged`/`seen` 循环）；R1 前的"覆盖赋值"已删除；`test_auto_loop_rule_ids_union_across_decide_events` 用 `["a"]→[]→["b","a"]` 断言 `["a","b"]` |
| `rule_ids_by_iteration` 与并集自洽 | ✅ | `runtime.py:993-1019/1043-1054`；门禁断言⑥实测 `service_union == merged == gate_union` 且逐轮与 trace `decide` 一一对应 |
| 内部异常不裸抛 500（异步 + sync 两路） | ✅ | `_execute_auto_loop:405-442` catch-all → `status=failed` + `error=类型:首行`（提取也在同一 try 内，不会卡 running）；`test_auto_loop_internal_error_no_500` 两路各 202/200 + `failed` |
| `max_iterations` 校验与硬上限 | ✅ | `_validate_max_iterations`（bool/非 int/≤0/>5 → ValueError→400）、`_auto_loop_default_iterations`（env 覆盖、非法回退 3、超限裁 5） |
| 任务表字段纯追加 | ✅ | `:847-861` 初始化 + `_auto_loop_submit_view:887-897` + `_auto_loop_view:899-921`；design 列的既有键一个不少、不改名 |
| F03 接线：proxies 顶层合并时机 | ✅ | `measure_session` 内 `merge_proxy_metrics(measurement, image)` 在回写 `photo.last_measurement` **之前**（diff hunk `@@ -621,6 +710,16 @@`） |
| F03 接线：`decide_photo` 展平 + 传 rules、字段集合不变 | ✅ | `decide({"metrics": metrics_for_decide(measurement), ..., "rules": _load_auto_loop_rules(...)})`；`test_decide_photo_params_nonempty` 断言字段超集 + `rule_ids`/`params` 非空；既有 `test_service_api.py`/`test_service_runtime_fixes.py` 零回归（全量 1574 内） |
| 架构红线：service → pipeline 单向 | ✅ | `runtime.py` 顶部 import `RawRenderBackend`（测试可注入点，dev-1 D7 已说明）；`pipeline/**` 未反向 import service（见 2.4） |

### 2.2 `src/pixo/service/app.py`（dev-1）

- 新增 `POST /api/photos/{photo_id}/auto-loop`（`app.py:249-285`）：`await request.body()` + `json.loads`（空 body → `{}`；非法 JSON → 400；非对象 → 400），`run_in_threadpool` 调 `rt.run_auto_loop`，`KeyError→404`、`ValueError→400`，`JSONResponse(status_code=200 if sync else 202)` ✅（design §2.2 契约）。
- 新增 `GET /api/auto-loop/{task_id}`（`:286-290`）：`KeyError→404` ✅。
- 路由风格与既有 `api_submit_export`/`api_decide` 一致（`run_in_threadpool` + `_not_found`/`_bad_request`）✅。

### 2.3 `src/pixo/pipeline/metrics.py`（dev-2，新建）

- **无 `pixo.service` 依赖** ✅（源码仅 import `collections.abc`/`typing`/`pixo.vision.measure`；`test_metrics_module_does_not_import_service` 正则守卫）。
- `metrics_for_decide` 与旧 loop 实现逐键一致 ✅（对**冻结期望 dict** 断言，非与 wrapper 自比）；代理键仅顶层存在时产出；region `reliable` 强转 bool；非 Mapping → `{}`（`Mapping` 判定比旧 `dict` 略宽，dev-2 D-1 已申报，生产唯一调用点传 dict ⇒ 行为不变）。
- `METRIC_KEYS` = 10 键（6 global + 3 代理 + `crop_suggestion_applicable`），`metric_universe(prompts)` = ∪ 区域键 ✅；**显式传键宇宙**是 F02 装配不抛 `DecideError` 的必要条件（负控实测：只传 `METRIC_KEYS` 必抛）。
- `merge_proxy_metrics` 原地 + 返回同对象、顶层落位 ✅（`test_merge_proxy_metrics_lands_on_measurement_top_level` 断言 `out is measurement` 且键不在 `global` 下）。

### 2.4 `src/pixo/pipeline/loop.py` / `batch.py`（dev-2）

- `loop.py`：展平实体迁出，`_metrics_for_decide` 变**薄 wrapper**（`loop.py:522-529`），模块内调用点语义不变；`pipeline/__init__`/`__all__` 未动（避免跨文件域）✅。
- `batch.py`：**仅新增** `_PixoScorerAdapter.__call__`（`batch.py:412-438`），返回 `{"overall", **dimensions, "source", "raw_overall", "domain_hint"}`；`.score(image_rgb, meta)` 签名与实体**零改动**（diff 为纯插入）✅；返回 dict 是**必需**而非风格（反面对照 `test_call_returns_dict_not_dataclass_and_floats_cleanly` + `test_callable_contract_is_load_bearing_for_loop` 固化"去 `__call__` 即静默丢分"）。

### 2.5 四个新测试文件

- `test_auto_loop_api.py`（20 用例）：覆盖 F02 规则注入/关闭（含 6 种 env 取值）、库层缺省空、异步闭环 + 单飞、sync 同构、并集口径（含去重/首现序）、**末轮自然不命中**形态（假 backend 状态化渲染复现真 RAW trace）、末轮不短路（直跑真 `LoopResult` 断言 `last_iteration=True` + `adjust_and_continue`）、非法入参/未知 photo、env 覆盖、HTTP 202→GET→done、sync=200、内部异常不 500、`decide_photo` 非空、proxies 顶层 ✅（F01/F02/F03 逐条落点，断言均非空转）。
- `test_metrics_for_decide_public.py`（14）：含**冻结期望**全等、区域引用解析的反向护栏（确保测试真取到 `sky_*`/`plant_*`）、`METRIC_KEYS` 是 universe 真子集、6 文件 11 条全加载、架构/导入来源守卫 ✅。
- `test_scorer_adapter_callable.py`（6）：`__call__` 契约本体（dict/float 不抛/溯源字段）+ 双参容忍 + None 防御 + `.score` 签名不变 + 跨层注入 loop（`final_measurement["aesthetic"]` 非空、每轮 measurement 亦带）+ `suggest_crop` 的 `parts.scorer is not None`（明确**不用**"非 fallback"）+ 反向护栏 ✅。
- `test_gate_auto_loop_e2e.py`（2）：文件级 `pytestmark=gate` + 用例级 `gate_e2e`（`-m gate` 可选中、无 env 时 skip 不被 conftest 转 fail —— 两件都已实测）；真 RAW 五条断言 + 断言⑥聚合自洽 + 断言⑦负控镜像；DSC_5236 专属形态只在该语料上才断言（**未**把"末轮必空"写成不变量）✅。

---

## 3. 独立复跑证据（命令 → 关键输出）

### 3.1 全量回归（红线 1533）——PASS

```
python -m pytest tests -q -m "not e2e"
1574 passed, 6 skipped, 1 xfailed, 13 warnings in 212.66s   ← QA 终态复跑（FIX-1/2 之后）
（同一命令早前一次：1574 passed, 6 skipped, 1 xfailed, 13 warnings in 251.99s）
```
- 与 tester 报告（`tmp-r21-fulltest.txt`：1574/6/1）**逐项一致**；+41 的构成可自洽核对：dev-1 20 + dev-2 14 + dev-2 6 + tester 门禁负控镜像 1（真 RAW e2e 无 env 时 skip）。
- skipped 6 = R20 的 5 + 新增 F05 e2e（`gate_e2e` 豁免）；`failed=0`。

### 3.2 F05 真 RAW 门禁——PASS（2 passed in 124.06s）

```
[R21-F05] {"state": "ACCEPTED", "reason": "FINAL_QC 达标；preview 终止: 达到最大迭代轮数 (2)", "iteration": 2,
 "rules_count": 11, "params": {"colorcal": {"saturation": -0.15}}, "rule_ids": ["saturation_high_rule"],
 "rule_ids_last_nonempty": ["saturation_high_rule"], "trace_event_count": 12, "measurements": 2,
 "has_param_update": true, "highlight_clip_ratio": 0.025923, "colorfulness_proxy": 9.2987, "segmenter_last_degraded": []}
[R21-F05-decide-events] [{"iteration": 1, ..., "rule_ids": ["saturation_high_rule"], "last_iteration": false, "colorfulness_proxy": 6.1888},
 {"iteration": 2, ..., "rule_ids": [], "last_iteration": true, "colorfulness_proxy": 5.8936}]
[R21-F05] baseline_pixel_diff=56293263
[R21-F05-rule-ids-by-iteration] [{"iteration": 1, "rule_ids": ["saturation_high_rule"]}, {"iteration": 2, "rule_ids": []}]
2 passed in 124.06s
```
- 断言①~⑦全绿；`baseline_pixel_diff=56,293,263`（与 tester 报告数字**完全一致**）；唯一的 segmenter 告警是 `sapiens`/`uniface` 许可未注册 + `face` 零掩码降级（与"不设 `PIXO_ALLOW_RESTRICTED`"一致，非失败）。

### 3.3 金样本零漂移——PASS

```
python -m pytest tests/regression/test_gate_golden.py -q      → 7 passed in 26.94s
python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json \
  --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512
  → feature/sample 表 24 行全部 u8_max=0 / u16_max=0 → RESULT: PASS
  → git status -- data = 0 行（基线未被改写）
```

### 3.4 定向测试——PASS（40 passed）

```
python -m pytest tests/integration/test_auto_loop_api.py tests/unit/test_metrics_for_decide_public.py tests/unit/test_scorer_adapter_callable.py -q
40 passed, 1 warning in 26.69s        （20 + 14 + 6）
```

---

## 4. 需求逐条核对（F01~F05 × CR-01~05 × brief 完成标准）

| 条目 | 判定 | 证据 |
|---|---|---|
| **F01** 闭环生产入口（CR-01） | ✅ 满足 | `run_auto_loop` + 两端点落地；202→GET→done、sync=200 同构、404/400/failed 语义、单飞 均有 HTTP 真实往返用例（`test_auto_loop_*_http_*`）；`iteration=2 ≥ 2`、`rule_ids` 非空；CR-01 原"curl 手测真 NEF"由 F05 门禁 + TestClient 往返替代（**D5 队长已同意**）。`decide_photo` 单轮语义与响应字段保留（`test_decide_photo_params_nonempty` 断言字段超集） |
| **F02** 默认规则注入可关（CR-02） | ✅ 满足 | 装配层 11 条（6 文件）全加载；`PIXO_RULES ∈ {0,false,off,no}`（含大小写/空白）→ `[]`；库层 `SinglePhotoLoop()` 仍 `rules == []`（纯库语义）；触发证据由 F05 门禁 `rule_ids=["saturation_high_rule"]` 提供 |
| **F03** 指标口径单一来源（CR-03） | ✅ 满足（三件套齐） | ①公共 `metrics_for_decide`（`pipeline/metrics.py`，无 service 依赖）②service 顶层合并 proxies（`measure_session`，门禁/用例证 measurement 顶层三键）③`decide_photo` 展平 + 传 rules（`decision.params` 由 `{}` 变非空）；lint 用例显式 `metric_keys=metric_universe(...)`，含"只传 `METRIC_KEYS` 必抛"负控 |
| **F04** 评分器适配器可调用（CR-04） | ✅ 满足 | `__call__` 返回 dict；跨层注入 loop → `final_measurement["aesthetic"]` 非空；`suggest_crop(scorer=…)` → `parts.scorer is not None`（**未**用"非 fallback"）；`.score` 契约不变；断言口径较 CR-04 字面更严（确定性假内层 scorer，**D2 已裁决采纳**） |
| **F05** 端到端门禁（CR-05） | ✅ 满足 | 真 RAW 闭环 2 passed（五条断言 + 正控⑥ + 负控镜像⑦）；`.r21_ok` 本轮签署；env/marker 语义实测自检（`-m gate` 选中 / 无 env skip 豁免） |
| brief 完成标准 1（F01~F05 + 带命令输出） | ✅ | 本报告 §3/§4 + `test-report-r21.md` §2~§3 |
| brief 完成标准 2（真 RAW 闭环：params/rule_ids 非空、像素差、QC ≤3%、trace 完整） | ✅ | `params={"colorcal":{"saturation":-0.15}}`、`rule_ids=["saturation_high_rule"]`、`baseline_pixel_diff=56,293,263`、`highlight_clip_ratio=0.025923 ≤ 0.03`、`trace_event_count=12` 含 `param_update` |
| brief 完成标准 3（新增/改代码有测试：正常 + 边界 + 异常） | ✅ | 40 定向用例覆盖正常/边界（`max_iterations` 0/-1/6/2.5/"3"/True、未知 photo/task、6 种 env）/异常（内部异常不 500）；门禁含正负控 |
| brief 完成标准 4（全量 ≥1533/0 failed + 金样本零漂移） | ✅ | 1574/0（复跑两次）+ 7 passed + 24 case `u8_max=0` |
| brief 完成标准 5（`.qa_ok` 签章） | ✅ | 本轮签署 |
| brief 完成标准 6（changelog + DELIVERY-R21） | ⏭ 归队长 | `docs/changelog.md` 与 `.agent-team/DELIVERY-R21.md` 由队长收尾（QA 不越界）；本报告 §7 提供必须写入清单 |
| brief 非目标（CR-06/07、09~13、前端零改动、不动渲染算子/金样本/`calib_out/`） | ✅ 未越界 | `git status` 仅 4 个 src 文件 + 3 个新测试 + 1 新 src 模块；`frontend/**`、`configs/**`、`resources/**` 零改动；金样本 `data/` 零改动 |

---

## 5. D1~D5 裁决执行复核

### 5.1 D1（`saturation_high_rule` 1% 余量真实性 + 三样本证据）——✅ 成立，**但证据表有一处误标已由 QA 勘误**

QA 自写只读探针（与门禁同装配）独立复算两个样本：

| 样本 | 逐轮 `colorfulness_proxy` / `rule_ids` | 真并集（QA 复算） | 末轮 `rule_ids`（旧口径） | state / final QC |
|---|---|---|---|---|
| DSC_5237 | ① 5.8847 / `[dehaze_rule_030]` ② **6.1472** / `[dehaze_rule_030, saturation_high_rule]` | `[dehaze_rule_030, saturation_high_rule]` | **非空**（旧口径在该样本会"通过"） | ACCEPTED / 0.007422 |
| DSC_5238 | ① 6.5627 / `[dehaze_rule_030, saturation_high_rule]` ② 6.562 / `[clarity_flat_rule_031, saturation_high_rule]` | `[dehaze_rule_030, saturation_high_rule, clarity_flat_rule_031]` | 非空（但**丢首轮 `dehaze_rule_030`**） | ACCEPTED / 0.013096 |

- 与 tester 报告 §5 的数字**逐位一致**（含 duration、final 指标）⇒ D1 证据可信。
- **勘误（FIX-3）**：`tmp-r21-d1-table.txt` 的 `union_rule_ids` 列原由 `tmp-r21-d1-extract.py:35` 从探针的 `rule_ids_last_nonempty`（"最后一条非空轮"）直接改名而来，**不是真并集** —— 在 DSC_5238 上二者不等（真并集含首轮 `dehaze_rule_030`），与同表逐轮列自相矛盾。已修 extractor（真并集 + "最后一条非空轮"单列）并重生成表；原件备份为 `tmp-r21-d1-table-orig.txt`。**产品代码无此问题**（并集实现与门禁断言⑥均自洽，QA 独立复算一致）。
- 结论：**3/3 样本真并集非空**，D1 论断成立、无需触发"报队长"分支；`saturation_high_rule` 余量 +0.96%/+0.28%/+7.06%（不宽裕但已实测命中）。

### 5.2 D2（确定性假内层 scorer + `callable(make_default_scorer())` 观测）——✅ 执行到位

- 门禁断言口径：`test_scorer_adapter_callable.py` 用固定假内层 scorer 构造真 `_PixoScorerAdapter`（不依赖真假分支）✅。
- QA 独立观测（本机）：`{"default_scorer_type": "_PixoScorerAdapter", "is_pixo_adapter": true, "callable": true, "has_call_attr": true, "call_result": {"return_type": "dict", "keys": [color, composition, content, depth_of_field, domain_hint, lighting, overall, quality, raw_overall, source]}}` ⇒ 真模型可用时 `make_default_scorer()` 返回可调用适配器；真模型不可用时回退的无 `__call__` Mock 已被确定性用例挡住（不假绿）。

### 5.3 D3（tech_debt 登记）/ D4（无超时取消 + `duration`）/ D5（TestClient 往返）

- D3：本轮按 design §2.3「不回写任何既有缓存」执行（`photo.last_decision` 未被子闭环污染，`test_service_runtime_fixes.py:164-173` 零回归）✅ → 见 §7 记债 #20。
- D4：`max_iterations ≤ 5` + `duration` 已落任务结果（get/202/门禁证据均可见 `duration`）✅ → 记债 #21。
- D5：`test_auto_loop_http_post_202_then_get_done` 提供 POST→202→GET→done 的真实 HTTP 往返，另有 404/400/未知 task 三态 ✅。

---

## 6. 缺陷与修复记录（QA 最小修复 3 项，均已复验）

| # | 位置 | 问题 | 修复 | 复验 |
|---|---|---|---|---|
| **FIX-1** | `tests/integration/test_auto_loop_api.py:300-302`（docstring） | 写成「闭环收敛后末轮 `rule_ids` **恒为** `[]`」——即被队长明令禁止的"终止轮必空"不变量表述，且与 DSC_5237 反例矛盾 | 改为「末轮是否命中取决于该轮指标是否跨过阈值（5236 不命中 / 5237 命中，两形态并存）；取最后一条会**静默丢掉早期命中**」，并显式写"**不得**把末轮必空写成不变量" | `python -m pytest tests/integration/test_auto_loop_api.py -q` → **20 passed**；repo 内 `恒为 []`/`末轮必空`（非否定式）零残留 |
| **FIX-2** | `tests/regression/test_gate_auto_loop_e2e.py:27-28`（docstring） | 同一句"口径经队长裁决修订"重复两遍（文档瑕疵） | 去重 | `python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate`（无 env）→ **1 passed, 1 skipped**（skip 豁免语义不变） |
| **FIX-3** | `.agent-team/tmp-r21-d1-extract.py:35`（证据脚本） | 把探针字段 `rule_ids_last_nonempty` 误标为 `union_rule_ids`（"最后一条非空轮" ≠ "全轮并集"），DSC_5238 上与同表逐轮列自相矛盾 | 按全 `decide` 事件真并集（首现序、去重）计算 `union_rule_ids`，并把"最后一条非空轮"单列 `last_nonempty_rule_ids`；重生成 `tmp-r21-d1-table.txt`（原件备份 `tmp-r21-d1-table-orig.txt`） | 重生成后三行与 QA 独立复算**逐项一致**：5236 `[saturation_high_rule]`、5237 `[dehaze_rule_030, saturation_high_rule]`、5238 `[dehaze_rule_030, saturation_high_rule, clarity_flat_rule_031]` |

- **未发现产品代码缺陷**（`src/**`）：门禁首跑的唯一失败是**测试侧提取口径**（已由契约修订 R1 修复，QA 增量复核已定稿，见 `design-review-r21.md §11`）。
- 全量回归在 FIX-1/2 之后**重跑**（1574/0），故终态数字与最终树一致。

---

## 7. 遗留分级（三级）+ 交付时必须写入的清单

> 编号口径依队长 2026-09-10 更正：`docs/tech_debt.md` 现最后一条为 **19**，本轮待登记为 **#20/#21**（**不是** #21/#22）。
> 注：`design-r21.md §2.3/§7/§10` 内仍写"tech_debt #21 候选/#22"（旧编号），**属队长文档域**，请队长写 `docs/tech_debt.md` 时以 #20/#21 为准并对齐该两处措辞（QA 未改 design）。

### 7.1 阻塞交付：**0 项**

### 7.2 记债（必须写进 `docs/tech_debt.md` 与 `DELIVERY-R21.md`）

| # | 条目 | 来源/证据 | 影响 |
|---|---|---|---|
| **#20** | auto-loop **不联动** `/api/photos/{id}/timeline` 与 `/decide` 缓存（不回写 `runtime.state_machines` / `photo.last_decision`） | design §2.3 + §7 D3 裁决；`runtime.py` 只写任务表；实测跑完 `ACCEPTED` 后 timeline 仍 `RAW_PENDING` | 用户视角"跑完了状态没变"；需新字段/端点才能联动 |
| **#21** | auto-loop **无任务级超时/取消**（渲染无中断点；`max_iterations ≤ 5` + `preview_long_edge` 仅软控；实测单张 72–124s） | design §2.2 时长口径 + D4 裁决；门禁 `duration` 字段 | 长任务无法中止；资源占用靠上限兜底 |
| #22（建议，编号由队长续排） | `_auto_loop_tasks` **无淘汰**（与 `ExportManager._tasks` 同现状） | dev-1 遗留 3 / tester §7.3 | 长跑服务下任务表无界增长 |
| #23（建议） | 不同 photo **共用 `max_workers=1` 队列且无 `queued` 态**（提交即 `running`，实际可能在排队） | dev-1 遗留 4 / tester §7.4 | 轮询进度不精确；单飞只保证同 photo 不重跑 |
| #24（建议） | auto-loop 后台 `segmenter.segment` **未持 `runtime._segmenter_infer_lock`**（R16 已识别的"后端懒加载非线程安全"面）；与 HTTP `measure_session`/region 供给并发时可能重复加载权重 | QA 代码检视：`runtime.py:945` 传 `self._segmenter`，loop 内直接 `segment()`；对比 `_segmenter_infer_lock` 的既有用法（R15/R16） | 仅冗余加载/内存峰值，无正确性证据受损（本轮 max_workers=1 已限流） |
| #25（建议） | `build/lib/pixo/**` 旧副本漂移（**不含** `metrics.py`，`loop.py` 仍是旧实体）⇒ 若打包/导入误取 `build/lib` 会 `ImportError` | dev-2 遗留 1 / exploration §7.4（QA 已确认 pytest 下 `tests/conftest.py:21-22` 先插 `src`，无实际影响） | 打包路径需确认并清理 |
| #26（建议） | `crop_suggestion_applicable`（注册）与 `crop_suggestion_available`（运行期产）**命名并存** | dev-2 D-5 / 遗留 3 | 易误用；当前无规则引用后者 |
| #27（建议） | 坏 JSON `src/pixo/render/bench/preview_cold_baseline.json` + `preview_v16_nef_baseline_{cold,hot}.json` 与 **单 RAW gate manifest** 的 `raw` 指向已消失的 `K:\data\photo\corpus_a\...` | tester §7.6 / exploration §7.1-7.2 | 该 manifest 的 compare 无法本机复跑（sha 仍可校验） |

### 7.3 已知无害（登记即可，不进 tech_debt 硬清单）

1. `pixo.pipeline.metrics` 未 re-export 到 `pipeline/__init__.py`（design §2.1 明确允许；调用方显式 import）。
2. `task-brief.md:35` 语料计数"3428"与实测 765 不符（文档口径，队长域）。
3. 门禁对"末轮机制形态"（`last_iteration=True` + `adjust_and_continue`）的无条件断言与**默认语料**耦合：默认 env 固定 DSC_5236 且三样本实测一致；若换语料且末轮走 `stopped` 短路需同步该断言（换语料时仅打印不判的 DSC_5236 专属块已做语料守卫）。
4. 服务缺省 `PIXO_SEGMENTER=mock` ⇒ auto-loop 默认拿到合成掩码：已按 design 在响应暴露 `segmenter_type` + `degraded:["mock_segmenter"]`；真路由需运维设 `multi`（改缺省会影响既有测量/region 线，属越界）。
5. `_metrics_for_decide` 保留为 wrapper（意图内，`loop.py:522-529`）。
6. 前端零改动（非目标；`decidePhoto` 仍零调用）。
7. `src/pixo` 下 131 处 `except Exception` 静默降级（CR-08 范围，本轮不动）。

---

## 8. 门禁与结论

- **需求逐条核对**：F01~F05 对 CR-01~05 + brief 完成标准 1~6 → 全部满足（完成标准 6 归队长收尾）。
- **测试证据**：命令 + 输出齐全（§3；原始输出落 `.agent-team/tmp-qa-r21-*.txt`）。
- **遗留分级**：阻塞 0；记债 #20/#21（+ 建议 #22~#27）；已知无害 7 项。
- **结论：通过（修复后通过）。** 据此签章 `.qa_ok` 与 `.r21_ok`（`.r21_ok` 含审核人/覆盖 F-ID/ISO 时间戳/全量回归计数/门禁与金样本结论）。
- 本轮 QA **未改** `src/**`、`frontend/**`、`configs/**`、`docs/changelog.md`；未执行任何 git 写操作（提交归队长）。

## 附：QA 本轮新增证据文件（`.agent-team/`）

| 文件 | 内容 |
|---|---|
| `tmp-qa-r21-full.txt` / `tmp-qa-r21-full-final.txt` | 全量回归两次复跑输出 |
| `tmp-qa-r21-gate.txt` / `tmp-qa-r21-gate-noenv.txt` | F05 门禁（有 env 2 passed / 无 env 1 passed+1 skipped） |
| `tmp-qa-r21-golden.txt` / `tmp-qa-r21-golden-compare.txt` | 合成 gate 7 passed / 真 RAW 24 case RESULT: PASS |
| `tmp-qa-r21-targeted.txt` / `tmp-qa-r21-targeted2.txt` | 定向 40 passed / FIX 后 `test_auto_loop_api.py` 20 passed |
| `tmp-qa-r21-d1-recheck.py` / `-recheck.txt` / `-recheck-5238.txt` | D1 独立复算（5237 / 5238，含逐轮 cp 与真并集） |
| `tmp-qa-r21-d2-probe.py` / `tmp-qa-r21-d2.txt` | D2 独立观测（`make_default_scorer()` 类型/可调用/返回 dict） |
| `tmp-r21-d1-table.txt`（重生成）/ `tmp-r21-d1-table-orig.txt`（原件备份） | D1 证据表与勘误前后对照 |
| `tmp-qa-r21-diff-svc.txt` / `tmp-qa-r21-diff-pipe.txt` / `tmp-qa-r21-status.txt` | 代码检视用 diff 与工作树清单 |
