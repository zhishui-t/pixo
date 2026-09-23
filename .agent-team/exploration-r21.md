# R21 前期探索报告（exploration-r21）

> 角色：`researcher`｜阶段 2（前期探索）｜产出时间 2026-09-10
> 上游：`.agent-team/task-brief.md`、`docs/R21_CHANGE_REQUESTS.md`
> 下游：队长据此撰写 `.agent-team/design-r21.md`
> **只读纪律**：本报告除自身文件外未修改/创建/删除任何仓库文件；所有探针脚本写在
> `%TEMP%\pixo_r21_probe*.py`（仓库外），仅做只读计算/渲染，不落盘仓库产物。
> 证据标注约定：`文件:行号` = 源码事实；`probeN` = 本次实测（命令+输出摘要见 §8）；
> `推测` = 无法直接溯源的推断。

---

## 0. 三条必须让队长先知道的结论（改变设计前提）

### 0.1 【新发现，CR 文档未点名】服务层 decide 零触发的主因是**根本没传 rules**，不是指标形态

`runtime.decide_photo` 调用 `decide({...})` 时既没有 `rules=` 实参，也没有 `context["rules"]`
（`src/pixo/service/runtime.py:651-655`）；而引擎的缺省是
`rules = list(rules) if rules is not None else list(context.get("rules") or [])`
（`src/pixo/decide/engine.py:1131`）——空 rules ⇒ `apply_rules` 永不执行 ⇒ `rule_ids` **结构性恒空**。

probe3 实测（四组对照，同一 11 条规则）：

| 用例 | metrics | rules | rule_ids | params |
|---|---|---|---|---|
| A 现状 service 形态 | 嵌套 measurement | **无** | `[]` | `{}` |
| B | 嵌套 measurement | DEFAULT_RULES | `[]` | `{}` |
| C | 展平后 | **无** | `[]` | `{}` |
| D | 展平后 | DEFAULT_RULES | `[]`（该样本确实不满足任何条件） | `{}` |

> ⚠ CR 文档 §1 用 `.artifacts/_probe_metric_shape2.py` 的「裸 measurement → 0/11」把零触发
> 归因于**指标形态**；该探针同时给出「展平后也是 0/11」（我复跑 probe2 一致）。
> 即：**形态是真因之一，但不是唯一真因，更不是服务路径的直接真因**。CR-03 的验收口径
> （lint 测试）并不会自动修掉「不传 rules」。

probe3 进一步**分离证明**了三条独立链路（同一组数值，仅改一处）：

| 对照 | rule_ids |
|---|---|
| 嵌套 `{"global":{...}}` + rules | `[]` |
| 同值经 `_metrics_for_decide` 展平 + rules | `highlight_protect_rule_002, shadow_open_rule_032, highlight_recover_rule_033` |
| 展平但**无 proxies** + rules | `[]` |
| 展平 + **补 proxies**（colorfulness 4.0 / haze 0.3 / tonal 0.4） | `dehaze_rule_030, vibrance_low_rule` |

**⇒ 设计必须同时覆盖三件事：①传 rules ②展平 ③补 proxies。缺任一条，F05 的
「`rule_ids` 非空」都可能落空。**

### 0.2 【新发现，最可能导致 F05 直接失败】`manual_on_unreliable` 库层缺省 `True` 会让闭环在第 1 轮直接转 MANUAL_REVIEW

- 库层缺省：`src/pixo/pipeline/loop.py:751`（`manual_on_unreliable: bool = True`），
  透传进 decide_context：`loop.py:1465`。
- 引擎在**应用规则之前**先判终止：`src/pixo/decide/engine.py:1147` → `check_termination`；
  命中 `engine.py:866-872`（`unreliable and manual_on_unreliable`）即返回
  `decision="manual_review"`、**`rule_ids=[]`、params 原样回填**（`engine.py:1156-1163`）。
- **本机对 R21 语料实测**：`K:\data\photo\0711\raw\DSC_5236.NEF` 在长边 1024 下
  `sky`/`plant` 掩码**全零**（probe4：`mask_nonzero={'face':164145,'sky':0,'plant':0}`）
  ⇒ `_unreliable_regions` 返回 `["sky","plant"]` ⇒ 若装配用库层缺省，闭环立刻 MANUAL_REVIEW。
- probe7 双路实测：
  - `manual_on_unreliable=True` → engine `decision=manual_review, rule_ids=[]`，
    reason「关键区域不可靠，无法执行确定性规则」；loop `state=MANUAL_REVIEW, iteration=1,
    1 条 measurement`，trace 只有 `AGENT_ESCALATED`，**无 `param_update`**。
  - `manual_on_unreliable=False` → engine `adjust_and_continue`，3 条规则落地；
    loop `state=ACCEPTED, iteration=3`，含 `param_update`。

**⇒ 参考实现 `scripts/auto_real_edit.py:80` 显式写 `manual_on_unreliable=False` 不是随手写的，
是踩过坑的。R21 装配层必须同样显式置 False（或在设计里论证其他等价手段）。**

### 0.3 【实测成本】真 RAW 单张闭环 ≈ 73s（1 轮），远超仓库自己的 30s 预算

`src/pixo/render/bench/gate_e2e_loop_budget.json:3` 写着 `single_photo_max_seconds: 30.0`。
probe6 用仓库自带刨面工具跑**一次**真实闭环（`max_iterations=1`、`preview_long_edge=512`、
MockSegmenter）：

| 阶段 | 秒 |
|---|---|
| preview 渲染（512） | 1.384 |
| segment（mock） | 0.002 |
| **FINAL_QC 全分辨率渲染** | **40.445** |
| 其余（全分辨率测量 + meta + 掩码上采样等，按总时长扣减得出） | ≈31.2 |
| **总计** | **73.09** |

历史真跑（`exports/auto/report/*.json`，5 份报告 17 次 run，12 prompts + 真分割器、
`max_iterations=1/3/4`）：**43.95 – 107.4s**，其中 `max_iterations=1` 那次 58.32s。

**⇒ F01 的「端点须可控」不是礼貌提醒，是硬约束：同步 def 路由会让一个 HTTP 请求挂 70s+；
设计必须二选一（后台 202 + task，或 max_iterations 上限 + 明确超时/降级文案）。**

---

## 1. 服务层装配面

### 1.1 ServiceRuntime 现状（构造依赖与持有物）

| 事实 | 证据 |
|---|---|
| 构造签名：`profile` / `profile_path` / `work_dir` / `session_factory` / `export_manager` | `src/pixo/service/runtime.py:151-158` |
| 缺省 DCP = 仓库内置 Nikon Z5 基线；经 `load_dcp()` 载入到 `self.profile` | `runtime.py:37-42`、`runtime.py:159-164` |
| 持有 `photos: dict` / `sessions: OrderedDict`（LRU） / `state_machines: dict` | `runtime.py:172-178` |
| 另有 `_session_photo` 反查索引、`max_sessions`（`PIXO_MAX_SESSIONS`，缺省 8） | `runtime.py:44-45`、`runtime.py:176-178` |
| 并发锁：`_lock`（photos/sessions）、`_region_supply_lock`、`_segmenter_infer_lock` | `runtime.py:179-186` |
| 分割器：`PIXO_SEGMENTER`（`mock`/`multi`，**缺省 mock**）→ `self._segmenter` / `self.segmenter_type` | `runtime.py:191-197`、`runtime.py:201-224` |
| 状态机在 `create_photo` 建立（非 create_session） | `runtime.py:302` |
| `measure_session()`：渲染 → `self._segmenter.segment(image, ["face","sky","plant"])` → `VisionMeasure().measure(...)` → 回写 `photo.last_measurement` | `runtime.py:592-631`（measure 在 614-623，回写在 625） |
| `decide_photo()`：取 `sessions[-1]` → `measure_session` → `session.canonical_params()` → `decide({...})` → 回写 `photo.last_decision` | `runtime.py:633-664`（`decide` 调用 651-655） |
| 导出：`ExportManager.submit()` 异步 + `status()`；端点 202 返回 task_id | `runtime.py:682-700`、`src/pixo/render/web/export.py:87-138`（ThreadPoolExecutor + `_tasks` + lock） |
| 会话 LRU 逐出时防御式 `close()` | `runtime.py:345-366` |

> 装配要点：**`self.profile` 与 `self._segmenter` 已就绪可直用**，无需另建 DCP/模型；
> 但 `self._segmenter` 缺省是 `MockSegmenter`（见 §5.5 风险）。

### 1.2 路由注册方式（可复制样式）

现有风格（`src/pixo/service/app.py`）：

```python
    @app.post("/api/photos/{photo_id}/decide")
    def api_decide(photo_id: str) -> dict[str, Any]:
        """触发一轮 Decide：渲染 + 测量 + 规则决策，结果缓存到照片。

        整条链路同步阻塞（渲染/测量），sync def 让 FastAPI 自动进线程池。
        """
        try:
            return rt.decide_photo(photo_id)
        except KeyError as exc:
            raise _not_found(str(exc)) from exc
```
——`app.py:256-265`。三条可复制的约定：

1. **同步阻塞链路用裸 `def`**（FastAPI 自动丢线程池），注释明示理由（`app.py:260`）；
   需要显式线程池的是 `async def` + `await run_in_threadpool(...)`（`app.py:91`、`app.py:103-105`、
   `app.py:144-146`、`app.py:227-233`）。
2. **异常映射统一**：`_not_found()` / `_bad_request()`（`app.py:37-44`），
   `KeyError→404`、`ValueError→400`。
3. **路由全部闭包在 `create_app(runtime)` 内**，`rt = runtime or PixoServiceRuntime()`
   （`app.py:76-82`）；`app.state.runtime` 供 lifespan 使用（`app.py:64`）。

长耗时任务的**既有先例**是导出线：`POST /api/sessions/{id}/exports` 返回 **202 + task_id**
（`app.py:214-238`），配 `GET /api/exports/{task_id}` 轮询（`app.py:240-246`）；
集成测试的轮询写法见 `tests/integration/test_service_api.py:275-291`。**建议 auto-loop 复用此模式。**

启动侧钩子（若 auto-loop 需要预热）：`app.py:47-73` —— scorer 预热在线程池内 await，
segmenter 预热走 **daemon 后台线程不 join**（`app.py:70-72`），可用
`PIXO_SCORER_WARMUP` / `PIXO_SEGMENTER_WARMUP` 关（`runtime.py:87-103`）。

### 1.3 最小侵入接入点建议：**新增端点**，不改造 `decide_photo`

| 方案 | 改动面 | 证据/理由 |
|---|---|---|
| **A（推荐）新增 `POST /api/photos/{photo_id}/auto-loop` + `runtime.run_auto_loop()`** | `app.py` 加 1 个路由；`runtime.py` 加 1 个方法（放在 `decide_photo` 旁，`runtime.py:633` 之后） | 与 CR-01 原文一致（`docs/R21_CHANGE_REQUESTS.md:54`）；`decide_photo` 零改动 ⇒ 现有 8 个 service 测试（`tests/integration/test_service_api.py:170-292`）不受影响；装配材料齐备（`self.profile` `runtime.py:164`、`self._segmenter` `runtime.py:197`） |
| B 改造 `decide_photo` 内部走闭环 | `runtime.py:633-664` 重写 | 破坏「单轮语义」这一任务书硬约束（`task-brief.md:43`）；且现有测试只断言字段存在（`test_service_api.py:188-189`：`"decision" in decide` / `"params" in decide["decision"]`）⇒ 破坏会是**静默**的 |

**推荐 A + 一处补充（需队长裁决，见下）。**

### 1.4 需队长拍板的一个设计分叉：F03 是否同时修好 `decide_photo`？

F03 的目标是「消除成因①②」，但 §0.1 证明还有成因③（不传 rules）。
两种落法：

- **A1（保守）**：F03 只在 `measure_session` 里补 proxies + 在 `decide_photo` 里换成
  `metrics_for_decide(...)` 展平；**不给 `decide_photo` 传 rules**。→ 响应字段不变、
  `params` 仍为 `{}`，但 CR 里「服务层 decide 规则零触发」**依旧存在**（只是形态修好了）。
- **A2（推荐）**：`decide_photo` 走装配层取到的 rules（`PIXO_RULES=off` 可关），
  `decide({... "rules": rules})`。→ 响应**字段集合**不变（仍 `photo_id/state/iteration/
  measurement/decision`，`runtime.py:658-664`），只有 `decision.params` 由 `{}` 变非空。
  现有测试仍绿（只断言字段存在，`test_service_api.py:188-189`）。
  「单轮语义」= 不迭代/不回写渲染，A2 不触碰这一点。

> 建议 A2，并在 design 里显式写明「`decision.params` 由空转非空属于**预期行为变更**，
> 不是契约破坏」。若队长选 A1，请在 design 的风险节登记「服务层 decide 仍是空决策」。

---

## 2. `SinglePhotoLoop` 装配契约

### 2.1 构造参数（**全 keyword-only**，`src/pixo/pipeline/loop.py:734-765`）

| 参数 | 缺省 | R21 关注点 |
|---|---|---|
| `render_backend` / `renderer` | None | 传了就不看 `raw_path`；RAW 线可不传，靠 `run(raw_path=...)` + `prof` 自动建 `RawRenderBackend`（`loop.py:876-892`） |
| `segmenter` | None | 为 None 时 `run()` 内兜底 `MockSegmenter()`（`loop.py:1779-1780`）——**生产装配必须显式传** |
| `measurer` | `VisionMeasure()` | 可略 |
| `meta_extractor` | `_default_meta_extractor` | 略 |
| `rules` | `None` → `self.rules = list(rules or [])`（`loop.py:770`） | **库层缺省保持空的约束点在 770**，F02 不得改这里 |
| `store` | None | 传给 loop 自建的状态机（`loop.py:1783`），见 §2.4 |
| `prof` | None | **真 RAW 必需**（否则 `_build_backend` 抛 `LoopError`，`loop.py:889-892`） |
| `preview_long_edge` | `512` | 参考实现用 1024（`auto_real_edit.py:76`） |
| `max_iterations` | `3` | 参考实现 CLI 缺省 2（`auto_real_edit.py:140`） |
| `prompts` | `None` → `["face","sky","plant"]`（`loop.py:775`） | 参考实现用 12 个（`auto_real_edit.py:29-32`） |
| `confidences` / `targets` / `locked_params` | `{}`/`{}`/`[]` | 可略 |
| `manual_on_unreliable` | **`True`** | **见 §0.2，装配层应显式 False** |
| `export_path` | None | 非 None 时在 `run()` 末尾落盘最终图（`loop.py:1914-1915` → `_save_image` `loop.py:691-703`） |
| `aesthetic_scorer` | None | 见 §4 |
| `aesthetic_accept_threshold` / `aesthetic_stagnation_eps` | None（关） | 见 §4 |
| `jnd_threshold` / `jnd_window` | `0.5` / `2` | 感知收敛早停，缺省开 |
| `crop_suggest` | `False` | 开则启用 `suggest_crop`（`loop.py:1023-1025`）与 `crop_suggestion_applicable` 指标（`loop.py:1408-1413`） |
| `box_provider` / `agent_suggest` / `llm_shadow` / `enable_style_cards` | None/False/None/None | 非目标，保持缺省 |
| **副作用**：构造期写全局 `register_metric_keys({...})` | `loop.py:783-801` | 见 §3.4，有顺序副作用 |

### 2.2 `run()` 入参与返回

```python
def run(self, photo_id: str, *, raw_path=None, image_rgb=None, image=None,
        meta=None, metadata=None, compose_params=None, params=None,
        agent_decision="agree", max_iterations=None) -> LoopResult
```
`loop.py:1759-1772`。RAW 线：`run(photo_id, raw_path=str(nef), max_iterations=n)`
（参考实现 `auto_real_edit.py:86-90`）。

`LoopResult` 字段（`loop.py:206-224`）：`photo_id`/`state`/`iteration`/`params`/
`measurements`/`final_measurement`/`final_image(np.ndarray|None)`/`trace_events`/
`decision(=sm.state)`/`reason`/`qc_rollback_count`/`metadata`/`compose_geometry`/
`agent_decision`/`llm_review`。
`to_dict()`（`loop.py:234-261`）把 `final_image` 降为 `{shape,dtype}` 摘要——**HTTP 响应
应走 `to_dict()`**；要算像素差得直接用 `.final_image`（`auto_real_edit.py:92`、`107-110`）。

异常类型：
- `LoopError(RuntimeError)`（`loop.py:202`）：无后端（`loop.py:889-892`）、保存失败（`loop.py:702`）
- `SegmenterUnavailable` → 转 `MANUAL_REVIEW`，不抛出（`loop.py:1330-1332` + trace `AGENT_ESCALATED`）
- 其它异常目前**会穿出 `run()`**（无整体兜底）——端点必须自己 try/映射，别指望 loop 自愈

### 2.3 `RawRenderBackend` 真 RAW 用法要点

| 要点 | 证据 |
|---|---|
| 构造：`RawRenderBackend(raw_path, prof)`；不传 `render_backend` 时由 `_build_backend` 自动建 | `loop.py:406-412`、`loop.py:887-888` |
| `render_preview(params, long_edge=1024)`：每次**新建** `RawPreviewSession` 并 `close()`，`output_bps=8`，透传 `state_extras` | `loop.py:428-447` |
| `render_full(params)`：走导出主线 `_render_full_quality(..., output_bps=8, state_extras=...)` | `loop.py:449-461`、`src/pixo/render/web/export.py:30` |
| `full_size()`：rawpy 惰性读尺寸并缓存 | `loop.py:414-426` |
| `prof` 来源：`load_dcp(DCP)`（`runtime.py:161-164`）或 `Renderer(DCP).profile`（`auto_real_edit.py:177` + `:65/:73`） | 两条路都实测可用（probe1/probe4 用前者；probe6 走 `bench_e2e_loop` 用前者） |
| DCP 路径常量 | `resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp`（`runtime.py:37-42`、`auto_real_edit.py:27`） |
| prompts / preview_long_edge / manual_on_unreliable / rules 的参考取值 | `auto_real_edit.py:29-32`、`:76`、`:80`、`:70+79` |

### 2.4 ⚠ 状态机双实例（装配必须处理）

`run()` 内部**自建**状态机：`sm = PhotoStateMachine(photo_id, store=self.store)`
（`loop.py:1783`），与外层 `PIXO_SERVICE` 的 `runtime.state_machines[photo_id]`
（`runtime.py:302`）是**两个对象**。`PhotoStateMachine.__init__` 只在给了 store 时才
`load_state`（`src/pixo/state/machine.py:143-154`、`:184-190`），而 runtime 建状态机时没传 store
（`runtime.py:302`）、`SinglePhotoLoop.store` 缺省 None。

**后果**：auto-loop 跑完 `ACCEPTED` 后，`GET /api/photos/{id}/timeline`
（`runtime.py:666-678`）仍会显示 `RAW_PENDING` / `iteration=0`。
设计需明确：①响应直接返回 loop 侧 `state/iteration/trace_events`；或 ②给两边接同一个 store；
或 ③跑完后把结果回写 `rt.state_machines`（注意 loop 侧 sm 不经 `LoopResult` 暴露）。

---

## 3. 指标口径公共化落点

### 3.1 `_metrics_for_decide` 现状

- 定义：`src/pixo/pipeline/loop.py:521-551`（私有名）。
- **唯一调用点**：`loop.py:1393`（`grep -rn _metrics_for_decide src/` ⇒ 仅 521 定义 + 1393 调用 + 文档串 784）。
- 未进 `__all__`（`loop.py:2018-2026`）。
- 产出键（实测 probe2 `flat_keys`）：`mean_luminance`/`highlight_clip_ratio`/`shadow_clip_ratio`/
  `contrast`/`preview_highlight_clip_estimate`/`preview_overflow_ratio`（后两者同源，
  `loop.py:532-537`），以及**条件性**顶层键 `haze_proxy`/`colorfulness_proxy`/`tonal_range`
  （`loop.py:539-541`，只有 measurement 顶层存在才写），加 `<prompt>_{luminance,area_ratio,
  highlight_clip_ratio,reliable}`（`loop.py:542-550`）。

### 3.2 放哪个模块、为何不产生循环依赖

**推荐 `src/pixo/pipeline/metrics.py`（新文件，dev-2 文件域）**，并把
`loop.py:521-551` 的实体搬过去、`loop.py` 保留 `from .metrics import metrics_for_decide`
（1393 行改用它），同时 `pipeline/__init__.py` 导出（对齐 `pipeline/__init__.py:24-31` 风格）。

依据：

| 检查项 | 结果 | 证据 |
|---|---|---|
| pipeline 是否反向依赖 service | **否** | `grep -rn "service" src/pixo/pipeline/*.py` 仅命中 docstring `loop.py:713` |
| service 是否已依赖 pipeline | 是（已有先例） | `src/pixo/service/loop.py:8` |
| `pipeline/__init__` 导入开销 | 0.587s（vs `pixo.decide` 0.251s、`pixo.service` 1.404s） | 导入计时（§8.7）；**无 torch 级重依赖** |
| 放进 `pipeline/metrics.py` 是否触发 `pipeline/__init__` | 会触发（Python 语义），但那只是上面那 0.587s | 实测 |
| 备选：`decide/metrics.py` | `decide/engine.py:29` 只 import `pixo.state.machine`，最轻（0.251s） | 但 `team-manifest.md:39` 已把 F03 公共 API 划给 `pipeline/` 侧 |

> 结论：**放 `pipeline/`**（尊重文件域仲裁 + 无环 + 成本可忽略）。若队长坚持零成本，
> `decide/` 也是无环的，但会与花名册的文件域约定冲突。

### 3.3 service 侧如何补 `compute_proxy_metrics`（合并位置 = measurement **顶层**）

与 loop 完全同源同层：

```python
# loop.py:1352-1354（preview）
proxies = compute_proxy_metrics(preview_img)
if proxies:
    measurement.update(proxies)          # ← 顶层，不是 measurement["global"]
# loop.py:1730-1732（FINAL_QC 全分辨率）
qc_proxies = compute_proxy_metrics(full_img)
if qc_proxies:
    full_measurement.update(qc_proxies)
```

`measure()` 自身的返回结构是 `{image_id, render_version, detection_version, mask_version,
regions, global}`（`src/pixo/vision/measure.py:574-581`）——**不含 proxies**（`measure.py:548`
只调 `measure_global`）。所以 service 侧：

```python
# src/pixo/service/runtime.py，measure_session 内，measure(...) 之后（现 614-623 之后）
from pixo.vision.measure import compute_proxy_metrics   # 新增 import（pixo.vision.__init__ 未 re-export）
proxies = compute_proxy_metrics(image)
if proxies:
    measurement.update(proxies)
```
- `pixo.vision.__init__` **只导出** `VisionMeasure` / `measure_global` / `measure_region` 等
  （`src/pixo/vision/__init__.py:38`、`:51-52`），`compute_proxy_metrics` 必须从
  `pixo.vision.measure` 取（`measure.py:586` 在 `__all__` 里）。
- **合并层级必须是 measurement 顶层**，否则 `_metrics_for_decide` 的
  `if key in measurement`（`loop.py:539-541`）取不到，probe3 已证「无 proxies ⇒ 0 触发」。

**副作用提示**：`measure_session` 顺带回写 `photo.last_measurement`（`runtime.py:625`），
所以 `GET /sessions/{id}/measurements` 与 `GET /photos/{id}/decide` 的 `measurement`
会**多出 3 个顶层键**——属**追加**，不改既有字段（`app.py:198-212` 直接透传）。

### 3.4 规则 metric 键 lint 怎么接

现有机制（`src/pixo/decide/engine.py`）：

| 元素 | 位置 | 说明 |
|---|---|---|
| 键宇宙（全局 set） | `engine.py:446` `_METRIC_KEY_REGISTRY` | 进程级 |
| 注册/清空/快照 | `engine.py:449-453` / `456-458` / `461-463` | `reset_metric_keys()` 是测试辅助 |
| lint 入口 | `engine.py:151-160` `_enforce_formula_lint` | `known = metric_keys ∪ registry`；**known 为空 ⇒ 直接 return（宽松）**（`:154-155`） |
| 实际校验 | `engine.py:184-229` `_lint_rule_formulas` | 校验 `action.formula` 的 AST 标识符，且 `check_condition_metrics=True` 时校验 `condition.all[].metric`（`:220-228`） |
| 挂载点 | `engine.py:270`（`load_rules` 内） | 也可 `load_rules(source, metric_keys=...)`（`engine.py:232`、`:186`） |
| loop 侧注册内容 | `loop.py:783-801` | 6 个固定键 + 3 个“顶层代理” + `crop_suggestion_applicable` + `<prompt>_×4` |

**lint 测试的接法（建议）**：
```python
universe = {...}                      # 与 metrics_for_decide 产出键同源（含 crop_suggestion_applicable）
for p in DEFAULT_RULES:               # src/pixo/decide/rules/__init__.py:31-42，共 6 文件 / 11 条规则（probe2 实测）
    load_rules(p, metric_keys=universe)   # 不抛 DecideError = 通过
```
> ⚠ **顺序副作用**：`register_metric_keys` 在 **loop 构造期**执行（`loop.py:783`），是全局 set；
> 所以「load_rules 是严格还是宽松」取决于**先加载规则还是先建 loop**。
> 参考实现正是**先 load_rules（`auto_real_edit.py:70`）后建 loop（`:72`）⇒ 那次是宽松模式**。
> 新 lint 测试应**显式传 `metric_keys=`**，不要依赖全局 set 的时序。
>
> 另：键宇宙一旦非空，默认规则包必须能全过（`loop.py:777-782` 的注释记录了这条约束的历史踩坑）。

---

## 4. 评分器适配器契约（`_PixoScorerAdapter`）

### 4.1 现状

- 定义：`src/pixo/pipeline/batch.py:318-410`；**只有 `.score(image_rgb, meta=None)`**
  （`batch.py:353-410`），返回 `AestheticScore | None`（实际**从不返回 None**：异常/空结果
  都会永久降级 Mock 并返回分数，`batch.py:359-372`、`:383-390`、`_mock_score` `:348-351`）。
- `AestheticScore` 是 `@dataclass`（`batch.py:72-84`：`overall: float` + `dimensions` +
  `source` + `raw_overall`/`domain_hint`），**没有 `__float__`**（probe5 实测 TypeError 文案）。
- 批量侧契约使用者：`batch.py:710` `self.aesthetic_scorer.score(image, item.meta)`。

### 4.2 被当「可调用对象」使用的两个位置

| 位置 | 代码 | 期望返回 |
|---|---|---|
| `loop.py:907`（首选签名） / `loop.py:912`（单参回退） | `raw = self.aesthetic_scorer(image, masks)` | `float` 或含 `overall` 的 `dict`（`loop.py:924-932`） |
| `loop.py:1024` → `smart_crop.py:194` | `suggest_crop(preview_img, boxes, scorer=self.aesthetic_scorer)` → `out = scorer(crop)` | 宽容：`float` / `dict` / 带 `.overall` 的对象（`smart_crop.py:186-210`） |

### 4.3 实测：断裂的真实症状与 CR-04 措辞的一处不准

probe5（注入 `_PixoScorerAdapter(FakeInner())`，FakeInner 实现真评分器 `.score()` 契约）：

| 观测 | 结果 |
|---|---|
| `hasattr(adapter,"__call__")` | `false` |
| `adapter.score(...)` 返回类型 | `AestheticScore` |
| 注入 loop 后 | `run()` **正常返回 ACCEPTED**，但 `measurements[0]` 与 `final_measurement` **都没有 `"aesthetic"` 键** |
| stderr | `美学评分器签名不兼容，本轮跳过计分：'_PixoScorerAdapter' object is not callable`（来自 `loop.py:914`） |
| 注入 `suggest_crop` | `cands[0]["parts"]["scorer"] is None`；**`fallback` 仍为 False**（结果照常产出，只是评分维度缺席） |

> ⚠ **CR-04 的验收描述「`suggest_crop(scorer=...)` 不返回全 fallback（当前两者恒空/恒 fallback）」不准确**：
> 现状**不是**全 fallback，而是 `parts.scorer=None` 的**静默降级**（probe5
> `current_crop_fallback=false`、`current_crop_scorer_part=null`）。
> 断言应写「`parts.scorer is not None`」，写「非 fallback」会**误判通过**。

### 4.4 ⚠ 天真修法会引入崩溃（CR-04 的字面最小修法不可直接用）

probe5 用 `class NaiveCallableAdapter(_PixoScorerAdapter)` 实现「`__call__` 委托 `.score()`」：

```
naive_call_return_type = "AestheticScore"
naive_state = "RAISED TypeError: float() argument must be a string or a real number, not 'AestheticScore'"
naive_crop_scorer_part = 1.0        # smart_crop 侧反而 OK（.overall 属性路径兜住）
```

根因链：`_score_aesthetic` 的 `try` 只包住调用（`loop.py:906-923`），而
`float(overall)`（`loop.py:932`）在 try **之外**；`AestheticScore` 不是 dict 也不是数值
⇒ 非签名类异常穿出 `run()`（`_run_preview_iterations` 在该段无 try，见 `loop.py:1274-1406`
的 try 分布）。当前无 `__call__` 时它是被 `except TypeError` 吞掉的**静默跳过**；
一旦补上 `__call__` 返回对象，**静默跳过会变成 HTTP 500**。

### 4.5 最小修法与副作用（建议）

**推荐**：`_PixoScorerAdapter.__call__(self, image_rgb, masks=None)` **返回 dict**：

```python
def __call__(self, image_rgb, masks=None):
    del masks                      # 真评分器不消费掩码（同 .score 的 meta 语义 batch.py:358）
    s = self.score(image_rgb)
    if s is None:                  # 防御：当前实现不会发生，保持契约完整
        return None
    return {"overall": s.overall, **s.dimensions}
```
- 对 `loop.py:924-932`：命中 dict 分支 → `overall=float(...)` OK，`dimensions` 进 `extra`
  → `measurement["aesthetic"]` 非空 ✅
- 对 `smart_crop.py:201-208`：命中 dict 分支 → `out["overall"]` ✅（`naive_crop_scorer_part=1.0` 已证）
- **副作用**：批量线不受影响（`batch.py:710` 仍走 `.score(image, meta)`）；dict 形态丢失
  `source`/`raw_overall`/`domain_hint`——若设计需要溯源字段，把它们一并塞进 dict
  （`loop.py:926` 会原样放进 `measurement["aesthetic"]`）。
- 备选：`__call__` 返回 `AestheticScore` 本体 + 在 `loop.py:927-931` 补 `.overall` 对象分支
  （即向 `smart_crop._score_scalar` 的宽容度看齐）。缺点：**两处改**，且要放在 dev-2 文件域内。

### 4.6 现有测试为何没暴露这个断裂

| 测试 | 注入的 scorer | 为何漏掉 |
|---|---|---|
| `tests/unit/test_loop_aesthetic.py:44` | `def scorer(image_rgb, masks=None)`（普通可调用） | 用的是 callable，不是 `_PixoScorerAdapter` |
| `tests/unit/test_smart_crop.py:66-76` | `def fake_scorer(crop)` / `lambda c: None` | 同上 |
| `tests/unit/test_scorer_calibration.py:17-27` | `_PixoScorerAdapter(_Fixed())` | **只调 `.score()`**，从不把它当可调用对象 |
| `tests/unit/test_aesthetic_wiring.py:76/104/147` | `make_default_scorer()` | 只喂给 `BatchPipeline`（`.score()` 契约） |
| `tests/integration/test_loop_e2e.py` | **完全不注入 scorer** | 闭环 E2E 骨架根本没覆盖美学维度 |

> 结论：`grep -rn "aesthetic_scorer" tests/` 里**没有任何一处**把 `make_default_scorer()` /
> `_PixoScorerAdapter` 注入 `SinglePhotoLoop` 或 `suggest_crop`——两个契约在测试里从未相遇。
> 新测试必须**跨层注入**（真 adapter → loop / suggest_crop）才能钉死。

---

## 5. 真 RAW 依赖与运行成本（全部实测）

### 5.1 语料路径

| 检查 | 结果 |
|---|---|
| `K:\data\photo\0711\raw\DSC_5236.NEF` | **EXISTS**，28,285,604 bytes，mtime 2026-07-01 21:18 |
| `K:\data\photo\0711\raw\` 计数 | **765 个 NEF + 4 个 MOV = 769 文件** |
| `task-brief.md:35` 称「同目录 NEF 共 3428 个」 | ⚠ **口径不符**（实测 765）。推测是旧 `corpus_a` 的数（该目录已不存在） |
| `K:\data\photo\` 子目录 | `0711` / `2026春节` / `厦门` |

### 5.2 `render/bench/*.json` 里的旧路径

| 文件 | `raw` 字段 | 判定 |
|---|---|---|
| `preview_v16_nef_baseline_cold.json:3`、`_hot.json:3` | `K:\data\photo\corpus_a\raw\DSC_5236.NEF` | **失效**（`K:\data\photo\corpus_a` 不存在；`corpus_a\raw\DSC_5236.NEF` 亦不存在） |
| `preview_{cold,hot,full,v16_*}_baseline*.json`（其余 6 个） | `K:\dsh-share\dng_verify\DSC_5607.dng` | 该文件**存在** |
| `native_baseline_v1.json:4` | `"raw": null` | 无路径 |
| `gate_e2e_loop_budget.json` | 无 raw | 预算文件（`single_photo_max_seconds=30.0`） |

### 5.3 ⚠ 额外发现：`src/pixo/render/bench/preview_cold_baseline.json` 是**坏 JSON**

```
BAD  bench\preview_cold_baseline.json JSONDecodeError Expecting ',' delimiter: line 35 column 30
     line 35: "tone": 14.8712999653corpus_a7,
```
（`json.load` 逐个校验 11 个 bench JSON，其余 10 个 OK。）
`grep` 全仓 `tests/**/*.py` 与 `src/pixo/**/*.py` **无任何消费者**——属死文件（见 §7）。

### 5.4 分割器模型是否就绪（**不需要联网**）

`resources/models/segmentation/` **只有 README.md（无权重）**（实测目录树）；
权重实际落在 HF hub 缓存 + roboflow 缓存：

| 后端 | 权重来源 | 本机状态 | 默认路由表 |
|---|---|---|---|
| `segformer` | `nvidia/segformer-b1-finetuned-ade-512-512`（`segformer_scenes.py:18-20`） | ✅ 缓存 54.9 MB | **在**（sky/plant/mountain/tree/grass） |
| `rfdetr` | `rf-detr-seg-xxlarge.pt`（`rfdetr_person.py:41-46` + rfdetr `config.py:979`） | ✅ `C:\Users\10042\.roboflow\models\` 154.9 MB | **在**（person/subject） |
| `uniface` | `jonathandinu/face-parsing`（`uniface_face.py:20-22`） | ✅ HF 缓存 338.6 MB | **不在**（许可门控） |
| `sapiens` | `facebook/sapiens-seg-0.3b`（`sapiens_body.py:31-32`） | ❌ 快照只有 `.no_exist` 零字节条目，**权重未下载** | **不在**（许可门控） |

许可门控：`uniface` / `sapiens` 在 `model_licenses.json` 里 `usage=internal_development_only`
⇒ 除 `PIXO_ALLOW_RESTRICTED=1` 外不注册（`multi_router.py:101-117`、`:64-91`）。
probe1 实测：`routed_backends=['rfdetr','segformer']`、`restricted=['sapiens','uniface']`，
并有告警「后端 uniface 许可为 internal_development_only，未注册进路由表」。
probe4 设 `PIXO_ALLOW_RESTRICTED=1` 后 `routed_backends=['rfdetr','sapiens','segformer','uniface']`。

**离线可用性**：probe1 与 probe4 均在 `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` 下跑通，
无下载、`last_degraded=[]` ⇒ **默认路由表（rfdetr+segformer）本机完全离线就绪**；
若开 `PIXO_ALLOW_RESTRICTED=1` 且用到 hair/skin/clothes/body ⇒ `sapiens` 权重缺失，
**会走联网下载或直接失败**（未实测，标注**推测**：`sapiens_body.py:175-176`
`from_pretrained()` 在离线且无缓存时抛异常 → 被 `multi_router.py:191-198` best-effort 零掩码降级）。

### 5.5 service 侧分割器来源 ⚠

`PixoServiceRuntime` 缺省 `PIXO_SEGMENTER=mock`（`runtime.py:191-197`）⇒ `rt._segmenter` 是
`MockSegmenter`。实测它**产非零合成掩码**（probe：200×300 图上 face 5647 / sky 24000 /
plant 27000 px）——如果 auto-loop 图省事直接用 `rt._segmenter`，则「真 RAW 真闭环」的
**决策依据是假掩码**。设计必须显式规定 segmenter 来源（要求 `multi` / 注入 / 缺失时降级留痕）。

### 5.6 耗时（分级实测）

| 项目 | 实测 | 备注 |
|---|---|---|
| segmenter 构造（路由表，不加载权重） | 0.316s | probe1 |
| `load_dcp()` | 0.145s | probe1 |
| preview 渲染 512 | 冷 2.086s / 热 0.196s | probe1（`RawRenderBackend.render_preview`） |
| preview 渲染 1024 | 0.723s / 0.901s / 2.249s | probe1 / probe4 |
| segment `{sky,plant}` | **冷 24.5s** / 热 1.825s | probe1（segformer 权重冷启） |
| segment `{face,sky,plant}`（ALLOW_RESTRICTED=1） | **冷 27.2s** | probe4（额外加载 uniface） |
| **一次真实闭环 `max_iterations=1`（512/mock）** | **73.09s**：preview 1.384 + segment 0.002 + **FINAL_QC 全分辨率渲染 40.445** + ≈31.2（全分辨率测量等，扣减得出） | probe6（跑的是仓库自带 `pixo.render.tools.bench_e2e_loop.run_single_benchmark`） |
| 历史真跑（12 prompts + 真分割器） | `max_iterations=1`→58.32s；`3–4`→**43.95 ~ 107.4s**（17 次） | `exports/auto/report/*.json`（5 份报告） |
| 仓库预算 | `single_photo_max_seconds = 30.0` | `src/pixo/render/bench/gate_e2e_loop_budget.json:3` |

> **成本结构结论**：**FINAL_QC 全分辨率渲染 + 全分辨率测量占了 ~98%**（probe6：71.7s / 73.1s）；
> preview 与分割都是小头（热态）。所以「加 max_iterations」几乎不涨总时长，
> **降 preview_long_edge 也救不了**；要压时间只能动全分辨率环节或走后台任务。

### 5.7 规则触发实测（含 F05 可达性预判）

对 R21 语料文件（`preview 1024`，`PIXO_ALLOW_RESTRICTED=1`，probe4）：

| 观察量 | 值 |
|---|---|
| face 掩码 | 164,145 px，`mean_luminance=104.93`，`area_ratio=0.235`，`reliable=true` |
| sky / plant 掩码 | **0 px**，`mean_luminance=null`，`reliable=false` |
| proxies | `haze_proxy=0.1823`、`colorfulness_proxy=6.1888`、`tonal_range=0.4974` |

| 评估形态 | rule_ids | params |
|---|---|---|
| 现状 service（nested + 无 rules） | `[]` | `{}` |
| nested + rules | `[]` | `{}` |
| flat（无 proxies）+ rules | `exposure_rule_001` | `exposure_ev=0.3726` |
| **flat + proxies + rules（F03 目标形态）** | **`exposure_rule_001, saturation_high_rule`** | `exposure_ev=0.3726`, `saturation.adjust=-0.15` |

**⇒ F05 的「`rule_ids` 非空」在该文件上可达**，且 `saturation_high_rule` 由
`colorfulness_proxy`（6.1888 ≥ 阈值 6.13，`src/pixo/decide/rules/color_rules.yaml:22-31`，
阈值在 `:27`）驱动，
**不依赖受限后端**；`exposure_rule_001` 依赖 `face_luminance` ⇒ 需要 `PIXO_ALLOW_RESTRICTED=1`。
> ⚠ **脆弱性**：6.1888 vs 6.13 只有 **~1% 余量**（见 §6.7），门禁别把「具体是哪条规则」写死。

### 5.8 失败降级路径（供设计写异常分支）

| 场景 | 行为 | 证据 |
|---|---|---|
| 请求的全部 prompt 组后端都不可用 | `MultiModelSegmenter` 抛 `SegmenterUnavailable`（`multi_router.py:200-206`）→ loop 捕获 → `MANUAL_REVIEW` + trace `AGENT_ESCALATED`（`loop.py:1330-1332`） |
| 部分后端失败 | 该组零掩码 + `last_degraded` 记录 + warn-once（`multi_router.py:182-198`、`:155-160`） |
| 未知 prompt（如默认路由表里没后端的 `face`） | 零掩码 + warn-once，**不**升级 manual_review（`multi_router.py:208-213`） |
| 权重缺失/加载异常 | 后端懒加载抛异常被上面的 best-effort 分支吞成零掩码（`multi_router.py:191-198`） |
| 渲染失败（service 测量线） | `measure_session` 返回 `{"measurement": None, "error": "render_failed"}`（`runtime.py:599-609`） |
| DCP 缺失 | `bench_e2e_loop.py:255-257` 明文返回 2；服务侧无显式守卫（`runtime.py:161-164` 直接 load，**推测**会抛异常穿透 create_app） |

---

## 6. 风险清单

| # | 风险 | 证据 | 影响面 | 建议规避 |
|---|---|---|---|---|
| 6.1 | **端点耗时 73s（1 轮）/ 44–107s（3–4 轮），超仓库 30s 预算 2.4×** | probe6（73.09s）；`exports/auto/report/*.json`（43.95–107.4s）；`gate_e2e_loop_budget.json:3` | F01 端点；同步 def 会让单请求挂 70s+，并发下线程池耗尽 | 走 `ExportManager` 式 202+task（`export.py:87-138` + `app.py:214-238`），或对 `max_iterations`/`preview_long_edge` 设上限并在响应里回 reason；**别承诺同步返回** |
| 6.2 | **`manual_on_unreliable` 缺省 True ⇒ 有任一不可靠区域即 MANUAL_REVIEW、规则全不落地** | `loop.py:751`、`engine.py:866-872`、`engine.py:1147-1163`；probe7；probe4 实测该语料 sky/plant 掩码全零 | F05 直接失败（无参数、无像素差） | 装配层**显式** `manual_on_unreliable=False`（对齐 `auto_real_edit.py:80`）；或在设计里给出替代论证 |
| 6.3 | service 缺省 `PIXO_SEGMENTER=mock` ⇒ 真 RAW 配假掩码 | `runtime.py:191-197`；MockSegmenter 实测产非零掩码 | F01 决策依据失真（region 规则基于合成掩码） | auto-loop 装配显式要求 multi/注入；缺失时降级并在响应/trace 留痕 |
| 6.4 | CR-04 字面修法（`__call__`→`.score()`）**引入 TypeError 崩溃** | probe5（`naive_state=RAISED TypeError ... 'AestheticScore'`）；`loop.py:906-932` | F04 变回归（闭环 500） | `__call__` 返回 **float/dict**；测试跨层断言 `measurement["aesthetic"]` 非空 + `parts.scorer is not None` |
| 6.5 | 库层反向依赖 service | `grep -rn service src/pixo/pipeline/*.py` 仅 docstring（`loop.py:713`）；`service/loop.py:8` 单向 | 架构红线 | 公共 API 落 `pipeline/metrics.py`；**不要在 pipeline 内 import service** |
| 6.6 | 新 gate 若复用既有 `RAW_PATH` 变量，会**连带激活** 30s 性能门禁 → 大概率 FAIL | `tests/regression/test_gate_e2e_perf.py:23,49-74`（`RAW_PATH` + `single_photo_max_seconds`）；probe6 实测 73s | F05「`pytest -m gate` 通过」 | 新门禁用**独立 marker/环境变量**（如 `PIXO_R21_RAW`），或明确只在 `-m gate_e2e` 下跑并接受既有 perf 门禁的现实；另注意 `tests/regression/conftest.py` 把 gate 内 skip **转 fail**（仅 `gate_e2e` 豁免） |
| 6.7 | 规则触发脆弱：`saturation_high_rule` 靠 6.1888 vs 6.13（1% 余量）；渲染默认值微调即翻转 | `color_rules.yaml:22-31`（阈值 `:27` + probe4 实测值 | F05 断言不稳 | 断言写「`rule_ids` 非空」而非钉死具体 rule_id；或同时锚定 `exposure_rule_001`（需受限后端） |
| 6.8 | `register_metric_keys` 全局顺序副作用（严格/宽松取决于 load_rules 与 loop 构造先后） | `loop.py:783`、`engine.py:154-155`；`auto_real_edit.py:70` 先于 `:72` | F03 lint 测试可能"假通过" | lint 测试**显式传 `metric_keys=`**；装配层也在 load_rules 时显式传 |
| 6.9 | 状态机双实例：loop 自建 sm ≠ `runtime.state_machines` ⇒ auto-loop 后 timeline 仍 RAW_PENDING | `loop.py:1783`、`runtime.py:302`、`state/machine.py:143-154` | API 语义不一致（用户看到"跑完了但状态没变"） | 响应内返回 loop 侧 `state/iteration/trace_events`；或共享 store；在 design 里明写回写策略 |
| 6.10 | `sapiens` 权重本机缺失 ⇒ 开 `PIXO_ALLOW_RESTRICTED=1` 触达 hair/skin/clothes/body 时**可能联网下载** | HF 缓存只有 `.no_exist` 零字节条目（实测）；`sapiens_body.py:31-32,175-176` | 离线环境失败/耗时不可控 | 默认不设 `PIXO_ALLOW_RESTRICTED`；F05 语料优势在于 `saturation_high_rule` 不需要它（§5.7） |
| 6.11 | F03 改动使 `measurement` 顶层多 3 键、`decision.params` 由空转非空 | `runtime.py:625`（缓存回写）、`runtime.py:658-664`；`app.py:198-212`（透传）；`test_service_api.py:188-189`（仅断言字段存在） | 前端/调用方若做严格字段断言会受影响（本轮前端零改动，风险低） | design 里显式声明为**追加式/预期行为变更** |
| 6.12 | 会话 LRU 上限 8 且逐出即 close | `runtime.py:44-45,177,345-366` | auto-loop 若依赖 session 存活会 KeyError | auto-loop 直接持 `photo.path` + `self.profile`，不依赖 session |

---

## 7. 遗留问题（范围外，仅登记）

1. **`src/pixo/render/bench/preview_cold_baseline.json` 是坏 JSON**（JSONDecodeError line 35
   col 30），且在 `src/` 内会被打包；全仓无消费者（`grep` 无命中）。建议后续清理或重生成。
2. `preview_v16_nef_baseline_cold.json` / `_hot.json` 的 `raw` 指向已消失的
   `K:\data\photo\corpus_a\raw\DSC_5236.NEF`。
3. **参考实现开箱不可跑**：`scripts/auto_real_edit.py:154,163` 的扫描根是字面量
   `<corpus_root>\corpus_a\raw` 占位符（`auto_full_scan.py:190` 同）⇒ 不带 `--photo` 时
   只会打印 "No photos found."。本轮 F05 若想复用它，需显式传 `--photo`。
4. `build/lib/pixo/**` 存在**旧副本**（如 `build/lib/pixo/pipeline/loop.py:495` 的
   `_metrics_for_decide` vs `src` 的 `:521`）⇒ 与 `src` 已漂移；建议确认打包/测试不会误取。
5. `src/pixo` 下 `except Exception` 静默降级共 **131 处**（实测：
   `(Get-ChildItem src\pixo -Recurse -Filter *.py | Select-String 'except Exception' | Measure-Object).Count`
   = 131，与 CR 文档 §1 一致），属 CR-08 范围，本轮不动。
6. `tests/regression/conftest.py` 的 hook 会把 gate 内 **skip 转成 failed**（仅 `gate_e2e` 豁免）
   —— 新 gate 用例必须带 `gate_e2e` marker 或保证永不 skip。
7. `task-brief.md:35` 的语料计数「3428」与实测 765 不符（建议队长在 design 里更正来源）。
8. `runtime.py:53-67` region 掩码供给缺省**关**（`PIXO_REGION_SUPPLY`），而 auto-loop 自走
   `RawRenderBackend` + loop 内部 `segmenter.segment`，两条掩码供给路径同源不同路，
   后续若统一需注意（本轮不处理）。

---

## 8. 探针与命令附录（可复现）

所有探针落 `%TEMP%`（仓库外），仅只读：

| 探针 | 用途 | 关键输出 |
|---|---|---|
| `pixo_r21_probe1.py` | 路由表 + preview 计时 + segment 冷热 | `routed=['rfdetr','segformer']`, `restricted=['sapiens','uniface']`, preview512 冷 2.086/热 0.196, segment 冷 24.516/热 1.825 |
| `pixo_r21_probe2.py` | 四组 decide 对照（复跑 CR 的 .artifacts 探针口径） | 嵌套/展平 **都** 0/11；`registered_metric_keys_before_loop_ctor=[]` |
| `pixo_r21_probe3.py` | 分离证明 缺陷①（无 rules）/ ②a（嵌套）/ ②b（无 proxies） | flat+无rules=0；nested+rules=0；flat+rules=3 条；补 proxies 后 +2 条 |
| `pixo_r21_probe4.py` | R21 语料真 RAW 规则可达性（`PIXO_ALLOW_RESTRICTED=1`） | `mask_nonzero={'face':164145,'sky':0,'plant':0}`；目标形态 → `exposure_rule_001, saturation_high_rule` |
| `pixo_r21_probe5.py` | 评分器适配器断裂 + 天真修法崩溃 | `adapter_has_call=false`；loop 无 aesthetic 键；`NaiveCallableAdapter` → `RAISED TypeError`；smart_crop `parts.scorer=1.0` |
| `pixo_r21_probe6.py` | 一次真实闭环分段耗时（用仓库自带 `bench_e2e_loop.run_single_benchmark`） | `total_s=73.09`，`final_qc_s=40.445`，preview 1.384，segment 0.002 |
| `pixo_r21_probe7.py` | `manual_on_unreliable` 阻断证明（engine + loop 双层） | True → `manual_review, rule_ids=[]`，loop `MANUAL_REVIEW, iteration=1`；False → `adjust_and_continue`（3 条规则）/ loop `ACCEPTED, iteration=3` |
| 导入计时 | 分层建议的成本依据 | `pixo.decide` 0.251s / `pixo.vision.measure` 0.454s / `pixo.pipeline` 0.587s / `pixo.pipeline.loop` 0.645s / `pixo.service` 1.404s |

关键命令（摘要）：
```powershell
# 语料与旧路径
Test-Path 'K:\data\photo\0711\raw\DSC_5236.NEF'        # True (28,285,604 B)
Test-Path 'K:\data\photo\corpus_a\raw\DSC_5236.NEF'    # False
Get-ChildItem 'K:\data\photo\0711\raw' -Filter *.NEF | Measure-Object   # 765
# bench JSON 合法性
python -c "import json,glob;[json.load(open(p,encoding='utf-8')) for p in glob.glob('src/pixo/render/bench/*.json')]"
#   -> preview_cold_baseline.json JSONDecodeError line 35
# 模型缓存
Get-ChildItem 'C:\Users\10042\.cache\huggingface\hub' -Directory   # segformer / face-parsing / clip / sam / dino
Get-ChildItem 'C:\Users\10042\.roboflow\models'                    # rf-detr-seg-xxlarge.pt 154,851,262 B
# 跑探针（离线，避免任何下载）
$env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"; python $env:TEMP\pixo_r21_probe1.py
```

---

## 9. 给队长的设计要点（一句话清单）

1. **接入点**：新增 `POST /api/photos/{id}/auto-loop` + `runtime.run_auto_loop()`；`decide_photo` 保持单轮语义（F03 是否顺带修好它 = **需裁决**，见 §1.4）。
2. **F02 注入点**：`rules = [r for p in DEFAULT_RULES for r in load_rules(p)]`（`auto_real_edit.py:70`），库层 `SinglePhotoLoop(rules=None)` 保持空（`loop.py:770`）；`PIXO_RULES=off` 需新加（全仓无此变量）。
3. **F03 三件套**：公共 `metrics_for_decide` 落 `pipeline/metrics.py` + service 在 `measure_session` 里**顶层**合并 `compute_proxy_metrics` + **给 decide 传 rules**（三者缺一不可，§0.1）。
4. **F04**：`__call__` 必须返回 **float/dict**（返回 `AestheticScore` 会 500），断言用 `measurement["aesthetic"]` 与 `parts.scorer is not None`（不是"非 fallback"）。
5. **F05**：真 RAW 门禁必须显式 `manual_on_unreliable=False`；断言"`rule_ids` 非空"即可（勿钉死 rule_id）；**别复用 `RAW_PATH`**（会连带激活 30s 性能门禁）；预算口径要按实测 ~73s 重新表述。
