# R21 设计（design-r21）— 闭环插电 M0

> 队长 2026-09-10 起草。依据：`.agent-team/exploration-r21.md`（researcher，466 行）+ 队长复核（本文 §0 的 6 条前提已逐条回读源码验证）。
> R9 设计已归档为 `design-r09.md`。**本文件 + 用户卡点②确认齐备后，才允许写业务代码。**

## §0 设计前提修正（探索结论 × 队长复核）

researcher 的 3 条"改变前提"发现我全部回读源码复核过，**成立**，并据此修正 CR 文档：

| # | 修正 | 复核证据 |
|---|------|----------|
| P1 | 服务层 decide 零触发是**三因叠加**（没传 rules + 指标嵌套 + 无 proxies），CR-01/03 只覆盖后两项 | `runtime.py:651-655` 调 `decide({...})` 无 `rules=`；`engine.py:1131` 缺省 `context.get("rules") or []` ⇒ `rule_ids` 结构性恒空 |
| P2 | `manual_on_unreliable` 库层缺省 `True`，**首轮即转 MANUAL_REVIEW** ⇒ 装配层必须显式 `False` | `loop.py:751` 缺省 True → `loop.py:1445/1465` 注入 context → `engine.py:866-872` 返回 `manual_review` |
| P3 | 单张真 RAW 闭环 **≈73s**（全分辨率 FINAL_QC 渲染占 98%），端点必须异步 | researcher probe6（bench_e2e_loop 实测 73.09s）；降 `preview_long_edge` 无效 |
| P4 | `_PixoScorerAdapter` 直接 `__call__` 委托 `.score()` 会 **500 崩溃**：`.score()` 返回 `AestheticScore` dataclass，无 `__float__` | `batch.py:82-88`（dataclass 字段）；`loop.py:932` `float(overall)` 位于 try 块（`:906-923`）**之外** |
| P5 | gate 内 skip 会被 conftest 转 fail，**仅 `gate_e2e` 关键字豁免** ⇒ 新 E2E 门禁必须带该标记 | `tests/regression/conftest.py` 的 `pytest_runtest_makereport` |
| P6 | 真分割器**离线可用**（`{rfdetr, segformer}` 本机权重齐），但 `resources/models/segmentation/` 目录为空是**误导**；`sapiens` 权重未下载，不得默认开 `PIXO_ALLOW_RESTRICTED` | researcher probe（`HF_HUB_OFFLINE=1` 下全通） |

**队长裁决 researcher 的两个分叉**：
- **分叉1 → 采纳 A2**：F03 顺带修好 `decide_photo`（给它展平 + 传 rules）。理由：响应**字段集合不变**，仅 `decision.params` 由 `{}` 变非空（`decide({... "metrics": metrics_for_decide(measurement), "rules": _load_auto_loop_rules(prompts)})`）；现有断言只查字段存在（`test_service_api.py:188-189`）；且不修则"服务层 decide 仍是空决策"，与 F03「口径单一来源」自相矛盾。**追加式披露**：`measurement` 顶层会多出 `haze_proxy`/`colorfulness_proxy`/`tonal_range` 3 键（`app.py:198-212` 直接透传；`test_service_api.py:151-156` 只断言 `global`/`regions`/`mask_version` 存在 ⇒ 纯追加，不改既有字段）。
- **分叉2 → 采纳**：新门禁用**独立 env** `PIXO_GATE_AUTOLOOP_RAW`，**不复用 `RAW_PATH`**（复用会连带激活 `test_gate_e2e_perf.py` 的 30s 性能门禁，而实测 73s 必 FAIL）；断言只写「`rule_ids` 非空」，**不钉死具体 rule_id**（`saturation_high_rule` 实测 6.1888 vs 阈值 6.13，仅 1% 余量）。

## §1 功能清单（F-ID → 交付物 → 验收）

| F-ID | 交付物 | 验收（可运行） |
|------|--------|----------------|
| **F01** | `PixoServiceRuntime.run_auto_loop()` + `POST /api/photos/{id}/auto-loop` + `GET /api/auto-loop/{task_id}` | 202 返回 task_id；轮询到 `status=done`、`rule_ids` 非空（= **全 trace `decide` 事件并集**，见 §2.2 与 §7「契约修订 R1」）、`iteration ≥ 2`；`tests/integration/test_auto_loop_api.py` 绿 |
| **F02** | 装配层规则注入（`PIXO_RULES=off` 可关） | `_load_auto_loop_rules(prompts)`（§2.2 规则 1）返回值非空、`PIXO_RULES=off` 时为空；"触发 ≥1 条"复用 F01 的 trace `decide` 事件证据；库层 `SinglePhotoLoop()` 仍 `rules == []`（`loop.py:770`） |
| **F03** | `src/pixo/pipeline/metrics.py`（公共 API）+ service 侧顶层合并 proxies + `decide_photo` 展平并传 rules | ①lint：显式 `metric_keys=metric_universe(("face","sky","plant"))` 后 6 个 `DEFAULT_RULES` 文件全部加载无 `DecideError` ②`decide_photo` 返回 `params` 非空（复用 `tests/integration/test_service_api.py:21-46` 的 FakeSession——`render` 返回全零图 → `shadow_clip_ratio=1.0 ≥ 0.18` 必触发 `shadow_open_rule_032`，`tone_clarity_rules.yaml:57-62`） |
| **F04** | `_PixoScorerAdapter.__call__(image_rgb, masks=None)` 返回 **dict**（契约见 §2.4） | 确定性断言（对齐 `tests/unit/test_scorer_calibration.py:17-27` 的固定假内层 scorer）：注入 loop → `measurement["aesthetic"]` 非空；同一 adapter 传 `suggest_crop(scorer=…)` → `parts.scorer is not None`（**禁止**写"非 fallback"：现状 `fallback=False` 而 `parts.scorer=None`，会误判通过） |
| **F05** | E2E 门禁 `tests/regression/test_gate_auto_loop_e2e.py` + `.r21_ok` | 真 RAW 闭环：state=ACCEPTED、params/rule_ids 非空、与"仅渲染基线"有像素差、QC overflow ≤3%、trace 含 `param_update` |

## §2 接口约定

### 2.1 公共指标 API（F03，dev-2）

新建 `src/pixo/pipeline/metrics.py`（**不得 import `pixo.service`**，方向：service → pipeline）：

```python
def metrics_for_decide(measurement: Mapping[str, Any]) -> dict[str, Any]
    """完整测量报告 → 规则引擎可引用的扁平指标 dict（现 loop.py:521-551 的公共化）。

    产出键 = 现 loop.py:527-551 全部键 + 顶层 proxies（若 measurement 已有）。
    """

METRIC_KEYS: frozenset[str]
    """flatten **固定键**（对齐 loop.py:783-792 注册面）：
    6 个 global 键（mean_luminance / highlight_clip_ratio / shadow_clip_ratio /
    contrast / preview_highlight_clip_estimate / preview_overflow_ratio）
    + 3 个顶层代理键（haze_proxy / colorfulness_proxy / tonal_range）
    + "crop_suggestion_applicable"。**不含区域键**。"""

def metric_universe(prompts: Sequence[str] = ("face", "sky", "plant")) -> frozenset[str]
    """lint/装配专用完整键宇宙 = METRIC_KEYS ∪
    {f"{p}_{s}" for p in prompts
     for s in ("luminance", "area_ratio", "highlight_clip_ratio", "reliable")}。
    **必须显式传**：区域键被 region_rules.yaml 的 condition 与 formula 同时引用
    （sky_luminance / plant_luminance，`region_rules.yaml:40-46,56,64-75,86`），
    只传 METRIC_KEYS 会让 load_rules 抛 DecideError。"""

def merge_proxy_metrics(measurement: dict[str, Any], image_rgb) -> dict[str, Any]
    """把 compute_proxy_metrics(image_rgb) 的顶层键合并进 measurement（原地+返回）。
    proxies 必须落 measurement **顶层**（与 loop.py:1352-1354 / :1730-1732 同层），
    且 service 在写 `photo.last_measurement`（runtime.py:625）**之前**调用。
    """
```

- `loop.py` 的 `_metrics_for_decide` 改为**薄别名**（`_metrics_for_decide = metrics_for_decide` 或 wrapper），保证既有导入/测试不破（实测全仓唯一引用是 `loop.py:1393`，`tests/` 零引用）。
- `compute_proxy_metrics` 须从 `pixo.vision.measure` 直接导入（`pixo.vision.__init__` 未 re-export，仅 `measure.py:584-594` 的 `__all__` 有）。
- lint 测试与 service 装配**都必须显式传 `metric_keys=metric_universe(...)`**（`register_metric_keys` 是 loop 构造期的全局 set 副作用，`loop.py:783`；严格/宽松取决于 load_rules 与 loop 构造先后，`engine.py:153-155`）。
- 公共入口：`from pixo.pipeline.metrics import metrics_for_decide, metric_universe, merge_proxy_metrics`（是否同时 re-export 到 `pipeline/__init__.py` 由 dev-2 自定，不影响契约）。

### 2.2 服务层闭环（F01/F02，dev-1）

```python
class PixoServiceRuntime:
    def run_auto_loop(
        self,
        photo_id: str,
        *,
        max_iterations: int = 3,          # env PIXO_LOOP_MAX_ITERATIONS 可覆盖，硬上限 5
        preview_long_edge: int = 1024,
        prompts: Sequence[str] | None = None,
        sync: bool = False,
    ) -> dict[str, Any]: ...
```

装配规则（**逐条固定，不允许实现者自行发挥**）：
1. `rules = _load_auto_loop_rules(prompts)`（**抽成模块级函数**，供 F02 单测直接断言）：`PIXO_RULES` ∈ {0,false,off,no} → `[]`；否则 `[r for p in DEFAULT_RULES for r in load_rules(p, metric_keys=metric_universe(prompts))]`——**必须显式传键宇宙**（§2.1），否则 `region_rules.yaml` 的 `sky_*`/`plant_*` 在 `_METRIC_KEY_REGISTRY` 非空时抛 `DecideError`。
2. `render_backend = RawRenderBackend(photo.path, self.profile)`（`loop.py:406-412`；`photo` 取自 `get_photo`，**不依赖 preview session**）
3. `segmenter = self._segmenter` **显式传入**（禁止依赖 loop 内部缺省；service 缺省 `PIXO_SEGMENTER=mock` 是合成掩码）→ 结果带 `segmenter_type`；`segmenter_type == "mock"` 时额外带 `degraded: ["mock_segmenter"]` 留痕（掩码为合成，结论不可信）
4. `manual_on_unreliable=False`（P2）
5. `aesthetic_scorer=None`（本轮只修 F04 契约，不接生产）
6. `targets={}`、`locked_params=[]`、`agent_suggest=False`、`enable_style_cards=False`（本轮不动这些层）
7. 异步执行：仿 `ExportManager` 先例（`render/web/export.py:87-138`：`ThreadPoolExecutor` + `_tasks` dict + `_lock` + `status()`），`max_workers=1`（全分辨率渲染内存开销大，串行；与"每 photo 单飞"双保险），**不复用** ExportManager 实例（职责分离）
8. 同 photo 单飞：`_active_by_photo: dict[str, str]` 记录 photo→running task_id；同 photo 已有 running 任务 → **不新起任务**，202 返回既有 task_id（幂等）；任务终结时清除。

HTTP（照 `app.py:214-246` / `:256-265` 风格，`_not_found` / `_bad_request` 映射）：
- `POST /api/photos/{photo_id}/auto-loop` → 缺省 `202 {task_id, status:"running", photo_id, segmenter_type}`（`segmenter_type=="mock"` 时追加 `degraded`）；可选 body `{"sync": true, "max_iterations": n}`；`sync=true` → **HTTP 200 + 与 GET 同构的结果体**（供测试/脚本），异常同样落 `status=failed`，**不裸抛**。
- `GET /api/auto-loop/{task_id}` → `{task_id, status: running|done|failed, photo_id, segmenter_type, state, iteration, params, rule_ids, rule_ids_by_iteration, trace_event_count, error, duration}`（`degraded` 仅非空时出现；与已落实现 `runtime.py:901-921` 一致，`photo_id/segmenter_type/duration` 为既有实现字段，`rule_ids_by_iteration` 为**追加**键——既有键不减、不改名）；`rule_ids` = **全 trace 中所有 `event_type=="decide"` 事件 `value["rule_ids"]` 的并集**（保持首次出现顺序、去重）——**不是**"最后一条"，也**不是** `LoopResult.decision`（后者是 `sm.state` 字符串，`loop.py:1937`）。`rule_ids_by_iteration` = `[{iteration, rule_ids}, ...]`（iteration 取 `value["iteration"]`，缺失回退 `metadata["iteration"]` 再回退事件序号；见 `runtime.py:993-1054`），诊断用。理由见 §7「契约修订 R1」。

**失败语义**：photo 不存在 → 404；`max_iterations` 非法（非整数 / ≤0 / >硬上限 5）→ 400；task_id 未知 → 404；闭环内部异常（`LoopError` 等）→ 结果 `status=failed` + `error`（异常类型 + 首行），**不让 HTTP 500 穿出**（异步与 sync 两路一致）。**"无 preview session" 不是错误**：auto-loop 只用 `photo.path` + `self.profile`（对齐 exploration §6.12），不读 session / `canonical_params`。
**超时/时长口径**：不实现任务级超时/取消（渲染无中断点）；可控手段 = `max_iterations`（缺省 3，env `PIXO_LOOP_MAX_ITERATIONS` 可覆盖，**硬上限 5**）+ `preview_long_edge`。实测单次闭环 43.95–107.4s（`exports/auto/report/*.json`；probe6 `max_iterations=1` = 73.09s）⇒ 必须 202 + 轮询。

### 2.3 状态机回写策略（researcher 遗留项，队长裁决）

loop 自建状态机（`loop.py:1783`）≠ `runtime.state_machines`（`runtime.py:302`）。
**本轮裁决：不回写任何既有缓存** —— 结果只落**任务表**（`state / iteration / params / rule_ids / rule_ids_by_iteration / trace_event_count / duration`）；**不改 `runtime.state_machines`**（避免双写不一致），**也不写 `photo.last_decision`**：该字段是引擎决策缓存，`GET /api/photos/{id}/decide` 按引擎 schema 原样透传（`app.py:287-288`），且 `tests/unit/test_service_runtime_fixes.py:164-173` 断言 `photo.last_decision == result["decision"]`——写入 `LoopResult` 会让该端点返回异形 `decision`（静默契约破坏）。`/timeline`（及 `/decide` 缓存）与 auto-loop 不联动作为**已登记遗留**（tech_debt **#20**，本轮不修；编号经队长核对台账：现有最后一条为 19）。

### 2.4 评分器适配器契约（F04，dev-2）

```python
def __call__(self, image_rgb, masks=None):
    del masks                      # 真评分器不消费掩码（同 .score 语义，batch.py:358）
    s = self.score(image_rgb)      # AestheticScore | None（batch.py:353-410，当前不返回 None）
    if s is None:                  # 防御，保持契约完整
        return None
    return {"overall": s.overall, **s.dimensions,
            "source": s.source, "raw_overall": s.raw_overall,
            "domain_hint": s.domain_hint}
```

- **必须返回 dict，不得返回 `AestheticScore` 本体**：loop 侧 `float(overall)`（`loop.py:932`）位于 `try`（`:906-923`）**之外**，dataclass 无 `__float__` ⇒ `TypeError` 穿出 `run()`（probe5 实测），静默跳过变 HTTP 500。
- dict 形态同时满足两个消费者：`loop.py:924-932`（`overall` + 其余键原样进 `measurement["aesthetic"]`）与 `smart_crop._score_scalar` 的 dict 分支（`smart_crop.py:199-208`）。
- 批量线不受影响（`batch.py:710` 仍走 `.score(image, meta)`）；dict 带 `source / raw_overall / domain_hint` 是为保住溯源字段（exploration §4.5 副作用项）。
- 测试必须**跨层注入真 adapter**：`tests/unit/test_scorer_adapter_callable.py` 用固定假内层 scorer 构造 `_PixoScorerAdapter`（对齐 `tests/unit/test_scorer_calibration.py:17-27`），分别注入 `SinglePhotoLoop` 与 `suggest_crop`；**不要**依赖 `make_default_scorer()` 的真假分支（真模型不可用时回退 `MockAestheticScorer`，`batch.py:302-315`，其只有 `.score()` 无 `__call__` ⇒ 会伪装成"契约正常"）。

## §3 开发流与文件域

| 流 | 角色 | 文件域（**互斥，越界报队长**） |
|----|------|-------------------------------|
| stream-1 | `dev-1` | `src/pixo/service/runtime.py`、`src/pixo/service/app.py`、`tests/integration/test_auto_loop_api.py`（新建） |
| stream-2 | `dev-2` | `src/pixo/pipeline/metrics.py`（新建）、`src/pixo/pipeline/loop.py`（仅别名/导入行）、`src/pixo/pipeline/batch.py`（仅 `_PixoScorerAdapter` 加 `__call__`）、`tests/unit/test_metrics_for_decide_public.py`、`tests/unit/test_scorer_adapter_callable.py`（均新建） |
| 门禁 | `tester` | `tests/regression/test_gate_auto_loop_e2e.py`（新建）+ 全量回归执行 |
| 审核 | `QA-checker` | `design-review-r21.md`、`qa-report-r21.md`、`.design_ok`、`.qa_ok`、`.r21_ok` |

**冲突点**：`loop.py` 归 dev-2；dev-1 只**调用**公共 API，不得改 `loop.py`。
**F03 接线归属（按 `team-manifest.md:39` 仲裁重申）**：公共 API（`metrics.py` / 别名 / 签名适配）由 dev-2 交付；**service 侧接线**（`measure_session` 顶层合并 proxies、`decide_photo` 展平 + 传 rules、F03 验收②及其测试，落 `tests/integration/test_auto_loop_api.py`）由 **dev-1** 执行——两流仍不共改任一文件。

## §4 门禁与验收（F05 细节）

- 新 gate：`tests/regression/test_gate_auto_loop_e2e.py`：文件级 `pytestmark = pytest.mark.gate` + 用例级 `@pytest.mark.gate_e2e`（**两个都要**——`gate` 才被 CR-05 的 `-m gate` 选中；`gate_e2e` 才被 conftest 的 skip→fail 规则豁免，`tests/regression/conftest.py:8-15`）；`@pytest.mark.skipif(not os.environ.get("PIXO_GATE_AUTOLOOP_RAW"), …)`；env `PIXO_GATE_AUTOLOOP_RAW=<NEF 路径>`（`PIXO_GATE_AUTOLOOP_MAX_ITER` 默认 2）。**不复用** `RAW_PATH`（否则连带激活 30s 性能门禁，`test_gate_e2e_perf.py:23,49-74`）。
- gate 装配：`SinglePhotoLoop(rules=_load_auto_loop_rules(prompts), segmenter=真路由（MultiModelSegmenter 或 PIXO_SEGMENTER=multi）, manual_on_unreliable=False, preview_long_edge=1024, max_iterations=PIXO_GATE_AUTOLOOP_MAX_ITER)`；**不设** `PIXO_ALLOW_RESTRICTED`（P6）。
- 运行命令（test-report 必须附输出）：`$env:PIXO_GATE_AUTOLOOP_RAW='K:\data\photo\0711\raw\DSC_5236.NEF'; python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate`（`import pixo` 依赖 `src` 入 `sys.path`，由 `tests/conftest.py:21-22` 保证 ⇒ 必须经 `python -m pytest` 跑，勿裸跑脚本）。
- **断言集（全部必须有运行证据）**：
  1. `result.state == "ACCEPTED"`（若 `MANUAL_REVIEW` 必须给出理由与证据，不得直接放宽断言）
  2. `result.params` 非空；`rule_ids` 非空 = **全 trace 所有 `event_type=="decide"` 事件 `value["rule_ids"]` 的并集**（保持首次出现顺序、去重；**不钉死 rule_id**）。**不得**取"最后一条"：末轮 `rule_ids=[]` 有两条**合法**成因——① 末轮 `iteration>=max_iterations` 的 `last_iteration` 分支**照跑规则**（`engine.py:977-989`，`should_stop=False`）但该轮规则自然不命中（本语料：首轮 `saturation_high_rule` 命中并写入降饱和参数后，末轮 `colorfulness_proxy` 降到 **5.8936** < 阈值 6.13 ⇒ 无规则命中，`tmp-r21-gate-run.txt:98`）；② `should_stop=True` 短路（`engine.py:1147-1163`）透传 `rule_ids=[]`。两者都合法 ⇒ 取"最后一条"会在**末轮自然不命中的样本**上漏掉早期命中（tester 2026-09-10 首跑 `DSC_5236` 即 `1 failed in 102.90s`，证据见 §7 契约修订 R1）。**措辞不得写成不变量**：既不是"终止轮必空"，也不是"旧口径必挂"——tester D1 实测 `DSC_5237` 末轮**就是命中的**（`colorfulness_proxy` 5.8847 → **6.1472**），旧口径在该样本上会通过。`LoopResult.decision` 是状态字符串（`loop.py:1937`），**不能**写 `decision.rule_ids`
  3. `final_image` 与"仅渲染基线"（同 backend `render_full(base_params)` 重渲一次）**存在像素差**：`np.any(final != baseline)`（同 shape/dtype）
  4. FINAL_QC 高光溢出 ≤ 3%：`result.final_measurement["global"]["highlight_clip_ratio"] <= 0.03`（阈值同源 `engine.py:81`；loop 读同键 `loop.py:1745-1749`）
  5. `trace_events` 含 `param_update`（`loop.py:1131-1142`），且 `measurements` 长度 ≥ 2
  6. **聚合自洽（正控，必跑）**：`rule_ids` 必须等于 `rule_ids_by_iteration` 的逐轮并集（同序去重后逐项相等）——钉住"服务提取口径与 trace 自洽"，不依赖特定语料形态。
  7. **负控（单元级、无 RAW、必跑）**：对聚合口径喂人工 trace —— ① 全部 `decide` 事件 `rule_ids=[]`（含空 trace）→ 必须返回 `[]`（证明不伪造命中）；② 第 1 轮命中 + 第 2 轮为空 → 必须返回第 1 轮命中（证明不丢早期命中）。落 `tests/integration/test_auto_loop_api.py`（承接方 dev-1）。
     - ⚠️ **不得**用 `PIXO_GATE_AUTOLOOP_MAX_ITER=1` 充当负控：`iteration>=max_iterations` 的末轮**不是短路**（`engine.py:977-989`，t107 off-by-one），规则照跑，本语料首轮必命中 ⇒ 并集非空，会得出错误结论（依据 `tmp-r21-gate-run.txt:98`：末轮 `last_iteration=True` 且 `decision='adjust_and_continue'`）。
- 耗时上限：单次 gate 600s 软上限（实测单次闭环 43.95–107.4s；probe6 `max_iterations=1` = 73.09s；gate `max_iterations=2`）。
- 全量回归 ≥ **1533 passed / 0 failed**；金样本 gate 零漂移（本轮不碰渲染像素路径）。
- `.r21_ok` 由 `QA-checker` 执笔：审核人 / 覆盖 F-ID / ISO 时间戳 / 结论。
- 队长收尾（brief 完成标准 6）：`docs/changelog.md` 追加 R21 条目 + `.agent-team/DELIVERY-R21.md`。

## §5 风险与规避

| 风险 | 影响 | 规避 |
|------|------|------|
| 单次 73s（全分辨率占 98%） | 端点超时、门禁慢 | 异步 task + 202；gate `max_iterations=2`；响应不下发大图（只给 state/params/统计） |
| `sky`/`plant` 掩码全零（默认路由下 `face` 亦为零掩码，本机 R21 语料实测） | 首轮 MANUAL_REVIEW，F05 直接失败 | 装配层 `manual_on_unreliable=False`（P2）；区域规则不触发可接受（proxy 规则触发）。**注意** F05 的 `rule_ids` 非空实际压在 `saturation_high_rule`（`colorfulness_proxy` 6.1888 vs 阈值 6.13，`color_rules.yaml:22-31`，约 1% 余量）上：若 gate 实测落空，按「需队长裁决」上报，**不得**放宽断言或改语料。**首跑实测已命中**（迭代 1 命中并写入 `colorcal.saturation=-0.15`，迭代 2 该指标降到 5.8936 ⇒ 规则自熄火，`tmp-r21-gate-run.txt:98`） |
| 缺省 `PIXO_SEGMENTER=mock` | 拿到合成掩码，结论不可信 | 显式传 segmenter + 响应暴露 `segmenter_type`；gate 用真路由（离线可用，P6） |
| `loop.py` 双向改动（别名 + 签名） | 与其他流冲突 | 文件域互斥：`loop.py` 归 dev-2 独占 |
| `register_metric_keys` 全局副作用 | lint 松紧不定，测试假绿 | lint 显式传 `metric_keys=`（§2.1） |
| 端点并发（同一 photo 重复提交） | 重复渲染、资源耗尽 | task 表 + 每 photo 单飞（同 photo 有 running 任务时返回既有 task_id） |

## §6 非目标（复核 brief，不变）

CR-06/07（降噪）、CR-09/10（风格 LUT/场景）、CR-11（多轴 QC）、CR-12/13（RP-CCM/skin）、前端零改动、不动渲染算子、不重生成金样本、不碰 `configs/color/calib_out/`。

## §7 用户确认记录（卡点②）+ 队长对 QA 待裁决项 D1~D5 的裁决

### 队长裁决（**不改任何设计规格**，仅收口 QA 在 `design-review-r21.md §10` 提出的 5 项）

| # | 事项 | 队长裁决 |
|---|------|----------|
| D1 | F05 的 `rule_ids` 非空实际只压在 `saturation_high_rule`（约 1% 余量） | **接受现状，不放宽断言、不改语料、不启用 `PIXO_ALLOW_RESTRICTED`**（离线纪律 + `sapiens` 权重缺失）。追加执行要求：`tester` 在 `test-report-r21.md` 附**固定 3 张**样本（`DSC_5236/5237/5238.NEF`，取字典序前 3，规则固定可复现）的实测 `colorfulness_proxy` 与 `rule_ids`，供队长判断余量真实性；若 DSC_5236 实测落空 → 报队长，**不得**自行放宽 |
| D2 | CR-04 字面点名的 `make_default_scorer()` 真假分支 | **采纳 QA**：必测用确定性假内层 scorer（真模型不可用时回退的 `MockAestheticScorer` 无 `__call__`，会假绿）。追加**非门禁观测**：若 `make_default_scorer()` 返回的是 `_PixoScorerAdapter`，`tester` 在报告里记一条 `callable(...)` 实测结果 |
| D3 | auto-loop 与 `/decide` 缓存、`/timeline` 不联动 | **同意登记为 tech_debt #20**（台账现有最后一条为 19，故新债从 20 起编），本轮不修（设计 §2.3 已定「不回写任何既有缓存」） |
| D4 | 长耗时端点无任务级超时/取消 | **M0 不加**（渲染无中断点）；可控手段 = `max_iterations ≤ 5` + `duration` 落任务结果。**登记为 tech_debt #21**（任务级超时/取消），交付时写入 `docs/tech_debt.md` |
| D5 | CR-01 的 curl 手测由 F05 gate 替代 | **同意**，但要求 `tests/integration/test_auto_loop_api.py` 用 FastAPI `TestClient` 打一次真实 HTTP 往返（POST→202→GET→done）作为 HTTP 层证据 |

### 卡点②用户确认

- 2026-09-10：**用户批准设计（卡点②通过）**，批准形式＝选项「批准设计，开写代码」。
- 开发放行前置齐备：`.design_ok`（`QA-checker` 签章，ISO `2026-09-10T21:45:36+08:00`）+ 本确认记录。
- 随之放行的开发流：`stream-1`（dev-1，F01+F02+F03 接线）、`stream-2`（dev-2，F03 公共 API + F04）。

### 契约修订 R1（2026-09-10，tester 真 RAW 首跑 FAILED 后；QA 增量复核**通过**，见 `design-review-r21.md §11`）

**触发**：tester 首跑 F05 门禁 → `1 failed in 102.90s`，失败点为断言②「`rule_ids` 结构性为空」；其余四条断言**全部通过**（`state=ACCEPTED`、`params` 非空、`has_param_update=True`、`measurements=2`、`highlight_clip_ratio=0.025923 ≤ 0.03`、`rules_count=11`、`segmenter_last_degraded=[]`）。

**根因（QA 增量复核：纠正首版归因，以 tester 实跑证据为准）**：末轮 `rule_ids=[]` 有**两条都合法**的空路径，engine/loop 均不改——

1. **本次实测触发的路径 = 末轮规则自然不命中（不是短路）**：`iteration >= max_iterations` 走 `check_termination` 的 `last_iteration` 分支，该分支返回 **`should_stop=False`**（`engine.py:977-989`，注释明写 t107 off-by-one：末轮规则**必须**触发一次）⇒ `decide()` 不短路、照常跑规则评估（`engine.py:1165-1173`，`_output` 第 4 位=applied 的 rule_ids，`engine.py:1086-1092`），loop 应用本轮参数后 break（`loop.py:1661-1664`）。实测末轮 decide 事件（`tmp-r21-gate-run.txt:98`）：`{decision:'adjust_and_continue', last_iteration:True, rule_ids:[], params:{'colorcal':{'saturation':-0.15}}, metrics.colorfulness_proxy:5.8936}` ⇒ 首轮 `saturation_high_rule` 命中（阈值 6.13，`color_rules.yaml:25-31`）并写入降饱和参数，**末轮该指标已降到 5.8936 < 6.13 ⇒ 该轮确实无规则命中**，`rule_ids=[]` 语义正确。
2. **短路路径（另一条合法空路径）**：`check_termination` 返回 `should_stop=True`（如 `low_improvement`/`targets_met`）时，`decide()` 在 `engine.py:1147-1163` 短路返回 `rule_ids=[]` + 原样透传 params。

两条路径共同说明：**错的是服务层「取最后一条 decide」这个口径**（修复前 `runtime._auto_loop_rule_ids()` 逐条**覆盖赋值**，旧 `runtime.py:984-1001` ⇒ 任何"末轮空"的闭环都结构性恒空），**不是**"末轮该有 rule_id"。同一口径使 §1 F01 的「`rule_ids` 非空」在真 RAW 上同样不成立（dev-1 的 18 passed 走注入假 backend 的合成路径，未覆盖此形态）。

**队长裁决（QA 复核后维持方向，规格纠正）**：
- **采纳 A（修订提取口径）**：`rule_ids` = **全 trace 所有 `event_type=="decide"` 事件 `value["rule_ids"]` 的并集**（保持首次出现顺序、去重）；任务结果追加 `rule_ids_by_iteration`（诊断）。承接方：**`dev-1`**（service 侧提取 + 单测；已落 `runtime.py:993-1054`：`_auto_loop_rule_ids`=并集、`_auto_loop_rule_ids_by_iteration`=逐轮）**+ `tester`**（gate 侧同源口径，`tests/regression/test_gate_auto_loop_e2e.py:106-116` `_decide_rule_ids_union`，复跑取数）。用例规格须写成「**首轮命中、末轮自然不命中**（`last_iteration=True` 且该轮 `colorfulness_proxy` 已低于阈值）⇒ 并集非空」；**禁止**断言"终止轮必空"——那是**错误不变量**（`iteration>=max_iterations` 的末轮照跑规则）。
- **不采纳 B（不修 engine/loop）**：终止/末轮"未应用规则"是正确语义，透传历史 rule_ids 会让 trace 失真。
- 已同步修订 §1 F01、§2.2 GET 契约、§4 断言②（已由 `QA-checker` 增量复核通过并生效；根因归因与负控规格经复核纠正，见 `design-review-r21.md §11`）。

**未放宽项**：tester **未**放宽断言、**未**改语料、**未**开 `PIXO_ALLOW_RESTRICTED`（遵 §7 D1 与任务书范围边界）。
