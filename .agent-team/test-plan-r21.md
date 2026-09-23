# 测试计划（test-plan-r21.md）— Pixo 第二十一轮（R21，闭环插电 M0）

> 角色：`tester`（阶段 7）｜拟定 2026-09-10｜工作目录 `K:\work\project\pixo`（Windows / PowerShell）
> 唯一验收依据：`.agent-team/design-r21.md` **§4（门禁与验收细节）**+ §1（F-ID 验收）+ §2.2（服务层接口与 HTTP 语义）+ §2.1（键宇宙）
> 上游交付：`.agent-team/streams/r21-stream-1.md`（dev-1：F01/F02/F03 接线）、`.agent-team/streams/r21-stream-2.md`（dev-2：F03 公共 API + F04）
> 下游消费者：`QA-checker`（阶段 8 总审，签 `.qa_ok` / `.r21_ok`）
> 范围边界：**只写** `tests/regression/test_gate_auto_loop_e2e.py`（新建）+ 本计划 + `test-report-r21.md`；**不改 `src/**`**。

## 0. 基线与环境前提

| 项 | 值 | 依据 |
|---|---|---|
| 全量回归口径 | `python -m pytest tests -q -m "not e2e"` | `.agent-team/.r20_ok:73`（R20 终态 1533 passed / 5 skipped / 1 xfailed / 0 failed） |
| 全量红线 | **≥ 1533 passed / 0 failed** | `task-brief.md:67-68`、design §4 |
| 金样本门禁口径 | `python -m pytest tests/regression/test_gate_golden.py -q` + `python src/pixo/render/tools/gate_golden.py compare ...` | `.agent-team/.r20_ok:17-19,72` |
| F05 门禁 env | `PIXO_GATE_AUTOLOOP_RAW`（缺省 `PIXO_GATE_AUTOLOOP_MAX_ITER=2`） | design §4；**禁止复用 `RAW_PATH`**（否则连带激活 `test_gate_e2e_perf.py` 的 30s 性能门禁而必挂，exploration §6.6） |
| F05 语料 | `K:\data\photo\0711\raw\DSC_5236.NEF` | design §4、`task-brief.md:35` |
| 离线纪律 | `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`；**不设** `PIXO_ALLOW_RESTRICTED` | design §4、exploration §5.4/§6.10（`sapiens` 权重缺失） |
| 单次真闭环成本 | ≈73s/1 轮，FINAL_QC 全分辨率占 ~98% | exploration §5.6；gate 软上限 600s（design §4） |
| 测试进程约束 | 长命令输出**重定向到文件**再读（PS 5.1 `*>` 写 UTF-16 ⇒ 改用 `cmd /c "... > f 2>&1"` + `PYTHONIOENCODING=utf-8`） | 本机陷阱（任务书执行纪律） |
| 被测实现 | `src/pixo/service/runtime.py`（`run_auto_loop`/`_load_auto_loop_rules`）、`src/pixo/service/app.py`（两端点）、`src/pixo/pipeline/metrics.py`、`src/pixo/pipeline/batch.py`（`__call__`） | design §2 |

## 1. F-ID × 用例 × 预期（F01~F05）

| F-ID | 验收条目（design §1） | 用例 / 命令 | 预期 |
|---|---|---|---|
| **F01** | 202 返回 task_id；轮询到 `status=done`、`rule_ids` 非空、`iteration ≥ 2`；`tests/integration/test_auto_loop_api.py` 绿 | ① `python -m pytest tests/integration/test_auto_loop_api.py -q`（整文件）② 关键子集 `-k "http or run_auto_loop or auto_loop_rule_ids or env_overrides or single_flight"` | ①`20 passed / 0 failed`（首版 18 + R1 新增 2）②HTTP 真实往返 POST→202→GET→done、`rule_ids` = **全 decide 事件并集**（R1 修订口径，见 §2.1）、`rule_ids_by_iteration` 自洽、单飞幂等、400/404 语义齐备 |
| **F02** | `_load_auto_loop_rules(prompts)` 非空、`PIXO_RULES=off` 时为空；库层 `SinglePhotoLoop()` 仍 `rules == []` | ① 探针：`from pixo.service.runtime import _load_auto_loop_rules` → 计数/RULE id 清单 ② `python -m pytest tests/integration/test_auto_loop_api.py -q -k "rules"` | ①`len==11` 且 id 清单与 6 个规则文件吻合 ②`PIXO_RULES=off`（0/false/no/大小写）→ `[]`；库层缺省 `[]` |
| **F03** | ①显式 `metric_keys=metric_universe(("face","sky","plant"))` 后 6 个文件全加载无 `DecideError` ②`decide_photo` 返回 `params` 非空 | ① `python -m pytest tests/unit/test_metrics_for_decide_public.py -q`（14 用例）② `python -m pytest tests/integration/test_auto_loop_api.py -q -k "decide_photo or proxy"` | ①`14 passed`（含负控：只传 `METRIC_KEYS` 抛 `DecideError`）②`decision.params` 非空、`measurement` 顶层含 `haze_proxy/colorfulness_proxy/tonal_range` 三键、既有字段集合不变 |
| **F04** | ①注入 loop → `measurement["aesthetic"]` 非空 ②同一 adapter 传 `suggest_crop(scorer=…)` → `parts.scorer is not None` | `python -m pytest tests/unit/test_scorer_adapter_callable.py -q`（6 用例，固定假内层 scorer） | `6 passed`；`__call__` 返回 **dict**（非 `AestheticScore` 本体，反面样本 `float()` 抛 `TypeError`）；`.score(image_rgb, meta)` 签名不变；D2 追加观测：`make_default_scorer()` 返回类型 + `callable(...)` 实测 |
| **F05** | 真 RAW 闭环：`state=ACCEPTED`、`params`/`rule_ids` 非空、与「仅渲染基线」有像素差、QC 溢出 ≤3%、trace 含 `param_update` | `$env:PIXO_GATE_AUTOLOOP_RAW='K:\data\photo\0711\raw\DSC_5236.NEF'; python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate -s -rA` | `1 passed`；五条断言逐条有打印证据（见 test-report §3） |

## 2. 门禁用例设计（`tests/regression/test_gate_auto_loop_e2e.py`）

**marker 双写**（缺一即挂）：
- 文件级 `pytestmark = pytest.mark.gate` ⇒ 被 CR-05 的 `-m gate` 选中；
- 用例级 `@pytest.mark.gate_e2e` ⇒ 被 `tests/regression/conftest.py:13-15` 的 skip→fail 规则豁免。

**装配**（design §4 逐条固定）：

```
SinglePhotoLoop(
    render_backend=RawRenderBackend(raw_path, prof),   # 同 backend 供基线重渲
    segmenter=MultiModelSegmenter(),                   # 真路由，非 mock 合成掩码
    rules=_load_auto_loop_rules(("face","sky","plant")),
    preview_long_edge=1024,
    max_iterations=int(os.environ.get("PIXO_GATE_AUTOLOOP_MAX_ITER","2")),
    prompts=["face","sky","plant"],
    manual_on_unreliable=False,                        # P2 硬要求
)
```
`prof = load_dcp(resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp)`；**不设** `PIXO_ALLOW_RESTRICTED`。
离线：用例内 `monkeypatch.setenv("HF_HUB_OFFLINE","1")` / `TRANSFORMERS_OFFLINE`（避免污染同进程其它测试）。

**断言与预期失败信号**：

| # | 断言 | 预期失败信号（诊断用） |
|---|---|---|
| 1 | `result.state == "ACCEPTED"` | 失败消息带 `reason` + 逐条 decide 事件 + `trace_event_types` |
| 2 | `result.params` 非空 且 `rule_ids` 非空 | **口径经队长 2026-09-10 裁决修订**（见 §2.1）：`rule_ids` = 全 trace `event_type=="decide"` 事件 `value["rule_ids"]` 的**并集**（首次出现序、去重）；**不钉死具体 rule_id**。失败时打印逐条 decide 事件 |
| 3 | `final_image` 与 `backend.render_full({})` 同 shape/dtype 且 `np.any(final != baseline)` | 打印 `baseline_pixel_diff` 计数 |
| 4 | `final_measurement["global"]["highlight_clip_ratio"] <= 0.03` | 阈值同源 `engine.py:81` / `loop.py:1745-1749` |
| 5 | `trace_events` 含 `param_update` 且 `len(measurements) >= 2` | 打印去重后的 `trace_event_types` |

### 2.1 断言② 口径修订（首跑 FAILED 的实测结论与裁决）

首跑（`PIXO_GATE_AUTOLOOP_RAW=DSC_5236.NEF`）实测：`state=ACCEPTED`、
`params={'colorcal':{'saturation':-0.15}}` 非空，但**最后一条 decide 的
`rule_ids` 为空** ⇒ 原「取最后一条」口径 FAILED。

实测结论（QA 增量复核纠正了 tester 首版归因）：末轮 `rule_ids=[]` 有**两条都合法**的
空路径 —— ① **本次触发的是「末轮规则自然不命中」（不是短路）**：`iteration >=
max_iterations` 走 `check_termination` 的 `last_iteration` 分支，该分支返回
`should_stop=False`（`engine.py:977-989`，t107 off-by-one：末轮规则**必须**触发一次）
⇒ `decide()` 照常评估规则（`engine.py:1165-1173`）；首轮 `saturation_high_rule` 命中
（preview `colorfulness_proxy` **6.1888** ≥ 6.13）并落地 `saturation=-0.15`，末轮该指标
降到 **5.8936** < 6.13 ⇒ 该轮确实无规则命中。② 另一条合法空路径：`should_stop=True`
时 `decide()` 在 `engine.py:1147-1163` 短路返回 `rule_ids=[]`（**本次未触发**）。

⇒ 缺陷是「取最后一条」这个**提取口径**：它**会漏掉早期命中**（**不是**必然为空 ——
D1 实测 DSC_5237 末轮命中、末条非空）。服务侧 `runtime._auto_loop_rule_ids` 原用同一
口径 ⇒ 真 RAW 下服务结果 `rule_ids` 亦可能为空。

**队长裁决（2026-09-10）：选 A —— 修订提取口径，不改 engine**（终止轮未应用规则是引擎
语义，不该让 trace 说谎）。新口径 = 全 decide 事件 `rule_ids` 并集 + 任务结果追加
`rule_ids_by_iteration` 诊断字段；design 新增断言⑥（正控）/⑦（负控）；已在
`test_gate_auto_loop_e2e.py` 落地（其余四条断言原文不动 + 断言⑥ + 负控镜像 +
逐条 decide 诊断打印）。dev-1 已同源修订 `runtime.py`。

**skip 语义**：无 `PIXO_GATE_AUTOLOOP_RAW` 时 `1 skipped`（因带 `gate_e2e` 豁免，**不得**变 failed）——此路径需先验证。

## 3. 执行批次（本轮实际执行）

| 批次 | 命令（工作目录 `K:\work\project\pixo`） | 覆盖 |
|---|---|---|
| B0 收集/豁免自检 | `python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate --collect-only`；无 env 复跑 → `1 skipped` | F05（marker 双写） |
| B1 F05 真 RAW 门禁 | `$env:PIXO_GATE_AUTOLOOP_RAW='K:\data\photo\0711\raw\DSC_5236.NEF'; python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate -s -rA` | F05 |
| B2 F01 定向 | `python -m pytest tests/integration/test_auto_loop_api.py -q` | F01 F02 F03(service) |
| B3 F03 定向 | `python -m pytest tests/unit/test_metrics_for_decide_public.py -q` | F03 |
| B4 F04 定向 | `python -m pytest tests/unit/test_scorer_adapter_callable.py -q` | F04 |
| B5 邻域回归 | `python -m pytest tests/integration/test_service_api.py tests/unit/test_service_runtime_fixes.py -q` | 服务层既有契约（含 `last_decision`） |
| B6 D1 三样本证据 | `.agent-team/tmp-r21-d1-probe.py`（真 RAW ×3：`DSC_5236/5237/5238.NEF`，与门禁同装配，`max_iterations=2`） | D1（队长追证） |
| B7 全量回归 | `python -m pytest tests -q -m "not e2e"` | 全部 |
| B8 金样本零漂移 | `python -m pytest tests/regression/test_gate_golden.py -q` + `python src/pixo/render/tools/gate_golden.py compare --samples … --out …` | design §4 |

## 4. 判定标准

- 各批次 **0 failed**；输出原样摘录入 `test-report-r21.md` 证据节（命令 → 关键行 → 结论）。
- 全量 **passed ≥ 1533**，`0 failed`；skip/xfailed 变动逐条给原因。
- 金样本 `test_gate_golden.py` 7 passed（含 `test_current_output_matches_goldens`）+ `gate_golden.py compare` 全 PASS；manifest sha 与 `.npy` 一致。
- **不得放宽断言**：F05 若 `state != ACCEPTED` 或 DSC_5236 `rule_ids` 落空 ⇒ 按 design §7 D1 上报队长，禁止改语料 / 放宽断言 / 开 `PIXO_ALLOW_RESTRICTED`。
- 发现缺陷：只记入 test-report 的「缺陷」节并回报队长（**不改 `src/**`**，回归/修复由原开发流执行）。

## 5. 范围外 / 移交

- CR-06/07/09/10/11/12/13、前端零改动、不动渲染算子/金样本/`configs/color/calib_out/`（design §6）→ 不在本轮测试面。
- `build/lib/pixo/**` 旧副本漂移、坏 JSON `preview_cold_baseline.json`、语料计数口径（3428 vs 765）等 exploration §7 项 → 「遗留问题」节登记，不验不改。
- `.r21_ok` 签章由 `QA-checker` 执笔（design §4）。
