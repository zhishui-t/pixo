# R22 总审计划（qa-plan-r22）

> 执笔：`QA-checker`（第 11 阶段总审 + 门禁）。依据：`design-r22.md` §0/§1/§2/§3/§4/§7(A1~A13)、`design-review-r22.md`、`streams/r22-stream-1.md`/`1b`/`2`、`DELIVERY-R21.md`、`qa-report-r21.md §7`。
> 预检快照：2026-09-10（HEAD `a092d3a`；W1 已交付未提交，`dag.json` wave2hard/wave2c=running，W3/review/test/qa 未启）。
> **纪律**：QA 只审设计与交付，**不代写业务代码**；文档/测试/小改可在最小范围内修复并复验，架构级/范围级问题列清单回报队长；不提交 git。
> 预检已实测（终审须重验，勿沿用快照）：`presets.py:15-17` 无 `denoise`、`loop.py:68-74` 无 `denoise.*`、`reshape.py:118-127` `wants()→False`；`engine.py:81/1048/1085`；`degradation.py:58/61`；`configs/rules` 7 文件 sha256 全等；`model_licenses.json` 6 条全用 `files`（仅 #0 有路径、5 条空、#5 另有 `isolation_file`）；`test_tech_debt_invariants.py:96-100` 只查 `path/local_path/file`（现 no-op）；`session.py:139-210` 栅栏在途且 `docs/STYLE_CARDS_USAGE.md` 暂缺。

## 1. 逐 F-ID 核对口径（验收判据 / 证据在哪 / 我如何独立复核）

| F-ID | 验收判据（可判定） | 证据在哪 | QA 独立复核动作 |
|------|--------------------|----------|------------------|
| F01 | `metric_universe()` 含 `noise_ratio`/`detail_score`；`METRIC_KEYS` 精确 12 键；新规则 `enabled:false`；缺 `detail` 层**不写空键** | `metrics.py` 4 层展平、`loop.register_metric_keys`、`noise_rules.yaml`、`test_noise_metric_keys.py`(13) | 读展平代码；跑 `test_noise_metric_keys.py` + `test_metrics_for_decide_public.py`（预期 13+14，且断言是**精确集合**非子集）；独立探针打印键与 universe(n=24) |
| F02 | 默认关⇒逐位零漂移；显式开⇒噪声降且细节损失受限；DLL≥1.7.0 + 新旧快照对拍；A/B 同图同全幅、≥20 张 ISO≥3200、串行，`noise_ratio↓≥30%` 且 `detail_score↓≤10%` | `stream-2`/`stream-1`、`.artifacts/r22-f02-spike/`、`r22-dll-backup-v1.6.0/`、tester A/B 原始输出 | 见 §2①；金样本 compare 零漂移；抽 2 张自跑 on/off；核对 A/B 表逐张 EV、同图同 tier、无 pytest 并发痕迹 |
| F03 | 13 条关键路径产结构化降级；**版本门合法拒绝不计 degraded**；`vision_health()` 暴露 `render_*` | `render/degradation.py`、8 文件 14 处 except、`vision/health.py`、`test_render_degradation.py`(10) | 见 §2②；独立注入三类 RuntimeError 文本 + tmp 损坏标定副本，双向断言 |
| F04 | 卡参数注入（复用 `/api/styles`）；未知 stage/键/数值域⇒400；`stylize.lut`/`lut_path` 一律 400；**路径类键按 A14 仓内包含性**（`configs/**`/`resources/**`/`data/**`，越界才 400）；**不误拒既有前端/标定参数**；前端 apply 可用 | `session.py:139+`、`runtime` 装配段、`frontend/src/**`、`test_f04_param_fence.py`/`test_f04_f05_injection.py` | 见 §2④；正/反向矩阵（含 `lut_path`、路径值、未知键）+ 用**仓内合法路径参数**做「不应误拒」观察 |
| F05 | 6 场景 id 可注入且响应 params 变化；未知 id 告警回退或 400 | `scenes.json`、`scene_apply.apply_scene_preset`、`test_f04_f05_injection.py` | 跑定向；独立调 6 个合法 id + 1 个非法 id，比对 trace/params |
| F06 | `soft_warnings` 出现在 engine 返回 / loop metadata / service payload；**不改变既有 ACCEPT/REJECT** | `engine.py:1048/1085`、`loop._qc_outcome`、`runtime.py` 三处、`test_qc_soft_warnings.py`(15) | 见 §2③；同输入「清单开/关」两次判定逐字段 diff |
| F07 | 运行时零接入；勘误节落 `R21_CHANGE_REQUESTS.md`；结论落 `tech_debt.md` | 两文档 + `src/` grep | 全仓 grep `apply_rp_ccm`（`src/` 仅 `render/core/rp_ccm.py` 自身）+ 逐条读勘误/结论 |
| F08 | 只复核销账，**不新增实现** | `test_skin_oklab.py`、`gate_cases.py:28/257/264` | `pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q`（预期 18+7）；确认无 skin 相关新 diff |
| F09 | 默认参数路径逐位不变；同归一化参数跨 tier **相对裁剪窗一致**（禁「掩码不相等」写法）；`compose.coord:"px"` legacy 行为不变；补 1 个 compose gate case（baseline 首次生成须授权） | `compose.py:63`、`loop.py adopt_crop/rect_*`、约 10 处测试、`gate_cases.py`、`docs/架构设计文档.md` | 见 §2⑤；golden compare 零漂移 + 相对窗脚本 + legacy px 用例 + baseline 授权/hash 留证 |
| F10 | #3 断言**真生效且可证伪**；segformer 矛盾裁决；`vision_models.json` 解析规则明确；DCP×6 核验；#10 重编号连续；#12 关闭；#25 明确处置 | `model_licenses.json`、`vision_models.json`、`test_tech_debt_invariants.py`、`tech_debt.md`、`resources/dcp/manifest.json`、`THIRD_PARTY_NOTICES.md` | 见 §2⑦；改坏资源路径须红；编号/条目双源对齐复算 |

## 2. 重点复核项（一律不采信自述）

① **A12/A15 `denoise` 执行位是否真生效**（队长已采纳为 A15 三层判据）：预检确证「登记缺失 + stage 未入链 + 入链亦 no-op」三重惰性。复核**三层递进**：(a) `denoise` 入 `DEFAULT_STAGES` **且** `denoise.luminance_strength` 入 `_DOTTED_PARAM_REGISTRY`；(b) `DenoiseStage.wants()` 在参数>0 时为真（不得仍是空占位）；(c) **像素/指标可观测变化**（显式开启 vs 关闭的渲染差值 ≠ 0），且默认关时 golden compare `u8_max=u16_max=0`。仅 (a) 满足 ⇒ 判**未交付**。
② **版本门反向控制**：`degradation.py:58/61` 靠异常文本分流（脆弱点）。逐条注入「需 DLL >= 1.6.0」「DLL 未导出」「native DLL unavailable」与真异常，断言 `render_degraded_count`/`render_status`/`version_gate_count` 四态正确；**合法拒绝必须 `render_degraded==[]` 且无 WARNING**。
③ **`soft_warnings` 不改判定**：`engine.py` 仅两处返回追加键（manual_review 两分支不加，由 loop `setdefault` 补齐）。复核「清单开 vs 关」两次运行的 `decision/params/reasons/rule_ids` 逐字段相等 + 硬门禁仍唯一 `_QC_OVERFLOW_THRESHOLD=0.03`；payload 纯追加（既有键齐全）。
④ **F04 栅栏正/反向 + A14 仓内包含性（队长已实测复核并裁决）**：在途 `_check_sensitive`（`session.py:180-190`）对**所有** `_path`/`_file` 后缀键无条件 400、strict/非 strict 都执行（`:286/:289`），`service/runtime.py:401` 传 `validate_params=True` ⇒ **真会误拒** `whitebalance.warm_cal_file`（默认值 = **绝对**仓内路径，`white_balance.py:118-120`）与 `huesat.oklch_points_file`（`""`=自动推导）。终审按 A14 四要点：仓内包含性（允许根 `configs/**`/`resources/**`/`data/**`，越界才 400）、`stylize.lut`/`lut_path` **仍无条件 400**、默认仓内路径正向用例、`docs/STYLE_CARDS_USAGE.md` **必须真实存在**；反向矩阵：`/tmp/x.json`、`..\x.json`、`C:/x.cube`、未知键、数值域外必 400。
⑤ **F09 归一化与翻转用例**：默认 `width<=0→全幅` + 生产 `crop_suggest=False` 下 gate compare 零漂移；翻转用例必须是**相对窗不变量**（`compute_crop_rect(...)[0]/w` 两线相等，exploration §8.4），明示拒绝 `assert not equal`；legacy `compose.coord:"px"` 走旧语义且原用例绿；新 compose gate case baseline 须有队长书面授权 + 生成命令 + hash 留证，生成后 `--check` 零漂移。
⑥ **`configs/rules` ↔ `src` 镜像**：预检 7/7 文件 sha256 全等。终审重验（W3 若改 `src` 侧 `noise_rules.yaml` 必须同步镜像），依据 `test_formula_guard_sunset.py:81-89`（全量枚举）+ 新单测双守。
⑦ **#3 许可断言可证伪**：现断言 key 集合不含 `files` ⇒ no-op。复核必须满足：(a) 改查 `files[]`；(b) **声明有仓内文件的条目 `files` 非空**（否则 5/6 条仍空转）；(c) 破坏性测试：改坏 `resources/models/aesthetic/aesthetic_scorer.pt` 路径后**必红**；(d) `vision_models.json` 的 `$GUANLAN_ROOT` 解析规则明确（可解析、缺省行为写明）。

## 3. 独立复跑清单（总审时 QA 亲自跑，非引报告）

| 项 | 命令 | 通过线 |
|----|------|--------|
| 全量回归 | `cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest tests -q -m \"not e2e\" > .agent-team\tmp-r22-qa-full.txt 2>&1"` | ≥ **1574 passed / 0 failed**（并核对用例增量=新增文件条数） |
| 定向用例 | 各新建/改动测试文件批跑（F01/F02/F03/F04/F05/F06/F09/F10 面） | 0 failed |
| 金样本 | `pytest tests/regression/test_gate_golden.py -q` + `gate_golden.py compare`（以仓内实际入口为准） | 既有 21 features `u8_max=u16_max=0`；新 compose case `--check` 零漂移 |
| 降噪 A/B | 复核 tester 原始输出（同图、同全幅 tier、每张 EV、串行证据）+ 抽 2 张自跑 on/off | `noise_ratio↓≥30%`、`detail_score↓≤10%`；默认关零漂移 |
| 几何 | 跨 tier 相对窗脚本 + legacy `px` 用例 | 相对量相等；legacy 行为逐位不变 |
| 真 RAW 门禁 | `PIXO_GATE_AUTOLOOP_RAW=… pytest -m gate`（若本轮未动闭环则引用 R21 结果并标注） | 通过且与 R21 口径一致 |
| 静态域 | `git status --porcelain -uall` 对照 design §3 文件域 + 共享文件串行约定 | 无域外/越界改动 |

> 约束：真 RAW 全分辨率渲染**严格串行单进程**（≈73s/张，禁与 pytest 并发）；pytest 输出走 `cmd /c` 重定向（PS5.1 `>` 落 UTF-16LE）；不提交 git。

## 4. 遗留分级模板 + 签章要素

- **三级定义**：**阻塞**＝门禁红/判据不可判定/越界改动/安全或功能回退 ⇒ 必修或队长裁决；**记债**＝功能可用但确认缺口或口径混用（例：R5 色彩轴 tier、R4 闭环噪声不可用、F03 进程级累积登记）⇒ 写 `tech_debt.md` 并给编号；**已知无害**＝文档口径/测试边界等 ⇒ 报告登记即可。
- **每条模板**：`编号 | 级别 | 现象 + 证据(file:line / 命令输出) | 影响面 | 处置(修复 / 记债编号 / 登记)`；每条须给出**复现命令**与**落盘证据文件名**。
- **`.qa_ok` 要素**：审核人 `QA-checker`；覆盖 F-ID 清单；ISO 时间戳（`YYYY-MM-DDTHH:mm:ss+08:00`）；结论（通过 / 修复后通过）；独立复跑计数（全量 passed/failed、金样本 u8/u16）；「未采信自述项」清单（即 §2 七项的实测结论）。
- **`.r22_ok` 要素**：审核人；覆盖 F01~F10 + A1~**A15** 执行情况；ISO 时间戳；全量回归计数（≥1574/0）；门禁与金样本结论；遗留分级计数（阻塞/记债/已知无害）；放行范围声明（提交归队长，QA 无 git 写）。
- **签章前置**：reviewer 评审 + tester 报告齐备；0 阻塞；§3 全部复跑数字到手；工作树为终态（无在途写入者）。

## 5. A14 最小修复预案（队长授权；仅当 dev-3 交付后栅栏仍是「后缀一律 400」时执行）

- **触发与边界**：dev-3 为一次性代理、不可中途接管 ⇒ 其交付后我**先重读当前文件**再动手（防写入冲突）；若修复面超出 `session.py` 栅栏 + 对应测试，**不硬修**，列清单回报队长。
- **改法（1 辅助函数 + 判定分支）**：路径类键的值 `None`/`""` 放行（空=自动推导）；否则解析（相对值按仓根、绝对值原样 `resolve()`）后必须落在允许根 `configs/**`、`resources/**`、`data/**`（`relative_to` 校验，防 `..` 逃逸；仓根复用 `calibration_store.resolve_repo_root()`，回退 `parents[4]`），越界抛 `ParamValidationError`。`stylize.lut`/`lut_path` 与「非路径键却传路径形态值」维持拒绝。
- **测试与文档**：在 dev-3 的 `test_f04_param_fence.py` 补正向（`warm_cal_file` = `DEFAULT_WARM_CAL_FILE`；`oklch_points_file` = `""` 及仓内相对路径）+ 越界反向；`docs/STYLE_CARDS_USAGE.md` 缺失则补最小说明（属我的文档小改范围）。
- **复验**：`pytest tests/unit/test_f04_param_fence.py tests/unit/test_f04_f05_injection.py tests/integration/test_preview_session.py tests/unit/test_wb_temp_tint.py -q` + 全量回归 0 failed；结论（diff + 理由 + 命令输出）记入 `qa-report-r22.md`。
