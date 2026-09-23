# 测试计划（test-plan-r22.md）— Pixo 第二十二轮（R22，清完剩余欠账）

> 角色：`tester`（第 10 阶段）｜拟定 2026-09-10｜工作目录 `K:\work\project\pixo`（Windows / PowerShell **5.1**）
> 唯一验收依据：`.agent-team/design-r22.md` **§4 门禁与验收全表** + §2.1（tier 口径）+ §7 A2/A8~A13 + §3（文件域）
> 上游已交付：`streams/r22-stream-1.md`（dev-1：F01+F06）、`r22-stream-1b.md`（dev-1：A8/A10/A12）、`r22-stream-2.md`（dev-2：F03+F08 复核）
> 上游在途（Wave2/Wave3）：super-dev（F02）、dev-3（F04+F05）、dev-1（F09）、dev-2（F07+F10）、dev-geom（F09 几何侦察）
> 下游消费者：`QA-checker`（总审，签 `.qa_ok` / `.r22_ok`）；队长（卡点③）
> 红线：全量 **≥ 1574 passed / 0 failed**（`DELIVERY-R21.md:50`）；金样本既有 21 features **逐位零漂移**
> 边界：**只写** `tests/regression/**`（除 `gate_cases.py` 的 compose case 需与 dev-1 串行）、`tests/integration/**`（新增）、本计划、`test-report-r22.md`；**不改 `src/**`**；**不提交 git**

---

## 0. 基线与环境前提

| 项 | 值 | 依据 |
|---|---|---|
| 全量回归口径 | `python -m pytest tests -q -m "not e2e"` | `DELIVERY-R21.md:50` |
| 全量红线 | **≥ 1574 passed / 0 failed**（R22 新增用例后 passed 应 >1574，0 failed 不可让步） | `DELIVERY-R21.md:50`、design §4 |
| 金样本口径 | `python -m pytest tests/regression/test_gate_golden.py -q` + `python src/pixo/render/tools/gate_golden.py compare --samples … --out …` | `gate_golden.py:504-523`（子命令 `generate` / `compare`；`compare` 有 `--samples/--dcp/--out/--long-edge`，**无** `--features`） |
| 既有金样本规模 | **21 features**（`manifest.json:features` 21 项；`gate_cases.py:25-42` FEATURES 同 21 项；`reviewer` 非 pending） | 本轮实测（见 §1 F-金样本） |
| tier 口径（裁决③） | 噪声/细节类指标（`noise_ratio`/`detail_score`/`fft_high_ratio`）**一律用导出全幅** `result.final_measurement`；报告必须写明 tier | design §2.1 |
| 色彩 ΔE 口径 | **不改**：沿用既有 `long_edge=512`（`eval_rp_ccm_ab` 默认 `--ccm-dir configs/color`） | design §2.1 / §7 A1 |
| 真 RAW 渲染纪律 | **严格串行、单进程**；`max_iterations=2` 时单次 ≈100–150s；**严禁与 pytest 或其他 RAW 任务并发**（R21 实测 45MP float64 → `ArrayMemoryError`，`DELIVERY-R21.md:43`） | design §5、任务书 |
| pytest 输出落盘 | `cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest ... > .agent-team\tmp-r22t-*.txt 2>&1"` → `Get-Content -Encoding UTF8` 读（PS 5.1 `>` 落 UTF-16LE） | 任务书环境纪律 |
| 离线 | `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`；**不设** `PIXO_ALLOW_RESTRICTED` | R21 惯例 |
| 目录 | A/B 输出 `.artifacts/r22-noise-ab/`；证据 `.agent-team/tmp-r22t-*` | design §5、A13 |

**本轮已完成的独立复算（Wave2 在途期间，不等产出）**

| # | 项 | 命令 | 实测结果 | 判定 |
|---|---|---|---|---|
| R-1 | 4 个关键单测复算（**非转述开发自述**） | `python -m pytest tests/unit/test_noise_metric_keys.py tests/unit/test_qc_soft_warnings.py tests/unit/test_render_degradation.py tests/unit/test_metrics_for_decide_public.py -q` | **53 passed / 0 failed in 24.61s**（14+15+10+14） | ✅ 与 dev 自述（29+10+14）逐文件吻合，**且 `test_metrics_for_decide_public.py` 已由 2 failed 转 0**（A8 兑现） | 
| R-2 | 高 ISO 语料独立复算 | `.agent-team/tmp-r22t-iso-corpus.py`（生产 EXIF 路径 `pixo.meta.extract`，765 NEF） | `NEF=765 / parse_failed=0`；`ISO≥1600=36`、**`ISO≥3200=32`**；直方图与 exploration §1.5 **逐档一致** | ✅ 语料满足 A13「≥20 张」 |
| R-3 | **口径纠正（复算发现）** | 同 R-2 | exploration §1.5 表述「归一化为 `meta["iso"]`」**不准确**：实测在 **`meta["exposure"]["iso"]`**（`src/pixo/meta/exif.py:452-457`）；首版脚本按顶层取键得 `iso=-1 ×765`（假 0 命中），已修正 | ⚠️ 记入报告「口径勘误」节；**不影响** exploration 结论（32 张成立） |
| R-4 | A/B 语料 EV 记录能力预检 | 同 R-2（`corpus-iso.json`） | 32 张已带 `shutter/fnumber/program`：ISO6400 子集中 **DSC_5292/5293/5295 = 1/800s、DSC_5294 = 1/640s**（欠曝帧）、DSC_5260–5264 = 1/640s；其余 1/15s–1/400s | ✅ 报告可逐张记 EV（A7 要求） |

---

## 1. F01~F10 × 用例 × 命令 × 预期 × 判定

| F-ID | 验收判据（design §4） | 用例 / 命令 | 预期 | 判定（PASS 条件） |
|---|---|---|---|---|
| **F01** 噪声/细节入键宇宙 | `metric_universe()` 含 `noise_ratio`/`detail_score`；新规则可加载且缺省 `enabled: false`；阈值证据注明 tier（全幅） | ① `python -m pytest tests/unit/test_noise_metric_keys.py -q`（14 用例）② 探针：`python -c "from pixo.pipeline.metrics import metric_universe, METRIC_KEYS; ..."` ③ `python -m pytest tests/unit/test_metrics_for_decide_public.py -q`（14 用例）④ 规则文件头注含 `enabled: false`/全幅/preview/1024 | ①`14 passed` ②`METRIC_KEYS` = 12 键且 `metric_universe()` ⊇ 两新键（实测 n=24）③`14 passed`（精确集合 12 键 / 7 文件 / total=12，**非子集**）④`noise_rules.yaml` 头注留证齐备 | 命令 exit 0 且 0 failed；`metric_universe` 键数报告实测值；**禁止**把 A8 的精确断言放宽为包含式 |
| **F02** 亮度降噪 | 默认关零漂移；DLL 版本门 `>=1.7.0`；新旧 DLL 快照对拍（旧 DLL 已备份）；A/B 见 §2 | ① `python -m pytest tests/unit/test_denoise_*.py tests/regression/test_gate_denoise*.py -q`（super-dev 交付）② 版本门探针 `python -c "from pixo.render import _native; print(_native.version())"` ③ 旧 DLL 备份存在性 + 新旧对拍探针（**关闭 denoise** 时逐位一致）④ `denoise` stage / `denoise.luminance_strength` 已登记（A12 硬性验收项）⑤ **A/B 全量（§2）** | ①全绿 ②`(1, 7, 0)` ③`.artifacts/r22-dll-backup-v1.6.0/pixo_render_native_v1.6.0.dll` 存在（**实测已存在，620,886 B，与 R21 同尺寸**）④`presets.DEFAULT_STAGES` 含 `denoise`（或显式执行位）+ `_DOTTED_PARAM_REGISTRY` 含键 ⑤见 §2 | ①④任一不成立 ⇒ **F02 未交付**（A12 明写是硬性验收项）；③对拍必须在 **denoise 关闭**路径上 u8/u16 全 0；A/B 判定见 §2 |
| **F03** 静默降级可观测 | 写坏 `configs/calibration/warmth_curve.json` → health/render 暴露 degraded；**版本门合法拒绝不算 degraded** | ① `python -m pytest tests/unit/test_render_degradation.py -q`（10 用例）② 探针：写坏**副本** + `warm_cal_file` → `vision_health()["render_degraded"]` 含 `source=="render.white_balance.warmth_curve"` ③ 反向控制：monkeypatch `colorcal_apply_lab_f32_oklch` 抛 `RuntimeError("... 需 DLL >= 1.6.0 ...")` → `render_degraded == []` 且 `render_version_gate_rejections` 非空 ④ `python -m pytest tests/unit/test_native_fallback.py tests/unit/test_vision_* -q`（邻域） | ①`10 passed` ②degraded 计数 =1、`render_status=="degraded"`、`status/ready` 不变 ③degraded=0、version_gate=1、**无 WARNING 级 `render-degraded`** ④全绿 | **前置铁律（A11③，design §4.4 口径）**：`render_degraded` 是**进程级累积态** ⇒ 任何「断言为空」前必须 `from pixo.render.degradation import clear_render_degradations; clear_render_degradations()`（并 `white_balance._reset_caches()`）；**验收靶子一律用 tmp 写坏副本 / monkeypatch，绝不真改 `configs/**`**；把 version_gate 误判为 degraded 漏报 ⇒ FAIL |
| **F04** 卡参数注入 + 栅栏 | 非法 stage/键/数值域 → 400；`lut_path` 一律 400；栅栏有正向+反向，且**不误拒既有前端调整参数** | ① `python -m pytest tests/unit/test_f04_param_fence.py tests/unit/test_f04_f05_injection.py -q`（dev-3 交付，**已见落盘**）② **安全矩阵（§4）**：`PUT /api/sessions/{id}/params` 4 类越界 → 400；③ 正向：既有前端调整参数可写（200 + params 变化）④ `python -m pytest tests/integration/test_service_api.py -q` | ①全绿 ②4/4 返 400 且 body 含可诊断原因 ③既有键 200 且 trace/params 有变化 ④全绿 | 矩阵逐格有 HTTP 状态码证据；`lut_path` **任何形态（含仓内合法相对路径）一律 400**（本轮不在白名单）；**越界必须 400 而非静默忽略**；正向用例缺一 ⇒ 「误拒」判 FAIL |
| **F05** 场景预设 | 6 个场景 id 均可注入且响应 params 变化；未知 id 走告警回退**或** 400 | ① `python -m pytest tests/unit/test_f04_f05_injection.py -q -k scene` ② 探针：6 个 id 逐个注入（`from pixo.render.pipeline.scene_apply import apply_scene_preset`）→ params 覆盖非空 ③ 未知 id → `warnings.warn` + `({}, None)` 或端点 400 | ①全绿 ②6/6 覆盖非空且与 `configs/styles/scenes.json` 键集一致 ③未知 id 有显式告警/400，**无静默** | 6 id = `scenes.json` 键集（**实测键集以文件为准**，不采信文档计数）；未知 id 静默通过 ⇒ FAIL（user profile：失败要明确提示） |
| **F06** 多轴 QC 软告警 | `soft_warnings` 出现在响应且**不改变**既有 ACCEPT/REJECT（硬门禁仍只 `_QC_OVERFLOW_THRESHOLD=0.03`） | ① `python -m pytest tests/unit/test_qc_soft_warnings.py -q`（15 用例）② `python -m pytest tests/integration/test_auto_loop_api.py tests/integration/test_loop_e2e.py -q` ③ 常量探针：`engine._QC_OVERFLOW_THRESHOLD == 0.03`；`loop._qc_soft_warnings` 组装轴集合 | ①`15 passed` ②全绿（含 auto-loop 任务视图既有 12 键齐全）③0.03 单源；软告警 schema `{axis,metric,op,value,threshold,tier:"full_export",gate:"soft",message}` | ①「组装强关为 `[]` 后 decision/params/reasons 逐字段一致」用例必须存在且通过；出现第二处硬阈值 ⇒ FAIL |
| **F07** RP-CCM 否决 | 勘误落 `docs/R21_CHANGE_REQUESTS.md`（队长执笔）；结论落 `docs/tech_debt.md`；`apply_rp_ccm` 运行时**零接入** | ① grep：`apply_rp_ccm`/`load_rp_ccm` 在 `src/` 命中仅 `render/core/rp_ccm.py` 自身（定义/`__all__`/docstring）⇒ 渲染链 0 调用点 ② 文档存在性：`docs/R21_CHANGE_REQUESTS.md` 勘误节 + `docs/tech_debt.md` 结论节 ③ `python -m pytest tests/unit/test_rp_ccm.py -q`（代码保留、不回归） | ①命中集合 ⊆ `{render/core/rp_ccm.py}`，渲染链调用点 **0** ②两处文本存在且引用 **2026-09-04 报告（+19.3%）** 而非 8/28 旧报告 ③全绿 | 若 `src/` 出现新的调用点 ⇒ FAIL；勘误节若仍引用 `−7.7%` 作结论依据 ⇒ FAIL（design §0 P1 裁决①） |
| **F08** 复核销账 | 复跑 `pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q` 留证 + 台账销账，**不新增实现** | ① 该命令 ② 探针：`degrees(SKIN_OKLAB_ANGLE)` ↔ JSON `angle_deg`；六常数 `float.hex()` 逐位 ③ `git status` 核对无 skin 相关 `src` 改动 ④ `docs/tech_debt.md` 销账条目存在 | ①`25 passed`（18+7，与 dev-2 自述一致）②逐位 == 且 \|Δangle\|≈2.07e-05 < 1e-3 ③无新增 skin 实现 ④销账文本存在 | ①必须 0 failed；若出现新增 F08 实现文件 ⇒ 偏离 design §0 P4（标「偏差」不判错） |
| **F09** 几何归一化 | 同归一化参数跨 tier **相对裁剪窗一致**（相对量断言，非简单取反）；legacy `px` 行为不变；原失配用例**有意翻转** | **见 §3 专项** | 见 §3 | 见 §3 |
| **F10** 台账治理 | `test_tech_debt_invariants.py` 断言**真正生效**（改查 `files[]` **且**要求「声明有仓内文件」的条目非空，破坏性测试可证伪）；`vision_models.json` 的 `path_or_source` 解析规则明确；#12 关闭、#10 重编号、#3 结论可发布（含 DCP×6 处置） | ① `python -m pytest tests/unit/test_tech_debt_invariants.py -q` ② **破坏性证伪**：临时把 `model_licenses.json` 某条 `files[0]` 改成不存在路径 → 该用例**必须红**（改回后绿；用副本 + 环境变量/临时文件，**不改仓库真文件**） ③ 编号探针：`docs/tech_debt.md` 中 `^\d+\.\s` 序号**唯一且连续**（R22 前 `10.` 出现两次于 `:129`/`:134`） ④ `resources/dcp/manifest.json` 逐项核验（DCP×6）→ 结论写入报告 + `THIRD_PARTY_NOTICES.md` | ①全绿 ②破坏性实验红→恢复绿（**空转即 FAIL**）③序号唯一连续（`:134` 起 +1 后至 `:333`）④条目数 == NOTICES 陈述数，结论「可发布 / 待处置」明确 | ②若破坏后仍绿 ⇒ **断言依旧空转**，判 FAIL（design §0 P8 / R7 的核心验收）；⑤ `vision_models.json` 的 `path_or_source`（`$GUANLAN_ROOT`）必须给出显式解析规则；`build/lib/pixo/**` 漂移按 A4 只登记+排除，**不动构建流程** |

---

## 2. 降噪 A/B 专项（A13：**由 tester 执行全量**）

> **状态：SUSPENDED（队长 2026-09-10 指令）** —— 判据 `noise↓≥30% 且 detail↓≤10%` 已被证据判定为**疑似本身不可判定**（机理与定量推导见 `test-report-r22.md §0.2`）；队长向用户拍板「解耦指标 / 下调阈值 / 能力+默认关+记债」三选一后再通知执行。**本批次一次都未跑，78min 预算零消耗**；§2.1~§2.3 已就绪，通知即可跑。

### 2.1 语料（独立复算，见 §0 R-2）

| 项 | 值 |
|---|---|
| 目录 | `K:\data\photo\0711\raw` |
| 总量 | **765 NEF**（parse_failed=0） |
| `ISO≥3200` | **32 张**（≥20 达标，余量 12） |
| `ISO≥1600` | 36 张（A/B 只取 ≥3200；低 ISO 不参与） |
| 32 张清单 + 快门/EV | `.artifacts/r22-noise-ab/corpus-iso.json`（`iso_ge_3200_files`，含 `shutter/fnumber/program`） |
| 语料构成 | 12800×2 / 8000×2 / 6400×11 / 5000×5 / 3200×12 |
| **欠曝警示帧** | ISO6400 的 `DSC_5292/5293/5295 = 1/800s`、`DSC_5294 = 1/640s`；ISO3200 的 `DSC_5260–5264 = 1/640s` ⇒ **必须逐张记 EV 并分桶**，防曝光差被误读为「降噪效果」（exploration R12） |
| 取用 | 全量 32 张；**若超预算降到 20 张下限**（设计 A7），降序取 ISO 最高 20 张并**在报告写明降级原因** |

### 2.2 口径（不可协商）

1. **同图、同 tier（导出全幅 `final_measurement`）、仅 denoise 开关不同**；tier 必须跑全幅，**不得**用 512/1024 preview 替代（exploration §2.3：512 tier `noise_ratio` 排序非单调，ISO12800 0.284 < ISO1600 0.668）。
2. 判据（design §2.2 / §4）：`noise_ratio` 降 **≥30%** **且** `detail_score` 降 **≤10%**
   - `noise_drop_pct = round(100*(1 - noise_ratio_denoised/noise_ratio_base), 2)`，要求 `>= 30.0`
   - `detail_drop_pct = round(100*(1 - detail_score_denoised/detail_score_base), 2)`，要求 `<= 10.0`（**>0 = 降低；<0 = 升高，同样满足「降≤10%」但须在报告单列**）
3. **严格串行单进程**：一个时刻只跑 1 个 RAW A/B 任务；**与 pytest 严格错峰**（跑 A/B 期间不跑任何 pytest，反之亦然）。单次真 RAW 全幅渲染 ≈100–150s。
4. 单张成本 = **2 次全幅渲染**（off / on）⇒ 32 张 × 2 × ~73–150s；**预算 ≈78min**（32×2×73s），20 张下限 ≈49min。
5. `params` 差异面：**只允许** denoise 参数不同（`denoise.luminance_strength` / `denoise.detail_preserve`，具体键名以 super-dev F02 交付为准）；其余参数/`max_iterations` 一律相同。

### 2.3 脚本契约（super-dev/W2 交付，tester 调用）

A13 分工：super-dev 交付**脚本 + 2~3 张 smoke**；tester 跑全量。接入前先核验脚本具备以下能力（缺项由我加外层 runner，**不改 `src/**`**）：

- 输入：`--raws <file-list|glob>`（或 `--raw` 单张）、`--on/--off`、denoise 参数覆盖（`--param denoise.luminance_strength=…`）
- 输出：**JSON**，每张至少
  `{file, iso, shutter, tier:"full_export", render_ms_off, render_ms_on, base:{noise_ratio,detail_score,fft_high_ratio}, denoised:{…}, noise_drop_pct, detail_drop_pct, pass}`
- 落盘：`.artifacts/r22-noise-ab/<chunk>.json`（**不落仓库根**）
- 幂等/可续跑：已存在结果的图跳过（分块后台执行需要）

**调用模板（分块、后台、串行）**

```powershell
# 一次性准备：32 张路径列表（按 ISO 降序）
cd K:\work\project\pixo
$env:PYTHONIOENCODING='utf-8'
# chunk 1/4（8 张）；提交 job 后**等它结束**再提交 chunk 2（串行，绝不同时跑两个）
cmd /c "python <super-dev 脚本> --raws .agent-team\tmp-r22t-ab-chunk1.txt --on --param denoise.luminance_strength=0.5 --out .artifacts\r22-noise-ab\chunk1.json > .agent-team\tmp-r22t-ab-chunk1.log 2>&1"
# 每块结束用 job_output 读结果；块内失败按 A7「降到 20 张」或重跑该块（不并行补跑）
```

**结果表模板**（报告 §A/B 节逐张填）

| # | file | ISO | shutter | base.noise_ratio | den.noise_ratio | noise_drop% | base.detail_score | den.detail_score | detail_drop% | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | DSC_5314.NEF | 12800 | 1/60 | | | | | | | |
| … | | | | | | | | | | |
| 汇总 | n=32 | | | median | median | **median / min** | median | median | **median / max** | **≥30% ≥20张? / ≤10% 全部?** |

### 2.4 判据可判定性风险（**已升级为证据结论，全文见 `test-report-r22.md §0.2`**；本批已 SUSPENDED）

**机理（决定性）**：`src/pixo/vision/measure.py:287-307` 定义
`noise_ratio = 1 − lap_denoised / lap_raw`、`detail_score = lap_denoised`
⇒ 两轴**同源耦合**（`noise_ratio` 只由 `lap_denoised/lap_raw` 之比定义，`detail_score` 即 `lap_denoised` 本身），一次去噪同时移动两者。

**定量充要式**：记 `r0 = 1 − d0/R0`（`R = lap_raw`）。要求 `r1 ≤ 0.7·r0` 且 `d1 ≥ 0.9·d0` ⇒
`R1/R0 ≤ 0.9·(1−r0) / (0.3 + 0.7·(1−r0))`。
`r0 = 0.97`（spike 全幅解码图基线）⇒ `R1/R0 ≤ 0.084`：**`lap_raw` 须降 ≥91.6%，而 `d` 只能降 ≤10%**；实测最优变体已把 `R` 砍 96.11%（超额）**但 `d` 同跌 66.46%** ⇒ 失败点只在 detail 侧。

**实测表**（`.artifacts/r22-f02-spike/spike_report.json`，全幅 4040×6064，DSC_5314，`r0=0.97`/`d0=6.5`）：

| 变体 | `noise_ratio↓` | `detail_score↓` | 反推 `R1/R0` | `R`↓ | 判据 |
|---|---|---|---|---|---|
| bilateral `preserve=0.00` | 23.61% | **66.46%** | 0.0388 | 96.11% | ❌ detail 侧 |
| bilateral `preserve=0.25` | 6.62% | **58.92%** | 0.1308 | 86.92% | ❌ 双侧 |
| guided `preserve=0.00` | 12.22% | **75.69%** | 0.0491 | 95.09% | ❌ 双侧 |
| gaussian（参考） | 29.65% | **79.85%** | 0.0190 | 98.10% | ❌ detail 侧 |
| 512 tier（不合规，仅参考） | 32.74% | **−28.96%**（反升） | — | — | ⚠️ tier 不合规 |

**结论**：`noise↓≥30% 且 detail↓≤10%` 在**高 `r0`** 图像上**不可判定**，属**判据设计问题**（非单纯实现不足；实现在 `R` 侧甚至超额）。**判据可判定性完全由渲染后基线的 `r0` 决定**：`r0=0.5→R1/R0≤0.69`（可判）、`r0=0.97→≤0.084`（不可判）。

**拍板前置建议（低成本，队长可采纳）**：先做**单张 2 次全幅渲染探针**（off/on，≈3–5min）取**渲染后** `r0/d0`，代入上式即知判据可判定性——远优于先烧 78min。若队长下令，我可立即执行（不改 `src/**`）。

**处置口径**：判据已冻结待拍板 ⇒ **B1 一次未跑**；拍板后按新口径执行。任何情况下 **tester 不得自行放宽阈值/换 tier/减语料后宣称达标**（§7 判定标准）。

---

## 3. 几何专项（F09）

### 3.1 可判定表达式（**待 dev-geom 侦察交付后回填精确式**）

dev-geom 尚未交付侦察结论 ⇒ 先固定**判定形态**（来自 exploration §8.4 与 design §2.4），交付后把 `<侦察表达式>` 替换为 dev-geom 给出的逐分量式，**表达式本身也要留证**（写在报告里，含来源）。

```python
from pixo.render.modules.compose import compute_crop_rect

def rel_window(frame, compose_norm):
    """同一归一化参数 → 该帧的相对裁剪窗（4 分量，全幅归一化口径 B1）。"""
    h, w = frame
    x0, y0, cw, ch = compute_crop_rect(h, w, "free", **compose_norm)
    return (x0 / w, y0 / h, cw / w, ch / h)

P = {"x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0}   # 归一化参数（[0,1]）
# 判据：跨 tier 逐分量一致（相对量断言；禁用「掩码不相等」替代）
assert rel_window((50, 100), P) == rel_window((100, 200), P) == (0.5, 0.0, 0.5, 1.0)
```

**跨 tier 实测面**：除纯函数对拍外，另经真实渲染链取三档 tier 的 compose 输出（512 / 1024 / 2048，或 `preview_long_edge` 两档）验证相对窗一致；**全幅档用已有轻量样本避免 78min 争用**（不与 §2 A/B 同时跑）。

### 3.2 三项门禁（design §4「几何专项」逐条）

| # | 判据 | 用例 / 命令 | 预期 | 判定 |
|---|---|---|---|---|
| G1 | 同归一化参数跨 tier **相对裁剪窗一致**（相对量断言，非简单取反） | ① 纯函数对拍（§3.1）② 渲染链三档 tier 探针 ③ `python -m pytest tests/regression/test_gate_compose.py -q` | ①逐分量相等 ②同参数两档相对窗一致 ③全绿（同步面已按新语义重写） | 两线相对窗差 <1e-6；**若把断言写成 `assert not np.array_equal`（简单取反）⇒ FAIL**（design §2.4 明令） |
| G2 | legacy `px` 路径行为不变 | ① `compose = {"mode":"free","coord":"px", ...}` 同 exploration §8.4 的 px 值 → `compute_crop_rect(50,100,...)`/`(100,200,...)` 相对窗仍 **0.5 / 0.25**（旧失配行为**有意保留**）② caplog 断言含 deprecated 告警 ③ 回归：`python -m pytest tests/regression/test_gate_compose.py tests/unit/test_compose_autolevel.py tests/unit/test_loop_replay.py -q` | ①旧行为逐值复现（可证「一个版本的兼容」）②有且仅有一次 deprecated 告警 ③全绿（`width<=0` 两处语义中性） | `coord="px"` 下相对窗必须仍是 `0.5 vs 0.25`（**不是**改成一致）；缺 deprecated 告警 ⇒ 记偏差 |
| G3 | 原失配用例**有意翻转并留旧行为记录** | `python -m pytest tests/unit/test_region_masks_channel.py -q`（重点 `::test_free_px_rect_cross_resolution_geometry_mismatch_recorded`） | 翻转后新断言 = 相对窗一致（在 **norm** 参数下）+ 旧行为（**px** 参数下 0.5/0.25）作为**对照**保留；docstring 记录翻转理由与旧值 | 用例名/docstring 必须体现「已翻转 + 旧行为对照」；`assert rel_a != rel_b` 若原样残留 ⇒ FAIL；**旧行为数值必须留档**（报告列出翻转前后 diff） |
| G4 | 同步面 ~10 处按新语义重写 | `python -m pytest tests/regression/test_gate_compose.py tests/unit/test_decide_region_wiring.py tests/integration/test_loop_e2e.py tests/unit/test_region_masks_channel.py -q` | 全绿；design §2.4 列的 `test_gate_compose.py:81/92/118/135/149`、`test_decide_region_wiring.py:488/491/514`、`test_loop_e2e.py:69`、`test_region_masks_channel.py:142/651` 逐处核到 | 逐处留证（grep 新旧值）；漏一处 ⇒ 全量回归会红，属 FAIL |
| G5 | 掩码层零改动 | ① `git diff --stat src/pixo/render/pipeline/region_masks.py` ② `tests/unit/test_region_masks_channel.py` 全绿 | ①无 diff（design §2.4：掩码层不改，仅复核）②全绿 | 有 diff ⇒ 记偏差（须 dev-1 说明理由） |
| G6 | 新增 1 个 compose gate case | 见 §5 金样本（baseline 首次生成，A2 授权） | 见 §5 | 见 §5 |
| G7 | docs 更正 | `docs/架构设计文档.md:384-393` legacy `"crop"` px 示例已更正（且标明 legacy） | 文本存在且语义与实现一致 | 未更正 ⇒ 记「遗留」不判 FAIL（非门禁项） |

---

## 4. F04 安全矩阵（越界 → 400 / 正向可写）

端点：`PUT /api/sessions/{session_id}/params`（`service/app.py:135-146` → `runtime.update_params` → `render/web/session.py update_params`）。用 FastAPI `TestClient`（真实 HTTP 往返，非直调函数）。

| # | 类别 | 请求体样例 | 预期 | 判定 |
|---|---|---|---|---|
| N1 | **越界路径** | `{"stylize": {"lut_path": "C:\\Windows\\win.ini"}}` / `"../../configs/x.cube"` / `"/etc/passwd"` | **400**（本轮 `lut_path` **不在白名单**，任何形态一律拒） | 4/4 均 400；若某个形态 200 ⇒ FAIL |
| N2 | 越界路径（仓内合法相对路径） | `{"stylize": {"lut_path": "configs/styles/films/fujifilm_astia.json"}}` | **400**（无 LUT 资产、不接 LUT） | 必须 400（design §7 A5） |
| N3 | **未知 stage** | `{"no_such_stage": {"x": 1}}` | **400** | 400 且 body 有可诊断原因 |
| N4 | **未知键（已知 stage 内）** | `{"tone": {"no_such_param": 1}}` | **400** | 400 |
| N5 | **越域值** | `{"colorcal": {"saturation": 99.0}}` / `{"colorcal": {"saturation": "abc"}}` | **400**（数值域由各 stage `param_schema` 派生） | 400/400 |
| N6 | **正向：既有前端调整参数仍可写** | `{"exposure": {"ev": 0.2}}`、`{"tone": {"shadows": 0.1}}`、`{"clarity": {"strength": 0.3}}`、`{"colorcal": {"saturation": -0.15}}` …（覆盖 `DEFAULT_STAGES` 各 stage 至少 1 个既有键） | **200** + 响应 params 反映变化 + `generation` 递增 | **任一既有键被误拒 ⇒ FAIL**（design §5 风险行：白名单必须由 `param_schema` 派生） |
| N7 | 正向：已知 stage 合法新值边界 | 域端点值（min/max） | 200（闭区间允许） | 端点 200、越端点 400 |
| N8 | 响应契约不破 | 比较 N6 前后响应键集合 | 既有键一个不少、不改名 | 缺键 ⇒ FAIL |
| N9 | 前端 | `frontend/src/**` 构建/类型检查（若 Wave2 交付前端改动） | `pnpm -C frontend run build`（或既有一致命令）成功 | 若前端未改则记「未涉及」；改而未构建 ⇒ 记缺陷 |

**F05 复用**：场景预设经同一装配函数 → 同上矩阵的 N3/N5 对 `scene_id` 同样适用（未知 id → 400 或显式告警回退）。

---

## 5. 金样本门禁

| # | 项 | 命令 | 预期 | 判定 |
|---|---|---|---|---|
| J1 | 既有 21 features **逐位零漂移** | `python -m pytest tests/regression/test_gate_golden.py -q` + `python src/pixo/render/tools/gate_golden.py compare --samples <samples.json> --out .agent-team/tmp-r22t-golden-compare.txt` | 合成 gate **7 passed**；compare `u8_max = u16_max = 0`（逐位） | 任一 `max>0` ⇒ FAIL；**红线：既有 21 features 不允许重生成** |
| J2 | F09 新增 compose case baseline **首次生成**（A2 授权） | `python src/pixo/render/tools/gate_golden.py generate --features compose --reviewer "tester(R22 A2 授权)" --out <gate 目录>` → 随后 `--check`/`compare` 复验 | 仅新增 `compose` 一项；**其余 21 项 .npy 字节不变**（生成前后对 21 个文件做 sha256 前后对比）；`--check` 零漂移 | ①生成只影响 `compose.npy` + `manifest.json` 中该条；②sha256 前后比：**21 项全部相同**；③`--check` OK；④证据落 `.artifacts/r22-compose-case-baseline.md`（case 定义 + 生成命令 + `.npy` sha256 + `manifest` reviewer + **新旧相对裁剪窗对照**） |
| J3 | F02 默认关零漂移 | 同 J1（denoise 默认关时既有 21 项不许漂移） | `u8_max = u16_max = 0` | 若 F02 让 `default_dispatch`/`card_portra_400`/`region_adjust` 漂移 ⇒ **F02 违反「不入 `DEFAULT_STAGES` 或 wants() 门控」**，判 FAIL 并报缺陷 |
| J4 | DLL 版本门 + 快照对拍 | 版本探针 + 旧备份 DLL 存在性 + 关闭 denoise 的逐位对拍 | `(1,7,0)`；备份存在；对拍全 0 | 备份缺失（须在 1.7.0 构建**之前**备份）⇒ FAIL；对拍非 0 ⇒ FAIL |

**生成纪律**：`generate` **禁止**不带 `--features` 全量重生成（会毁掉既有基线）；执行前先备份 `tests/regression/goldens/gate/` 整目录到 `.artifacts/r22-compose-goldens-before/`。

---

## 6. 执行批次（Wave2/Wave3 齐备后按序，**串行**）

| 批次 | 命令（`cd K:\work\project\pixo`） | 覆盖 | 备注 |
|---|---|---|---|
| B0 | 工作树快照 `git status --porcelain` + `git diff --stat` | 归因基线 | 不提交 |
| B1 | `python -m pytest tests/unit/test_noise_metric_keys.py tests/unit/test_qc_soft_warnings.py tests/unit/test_render_degradation.py tests/unit/test_metrics_for_decide_public.py -q` | F01 F03 F06 | **已预跑 53 passed**（§0 R-1），终态复跑 |
| B2 | `python -m pytest tests/unit/test_f04_param_fence.py tests/unit/test_f04_f05_injection.py -q` + §4 HTTP 矩阵探针 | F04 F05 | 矩阵探针脚本我写（`.agent-team/tmp-r22t-f04-matrix.py`） |
| B3 | `python -m pytest tests/unit/test_denoise_*.py tests/regression/test_gate_denoise*.py -q` + DLL 探针 | F02 | super-dev 交付面 |
| B4 | `python -m pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q` | F08 | F08 判据命令（预期 25 passed） |
| B5 | F07/F10 grep + 台账探针 + `python -m pytest tests/unit/test_tech_debt_invariants.py tests/unit/test_rp_ccm.py -q` | F07 F10 | 含破坏性证伪实验 |
| B6 | `python -m pytest tests/regression/test_gate_compose.py tests/unit/test_region_masks_channel.py tests/unit/test_decide_region_wiring.py tests/integration/test_loop_e2e.py -q` + §3.1 纯函数/渲染链探针 | F09 | 与 dev-1 串行（`gate_cases.py` 由 dev-1 先改） |
| B7 | 金样本 J1 → J2 → J3 → J4 | 金样本 | J2 前先备份 21 项 |
| B8 | **A/B 全量（§2）**：4 块 × 8 张，**逐块后台、串行、与 B9 错峰** | F02 | **SUSPENDED（判据待拍板，队长 2026-09-10 指令）**；可选前置=单张 2 次全幅探针取渲染后 `r0`（§2.4） |
| B9 | 全量回归 `python -m pytest tests -q -m "not e2e"` → `.agent-team/tmp-r22t-full.txt` | 全部 | 红线 ≥1574/0；**必须等 B8 全部结束** |
| B10 | 邻域回归（服务层/闭环/渲染）`tests/integration/** tests/unit/test_pipeline*.py tests/unit/test_native_*.py` | 回归面 | 可与 B9 合并 |

---

## 7. 判定标准（不可让步）

1. 各批次 **0 failed**；输出原样摘录进 `test-report-r22.md`（逐条「命令 → 输出关键行 → 结论」）。
2. 全量 **passed ≥ 1574** 且 **0 failed**；skip/xfailed 变动逐条给原因。
3. 金样本：既有 21 features `--check`/`compare` 逐位零漂移（`u8_max=u16_max=0`）；F09 新增 compose case 仅首次生成且有 A2 授权证据。
4. A/B：判据 `noise_ratio↓≥30%` **且** `detail_score↓≤10%`，**逐张出数**；不达标 ⇒ 写「缺陷/口径不可达」节 + 上报队长，**禁止放宽阈值/换 tier/减语料后仍宣称达标**。
5. F04：越界 **必须 400**；既有参数 **必须可写**；两者缺一即 FAIL。
6. F03：断言前必须 `clear_render_degradations()`；靶子**只许**写坏副本/monkeypatch；**不得真改 `configs/**`**。
7. F10：断言有效性必须**破坏性证伪**（红→绿），空转即 FAIL。
8. 发现缺陷：只记 `test-report-r22.md` 的「缺陷」节并**立即回报队长**（不改 `src/**`，修复由原开发流执行）。

---

## 8. 范围外 / 移交

- `build/lib/pixo/**` 旧副本漂移（#25）：按 A4 **只登记 + 打包排除**，**不清理**（触构建流程的不做）→ 报告「遗留」节。
- per-render 降级归因（登记表无 session 边界）、`/api/health` 透出 `render_degraded`、F08 `per_group_fit` 6 组接线、`native_unavailable` 口径备选 → 均为 Wave1/2 自陈遗留，报告「遗留」节登记，不验不改。
- 色彩轴 `colorfulness_proxy` **tier 混用**（值取全幅渲染、阈值取 512 语料分位，dev-1 R5/D6）→ 记「遗留 + QA 需知晓」，本轮不重标定。
- 规则级 env 开启机制缺失（dev-1 R2/L2）→ 登记，不实现。
- `.r22_ok` 签章由 `QA-checker` 执笔。

## 9. 附录：本机环境陷阱（复用）

| 陷阱 | 处置 |
|---|---|
| PS 5.1 `>` 重定向落 **UTF-16LE**（read 工具判为二进制） | pytest 一律 `cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest ... > f 2>&1"`；读用 `Get-Content -Encoding UTF8` |
| 仓库根 `python -c "import pixo"` 报 `ModuleNotFoundError` | 探针脚本自带 `sys.path.insert(0, <repo>/src)`（`tests/conftest.py:19-22` 只对 pytest 生效） |
| 45MP float64 并发 → `ArrayMemoryError` | RAW 渲染与 pytest **严格错峰**；A/B 单进程串行（实测空闲内存 ~11GB，不等于可并发） |
| `render_degraded` 进程级累积 | 断言前 `clear_render_degradations()` + `white_balance._reset_caches()` |
| ISO 取值层级 | `meta["exposure"]["iso"]`（**非** `meta["iso"]`，本轮复算纠正） |
