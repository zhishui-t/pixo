# R22 / Wave1 / stream-1（dev-1）交付报告 —— F01 噪声/细节指标入决策键宇宙 + F06 多轴 QC 软告警

- 角色：`dev-1`；范围：**仅 F01 + F06**（design-r22 §1 / §3 / §4）
- 工作目录：`K:\work\project\pixo`（Windows / PowerShell **5.1**）
- 上游依据：`.agent-team/design-r22.md`（唯一实现依据）、`.agent-team/exploration-r22.md`
- 未提交 git；未跑全量回归（按 brief）

---

## 0. 一句话结论

两项交付均已落地并有定向测试证据（**F01 13 passed / F06 15 passed / 合计 28 passed**，定向回归面 130 passed / 2 failed）；**遗留 R1 = 2 处既有冻结断言必红**（域外未改，等队长裁决）+ R2~R8 共 8 项遗留（见 §4）。

---

## 1. 改动清单（文件 → 关键 diff 摘要 → 对应验收）

### 1.1 F01 —— 噪声/细节指标入决策键宇宙

| # | 文件 | 关键改动 | 对应验收 |
|---|------|----------|----------|
| 1 | `src/pixo/pipeline/metrics.py` | 新常量 `SHARPNESS_METRIC_KEYS = ("noise_ratio","detail_score")`；`METRIC_KEYS` 10→12 键（新增两键）；`metrics_for_decide` 增加 **4 层**读取 `global["detail"]["sharpness"]`，**仅当该层存在且含对应键时**写入（缺省不写空键，与代理键同款语义）；模块 docstring 补 R22/F01 段；`__all__` +`SHARPNESS_METRIC_KEYS`。`metric_universe()` 由 `METRIC_KEYS` 派生 → **自动同步**（实测 n=24：12 + 3 prompts×4） | design §4「`metric_universe()` 含 `noise_ratio`/`detail_score`」；§1 F01 改动点 1/2 |
| 2 | `src/pixo/pipeline/loop.py` | `register_metric_keys({...})` 增 `"noise_ratio"`/`"detail_score"`（附 4 层来源与 lint 白名单注释） | §1 F01 改动点 3 |
| 3 | `src/pixo/decide/rules/noise_rules.yaml`（**新增**） | 规则 `noise_luminance_rule_040`：`enabled: false`、`priority: 40`、`condition {metric: noise_ratio, op: gte, value: 0.62}`、`action {param: denoise.luminance_strength, mode: set, formula: "0.5 * (noise_ratio / 0.62 - 1.0)", clamp: [0.0, 0.60]}`。头注**逐条留证**：口径=导出全幅；512 tier 排序非单调（0.2837 < 0.6680）；闭环只吃 preview（缺省 **1024**）⇒ 本规则闭环内不生效；26 张全幅实测分位与阈值推导；执行位待 F02 接线 | §1 F01 改动点 4 + §2.1 + §4 门禁 3 项 |
| 4 | `src/pixo/decide/rules/__init__.py` | `DEFAULT_RULES` 登记 `noise_rules.yaml`（第 7 个文件，附默认关/口径注释） | §1 F01 改动点 4 |
| 5 | `tests/unit/test_noise_metric_keys.py`（**新增**） | 13 用例：层级正确（4 层 vs 3 层/顶层干扰键）、缺省不写空键、畸形层容错、键宇宙同步、**显式 `metric_keys=` lint 放行 + 缺键必 DecideError（保存/恢复全局注册表）**、默认关零影响（±规则求值逐条相同，且反向护栏证明非「双空」）、显式开启可命中、口径留证断言（头注含 `enabled: false`/全幅/preview/1024/0.2837/0.6680） | §1 F01 单测 ①②③ + §4 |

### 1.2 F06 —— 多轴 QC 软告警

| # | 文件 | 关键改动 | 对应验收 |
|---|------|----------|----------|
| 6 | `src/pixo/decide/engine.py` | `qc_rollback()` **仅在** design 指定的两个返回（达标分支 `:1038`、回退分支 `:1071`）**追加** `"soft_warnings": list(context.get("soft_warnings") or [])`。既有键/判定逻辑一行未动 | §1 F06 落点 1；§4「不改变既有 ACCEPT/REJECT」 |
| 7 | `src/pixo/pipeline/loop.py` | 新增模块常量 `_QC_SOFT_NOISE_RATIO=0.62` / `_QC_SOFT_DETAIL_SCORE=1.2` / `_QC_SOFT_COLORFULNESS_LOW=4.78` / `_QC_SOFT_COLORFULNESS_HIGH=6.13`（带标定证据注释）；新增 `_soft_float()` + `_qc_soft_warnings(full_measurement)`（清晰度/运动模糊/噪声/色彩 4 轴产 JSON 友好 dict：`axis/metric/op/value/threshold/tier="full_export"/gate="soft"/message`）；`_qc_outcome` 组装并喂进 `qc_context`，用 `qc.setdefault` 补齐 manual_review 分支（**同一份清单，不重算**）；`run()` 在两次 QC 处把清单写进 `metadata["soft_warnings"]`。**判定分支零改动**（硬门禁仍只有 `highlight_clip_ratio ≤ 0.03`） | §1 F06 落点 2；§4 硬门禁唯一 |
| 8 | `src/pixo/service/runtime.py` | auto-loop **纯追加**：任务槽 `"soft_warnings": []`（`:858`）、payload `"soft_warnings"`（`:975`，读 `LoopResult.metadata`）、轮询/同步视图 `"soft_warnings"`（`:915`，视图是白名单构建）。既有键一个不少、不改名 | §1 F06 落点 3 |
| 9 | `tests/unit/test_qc_soft_warnings.py`（**新增**） | 15 用例：轴集合与 schema（JSON 可序列化/tier/gate）、色彩高分支、运动模糊轴、缺失/畸形输入静默、**引擎两分支回抄 + 缺席默认空表**、`qc_rollback` 4 类 context 参数化「±软告警逐字段相同」、loop metadata 与独立组装同源、**把组装强关为 `[]` 后判定/参数/原因逐字段一致**、硬门禁常量=0.03 并抓 `qc_context` 输入面、**service payload 透出软告警且既有键齐全** | §1 F06 单测 ①② + §4 QC 判据 |

**文件域核对**（`git status --porcelain`）：本流改动 = 上述 5 个 `src` 文件 + 1 个新 YAML + 2 个新测试文件，**全部在白名单内**；未触碰 `tests/regression/**`、`frontend/**`、`configs/**`、`src/pixo/render/**`。（工作树另有 dev-2 的 `src/pixo/render/**`、`src/pixo/vision/health.py` 等改动，非本流所为。）

**diff 规模**（`git diff --stat`）：5 个 `src` 文件共 **+232 / −5**；`git diff -U0` 逐行核对，**5 处删除全部是被替换的注释/docstring 行**（`loop._qc_outcome` 旧 docstring 与 `return qc_rollback(...)`、`metrics` 模块头一行、`METRIC_KEYS` 两行注释）——**无任何功能行被删除**。新增文件：`src/pixo/decide/rules/noise_rules.yaml`（含逐条留证头注）、`tests/unit/test_noise_metric_keys.py`（13 用例）、`tests/unit/test_qc_soft_warnings.py`（15 用例）。

---

## 2. 自测证据（命令 → 输出关键行 → 结论）

> 本机 PowerShell 5.1：`>` 重定向默认 **UTF-16LE**（`read` 工具会判为 binary，`Get-Content` 正常）。故一律「重定向到文件 → `Get-Content` 读」。

### E1 F01 单测
```
python -m pytest tests/unit/test_noise_metric_keys.py -q --color=no > .agent-team\tmp-r22-pytest-f01.txt 2>&1
→ 13 passed in 1.07s
```
**结论**：4 层展平/键宇宙/lint 放行+缺键拦下/默认关零影响/口径留证 全绿。

### E2 F06 单测
```
python -m pytest tests/unit/test_qc_soft_warnings.py -q --color=no > .agent-team\tmp-r22-pytest-f06.txt 2>&1
→ 15 passed in 1.77s
```
**结论**：软告警出现在（引擎返回 / loop metadata / **service payload**）；既有判定逐字段不变；硬门禁仍只 0.03。

### E3 两文件合跑（一次提交证据）
```
python -m pytest tests/unit/test_noise_metric_keys.py tests/unit/test_qc_soft_warnings.py -q --color=no
→ 28 passed in 4.96s        （输出存档 .agent-team\tmp-r22-pytest-1.txt）
# 全部改动落定后复跑（终态）
→ 28 passed in 2.46s        （输出存档 .agent-team\tmp-r22-pytest-final.txt）
```

### E4 定向回归面（触碰面覆盖，非全量）
```
python -m pytest tests/unit/test_metrics_for_decide_public.py tests/unit/test_decide.py \
  tests/integration/test_loop_e2e.py tests/integration/test_auto_loop_api.py \
  tests/unit/test_formula_guard_sunset.py tests/unit/test_phase_e.py tests/unit/test_color_rules.py \
  tests/unit/test_crop_wiring.py tests/unit/test_decide_region_wiring.py tests/unit/test_tone_clarity_rules.py \
  -q --color=no > .agent-team\tmp-r22-pytest-2.txt 2>&1
→ 2 failed, 130 passed, 1 warning in 45.11s
```
失败=**仅**两处既有冻结断言（见 §4-R1，域外未改）：
```
FAILED tests/unit/test_metrics_for_decide_public.py::test_metric_keys_is_flatten_fixed_set_without_region_keys
  E  Extra items in the left set: 'noise_ratio' 'detail_score'
FAILED tests/unit/test_metrics_for_decide_public.py::test_default_rules_load_with_explicit_metric_universe
  E  assert 7 == 6
```
**关键正向证据**：同文件第三条冻结断言
`test_public_flatten_matches_frozen_legacy_expectation`（`flat == _EXPECTED_FLAT`）**通过** —— 因为新键取「缺省不写空键」语义（该 fixture 无 `detail` 层），既有 21 项展平口径逐键未变。
`tests/integration/test_loop_e2e.py`（闭环 ACCEPTED/回退/二次超标）、`tests/integration/test_auto_loop_api.py`（auto-loop 任务视图全字段）**全绿** ⇒ F06 追加键未扰动既有 QC 判定与 payload 契约。

### E5 端到端探针（真实 `VisionMeasure.measure` 报告）
```
python .agent-team\tmp-r22-probe.py > .agent-team\tmp-r22-probe-out.txt 2>&1
→ [module]  K:\work\project\pixo\src\pixo\pipeline\metrics.py      ← 吃 src，非 build/lib 旧副本
→ [① 4-layer flatten] sharpness = {'laplacian_raw': 49682.55, 'laplacian_denoised': 773.72,
                                   'noise_ratio': 0.9844, 'fft_high_ratio': 0.5772, 'detail_score': 773.72}
→ [① flat keys] {'noise_ratio': 0.9844, 'detail_score': 773.72}
→ [① negative] fft_high_ratio leaked: False
→ [② METRIC_KEYS] ['colorfulness_proxy','contrast','crop_suggestion_applicable','detail_score',
                   'haze_proxy','highlight_clip_ratio','mean_luminance','noise_ratio',
                   'preview_highlight_clip_estimate','preview_overflow_ratio','shadow_clip_ratio','tonal_range']
→ [② universe] n = 24 | has noise keys = True
→ [③ soft_warnings] [{'axis':'noise',...,'threshold':0.62,'tier':'full_export','gate':'soft',...},
                      {'axis':'color',...,'threshold':6.13,'tier':'full_export','gate':'soft',...}]
→ [④ auto-loop rules] n = 12 | ids = [... 'region_plant_exposure_002','noise_luminance_rule_040']
→ [④ noise rule] [('noise_luminance_rule_040', False, 'noise_ratio', 'denoise.luminance_strength')]
```
**结论**：①4 层展平可用且不泄漏 `fft_high_ratio`；②键宇宙含两新键；③抽象告警在真实测量报告上可组装；④装配层 12 条规则含新规则且 `enabled=False`（生产零影响）。

### E6 阈值标定证据（全幅口径）
```
python .agent-team\tmp-r22-calib.py            > .agent-team\tmp-r22-calib-out.txt  2>&1   # 26 张，≈2min
python .agent-team\tmp-r22-calib-report.py     > .agent-team\tmp-r22-calib-report.txt 2>&1
→ wrote .agent-team\tmp-r22-calib-rows.tsv (26 rows)
```
口径：rawpy 内嵌相机 JPEG **全幅 6048×4032**（4 层路径同源）；抽样 DSC_5236~5335 中 26 张 = **低 ISO ≤1600 共 14** + **高 ISO ≥3200 共 12**。

| 指标 | 组 | min | p10 | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|---|---|
| `noise_ratio` | ALL(26) | 0.4137 | 0.4791 | 0.4997 | 0.5371 | **0.6240** | 0.6351 | 0.7473 |
| `noise_ratio` | ISO≤1600(14) | 0.4137 | 0.4541 | 0.5186 | 0.5317 | 0.5550 | 0.5968 | **0.6114** |
| `noise_ratio` | ISO≥3200(12) | **0.4724** | 0.4862 | 0.4916 | 0.6281 | 0.6350 | 0.7310 | 0.7473 |
| `detail_score` | ALL(26) | 0.81 | **1.40** | 1.8625 | 2.20 | 3.3475 | 3.69 | 4.13 |
| `detail_score` | ISO≥3200(12) | 1.81 | 1.837 | 2.005 | 2.285 | 3.4775 | 3.659 | 3.71 |
| `colorfulness_proxy` | ALL(26) | 6.8024 | 6.8672 | 7.0656 | 8.0808 | 9.2376 | 10.4277 | 10.4973 |

阈值推导（**全幅口径**，已写入 `noise_rules.yaml` 头注与 `loop.py` 常量注释）：
- 噪声 `0.62` = ALL p75(0.6240) 取整下移，且 **> 低 ISO 组上界 0.6114** ⇒ 该 26 张样本中低 ISO **零误触**，命中高 ISO 中高段（≈6/12）。
- 细节 `1.2` = 全样本 p10(1.40) 取整下移（命中 2/26：DSC_5240=1.20、DSC_5241=0.81）。
- 色彩 `4.78 / 6.13` = **沿用 `color_rules` 既有锚点**（p25/p75，`docs/metrics/proxy_distribution.md`，12 样张 512 tier **生产渲染**）—— 见 §3-D6。

**诚实边界**：本标定语料是**内嵌相机 JPEG 全幅**（与 exploration §1.4/§2.3 同口径），**不是** RAW→全幅渲染链；且高/低 ISO 的 `noise_ratio` 分布**有重叠**（低 ISO max 0.6114 > 高 ISO min 0.4724），0.62 是「低 ISO 零误触」的保守线，不是判别力切分。

### E7 文件域核对
```
git status --porcelain
→ M src/pixo/decide/engine.py, M src/pixo/decide/rules/__init__.py, M src/pixo/pipeline/loop.py,
  M src/pixo/pipeline/metrics.py, M src/pixo/service/runtime.py,
  ?? src/pixo/decide/rules/noise_rules.yaml,
  ?? tests/unit/test_noise_metric_keys.py, ?? tests/unit/test_qc_soft_warnings.py
  （另有 dev-2 的 src/pixo/render/**、src/pixo/vision/health.py 等，非本流）
```

---

## 3. 与 design 的偏差（逐条给理由）

| # | 偏差 | 理由 / 证据 |
|---|------|-------------|
| D1 | `loop._qc_outcome` 里用 `qc.setdefault("soft_warnings", list(soft_warnings))` **补齐** engine 未回抄的 manual_review 分支 | design §1 F06 只列 engine 两处返回；但 `loop.run` 的回退→二次超标路径读的是 `qc2`，若不补齐，**人工复核路径的 payload 会丢多轴信息**（与 CR-11「QC 报告含多轴字段」相悖）。补齐=**只加键不删不改**，判定零影响（E2 参数化用例证明）。engine 侧严格按 design 只改两处。 |
| D2 | `runtime.py` 改了 **3 处**（brief/design 只点名 `:963-972` payload） | `_auto_loop_view` 是**白名单**构建、且任务 dict 有显式初值 ⇒ 只在 payload 加键**不会出现在响应里**。三处均为纯追加（task 初值 `:858`、payload `:975`、view `:915`），既有键一个不少、不改名（E2 `test_service_payload_exposes_soft_warnings` 断言既有 12 键齐全）。 |
| D3 | 新扁平键取「**仅当 `global.detail.sharpness` 存在且含该键时**才写」的缺失语义 | exploration §2.2 #1 明写「恒写 or 仅存在时写——二选一需在 design 明确」，design 未定死。取此支：①与既有代理键「缺省不写空键」一致；②规则侧「键缺席」与「值为 None」都走引擎静默不触发（`engine.py:360`）；③**保住**既有冻结用例 `test_public_flatten_matches_frozen_legacy_expectation`（E4 实测通过）。若取「恒写 None」，第 3 处既有断言也会红。 |
| D4 | 新规则 YAML **只落 `src/pixo/decide/rules/`**，未同步 `configs/rules/` 镜像 | `configs/**` 属 brief 明令**禁改**域。仓内双镜像约定由 `test_formula_guard_sunset.py:81-89` 按 **configs→src** 单方向校验（不反向）⇒ 本改动不改红任何用例（E4 该文件全绿）。待队长授权补镜像。 |
| D5 | `enabled: false` **无 env 开启实现** | design §2.1 括注「（env 开启）」，但全仓**无规则级 env 开关**（唯一消费点是 `engine.evaluate_rules` 的 `rule.get("enabled") is False: continue`；`PIXO_RULES` 是整包开关）。实现需改 `engine.load_rules/evaluate_rules`，**超出**「engine.py 仅 soft_warnings 追加」的域 ⇒ 只做字面 `enabled: false`，env 开启登记遗留（R2；已提前报队长）。 |
| D6 | 色彩轴阈值**不用**我实测的全幅分布（6.80~10.50），而沿用 `color_rules` 的 512 tier 生产渲染 p25/p75（4.78/6.13） | design §2.1 的「全幅口径」**只收窄噪声/细节类**（色彩 ΔE 明确沿用 512）；`colorfulness_proxy` 是归一化比值型色彩代理，而我实测列是**未走渲染链的相机 JPEG** → 对「渲染后全幅」而言是另一个 tier，二者都不是理想锚点。取「与既有色彩规则同源」以避免同一代理出现两套互斥阈值。**需 QA 知晓/后续重标定**（R5）。 |
| D7 | 未加 exploration 建议的 `_add_trace(event_type="qc_soft_warning")` | 落地已满足 design §1/§4（返回 dict + metadata + payload 落库）。加 trace 事件会抬高 `trace_event_count`，扰动回放/门禁类对事件序列敏感的用例面；本轮取**最小可观测**面。design 未要求该项，故记为**实现选择**而非缺陷。 |

---

## 4. 遗留问题（范围外，未顺手处理）

**R1（阻断「全量回归 0 failed」——需队长 5 秒裁决）**：`tests/unit/test_metrics_for_decide_public.py` 两处**冻结断言**与 design 强制的改动直接冲突，必须更新（该文件在 `tests/unit/`，既不在「只许改」白名单、也不在「禁改」清单；我按纪律未改，已提前报队长）：

```python
# :160-171  test_metric_keys_is_flatten_fixed_set_without_region_keys
#   frozenset({... 10 键 ...})  →  追加 "noise_ratio", "detail_score"
# :229-242  test_default_rules_load_with_explicit_metric_universe
#   assert len(DEFAULT_RULES) == 6      →  == 7
#   assert total == 11, per_file        →  == 12
#   docstring「6 个 DEFAULT_RULES 文件」→「7 个」
```
最小改法即上（另建议把该文件改名为「R21 冻结口径 + R22 增量」并在 docstring 注明）。未改则该轮全量回归**必红 2 例**（E4 实测）。

**R2** 规则级 **env 开启机制**缺失（design §2.1 括注「env 开启」）：需在 engine 加规则级开关或装配层按 env 覆盖 `enabled`；超出本轮文件域。

**R3** 新规则**无渲染执行位**：`action.param = denoise.luminance_strength`，但 `denoise` Stage 不在 `DEFAULT_STAGES`、`loop._DOTTED_PARAM_REGISTRY` 无该键 ⇒ 即便显式开启，值也只落顶层 informational 键（`loop.py:631-638` 的告警路径）。待 **W2 super-dev 的 F02** 落地后登记执行位（design §1 F02 参数名一致）。

**R4** 噪声阈值**闭环内不可用**：本规则阈值只在导出全幅标定；闭环 decide 只吃 preview（`preview_long_edge` 缺省 1024）⇒ 本轮不承担闭环触发职责（design §2.1 / §7 A6 已认可）。闭环内启用须另立 preview 阈值标定专项。

**R5** **色彩轴 tier 混用**（D6）：软告警的 `colorfulness_proxy` 取自「渲染后全幅」，阈值取自「渲染后 512」语料分位。建议后续用「渲染后全幅」语料重标定（本轮无预算：真 RAW 全幅渲染 ≈73s/张，且 design §5 禁止与 pytest 并发）。

**R6** 标定语料边界：26 张来自**内嵌相机 JPEG 全幅**，非 RAW 全幅渲染链；高低 ISO 的 `noise_ratio` **分布重叠**（0.4724~0.7473 vs 0.4137~0.6114）⇒ 0.62 是保守零误触线而非判别切分。真实链全幅标定需另开（同 R5 预算问题）。

**R7** `configs/rules/` 双镜像缺 `noise_rules.yaml`（D4）：待队长授权补镜像 + 复核 `test_formula_guard_sunset.py` 的日落条款约束（新规则公式为纯算术、无比较/布尔守卫，预期直接兼容）。

**R8** `build/lib/pixo/**` 旧副本漂移（tech_debt #25，F10 域）：本轮探针证实 `pixo.pipeline.metrics` 实际解析到 **src**（E5 `[module]` 行），未取旧副本；不在本流处置。

---

## 5. 交接要点（给 tester / QA-checker）

1. **定向复跑**：`python -m pytest tests/unit/test_noise_metric_keys.py tests/unit/test_qc_soft_warnings.py -q`（预期 28 passed）。
2. **全量回归**：先处理 **R1**（否则必红 2 例）；其余面 E4 已覆盖且全绿。
3. **门禁相关**：`tests/regression/test_gate_auto_loop_e2e.py` 只**打印** `rules_count`、不做等值断言（已 grep 核实）⇒ 第 7 个规则文件不破门禁；但门禁用例会加载该文件，`enabled: false` ⇒ `rule_ids` 集合预期不变。
4. **软告警字段契约**（前端/消费方）：`soft_warnings: [{axis, metric, op, value, threshold, tier:"full_export", gate:"soft", message}]`，出现在 auto-loop **sync/GET 视图**；`POST` 202 提交视图不含（与既有 `state/params/...` 同策略）。
5. **口径红线复述**：硬门禁**唯一** `engine._QC_OVERFLOW_THRESHOLD = 0.03`；`soft_warnings` 全链惰性（`engine` 只回抄、`loop` 判定分支零改动、`runtime` 只透出）。
