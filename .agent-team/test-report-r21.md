# 测试报告（test-report-r21.md）— Pixo 第二十一轮（R21）F01~F05 验收 + 全量回归

> 角色：`tester`（阶段 7）｜产出时间 2026-09-10｜工作目录 `K:\work\project\pixo`（Windows / PowerShell）
> 验收依据：`.agent-team/design-r21.md` §4（门禁，含契约修订 R1 后的断言 1~7）/§1（F-ID）/§2.1·§2.2（接口与键宇宙）+ `.agent-team/test-plan-r21.md`
> 上游：`streams/r21-stream-1.md`（dev-1）、`streams/r21-stream-2.md`（dev-2）｜下游：`QA-checker`（阶段 8 总审，签 `.qa_ok` / `.r21_ok`）
> 范围：本轮 tester 新增 `tests/regression/test_gate_auto_loop_e2e.py`；**`src/**` 零改动**（发现缺陷只记不修，见 §4）

## 0. 一句话结论

**通过**。F01~F05 五条功能 ID 均有「命令 → 输出关键行 → 结论」的运行证据；**F05 真 RAW 门禁 `2 passed`**
（五条断言 + 契约修订 R1 的断言⑥正控 + 断言⑦负控镜像，全部有运行证据）；**全量回归 1574 passed / 0 failed**（≥1533 红线）；
**金样本门禁零漂移**（合成 gate 7 passed + 真 RAW 24 case compare）。

唯一硬性回退发生在首跑：design §4 断言② 的「最后一条 decide 事件」提取口径**会漏掉早期命中**
（本语料实测 DSC_5236 末条为空、DSC_5237 末条命中 —— 两种形态都存在，见 §5）；
经队长 2026-09-10 裁决（契约修订 R1）改为「全 decide 事件并集」后复跑通过 —— 属**契约修订**（QA 增量复核已定稿归因），
**不是**放宽断言：并集口径比原口径**更严**（原口径会静默丢掉早期命中）。

## 1. 交付物与执行环境

| 交付物 | 路径 | 状态 |
|---|---|---|
| F05 门禁（新建） | `tests/regression/test_gate_auto_loop_e2e.py` | ✅ 2 passed（e2e 1 + 聚合口径负控镜像 1；交付版最终复跑 `2 passed in 122.12s`） |
| 用例计划 | `.agent-team/test-plan-r21.md` | ✅ |
| 本报告 | `.agent-team/test-report-r21.md` | ✅ |
| 原始运行证据（UTF-8 文本，可复核） | `.agent-team/tmp-r21-gate-run{,-2,-3}.txt`、`tmp-r21-gate-final.txt`、`tmp-r21-gate-collect*.txt`、`tmp-r21-gate-skip.txt`、`tmp-r21-gate-mirror.txt`、`tmp-r21-b2-targeted.txt`、`tmp-r21-b2-autoloop.txt`、`tmp-r21-b3-metrics.txt`、`tmp-r21-f02-d2.txt`、`tmp-r21-d1-probe.txt`、`tmp-r21-d1-table.txt`、`tmp-r21-fulltest.txt`、`tmp-r21-golden-pytest.txt`、`tmp-r21-golden-compare.txt` | ✅ |
| 探针脚本（只读） | `.agent-team/tmp-r21-d1-probe.py`、`tmp-r21-d1-extract.py`、`tmp-r21-f02-d2-probe.py` | ✅ |

- 解释器：`D:\Python\Python312`；`import pixo` 的 `src` 入 `sys.path` 由 `tests/conftest.py:18-22` 保证 ⇒ **全部经 `python -m pytest` 运行**。
- 本机陷阱规避：所有 pytest/探针输出经 `cmd /c "set PYTHONIOENCODING=utf-8&& python … > .agent-team\tmp-*.txt 2>&1"` 落 **UTF-8**
  文件再读（PS 5.1 的 `*>` 写 UTF-16 ⇒ 读取工具判为二进制）。
- 离线纪律：`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`（门禁内 `monkeypatch.setenv`）；**未设** `PIXO_ALLOW_RESTRICTED`；
  `segmenter_last_degraded=[]`（真路由 `rfdetr`+`segformer` 离线可用，P6 复核成立）。

## 2. F01~F05 验收矩阵

### F01 — 闭环生产入口（`run_auto_loop` + `POST /api/photos/{id}/auto-loop` + `GET /api/auto-loop/{task_id}`）

| 项 | 内容 |
|---|---|
| 命令 | ① `python -m pytest tests/integration/test_auto_loop_api.py -q` ② `python -m pytest tests/integration/test_auto_loop_api.py tests/unit/test_scorer_adapter_callable.py tests/unit/test_metrics_for_decide_public.py tests/integration/test_service_api.py tests/unit/test_service_runtime_fixes.py -q` |
| 输出关键行 | ① `20 passed, 1 warning in 35.53s` ② `61 passed, 1 warning in 46.20s`（`test_auto_loop_api.py` 20 = dev-1 首版 18 + R1 新增 2；`test_service_api.py`+`test_service_runtime_fixes.py` 合 21） |
| 结论 | ✅ 通过。HTTP 真实往返（POST→202→GET→done）、`sync=true` → 200 同构、404/400 语义、内部异常不穿 500（`status=failed`+`error`）、同 photo 单飞幂等、`rule_ids` 并集口径与 `rule_ids_by_iteration` 自洽 —— 均有用例覆盖。**真 RAW 形态由 F05 门禁兜底**（见 §3）。 |

### F02 — 装配层默认规则注入（`PIXO_RULES=off` 可关）

| 项 | 内容 |
|---|---|
| 命令 | `python .agent-team/tmp-r21-f02-d2-probe.py`；`python -m pytest tests/integration/test_auto_loop_api.py -q -k "rules"`（含于 F01 的 61 passed） |
| 输出关键行 | `{"rules_count": 11, "rules_ids": ["exposure_rule_001","highlight_protect_rule_002","crop_suggest_rule_003","dehaze_rule_030","clarity_flat_rule_031","shadow_open_rule_032","highlight_recover_rule_033","vibrance_low_rule","saturation_high_rule","region_sky_exposure_001","region_plant_exposure_002"]}`<br>`{"rules_off_matrix": {"0":0,"false":0,"off":0,"no":0,"OFF":0,"False":0," off ":0}, "rules_on_again": 11}`<br>`{"lib_default_rules": []}` |
| 结论 | ✅ 通过。6 个规则文件共 **11 条**全加载（显式 `metric_keys=metric_universe(("face","sky","plant"))`，无 `DecideError`）；`PIXO_RULES` ∈ {0,false,off,no}（任意大小写/空白）→ `[]`；**库层 `SinglePhotoLoop()` 缺省仍 `rules == []`**（纯库语义未被污染）。 |

### F03 — 指标口径单一来源（`pipeline/metrics.py` 公共 API + service 侧接线）

| 项 | 内容 |
|---|---|
| 命令 | ① `python -m pytest tests/unit/test_metrics_for_decide_public.py -q` ② 含于 F01 的 61 passed（`-k "decide_photo or proxy"` 子集在 `test_auto_loop_api.py` 内） |
| 输出关键行 | ① `14 passed in 0.77s` ② 探针：`{"METRIC_KEYS_count": 10, "METRIC_KEYS": [colorfulness_proxy, contrast, crop_suggestion_applicable, haze_proxy, highlight_clip_ratio, mean_luminance, preview_highlight_clip_estimate, preview_overflow_ratio, shadow_clip_ratio, tonal_range], "universe_count": 22}` |
| 结论 | ✅ 通过。① 显式键宇宙下 6 文件全加载、`metric_universe` 覆盖 `region_rules.yaml` 全部引用键（含负控：只传 `METRIC_KEYS` 必抛 `DecideError`）；② `decide_photo` 展平 + 传 rules 后 `decision.params` 非空、`measurement` 顶层追加 `haze_proxy/colorfulness_proxy/tonal_range`、既有字段集合不变；③ `pipeline/` 不反向 import `service`（架构红线用例在 14 passed 内）。 |

### F04 — 评分器适配器可调用契约（`_PixoScorerAdapter.__call__` → dict）

| 项 | 内容 |
|---|---|
| 命令 | `python -m pytest tests/unit/test_scorer_adapter_callable.py -q`（含于 F01 的 61 passed） |
| 输出关键行 | 6 用例全绿（含 `test_call_returns_dict_not_dataclass_and_floats_cleanly` 反面对照：返回 `AestheticScore` 本体时 `float()` 抛 `TypeError`）；D2 非门禁观测：`{"default_scorer_type": "_PixoScorerAdapter", "default_scorer_callable": true, "default_scorer_has_call_attr": true}` |
| 结论 | ✅ 通过。`__call__(image_rgb, masks=None)` 返回 **dict**（`overall` + dimensions + `source/raw_overall/domain_hint`）；跨层注入真 adapter 后 `measurement["aesthetic"]` 非空、`suggest_crop` 的 `parts.scorer is not None`；`.score(image_rgb, meta)` 签名不变。**D2**：本机 `make_default_scorer()` 实际返回 `_PixoScorerAdapter` 且 `callable(...) is True`（记录，不作验收依据）。 |

### F05 — 真 RAW 端到端门禁

| 项 | 内容 |
|---|---|
| 命令 | `$env:PIXO_GATE_AUTOLOOP_RAW='K:\data\photo\0711\raw\DSC_5236.NEF'; python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate -s -rA --durations=5` |
| 输出关键行 | `PASSED tests/regression/test_gate_auto_loop_e2e.py::test_real_raw_auto_loop_end_to_end` / `PASSED …::test_rule_ids_aggregation_negative_and_positive_control` / **`2 passed in 122.12s (0:02:02)`**（交付版最终复跑；此前 run3 同结果 `2 passed in 119.72s`） |
| 结论 | ✅ 通过（断言 1~7 全绿，详见 §3）。 |

## 3. F05 门禁运行证据

### 3.1 marker / skip 语义自检

| 命令 | 输出关键行 | 结论 |
|---|---|---|
| `python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate --collect-only` | `1 test collected in 0.05s`（`-m gate` 能选中 ⇒ 文件级 `pytestmark` 生效） | ✅ |
| 同文件无 env 复跑 | `1 skipped in 0.05s`（e2e 用例；**未**被 conftest 转 fail ⇒ `gate_e2e` marker 生效） | ✅ |
| 无 env 复跑（R1 后，含负控镜像） | `1 passed, 1 skipped in 0.90s`；`SKIPPED … : PIXO_GATE_AUTOLOOP_RAW not set` | ✅ |
| env 名 | `PIXO_GATE_AUTOLOOP_RAW`（**未复用 `RAW_PATH`** ⇒ 未激活 `test_gate_e2e_perf.py` 的 30s 性能门禁） | ✅ |

### 3.2 最终复跑（PASS，全场证据）

命令：
```powershell
$env:PIXO_GATE_AUTOLOOP_RAW='K:\data\photo\0711\raw\DSC_5236.NEF'
python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate -s -rA --durations=5
```
原始输出（**交付版最终复跑**，`.agent-team/tmp-r21-gate-final.txt`，逐字；run3 `tmp-r21-gate-run3.txt` 同结果）：
```
[R21-F05] rules_count=11
[R21-F05] {"state": "ACCEPTED", "reason": "FINAL_QC 达标；preview 终止: 达到最大迭代轮数 (2)", "iteration": 2,
 "rules_count": 11, "params": {"colorcal": {"saturation": -0.15}},
 "rule_ids": ["saturation_high_rule"], "rule_ids_last_nonempty": ["saturation_high_rule"],
 "trace_event_count": 12, "measurements": 2, "has_param_update": true,
 "highlight_clip_ratio": 0.025923, "colorfulness_proxy": 9.2987, "segmenter_last_degraded": []}
[R21-F05-decide-events] [{"iteration": 1, "decision": "adjust_and_continue",
 "rule_ids": ["saturation_high_rule"], "last_iteration": false, "colorfulness_proxy": 6.1888},
 {"iteration": 2, "decision": "adjust_and_continue", "rule_ids": [], "last_iteration": true,
 "colorfulness_proxy": 5.8936}]
[R21-F05] baseline_pixel_diff=56293263
[R21-F05-rule-ids-by-iteration] [{"iteration": 1, "rule_ids": ["saturation_high_rule"]}, {"iteration": 2, "rule_ids": []}]
PASSED tests/regression/test_gate_auto_loop_e2e.py::test_real_raw_auto_loop_end_to_end
PASSED tests/regression/test_gate_auto_loop_e2e.py::test_rule_ids_aggregation_negative_and_positive_control
2 passed in 122.12s (0:02:02)
```
（`segmenter` 唯一告警：`sapiens` / `uniface` 因 `internal_development_only` 未注册 + `prompt 'face' 无后端返回，零掩码降级` —— 与 design §4「不设 `PIXO_ALLOW_RESTRICTED`」一致，非失败。）

### 3.3 断言 1~7 逐条落点

| # | 断言 | 实测 | 结论 |
|---|---|---|---|
| ① | `state == "ACCEPTED"` | `"ACCEPTED"`（reason：`FINAL_QC 达标；preview 终止: 达到最大迭代轮数 (2)`） | ✅ |
| ② | `params` 非空 + `rule_ids` 非空（**并集口径**） | `params={"colorcal":{"saturation":-0.15}}`；`rule_ids=["saturation_high_rule"]` | ✅ |
| ③ | 与「仅渲染基线」存在像素差（同 shape/dtype） | `baseline_pixel_diff=56,293,263` | ✅ |
| ④ | `final_measurement["global"]["highlight_clip_ratio"] <= 0.03` | `0.025923` | ✅ |
| ⑤ | trace 含 `param_update` 且 `len(measurements) >= 2` | `has_param_update=true`、`measurements=2`、`trace_event_count=12` | ✅ |
| ⑥ | 聚合自洽（正控）：服务口径 `rule_ids` == `rule_ids_by_iteration` 逐轮并集 == 门禁并集口径；逐轮条目与 trace decide 一一对应 | `[{"iteration":1,"rule_ids":["saturation_high_rule"]},{"iteration":2,"rule_ids":[]}]`，三者逐项相等 | ✅ |
| ⑦ | 末轮机制形态 + 负控镜像 | 末轮 `last_iteration=true` 且 `decision="adjust_and_continue"`（**未走** `engine.py:1147-1163` 短路）；DSC_5236 末轮 `rule_ids=[]` 而并集非空；镜像用例（无 RAW）：空 trace → `[]`、全 decide 空 → `[]`、首轮命中 + 末轮空 → 返回首轮命中（含去重/首现序） | ✅ |

耗时 **122.12s**（交付版最终复跑；run3 119.72s。均 <600s 软上限）。
> 断言⑦主责用例在 `tests/integration/test_auto_loop_api.py`（design §4-7，承接方 dev-1，已 20 passed）；
> 本门禁文件内的 `test_rule_ids_aggregation_negative_and_positive_control` 是其**镜像**（保证单独跑 `-m gate` 门禁文件时该口径也被钉住）。
> **未**把「终止轮必空」写成不变量：末轮走 `last_iteration` 分支照常评估规则（`engine.py:977-989`），空与不空都合法 —— 反例见 §5 的 DSC_5237（**末轮命中**）。

## 4. 缺陷 / 裁决记录

### 4.1 【已裁决·已修复·已回归】`rule_ids`「最后一条 decide」提取口径会漏掉早期命中（契约修订 R1）

- **发现时点**：F05 门禁首跑 —— `1 failed in 102.90s`（证据 `.agent-team/tmp-r21-gate-run.txt`）。
- **现象**：`state=ACCEPTED`、`params={"colorcal":{"saturation":-0.15}}` 非空，其余四条断言全绿；
  仅断言②失败 —— 最后一条 decide 事件 `{"iteration":2, "decision":"adjust_and_continue", "rule_ids":[],
  "last_iteration":true, "metrics.colorfulness_proxy":5.8936}`。
- **根因（以实跑证据定稿；QA 增量复核纠正了 tester 首版归因）**：末轮 `rule_ids=[]` 有**两条都合法**的空路径：
  1. **本次实测触发的路径 = 末轮规则自然不命中（不是短路）**：`iteration >= max_iterations` 走
     `check_termination` 的 `last_iteration` 分支，该分支返回 **`should_stop=False`**（`engine.py:977-989`，
     t107 off-by-one 注释明写「末轮规则**必须**触发一次」）⇒ `decide()` 不短路、照常评估规则（`engine.py:1165-1173`）。
     真 RAW 实况：首轮 `saturation_high_rule` 命中（`colorfulness_proxy` **6.1888** ≥ 阈值 **6.13**）并写入
     `saturation=-0.15`；末轮该指标降到 **5.8936** < 6.13 ⇒ **该轮确实无规则命中**，`rule_ids=[]` 语义正确。
  2. 另一条合法空路径：`check_termination` 返回 `should_stop=True`（如 `low_improvement`/`targets_met`）时，
     `decide()` 在 `engine.py:1147-1163` 短路返回 `rule_ids=[]` + 原样透传 params（**本次未触发**）。
- **缺陷定位**：不在 engine/loop，而在 **`rule_ids = 最后一条 decide 事件` 这个提取口径**：它**不是**必然为空
  （D1 实测 DSC_5237 末轮**命中**、末条非空），而是**会静默丢掉早期的真实命中** —— 服务层
  `runtime._auto_loop_rule_ids()` 用同一口径 ⇒ design §1 F01 的「真 RAW `rule_ids` 非空」在 DSC_5236 这类
  形态上同样返回空（dev-1 的 18 passed 走注入假 backend 的合成路径，未覆盖该形态）。
- **⚠ 措辞提示（给 QA/队长，避免错误不变量回流）**：design §4:147 括注「取"最后一条"会让本断言在真 RAW
  常规路径上**必挂**」在 D1 三样本实测下**偏强**：DSC_5237 末轮命中 ⇒ 旧口径在该样本上会**通过**。
  准确表述应是「会**漏掉早期命中**（末轮是否命中取决于该轮指标是否跨过阈值）」——不得写成「末轮必空」。
  tester 门禁文件已按此措辞落地，且**未**把「末轮必空」写成断言。
- **处置（tester）**：按纪律**未放宽断言 / 未改语料 / 未开 `PIXO_ALLOW_RESTRICTED` / 未改 `src/**`**，即时上报队长（含源码定位）。
- **队长裁决（2026-09-10）**：**选 A —— 修订提取口径，不改 engine**（终止轮未应用规则是引擎语义，不该让 trace 说谎）。
  新口径 = 全 trace `event_type=="decide"` 事件 `value["rule_ids"]` 的**并集**（首次出现顺序、去重）；
  任务结果追加 `rule_ids_by_iteration`；design §1 F01 / §2.2 / §4 断言② 就地修订，新增断言⑥（正控）/⑦（负控）。
- **落地与回归**：dev-1 修订 `runtime.py`（`_auto_loop_decide_events` / `_auto_loop_rule_ids` 并集 /
  `_auto_loop_rule_ids_by_iteration`，`runtime.py:993-1054`）+ `tests/integration/test_auto_loop_api.py` 20 passed
  （含正面机制用例 `test_last_round_evaluates_rules_before_natural_miss`）；tester 依新口径改门禁 + 补断言⑥与负控镜像
  → **复跑 `2 passed in 119.72s`**。

### 4.2 【工具/流程·非产品缺陷】并发跑全分辨率渲染触发内存不足（tester 操作失误）

- D1 探针首跑**与定向 pytest 并发**，在 `render/core/skin.py:245 → oklab.py:118` 抛
  `numpy._core._exceptions._ArrayMemoryError: Unable to allocate 187. MiB for an array with shape (4040, 6064) and data type float64`。
- 定性：**内存竞争**，非产品缺陷（门禁单独复跑 119.72s 全绿；探针单独复跑三样本全绿，见 §5）。
- 教训（已沉淀）：真 RAW 全分辨率渲染（约 45MP、`float64` 中间量）**必须串行**，不得与其它 pytest/探针并发。

### 4.3 未发现其它产品缺陷

`src/**` 本会话零改动（`git diff --stat src/` 仅 dev-1/dev-2 的本轮改动）。F01~F04 的 61 定向用例、
F05 门禁 2 用例、全量回归 1574 用例 **0 failed**。

## 5. D1 三样本证据（队长追证：`saturation_high_rule` 1% 余量真实性）

命令：`python .agent-team/tmp-r21-d1-probe.py`（与门禁**同装配**：真路由 `MultiModelSegmenter`、装配层 11 条规则、
`manual_on_unreliable=False`、`preview_long_edge=1024`、`max_iterations=2`、**不设** `PIXO_ALLOW_RESTRICTED`）；
固定 3 样本 = `K:\data\photo\0711\raw\` 下字典序前 3：`DSC_5236/5237/5238.NEF`。
原始输出：`.agent-team/tmp-r21-d1-probe.txt`；紧凑表：`.agent-team/tmp-r21-d1-table.txt`。

阈值：`saturation_high_rule` = `colorfulness_proxy >= 6.13`（`src/pixo/decide/rules/color_rules.yaml:22-31`，
`# = 分布表 p75(6.1292)；触发样本 5238/0353/0355`）。

| 样本 | preview `colorfulness_proxy`（顶层，逐轮） | 逐轮 `rule_ids` | 并集 `rule_ids`（新口径） | 末轮 `rule_ids`（旧口径） | `result.params` | `state` / 耗时 | `final` 顶层 `colorfulness_proxy` | `highlight_clip_ratio` | `saturation` 余量 |
|---|---|---|---|---|---|---|---|---|---|
| **DSC_5236** | **6.1888** → 5.8936 | ①`[saturation_high_rule]` ②`[]` | `[saturation_high_rule]` | `[]`（**旧口径落空**） | `{colorcal:{saturation:-0.15}}` | ACCEPTED / 108.89s | 9.2987 | 0.025923 | **+0.96%**（6.1888 vs 6.13） |
| **DSC_5237** | 5.8847 → **6.1472** | ①`[dehaze_rule_030]` ②`[dehaze_rule_030, saturation_high_rule]` | `[dehaze_rule_030, saturation_high_rule]` | `[dehaze_rule_030, saturation_high_rule]` | `{dehaze:{strength:0.15,enabled:true}, colorcal:{saturation:-0.15}}` | ACCEPTED / 72.33s | 9.6312 | 0.007422 | **+0.28%**（6.1472 vs 6.13，**末轮命中**） |
| **DSC_5238** | **6.5627** → 6.562 | ①`[dehaze_rule_030, saturation_high_rule]` ②`[clarity_flat_rule_031, saturation_high_rule]` | `[clarity_flat_rule_031, saturation_high_rule]` | `[clarity_flat_rule_031, saturation_high_rule]` | `{dehaze:{strength:0.15,enabled:true}, colorcal:{saturation:-0.15}, clarity:{strength:0.1}}` | ACCEPTED / 73.61s | 10.0481 | 0.013096 | **+7.06%**（6.5627 vs 6.13） |

**供队长判断的要点**：

1. **3/3 样本并集非空**，且 `saturation_high_rule` 在 3 张上全部命中 ⇒ D1 的 1% 余量论断**在本语料上成立但不宽裕**：
   DSC_5236 余量 **+0.96%**、DSC_5237 **+0.28%**（更窄）、DSC_5238 **+7.06%**。
2. **DSC_5236 未落空**（首轮命中并落地 `saturation=-0.15`）⇒ 无需触发「报队长、不得放宽」的处置分支；
   但落空的不是「命中」而是「**旧口径的末条**」（末轮自然不命中）——契约修订 R1 的直接实证。
3. **DSC_5237 是「末轮命中」的反例**（首轮 `colorfulness_proxy` 5.8847 < 6.13 未命中，末轮 6.1472 才命中）
   ⇒ 证明「终止轮必空」**不是不变量**，也证明并集口径对两个方向都必要（既不丢早期命中、也不丢末轮命中）。
4. 区域规则在本语料全部不可达：`mask_nonzero_px = {sky:0, plant:0, face:0}`（默认路由下 `face` 无后端零掩码降级，
   `sky/plant` 走 `segformer` 亦全零）⇒ 11 条规则里能被触发的就是 proxy 驱动的少数几条（dehaze / clarity_flat /
   saturation_high）；`segmenter_last_degraded=[]`（后端本身健康，只是没检出该区域）。

## 6. 全量回归 + 金样本零漂移

### 6.1 全量回归

命令（R20 口径，`.r20_ok:73`）：
```powershell
python -m pytest tests -q -m "not e2e"
```
输出关键行（`.agent-team/tmp-r21-fulltest.txt`）：
```
1574 passed, 6 skipped, 1 xfailed, 13 warnings in 277.51s (0:04:37)
```
| 指标 | R20 终态（`.r20_ok:7`） | R21 实测 | 判定 |
|---|---|---|---|
| passed | 1533 | **1574** | ✅ ≥1533（+41） |
| failed | 0 | **0** | ✅ |
| skipped | 5 | **6** | ✅（+1 = 新增 F05 e2e 门禁未设 `PIXO_GATE_AUTOLOOP_RAW` 时 skip，`gate_e2e` 豁免） |
| xfailed | 1 | **1** | ✅ 不变 |

**+41 passed 的构成（自洽核对）**：dev-1 `tests/integration/test_auto_loop_api.py` 20（首版 18 + R1 新增 2）
+ dev-2 `tests/unit/test_metrics_for_decide_public.py` 14 + dev-2 `tests/unit/test_scorer_adapter_callable.py` 6
+ tester 门禁新增 `test_rule_ids_aggregation_negative_and_positive_control` 1 = **41** ✅

### 6.2 金样本门禁（零漂移）

命令（`.r20_ok:17-19,72` 记录的 gate 口径）：
```powershell
python -m pytest tests/regression/test_gate_golden.py -q
python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json `
  --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512
```

**(a) 合成 gate 金样本（21 features）** —— `.agent-team/tmp-r21-golden-pytest.txt`：
```
7 passed in 37.50s
```
覆盖：`test_manifest_schema_and_files`（`schema=render-gate-...`/21 features/reviewer 非空/文件存在）、
`test_baseline_files_match_manifest_sha256`（sha256 逐文件一致 = 基线未被误替换/损坏）、
`test_generator_check_mode_reports_no_drift`（`generate_gate_goldens.run_check` 退出码 0 = **当前实现与 manifest 零漂移**）、
`test_current_output_matches_goldens`（21 features 逐像素 `max|Δ| <= 1e-6`）、skin_oklch 软边带 3 条探针。

**(b) 真 RAW 金样本（4 features × 6 样本 = 24 case）** —— `.agent-team/tmp-r21-golden-compare.txt`：
```
feature/sample                           u8_max  u16_max verdict
wb_as_shot_default/night_lowlight             0        0 PASS
wb_as_shot_default/day_normal                 0        0 PASS
...（24 行全部 u8_max=0 / u16_max=0）...
clarity_default/high_contrast                 0        0 PASS
RESULT: PASS
```

| 项 | 实测 | 判定 |
|---|---|---|
| 合成 gate 21 features | 7 passed（含 `--check` 退出码 0 + sha 一致 + 逐像素 1e-6） | ✅ 零漂移 |
| 真 RAW 24 case | 24/24 PASS，`u8_max=0`、`u16_max=0`（**逐位一致**） | ✅ 零漂移 |
| 与 design §4 预期一致性 | 本轮不碰渲染像素路径（`git diff --stat -- src` 仅 `batch.py`/`loop.py`/`app.py`/`runtime.py` 4 个非渲染像素文件） | ✅ 预期一致 |

> 说明：`gate_golden.py compare` 的运行告警（`[skin] 未分类图掩码占比 6x% 超上限 50%, 磨皮 no-op`、
> `wb_B=1.090 超出暖度标定适用域 [1.100, 2.398]`）是**既有的域外垫片/场景误判降级路径**，与 R21 改动无关，
> 且结果仍逐位一致（`u8_max=0`）—— 属基线口径内行为，非漂移。
> 另一路「单 RAW gate manifest」（`data/golden/reference/render_bench/goldens/gate/manifest.json`，8 features）的 `raw`
> 指向**已消失**的 `K:\data\photo\corpus_a\raw\DSC_5236.NEF` ⇒ 无法在本机复跑 compare（登记为遗留 §7.6）。
> 本轮零漂移结论由 (a) 合成 gate 21 features（含 `--check` 与 sha256 校验）与 (b) 真 RAW `gate_defaults` 24 case 双路支撑。

## 7. 遗留问题（范围外，登记不处理）

1. **tech_debt #21**（design D3 裁决）：auto-loop 不回写 `runtime.state_machines` / `photo.last_decision` ⇒
   跑完 `ACCEPTED` 后 `GET /api/photos/{id}/timeline` 仍 `RAW_PENDING`、`GET /decide` 缓存不联动。本轮设计固化为「不回写」。
2. **tech_debt #22**（design D4 裁决）：长耗时端点无任务级超时/取消；可控手段 = `max_iterations ≤ 5` + `preview_long_edge`，
   结果落 `duration`（门禁实测 119.72s、单样本探针 72–109s）。交付时写入 `docs/tech_debt.md`。
3. **任务表无淘汰**（dev-1 遗留 3）：`_auto_loop_tasks` 与 `ExportManager._tasks` 同现状，长跑服务下无界增长。
4. **不同 photo 共用 `max_workers=1` 队列且无 `queued` 态**（dev-1 遗留 4）：单飞只保证「同 photo 不重跑」。
5. **`build/lib/pixo/**` 旧副本漂移**（exploration §7.4）：`build/lib/pixo/pipeline/metrics.py` 不存在，
   `loop.py` 仍是旧实体；若打包/导入误取 `build/lib` 会 `ImportError`。本轮未动 build 产物。
6. **`src/pixo/render/bench/preview_cold_baseline.json` 是坏 JSON**（exploration §7.1，全仓无消费者）+
   `preview_v16_nef_baseline_{cold,hot}.json` 的 `raw` 指向已消失的 `corpus_a` 路径（§7.2）+
   **单 RAW 金样本 manifest `data/.../goldens/gate/manifest.json` 的 `raw` 同样指向不存在的
   `K:\data\photo\corpus_a\raw\DSC_5236.NEF`** ⇒ 该 manifest 的 compare 无法在本机复跑（其基线 sha 仍可校验）。
7. **`task-brief.md:35` 语料计数口径**：写「3428 个 NEF」，实测 `0711\raw` 下 765 个（exploration §5.1）。
8. **`crop_suggestion_applicable` vs `crop_suggestion_available` 命名并存**（dev-2 遗留 3）：本轮只注册前者，未动后者。
9. **`pixo.pipeline.metrics` 未 re-export 到 `pipeline/__init__.py`**（dev-2 D-3）：调用方须显式 `from pixo.pipeline.metrics import …`。
10. **`src/pixo` 下 131 处 `except Exception` 静默降级**（exploration §7.5，属 CR-08 范围，本轮不动）。
