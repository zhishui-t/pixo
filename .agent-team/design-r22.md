# R22 设计（design-r22）— 清完剩余欠账

> 队长 2026-09-10 起草。依据：`.agent-team/exploration-r22.md`（researcher，754 行 / 13 节）。
> **§0 的 8 条前提已由队长按探索证据复核**（其中 3 条为队长裁决）。本文件 + 卡点②用户确认齐备后才允许写业务代码。

## §0 前提修正与队长裁决（探索推翻了 3 条 CR 原文）

| # | 修正 | 证据（已复核） | 处置 |
|---|------|----------------|------|
| P1 | **CR-12 证据已翻转**：`−7.7%` 出自 08-28 旧系数报告；`configs/color/rp_ccm_nikon_z5_2.json` 于 09-04 被 `3fbe56d` 换成阶段二联合优化系数后，同脚本同语料复评 = **+1.147 (+19.3%)**、仅 22/54 优 | 队长实读两份报告：`eval_rp_ccm_ab_...20260828_232324.md:14-16` = −0.475 (−7.7%)；`...20260904_235522.md:14-16` = +1.147 (+19.3%) | **裁决①：F07 改判「显式否决」（B）**，并在 `docs/R21_CHANGE_REQUESTS.md` 加**勘误节**（照 §0 手法）。门槛线（median 改善≥15% / 无>1JND 回归 / p95 不劣化 / ≥2 相机）现行系数 **0/4** 通过，且第二相机语料本机不可得 |
| P2 | **CR-09 口径不成立**：仓内 **0 个 `.cube`**（glob `**/*.cube` 零命中）；25 张 film 卡是**参数卡**（`fujifilm_astia.json:45 "stylize": {}`）；`GET /api/styles` + `/{id}` **已存在**且前端已接线 | 队长实读 + **QA 复核（行号更正）**：`app.py:338`（`GET /api/styles`）/ `:352`（`GET /api/styles/{style_id}`）；`frontend/src/api/client.ts:138-149`、`useAppStore.ts:391`、`StyleAiPanel.tsx:16-26`（原稿 `app.py:292-314` 实为 auto-loop/timeline/decide 端点，已更正） | **裁决②：F04 改口径为「卡参数注入」**（复用既有 `/api/styles`），**不新增自产 `.cube`**；`lut_path` 登记为未来扩展位 |
| P3 | **噪声指标强分辨率依赖且 512 tier 排序非单调**：`noise_ratio` 在 512 tier 下 ISO12800(0.284) **低于** ISO1600(0.668)；全幅恢复正确排序；`detail_score` 512→全幅差 ~26× | researcher 实测（512/1024/2048/全幅四档） | **裁决③：钉死「导出全幅」（`final_measurement`）为门禁与 A/B 的唯一口径**（限噪声/细节类指标，见 §2.1）；preview tier 噪声指标**不得**用于阈值规则（噪声规则默认关，阈值只在全幅口径标定） |
| P4 | **F08/CR-13 已交付，勿重复造** | `tests/unit/test_skin_oklab.py:354-383`（六常数与 JSON IEEE754 逐位 ==）+ `:386-396`（angle↔rad）；`gate_cases.py:28` 的 `skin_oklch`/`skin_oklch_softband` | **F08 降级为「复核销账」**：tester 复核 + 台账更新，不新建实现 |
| P5 | **#17 迁移面实测 ≈ 0**：仓内 0 处持久化 free px 矩形；掩码层与 compose 同源（`region_masks.py:36-62` 调同一 `compute_crop_rect`）；`gate_cases.py` **无 compose case** | researcher 全仓 grep + 队长复核 | **F09 取「全幅归一化（B1）」**：掩码层零改动、21 features 不漂移；须补 1 个 compose gate case（现零覆盖） |
| P6 | **CR-07 算子选型**：NLM 不可用（512 tier 实测 NLM 382ms / NLMColored 881ms），bilateral 4.1ms / guidedFilter 6.1ms | researcher 实测 | F02 候选 = **bilateral 或 guided filter**（spike 定），**禁止 NLM** |
| P7 | **#12 前置已满足**：`engine.py:222`(`all`) / `:384`(`between`) 已落地，首例已迁移（`tone_clarity_rules.yaml:36`） | 队长实读 engine.py | **#12 判「日落关闭」**（tech_debt `:24/:156-158` 的「前置未到」表述陈旧） |
| P8 | **#3 防复发断言名存实亡**：`test_tech_debt_invariants.py:92-102` 只查 `path`/`local_path`/`file` 三键，而 `model_licenses.json`（**在仓库根**，6 条）全部以 **`files`** 键登记 | 队长实读 + QA 复核（`files` 键 6/6 命中；但**仅 `aesthetic_scorer.pt` 1 条有路径，其余 5 条为 `files: []`**；`vision_models.json` 用 `path_or_source`（`$GUANLAN_ROOT`）而非 `files`） | F10 必须**修复该断言**（改查 `files[]`），否则 #3 无守卫；且断言须**同时要求「声明有仓内文件」的条目 `files` 非空**，否则 6 条里 5 条仍空转；`vision_models.json` 的 `path_or_source` 需另定环境变量解析规则 |

### §0.1 三项裁决的证伪条件与备选路径（QA 补，卡点②需用户知晓）

| 裁决 | 证伪条件（出现即须回退重议） | 若用户不同意时的备选路径 |
|------|------------------------------|--------------------------|
| ① F07 显式否决 | 出现**中性语境**下 median 改善 ≥15% 且 p95 不劣化的新 A/B（同脚本 `scripts/eval_rp_ccm_ab.py`、同语料 54 张）；或第二台相机语料入库后复验通过 | 路径 A（切换）：须先重拟合中性系数 → 换表 → 重跑 4 项门槛 → 定死在线插入点（新增 `rpccm` Stage）+ 补 gate case + 全量回归；**本机缺第二相机语料 ⇒ 门槛第 4 项物理不可达**，属独立战役，本轮不接 |
| ② F04 改「卡参数注入」 | 若团队/用户要求保留 CR-09 原文的 `lut_path` LUT 口径，则必须**同时自产 ≥1 个 `.cube` 资产**并给出许可结论（仓内 0 个 `.cube`、外置 LUT 目录指向仓外 `guanlan/luts`） | 自产 `.cube` + 机制层栅栏落 `core/lut.py:90 load_lut_path`（一处覆盖所有调用方）+ 补资产许可登记；工作量约 +0.5 人日 |
| ③ 钉死「导出全幅」口径 | 若实测在全幅口径下 `noise_ratio` 反而失去噪声区分度（ISO 排序不复现），则须改判口径 | 退化为「双 tier 口径」：门禁用全幅、闭环规则按 `preview_long_edge` 单独标定并写明 tier；代价 = 两套阈值 + 两处留证 |

## §1 功能清单（F-ID 修订后）

| F-ID | 交付 | 备注（修订） |
|------|------|--------------|
| **F01** | 噪声/细节指标入决策键宇宙（`noise_ratio`/`detail_score`）+ 1 条噪声规则（**默认关**） | 层级 = `measurement["global"]["detail"]["sharpness"][*]`；改动 4 处：`metrics.py:78-89` 展平、`metrics.py:39-55 METRIC_KEYS`、`loop.py:761-770 register_metric_keys`、新增规则 YAML 并登记 `decide/rules/__init__.py:31`。**规则适用口径 = 全幅**：闭环 decide 只吃 preview measurement（`loop.py:1322` measure → `:1371 _metrics_for_decide`），故该规则在本轮**默认关**且在闭环内不生效，适用面 = 全幅 QC/导出判定；若未来闭环内启用，阈值须按 `preview_long_edge`（生产缺省 **1024**，`runtime.py:795`）单独标定并写明 tier |
| **F02** | 亮度降噪（native 内核 + Python 等价位回退），**默认关** | 参数 `denoise.luminance_strength` / `detail_preserve`；按 `noise_ratio` 自适应；DLL 版本 +1 + 新旧快照对拍。**判据已修订为解耦版**（见 §2.2 / §4 / §7 A16）：CR-07 原文「`noise_ratio`↓≥30% 且 `detail_score`↓≤10%」经 spike 实测**不可达**（两指标同源耦合：`noise_ratio = 1 − detail/lap_raw`） |
| **F03** | 关键路径静默降级可观测（13 条） | 两层：render 侧采集 + `vision/health.py` 暴露；**须区分「版本门合法拒绝」与「真异常」**（否则 colorcal DLL<1.6.0 回退会被误告警） |
| **F04** | 风格**卡参数注入** + 前端「应用」动作 + **参数路径栅栏** | 复用 `/api/styles`；前端 `StyleAiPanel` 补 apply（简约）；**修 `render/web/session.py:175-180 update_params` 零校验**（白名单 + 目录栅栏）。白名单须由各 stage `param_schema` **派生**（防误拒既有前端调整参数 ⇒ 回归翻红）；本轮 **`lut_path` 不在白名单 ⇒ 任何 `lut_path` 一律 400**（无 LUT 资产，登记为未来扩展位）；既有 `PIXO_STYLE_CARDS`/`enable_style_cards`（`loop.py:742`/`:831`，R13 决定卡源）**保持关闭、不改语义**（F04 只做参数注入） |
| **F05** | 场景预设生产路径（6 预设，`lut` 全为 null ⇒ 纯 params 覆盖） | 复用 `apply_scene_preset`（有进程内缓存 + `_reset_caches()`） |
| **F06** | 多轴 QC 软告警（`soft_warnings`） | 3 处落点：`engine.py:1037/1071` 返回 dict、`loop.py:1716` 组装、`runtime.py:963-972` 透出；硬门禁仍只 `engine.py:81 _QC_OVERFLOW_THRESHOLD=0.03` |
| **F07** | RP-CCM **显式否决** + 勘误 + 结论落档 | 见 §0 P1；代码/测试保留（未来中性语境重拟合的基础），运行时零接入 |
| **F08** | skin OKLab 一致性**复核销账** | 见 §0 P4 |
| **F09** | `compose` px→**全幅归一化** + `compose.coord:"norm"\|"px"` legacy 开关 | 见 §0 P5；`test_region_masks_channel.py:637-672` **有意翻转**为「两线相对裁剪窗一致」；测试同步面（带 `x/y/width>0` 语义的硬编码）：`test_gate_compose.py:81/92/118/135/149`、`test_decide_region_wiring.py:488/491/514`、`test_loop_e2e.py:69`、`test_region_masks_channel.py:142/651`（共约 10 处；`width<=0` 的 `compose_autolevel.py:109`、`loop_replay.py:48` 语义中性）；另**顺带更正** `docs/架构设计文档.md:384-393` 的 legacy `"crop"` px 示例 |
| **F10** | 台账治理：#3（含**修 no-op 断言**、segformer 矛盾裁决、`vision_models.json` 2 条 vs 根 6 条对齐、**DCP×6 再分发核验**）、#7 提案、#10 重编号、#12 日落关闭、**#25 登记处置** | #3 为发布前必收（CR-15 #3 三项：aesthetic 旧路径 vs MIT / segformer 自相矛盾 / **DCP×6 再分发**）。#10 重编号影响面：`docs/tech_debt.md:134` 起后续序号整体 +1（至 `:333` 的 21.），**不动外部引用编号**，并核对 R21 续排候选 `qa-report-r21.md §7.2` 的 #20~#27（其中 #25 见下条）。**#25 `build/lib/pixo/**` 旧副本漂移**（`build/lib/pixo/render/core/skin.py` 仍是旧 OKLab 常数 `A=0.01516/SOFT_BAND=0.25`，与 `src/.../skin.py:188-196` 不一致）本轮**登记 + 明确处置口径**（清或排除），不静默留债 |

## §2 关键约定

### 2.1 测量 tier 口径（裁决③；适用范围＝噪声/细节类指标，见下）
- **口径适用范围 = 噪声/细节类指标**（`noise_ratio` / `detail_score` / `fft_high_ratio`）：门禁与其 A/B **一律用导出全幅**（`result.final_measurement`）；报告中必须写明 tier。
- **不改既有色彩 ΔE A/B 口径**：F07 否决依据的两份 `eval_rp_ccm_ab` 报告均在 `long_edge=512` 下产出（`--ccm-dir configs/color`），ΔE2000 对尺度不敏感，沿用 512 口径即可，**不得**据本条宣布 F07 证据无效。
- preview tier 的 `noise_ratio` **禁止**用作阈值规则输入；F01 新增规则默认 `enabled: false`。**勘误（2026-09-10，dev-1 开工前置发现，见 §7 A8/A9）**：全仓**不存在** per-rule env 开启机制（`engine.py` 只有 `rule.get("enabled") is False: continue`；`PIXO_RULES` 是整包开关）⇒ **本轮唯一开关 = YAML `enabled`**；per-rule env 机制登记遗留（改 `load_rules`/`evaluate_rules` 超出本轮文件域）。阈值须在全幅口径下标定并留证。
- 闭环内的 decide 只吃 preview measurement（`loop.py:1322`/`:1371`），生产 `preview_long_edge` 缺省 **1024**：任何「闭环内生效」的噪声阈值都必须按该值单独标定并写明；本轮 F01 规则不承担闭环触发职责（默认关）。

### 2.2 降噪（F02）
- 算法候选：**bilateral / guided filter**（spike 二选一，给 512 tier 计时与质量对比）；**NLM 禁止**。
- native：新增内核进 `native/src/`（含 ABI 导出 + `build.bat` 流程 + `_native` 加载与**版本门 `>= 1.7.0`**），Python 侧等价位回退；DLL 版本 +1，做**新旧 DLL 快照对拍**（无 denoise 调用时逐位一致）。
- **默认关** ⇒ 金样本零漂移；gate case 仅在显式开启时跑。
- **重建前置**：先备份现行 DLL（`src/pixo/render/_native/pixo_render_native.dll` → `.artifacts/` 存证）再做 1.7.0 构建，否则「新旧快照对拍」无基线可对。
- A/B（**解耦判据版，2026-09-10 用户批准方向，见 §7 A16**）：`K:\data\photo\0711\raw` 中 **ISO ≥ 3200 共 32 张**（≥20 达标），**同图、同 tier（导出全幅）、仅 denoise 开关/强度不同**；三轴须**同时**满足：
  - **噪声轴（平坦区）**：低梯度区域（梯度幅值**最低 30%** 像素 + 形态学开运算去边缘，参数写死）上估噪声 σ（建议「laplacian 绝对中位差 / 1.4826」或「局部 std 中位数」，估算器**确定性可复现**并落报告）；要求 **↓≥30%**（若标定证明不可达 ⇒ **记录实测上限并报队长**，不得静默放宽）
  - **细节轴（纹理区）**：高梯度区域（梯度幅值**最高 30%**）上测高频能量（laplacian 绝对中位差）**↓≤10%**
  - **保真轴（新增）**：与「未去噪」参考的 **ΔE2000 中位数不劣化**（≤ +0.5 JND），防结构性破坏
  - 真 RAW 全幅渲染 **严格串行、单进程**（≈73s/张，禁与 pytest 并发），报告逐张记 **EV**（高 ISO 子集含 1/640~1/800s 欠曝帧，防曝光差被误读为降噪效果）；`strength` 取值由 **spike 选定**并写明依据

### 2.3 风格注入（F04/F05）
- 注入形态 = **卡参数注入**（`stages`/`params` 深合并，仿 `scene_apply.py:64`），非 LUT；`lut_path` 仅登记扩展位（`style.py` 已有参数，不改语义）。
- 安全栅栏：`update_params` / 渲染参数装配处**白名单**校验（stage 名 + 参数键 + 数值域，由各 stage `param_schema` 派生），**拒绝任何仓外路径**；越界一律 400。本轮 `lut_path` **不在白名单内 ⇒ 一律 400**（无 LUT 资产可指；未来做 LUT 注入时再放开并补机制层栅栏 `core/lut.py:90`）。
- **与既有决定卡源划界**：`SinglePhotoLoop.enable_style_cards` / env `PIXO_STYLE_CARDS`（`loop.py:742`/`:831`，R13 裁决缺省关）是「内置卡→decide 规则」的另一条链，**本轮保持关闭、不改语义**，F04 不启用它（避免两条卡源叠加改判定）。
- 场景预设（F05）：走同一装配函数（`apply_scene_preset` → 深合并），6 个场景 id 白名单 = `scenes.json` 键集；前端与风格选择器**同一组件**（置风格选择器上方，紧凑 chip/Select，禁大卡片）。
- 前端：`StyleAiPanel` 增加「应用」动作（调 `patchParam`），**简约**（不新增大卡片/动画），移动端优先。

### 2.4 几何归一化（F09）
- 基准 **B1 = 全幅归一化**：free 模式 `x/y/width/height` 语义改为**相对全幅比例**（`[0,1]`）。
- legacy：`compose.coord: "norm"(缺省新) | "px"(旧语义)`；`adopt_crop` 段（`loop.py:1612-1652`；`:1619-1624` 用 `_full_canvas_size` 取真 RAW 全幅，`:1633-1640` 写回矩形）与 `compute_crop_rect`（`compose.py:63`）为主要改动点；`rect_px_to_norm`（`loop.py:265`，当前零调用）可复用作迁移工具。
- **默认路径零变化证据**：`compose.py:222 default_params` = `mode=free, width=0` ⇒ `compute_crop_rect` 走 `width<=0` 全幅（`compose.py:76-77`）；生产 `crop_suggest` 缺省 `False`（`loop.py:736`，`runtime.py:943-957` 未传）⇒ 生产默认既不触发 adopt_crop 也不带 px 矩形，归一化后**逐位不变**；`px` 分支加 deprecated 告警。
- 掩码层**不改**（同源 `compute_crop_rect`）；`region_masks.py:36-62` 仅复核。
- 测试：`test_region_masks_channel.py:637-672` 有意翻转（新不变量 = 两线相对裁剪窗一致，如 `compute_crop_rect(...)[0]/w` 相等，**不得**简化为「掩码不相等」）；同步面 `test_gate_compose.py:81/92/118/135/149`、`test_decide_region_wiring.py:488/491/514`、`test_loop_e2e.py:69`、`test_region_masks_channel.py:142/651`（`width<=0` 的 `test_compose_autolevel.py:109`、`test_loop_replay.py:48` 语义中性，仅复核）；**新增 1 个 compose gate case**（现 `gate_cases.py` 对 `compose` 零命中），其 baseline 属**首次生成**（见 §4）；另更正 `docs/架构设计文档.md:384-393` 的 legacy `"crop"` px 示例。

## §3 开发流与文件域（**冻结**，越界报队长）

| 波 | 角色 | F-ID | 文件域 |
|----|------|------|--------|
| W1 | `dev-1` | F01 + F06 | `src/pixo/pipeline/metrics.py`、`src/pixo/pipeline/loop.py`（**独占**）、`src/pixo/vision/measure.py`（如需）、`src/pixo/decide/rules/*`（新增 YAML + `__init__.py` 登记）、`src/pixo/decide/engine.py`（仅 soft_warnings 返回字段）、`src/pixo/service/runtime.py`（仅 QC payload 透出段）、新建 `tests/unit/test_noise_metric_keys*.py`、`tests/unit/test_qc_soft_warnings*.py` |
| W1 | `dev-2` | F03 + F08 复核 | `src/pixo/render/**`（**仅 13 条关键路径的 except 处**）、`src/pixo/vision/health.py`、新建 `tests/unit/test_render_degradation*.py`；F08 仅**只读复核** |
| W2 | `super-dev` | F02 | `src/pixo/render/native/**`、`src/pixo/render/_native/**`、`src/pixo/render/modules/reshape.py`、`src/pixo/render/modules/refine.py`（如需）、新建 `tests/unit/test_denoise_*.py`、`tests/regression/test_gate_denoise*.py` |
| W2 | `dev-3` | F04 + F05 | `src/pixo/render/pipeline/scene_apply.py`（实测存在，`apply_scene_preset:47`）、`src/pixo/service/runtime.py`（**仅参数装配/白名单段**）、`src/pixo/render/web/session.py`（栅栏）、`frontend/src/**`（`StyleAiPanel.tsx`/`store`/`api`）、**新建** `docs/` 说明文件（仅新增 F04/F05 用户说明；**不含** `changelog.md`/`tech_debt.md`/`R21_CHANGE_REQUESTS.md`） |
| W3 | `dev-geom`（原 dev-1 席位） | F09 | `src/pixo/render/modules/compose.py`、`src/pixo/render/pipeline/region_masks.py`（A′ 下仅 1 行透传）、`src/pixo/pipeline/loop.py`（`rect_norm_to_px`/`rect_px_to_norm`/`adopt_crop` 段 —— **与 F02 在 `loop.py:68` 的 `_DOTTED_PARAM_REGISTRY` 冲突 ⇒ 必须串行，见 A17**）、`tests/unit/test_crop_wiring.py`（**dev-geom 侦察补入，原清单遗漏、含硬断言 `:173-178/:201-209`**）、`tests/unit/test_region_masks_channel.py`、`tests/unit/test_decide_region_wiring.py`、`tests/integration/test_loop_e2e.py`、`docs/架构设计文档.md`（仅 F09 legacy px 示例更正段）、`tests/regression/goldens/gate_cases.py`（加 compose case；**`tests/regression/test_gate_compose.py` 与 baseline 首次生成归 tester，串行**）。**更正**：原稿引用的 `src/pixo/render/pipeline/params.py` **不存在**（dev-geom 实证）；`test_gate_compose.py` 在 `tests/regression/` 而非 `tests/unit/` |
| W3 | `dev-2` | F07 + F10 | `docs/tech_debt.md`、`model_licenses.json`、`src/pixo/manifests/vision_models.json`、`tests/unit/test_tech_debt_invariants.py`（修断言）、`docs/R21_CHANGE_REQUESTS.md`（**勘误节由队长执笔，dev-2 只提供事实**） |
| 评审 | `reviewer` | F02/F09 | 只读 + `.agent-team/reviews/r22-review.md` |
| 测试 | `tester` | 全部 | `tests/regression/**`（除 `gate_cases.py` 的 compose case 需与 dev-1 串行）、`tests/integration/**`（新增）、报告 |
| 门禁 | `QA-checker` | — | `design-review-r22.md`、`qa-report-r22.md`、`.design_ok`、`.qa_ok`、`.r22_ok` |

**共享文件串行约定**（跨波次同文件一律「先列者先做、后列者后做」，不得并行改同一文件）：
1. `src/pixo/service/runtime.py`：W1 dev-1 QC payload 段 → W2 dev-3 参数装配/白名单段；
2. `src/pixo/render/modules/refine.py`：W1 dev-2（仅 except 处，F03 清单 #2-#6）→ W2 super-dev（内核接线，如需）；
3. `src/pixo/render/modules/reshape.py`：W1 dev-2（`clarity` except 处 #1）→ W2 super-dev（`DenoiseStage` 实现）；
4. `src/pixo/render/web/session.py`：W1 dev-2（解码/校验 except 处 #13）→ W2 dev-3（`update_params` 栅栏）；
5. `src/pixo/pipeline/loop.py`：W1/W3 均归 dev-1 **独占**（同人，无并行冲突）；
6. `tests/regression/goldens/gate_cases.py`：W3 dev-1（加 compose case）→ tester 复核 + 生成 baseline（**队长授权**）。
（W1 内 dev-1 与 dev-2 无同文件交叠；W2 内 super-dev 与 dev-3 无同文件交叠。）

## §4 门禁与验收

| 项 | 判据 |
|----|------|
| 全量回归 | ≥ **1574 passed / 0 failed**（R21 终态红线；R22 新增用例后应 ≥1574 且 0 failed，可在 tester 报告核对用例增量） |
| 金样本（既有 21 features） | **逐位零漂移**（`gate_golden.py compare` → `u8_max=u16_max=0`）：F02 默认关、F09 归一化在生产缺省参数下逐位不变（证据见 §2.4） |
| 金样本（F09 新增 case） | 新增 1 个 `compose` gate case ⇒ 其 baseline 属**首次生成**（既有 21 features 不受影响），须**队长书面授权**单点执行生成并留证，生成后 `--check` 复验零漂移 |
| F01 键宇宙/规则 | `metric_universe()` 含 `noise_ratio`/`detail_score`；新规则可加载（lint 放行）且缺省 `enabled: false`；阈值标定证据**注明 tier（导出全幅）** |
| F05 场景预设 | 6 个场景 id 均可注入且响应 params 变化（trace/params 可证）；未知 id 走告警回退或 400（正向+反向测试） |
| F07 否决 | 勘误节落 `docs/R21_CHANGE_REQUESTS.md`（队长执笔）；结论落 `docs/tech_debt.md`；`apply_rp_ccm` 运行时零接入（`src/` 内命中仅 `render/core/rp_ccm.py` 自身：定义/`__all__`/docstring，渲染链 0 调用点） |
| F08 复核销账 | 复跑 `pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q` 留证 + 台账销账，**不新增实现** |
| 降噪专项 | 默认关零漂移 + A/B（≥20 张 ISO≥3200，**同图同 tier＝全幅**）**解耦三轴**：①平坦区噪声 σ **↓≥30%**（不可达 ⇒ 记录实测上限并报队长，不得静默放宽）②纹理区高频能量 **↓≤10%** ③与未去噪参考的 **ΔE2000 中位数不劣化（≤+0.5 JND）**；报告记 EV、严格串行；DLL 版本门 `>=1.7.0` + 新旧快照对拍（旧 DLL 已备份存证） |
| 几何专项 | 同归一化参数跨 tier **相对裁剪窗一致**（相对量断言，非简单取反）；legacy `px` 路径行为不变（回归可证）；原失配用例有意翻转并留旧行为记录 |
| 安全（F04） | 非法 stage/键/数值域 → 400；`lut_path`（本轮不在白名单）→ 一律 400；栅栏有正向+反向测试，且**不误拒既有前端调整参数**（全量回归可证） |
| 可观测（F03） | 写坏 `configs/calibration/warmth_curve.json` → health/render 暴露 degraded 条目；**版本门合法拒绝不算 degraded** |
| QC（F06） | `soft_warnings` 出现在响应且**不改变**既有 ACCEPT/REJECT 判定（硬门禁仍只 `_QC_OVERFLOW_THRESHOLD=0.03`） |
| 台账（F10） | `test_tech_debt_invariants.py` 断言**真正生效**：改查 `files[]` **且**要求声明有仓内文件的条目非空（否则 5/6 条仍空转），破坏性测试可证伪；`vision_models.json` 的 `path_or_source` 解析规则明确；#12 关闭、#10 重编号（含 :134 后续 +1）、#3 结论可发布（含 DCP×6 处置） |

## §5 风险

| 风险 | 影响 | 规避 |
|------|------|------|
| 降噪 native 内核引入逐位漂移 | 金样本/门禁红 | 默认关 + 无调用时逐位不变断言 + DLL 版本门 + 快照对拍（重建前备份旧 DLL） |
| F09 归一化改变既有导出取景 | 用户可感知变化 | 生产缺省（`width=0` + `crop_suggest=False`）逐位不变（§2.4 已证）；legacy `px` 开关保留一个版本；文档明示；补 gate case |
| noise 指标 tier 依赖 | 规则误触发/误判 | 裁决③ 钉死全幅口径 + 噪声规则默认关；**闭环 decide 只吃 preview（1024）** ⇒ 规则适用面显式限定（§2.1） |
| 裁决③ 被误读为「所有 A/B 一律全幅」（会误废 F07 的 512-tier ΔE 证据） | 结论自相矛盾 | §2.1 已收窄适用范围＝噪声/细节指标；色彩 ΔE A/B 沿用既有 512 口径 |
| F04 白名单过严（非由 `param_schema` 派生） | 误拒既有前端调整参数 ⇒ 回归红/功能回退 | 白名单必须从各 stage `param_schema` 派生；补正向用例（既有参数仍可写） |
| `build/lib/pixo/**` 旧副本漂移（#25） | 打包/导入误取 → 用错 OKLab 常数或 ImportError | F10 登记并明确处置口径（清或排除），不静默留债 |
| 真 RAW 全幅 A/B 时间/内存 | 与 pytest 并发 OOM、A/B 崩 | A/B **严格串行单进程**、输出落 `.artifacts/`；语料筛选用 `rawpy.extract_thumb`（毫秒级）预检 |
| `update_params` 零校验（既存） | 任意路径注入 | 本轮纳入 F04 必修（白名单 + 目录栅栏 + 反向测试） |
| 三波串行导致周期长 | 交付晚 | W1 并行 2 流、W2 并行 2 流；W3 与 reviewer 并行 |

## §6 非目标

不改色彩标定表（含 `calib_out`）、不接 LLM 副驾/风格卡决策卡、不做 learned ISP、不新增第三方依赖、不动 `frontend` 其他页面结构。

## §7 用户确认记录（卡点②）

### 队长对 QA 待裁决项 A1~A7 的裁决（2026-09-10，**不改 F-ID 范围**）

| # | 裁决 | 要点 |
|---|------|------|
| A1 | **接受收窄** | 「全幅口径」只约束**噪声/细节类**指标；色彩 ΔE A/B 沿用 512 tier（否则 F07 的否决证据会被自身口径废除） |
| A2 | **授权（书面）** | F09 新增 compose gate case 的 baseline 属**首次生成**，由 `tester` 执行、队长授权，证据落 `.artifacts/r22-compose-case-baseline.md`（case 定义 + 生成命令 + hash + 新旧相对裁剪窗对照）；**既有 21 features 必须 `--check` 逐位零漂移** |
| A3 | **纳入本轮** | #3 为发布前必收：F10 增 **DCP×6 逐项核验**（读 `resources/dcp/manifest.json`），给"可发布 / 待处置"结论并更新 `THIRD_PARTY_NOTICES.md` |
| A4 | **排除 + 登记** | #25 `build/lib/pixo/**` 漂移：本轮先查清**误取风险**（打包/测试/sys.path 配置），在打包说明与 `.gitignore` 明确排除 + 文档说明；**清理动作若触及构建流程则不做**，登记 R23 |
| A5 | **采纳 QA 建议** | 白名单由 `param_schema` **派生**（不误拒既有键）；仅**敏感面**（路径类、新 stage 名）严格 400；既有参数走正向用例；`lut_path` 一律 400（本轮不接 LUT） |
| A6 | **接受** | F01 噪声规则本轮**不承担闭环触发职责**（适用面 = 全幅、闭环内不生效、默认关）；闭环内触发需另立 preview 阈值标定专项 |
| A7 | **接受** | 降噪 A/B 全幅串行 ≈78min：`tester` 分块后台执行、与 pytest **严格错峰**、报告记 EV；超预算时降到 20 张下限并记录 |
| A8 | **授权 (A)** | `dev-1` 可**最小改** `tests/unit/test_metrics_for_decide_public.py` 的两处冻结断言（`:160-171` 精确键集合、`:229-242` 6 文件/11 条）——它们是我方在 R21 为**当时契约**写的守卫，F01 扩容属**设计内变更**。硬要求：①必须改成**新的精确集合断言**（12 键 / 7 文件 / total=12 条），**禁止**放宽为子集或"包含式"；②改动处注明「R22 F01 扩容（design §1/§2.1）」；③stream 报告逐行给 diff 与理由；④若已按 (B) 交卷，由队长在 Wave1 收口时派最小修复单（同文件）。**这是 `tests/unit/**` 的定向授权，不改变「`tests/regression/**` 归 tester」的既有约定** |
| A9 | **按 dev-1 方案落地** | F01 规则本轮**唯一开关 = YAML `enabled: false`**（engine 现有检查已足够）；**per-rule env 机制不存在**，登记遗留（涉 `load_rules`/`evaluate_rules`，超本轮域）；§2.1 已同步勘误 |
| A10 | **授权并指派收口** | `configs/rules/` 是**镜像目录**（`test_decide_region_wiring.py:205` 断言镜像存在、`test_color_rules.py:79` 读镜像字节）⇒ 新增 `configs/rules/noise_rules.yaml`（与 `src/pixo/decide/rules/noise_rules.yaml` **字节一致**），并在新单测里断言镜像存在且相等。**这是本轮的定向 `configs/**` 授权（仅此一个文件）**，不改变「`configs/**` 默认禁改」 |
| A11 | **授权 dev-2 方案** | ①新增 `src/pixo/render/degradation.py` 属 §4.4 授权的"render 侧模块级登记"，**§3 文件域措辞收紧为「`render/**`（仅 13 条 except 处 + §4.4 授权的登记模块）」**；②`/api/health` 透出**本轮不做**（判据是 `vision_health()` 字典，已满足；UI 透出登记为后续）；③`clear_render_degradations()` 作为 tester 前置写进测试计划 |
| A12 | **跨波次契约（R3）** | F01 的 `noise_luminance_rule_040` 当前**无渲染执行位**（`denoise` 不在 `DEFAULT_STAGES`、`_DOTTED_PARAM_REGISTRY` 无键）⇒ **Wave2 `super-dev` 必须登记 `denoise` stage + `denoise.luminance_strength` 参数键**，否则该规则永不生效（规则仍默认关）。此为 F02 交付的**硬性验收项** |
| A13 | **A/B 分工（R6/进度）** | 降噪 A/B **由 `tester` 执行全量**（≥20 张 ISO≥3200、全幅、严格串行）；`super-dev` 只交付**脚本 + 2~3 张 smoke**，避免 78min 重复跑。阈值/标定语料口径（内嵌 JPEG 全幅、高低 ISO 有重叠）须在报告中如实标注 |
| A14 | **F04 栅栏边界（队长实测复核后裁决，2026-09-10）** | QA 预检指出 & 队长实读确认：在途 `render/web/session.py:180-190` 的 `_check_sensitive` **对所有 `_path`/`_file` 后缀键无条件 400**（且 strict/非 strict 都执行，`:286/:289`），而 `whitebalance.warm_cal_file`（`white_balance.py:286`，默认 `DEFAULT_WARM_CAL_FILE`）与 `huesat.oklch_points_file`（`huesat.py:149`）是**仓内既有合法参数**；`service/runtime.py:401` 确实传 `validate_params=True` ⇒ **会误拒 t14 标定链既有参数，违反 §4「不得误拒既有参数」**。裁决：①**路径类键不得一律 400**，改为「**仓内包含性检查**」（解析后必须落在仓内白名单根 `configs/**`、`resources/**`、`data/**`；越界才 400）；②`stylize.lut`/`lut_path` **保持无条件 400**（本轮无 LUT 资产）；③补正向用例：`warm_cal_file`/`oklch_points_file` 取**默认仓内路径**必须放行；④错误信息引用的 `docs/STYLE_CARDS_USAGE.md` 必须真实存在（否则引导失效） |
| A15 | **A12 三层判据（QA 预检采纳）** | 「登记 ≠ 生效」。`denoise` 执行位须**三层递进**全部满足才算交付：①`DEFAULT_STAGES` + `_DOTTED_PARAM_REGISTRY` 登记；②`DenoiseStage.wants()` 真为真（非空占位）；③开启 vs 关闭**像素可观测差异**，且**默认关**时 golden `u8_max=u16_max=0`。仅满足①即判**未交付** |
| A16 | **判据修订「解耦指标」（用户 2026-09-10 批准方向）** | CR-07 原判据**不可判定**：`noise_ratio = 1 − laplacian_denoised/laplacian_raw`，而 `detail_score = laplacian_denoised` ⇒ 两指标在同一次去噪中**同源耦合**。spike 全幅实测（base noise 0.97 / detail 6.5）：bilateral 0.0 = noise↓23.6%/detail↓66.5%；bilateral 0.25 = 6.6%/58.9%；guided 0.0 = 12.2%/75.7%；gaussian 参考 = 29.7%/79.9% ⇒ **无一组满足 30%/10%**。修订为**平坦区噪声轴 ↓≥30% / 纹理区细节轴 ↓≤10% / ΔE2000 保真轴 ≤+0.5 JND** 三轴同图同 tier 同时满足（§2.2 已改写）；估算器（梯度分位阈值、核大小、形态学）必须写死可复现；并在 `docs/R21_CHANGE_REQUESTS.md` 的 CR-07 加**勘误节**（同 CR-12 手法）。**不得静默放宽**：解耦后仍不达标 ⇒ 报队长 |
| A17 | **F09/F02 在 `loop.py` 的串行约束（队长实证）** | `_DOTTED_PARAM_REGISTRY` 在 `src/pixo/pipeline/loop.py:68`（A12 要求 super-dev 在此登记 `denoise`），而 F09 亦需改 `loop.py` 的 `rect_norm_to_px`/`adopt_crop` 段 ⇒ **两流不得并行改同一文件**。裁决：`super-dev`（F02，在途）**先**完成 `loop.py` 段；`dev-geom` 的 `loop.py` 改动**暂缓**，先做 `compose.py`/`region_masks.py`/`tests/unit/**`（互不冲突），等队长通知再动 `loop.py` |
| A18 | **F09 实施方案 A′（dev-geom 侦察采纳）** | ①开关**只能落在 `compute_crop_rect` 内部**（掩码 shape 预测线 `region_masks.py:51-60` 调同一函数 ⇒ 放 ComposeStage 会让两线静默分叉）；②纯函数**默认保持 `px`**，新语义只从 `default_params` 进入；③`adopt_crop` 改写为归一化并**强制** `coord:"norm"`；④**S0：改码前先冻结基线**（零容差等式 `compute_crop_rect(coord="norm", x…) == compute_crop_rect(coord="px", x*w…)` + 既有 golden 快照）；跨 tier 相对窗容差用推界 **2.932e-3**（实测最大偏差 1.223e-3；**勿用 5e-4 级"看着紧"常数**；先例 `test_crop_wiring.py:149` 的 `1.0/min(w,h)`）；⑤补**同源守门断言**（现有测试抓不到两线不同源，须专补） |

- 队长裁决 P1/P2/P3 记录在上文 §0；其**证伪条件与备选路径**见 §0.1（用户若对 ①/②/③ 任一项不同意，按对应备选路径改范围后由 QA 重审）。

### 卡点②用户确认

- 2026-09-10：**用户批准设计（卡点②通过）**，批准形式＝选项「全部批准，开工」（含 CR-12 改判否决、CR-09 改卡参数注入、全幅口径只约束噪声类、A2 baseline 授权、DCP×6 本轮核验）。
- 放行前置齐备：`.design_ok`（`QA-checker`，修复后通过、不含用户确认，原 R21 门禁另存 `.design_ok.r21`）+ 本确认记录。
- 随之放行：**Wave1** = `dev-1`（F01+F06）+ `dev-2`（F03+F08 复核）。
