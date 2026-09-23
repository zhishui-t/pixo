# R22 设计审核报告（design-review-r22）

> 审核人：`QA-checker`（第 4 阶段：设计审核 + 现场修复）
> 被审对象：`.agent-team/design-r22.md`（原 102 行 → 修订后 132 行；LF 行尾，`git status` 对 `src/tests/frontend/configs/docs` 为空）
> 参照：`task-brief.md`（F01~F10 / 非目标 / 完成标准）、`team-manifest.md`（花名册 + 三波 + 文件域仲裁 + 门禁定义）、`exploration-r22.md`（754 行，事实依据）、`docs/R21_CHANGE_REQUESTS.md`（CR-06~CR-15 原文，含 §0 更正手法）、`DELIVERY-R21.md` + `qa-report-r21.md §7`（R21 基线 1574/0 与续排候选 #20~#27）
> ISO 时间戳：2026-09-10T23:23:49+08:00（2026-09-10T15:23:49Z）
> 边界声明：本轮 QA **未改** `src/**`、`tests/**`、`frontend/**`、`configs/**`、`docs/**`（含 `changelog.md`/`tech_debt.md`）；仅改 `design-r22.md` 并写入本报告、`.design_ok`、以及 `.agent-team/tmp-r22-qa-probe*.{py,txt}` 核验脚本/输出。

---

## 0. 审核范围与方法

1. **前提核验**：§0 的 P1~P8 逐条独立复核（**不复用 exploration 结论**，重跑探针 / 重读源码）。
2. **CR 覆盖核验**：CR-06~CR-15 逐条对照 F01~F10，查要点丢失。
3. **裁决合理性**：三项队长裁决（①否决 RP-CCM ②F04 改卡参数注入 ③全幅口径）的**反例风险 / 证伪条件 / 备选路径**。
4. **文件域互斥**：§3 文件域 + 共享文件串行约定是否真互斥、有无同波次同文件交叠。
5. **可测性/误判风险**：§4 每条判据能否运行、有无「写错断言会误判通过」。
6. **风险与遗留**：exploration §11 的 8 条遗留是否有落点，#25 `build/lib/pixo/**` 漂移是否处置。
7. **门禁可判定性**：`.r22_ok` 放行条件是否 tester/QA 可复跑判定；金样本「零漂移」与 F09「新增 compose case」是否自洽。

核验手段：只读源码定点复核 + 4 个独立 Python 探针（指标层级/tier 敏感性/断言行号/许可台账/decide 口径/gate case 覆盖）+ 2 份 A/B 报告原文对拍。**未跑真 RAW 全渲染**（红线：单次 ≈73s 且须串行）。

---

## 1. 前提核验（§0 P1~P8）—— 8/8 成立，其中 2 条证据/表述需更正

| 前提 | 结论 | 独立证据（QA 本会话复得） |
|------|------|--------------------------|
| **P1** CR-12 证据翻转 | ✅ **成立**（数字逐项对上） | `.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md:12-17` = A 6.151/16.732、B 5.675/16.239、**B−A −0.475（−7.7%）**、`:77` 结论 45/54；`.artifacts/..._20260904_235522.md:12-17` = A 5.946/15.928、B 7.093/16.711、**+1.147（+19.3%）**、`:77` 结论 **22/54**；`git show --stat 3fbe56d` 确认 `configs/color/rp_ccm_nikon_z5_2.json` 同批变更（09-04） |
| **P2** 0 个 `.cube` + `/api/styles` 已存在 | ✅ **结论成立，但行号错**（已修 D1） | glob `**/*.cube,*.3dl,*.look` = **0**；`configs/**/*.json` 含 `lut_path` = **0**；`configs/styles/films/*.json` = 25，样卡 `stylize: {}`；端点实为 `app.py:338`(`/api/styles`)/`:352`(`/{style_id}`)——**原稿 `app.py:292-314` 实为 auto-loop/timeline/decide 端点**；前端 `client.ts:138-149`、`useAppStore.ts:391`(原稿 389)、`StyleAiPanel.tsx:16-26` |
| **P3** 噪声指标 tier 依赖 + 512 排序非单调 | ✅ **完全复现**（无需标注「未独立复核」） | 独立探针（rawpy 内嵌缩略图 + `pixo.vision.measure.measure_sharpness`，四档 512/1024/2048/6048）逐值复现 exploration §2.3 表：`noise_ratio` DSC_5314 0.2837/0.4678/0.8156/**0.7416**、DSC_5278 0.5512/0.4749/0.5887/**0.6139**、DSC_5236 0.6680/0.7110/0.7140/**0.5211**、DSC_5241 0.1427/0.1887/0.3602/**0.4137**；512 tier 最高者是 ISO1600(0.6680) 而非 ISO12800(0.2837)；全幅恢复 ISO 单调；`detail_score` 512→全幅 58.69→2.21（**26.6×**） |
| **P4** F08/CR-13 已交付 | ✅ 成立 | `tests/unit/test_skin_oklab.py:354`（IEEE754 逐位 ==）、`:386`（angle↔deg）；`gate_cases.py:28` 含 `skin_oklch`/`skin_oklch_softband`，`:257`/`:264` 分支齐备 |
| **P5** #17 迁移面 ≈0 + gate 无 compose case | ✅ 成立 | `gate_cases.py` 全文 `compose` 命中 **0**；`region_masks.py:36`/`:48`/`:51` 确为同源 `compute_crop_rect`；`configs/**`/`resources/**` 含 `"compose"` = 0 |
| **P6** NLM 不可用 | ✅ 成立（采信实测；本地复跑算子计时未做，代价量级与源码实现一致） | exploration §1.3 实测表；`refine.py:333-366` 现用 GaussianBlur 路径与之自洽 |
| **P7** #12 前置已满足 | ✅ 成立 | `engine.py:222`（`cond.get("all")`）、`:384`（`elif op == "between"`）；首例 `tone_clarity_rules.yaml:36-39`（注释明写「护栏④日落条款首例 (t60)」） |
| **P8** #3 断言 no-op | ✅ 成立，**但表述需收紧**（已修 D2） | `test_tech_debt_invariants.py:92-102` 只查 `("path","local_path","file")`；根 `model_licenses.json` 6 条**全部用 `files` 键**——但**只有 `aesthetic_scorer.pt` 有 1 条路径，其余 5 条 `files: []`**；`vision_models.json` 2 条用 `path_or_source`（`$GUANLAN_ROOT/...`），与 `files` 不同键 |

**新增/更正的事实（原设计未覆盖）**：

- **F-新增-1（重要）**：闭环 decide 只吃 **preview** measurement —— `loop.py:1322 measurement = self.measurer.measure(...)`（迭代内）→ `:1371 metrics = _metrics_for_decide(measurement)`；全幅 `full_measurement` 在 `:1700`（供 `_qc_outcome`）。生产 `preview_long_edge` 缺省 **1024**（`runtime.py:795`），**不是 512**（exploration §8.1 的「preview_long_edge=512」不准确）。⇒ F01 噪声规则的阈值口径与作用面必须显式写死（已修 D4/§2.1）。
- **F-新增-2**：仓内已存在**另一条风格卡链** —— `SinglePhotoLoop.enable_style_cards` / env `PIXO_STYLE_CARDS`（`loop.py:742`/`:831-852`，R13 裁决缺省关，内置 6 卡→decide 规则）。F04 若不明示「本轮只做参数注入、该链保持关闭」，存在两条卡源叠加改判定的风险（已修 D5/§2.3）。
- **F-新增-3**：`apply_rp_ccm` 在 `src/` 命中 4 处，**全部在 `render/core/rp_ccm.py` 自身**（定义/`__all__`/docstring），渲染链 0 调用点 —— 否决后的「运行时零接入」判据应按此措辞（已修 D20）。
- **F-新增-4**：#25 漂移**实测确认**：`build/lib/pixo/render/core/skin.py:183-191` = `A=0.01516/MAJOR=0.045692/ANGLE=0.191122/SOFT_BAND=0.25`，而 `src/pixo/render/core/skin.py:188-196` = `0.015127/0.049594/0.196323/0.31`（mtime 2026-09-04）。

---

## 2. CR 覆盖核验（CR-06~CR-15）

| CR | 原文要点 | 设计落点 | 判定 |
|----|----------|----------|------|
| CR-06 | 噪声/细节入键宇宙 + 1 条阈值规则 | F01（§1/§2.1，4 处改动点 + 规则适用面） | ✅ 覆盖（阈值口径已补死） |
| CR-07 | 亮度降噪 native + Python 回退；`luminance_strength`/`detail_preserve`；按 `noise_ratio` 自适应；**默认值须 A/B 裁决后才可开启**；DLL +1 + 快照对拍；A/B ≥20 张 | F02（§1/§2.2/§4 降噪专项） | ✅ 覆盖（A/B 口径、串行、旧 DLL 备份已补） |
| CR-08 | **分级**：关键路径 warning + 结构化 degraded；纯回退维持现状 | F03（13 条 vs 119 条；区分版本门拒绝/真异常；health 暴露 + warmth_curve 破坏性验收） | ✅ 覆盖（分级保留） |
| CR-09 | `style.lut_path` 白名单 + `/api/styles/films` + 前端简约选择器；越界拒绝 | F04（口径修正为**卡参数注入**，复用既有 `/api/styles`；白名单/栅栏；`lut_path` 一律 400） | ✅ 覆盖（口径修正属 §0 P2 裁决，见 §3） |
| CR-10 | 场景预设路径（与 CR-09 合并或紧随） | F05（`apply_scene_preset` + 6 id 白名单 + 前端同组件） | ✅ 覆盖 |
| CR-11 | 多轴 QC；**分级**：硬门禁只像素/溢出，其余软告警；美学阈值**不得**硬门禁；**不改变既有 ACCEPT/REJECT** | F06（3 处落点 + 硬门禁仍 `:81` 阈值；§4 QC 判据明写「不改变判定」） | ✅ 覆盖（红线与「不改变既有判定」双落点） |
| CR-12 | 切换或显式否决，禁止悬置 | F07（选 B + 勘误节 + 结论落档 + 运行时零接入） | ✅ 覆盖 |
| CR-13 | 一致性单测 + 1 个金样本 case | F08（复核销账；不新增实现） | ✅ 覆盖（已交付判定，见 §9 需队长确认口径） |
| CR-14 | 推送远端 | — | ✅ 不属 R22（R21 已交付） |
| CR-15 #3 | a) aesthetic「需核验」+旧路径 vs MIT；b) segformer 自相矛盾；c) **DCP×6 再分发** | F10（a/b 覆盖；**c 原缺失 → 已补 D7**） | ⚠️ 补齐后 ✅ |
| CR-15 #7 | 感知门禁提案 | F10（提案） | ✅ 覆盖（exploration §9.2 已列复用资产，建议提案引用 `pipeline/perceptual.py` 单源 ΔE2000） |
| CR-15 #10 | 重复编号重排 | F10（+ 影响面 `:134` 起后续 +1 至 `:333`，不动外部引用编号，核对 R21 续排 #20~#27 → D21） | ✅ 覆盖 |
| CR-15 #12 | 公式守卫（前置陈述陈旧） | F10 + §0 P7（日落关闭） | ✅ 覆盖 |
| #17（独立战役） | px→相对归一化 + 存量迁移 + legacy 开关 | F09（B1 全幅归一化 + `compose.coord` + 用例有意翻转 + 补 gate case + docs 更正） | ✅ 覆盖（迁移面≈0 已实证） |

**范围覆盖结论**：仅 CR-15 #3 的 DCP×6 一项要点丢失（已补），无其他 CR 要点丢失；F-ID 与 CR 的映射无孤儿（F01~F10 全部有 CR 归属）。

---

## 3. 三项裁决的反例风险与证伪条件

### 裁决① F07 改判「显式否决」（有数据支撑）
- **反例风险**：A/B 报告口径若与运行时会不一致（例如 B 轨用的系数不是生产加载位）就会误判。已核：`scripts/eval_rp_ccm_ab.py:73 --ccm-dir default="configs/color"`（生产位），两份报告语料/脚本/DCP/指标口径完全同源（报告头逐行一致），唯一变量是 09-04 换表 ⇒ 翻转成立。
- **残余风险**：门槛线第 4 项（≥2 相机）**本机物理不可达**（只有 nikon_z5_2 语料）；`stage2_adopt_eval_A.md:221` 报的 3/4 通过用的是 `calib_out/rp_ccm_by_group.json` 的另一套系数（不在生产链）。
- **处置**：design 已补 §0.1 证伪条件（出现中性语境 median 改善 ≥15% 且 p95 不劣化的新 A/B ⇒ 回退重议）与备选路径（切换＝独立战役，本轮不接）。**建议队长在 DELIVERY-R22 登记「触发条件：阶段三分簇门控 / ≥2 相机语料」。**

### 裁决② F04 改「卡参数注入」
- **反例风险**：若用户坚持 CR-09 原文 LUT 口径，仓内**无资产可指**（0 个 `.cube`；外置 LUT 目录指向仓外 `guanlan/luts`），照原文实现 = 死代码 + 无法验收。design §0.1 已给备选路径（自产 `.cube` + 机制层栅栏 `core/lut.py:90` + 资产许可登记，+≈0.5 人日）。
- **新增风险（已补 D5/§5）**：`update_params` 白名单若**不从各 stage `param_schema` 派生**，会误拒既有前端调整参数 ⇒ 全量回归红/功能回退。design 已把「派生」写成硬约束并加正向用例要求。

### 裁决③ 钉死「导出全幅」口径
- **反例风险 A（已修 D8）**：原文写「门禁与 A/B **一律**全幅」，字面会**误废 F07 的 512-tier ΔE 证据**（两份 A/B 报告均在 `long_edge=512` 产出），自相矛盾。修订后适用范围收窄为**噪声/细节类指标**，色彩 ΔE 沿用 512 并明写「不得据此宣布 F07 证据无效」。
- **反例风险 B（已修 D4/§2.1）**：闭环 decide 只吃 preview（1024）⇒ 若 F01 规则按全幅阈值在闭环内生效，必然误触发/不触发。修订后显式写死：F01 规则本轮**默认关且在闭环内不生效**，适用面 = 全幅 QC/导出判定；未来闭环启用须按 `preview_long_edge` 单独标定。
- **证伪条件（已补 §0.1）**：若全幅口径下 `noise_ratio` 失去噪声区分度（ISO 排序不复现）⇒ 改判。QA 独立实测：全幅排序 0.7416 > 0.6139 > 0.5211 > 0.4137（随 ISO 降序），**证伪条件当前不成立**，裁决③ 站得住。

---

## 4. 文件域互斥核验（§3）

| 检查项 | 结论 |
|--------|------|
| `pipeline/loop.py` W1 独占 | ✅ W1 dev-1 独占 + W3 仍归 **dev-1**（同人，无并行冲突），已在串行约定第 5 条写明 |
| `service/runtime.py` 跨波次 | ✅ W1 dev-1（QC payload 段）→ W2 dev-3（参数装配段），不同波次天然串行 |
| `gate_cases.py` 串行 | ✅ W3 dev-1 加 case → tester 复核 + 生成 baseline（队长授权） |
| `docs/` 归属（**原稿冲突，已修 D12**） | 原 W2 dev-3 域写「`docs/`（新能力用户说明）」过宽，与 dev-2（`tech_debt.md`/`R21_CHANGE_REQUESTS.md`）及队长（`changelog.md`）冲突；修订为「**仅新增** F04/F05 用户说明文件，明确排除 `changelog.md`/`tech_debt.md`/`R21_CHANGE_REQUESTS.md`」；`docs/架构设计文档.md` 的 F09 更正段划归 W3 dev-1 |
| W1/W2 内跨文件交叠（**原稿未写，已修 D14**） | 发现 3 处跨波次同文件：`refine.py`（W1 dev-2 except → W2 super-dev 内核）、`reshape.py`（W1 dev-2 clarity except → W2 super-dev DenoiseStage）、`web/session.py`（W1 dev-2 解码 except → W2 dev-3 栅栏）。已在串行约定逐条列明「先列者先做」；W1 内 dev-1/dev-2、W2 内 super-dev/dev-3 无同文件交叠 |
| 前端域 | ✅ 归 dev-3；`frontend/src/**` 与 QA/reviewer 无交叠 |
| 测试域 | ✅ 各开发流只新建自己的测试；`tests/regression/**` 归 tester |

---

## 5. 可测性 / 误判风险核验（§4 逐条）

| 判据 | 可运行？ | 误判风险 | 处置 |
|------|----------|----------|------|
| 全量回归 ≥1574/0 | ✅ `pytest tests -q -m "not e2e"` | 「≥」下限可能被用例删减掩盖 | 已补「核对用例增量」 |
| 金样本零漂移 | ⚠️ 与 F09 新增 case **不自洽** | 新增 case 无 baseline，必须**首次生成**；原稿把「零漂移」与「21 features 不变」混写 | 已拆为两行：既有 21 features 逐位零漂移（`u8_max=u16_max=0`）+ 新 case 首次生成须**队长书面授权**（D15） |
| 降噪 A/B | ✅（须串行） | **before/after 必须同图同 tier**，否则 `detail_score`（26× 分辨率敏感）不可判；欠曝帧 EV 干扰 | 已补「同图、同 tier（全幅）、仅 denoise 开关差异」+ 串行 + 记 EV（D9） |
| 几何专项 | ✅ | 翻转断言若写成「掩码不相等」＝另一侧错误钉死 | 已补「**不得**简化为『掩码不相等』」（D11） |
| 安全（F04） | ⚠️ 原稿要求「越界 `lut_path` → 400」但 §2.3 说 `lut_path` 仅登记扩展位 | 死代码/无法验收 | 已明确「本轮 `lut_path` 不在白名单 ⇒ **一律 400**」，判据与口径自洽（D10） |
| 可观测（F03） | ✅ 写坏 `warmth_curve.json` → degraded 条目 | — | 保留（`white_balance.py:146-159` 是最现成靶子） |
| QC（F06） | ✅ `soft_warnings` 出现且判定不变 | — | 保留 |
| 台账（F10） | ⚠️ 「改查 `files[]` 后能被证伪」**只对 1/6 条成立** | 改完仍近乎空转 | 已补「须同时要求声明有仓内文件的条目非空」+ `path_or_source` 解析规则（D2/D16） |
| **F01/F05/F07/F08 原无判据** | — | `.r22_ok` 覆盖不到这 4 个 F-ID | 已补 4 行判据（D15） |

---

## 6. 风险与遗留核验

- **exploration §11 的 8 条**：#1 build/lib 漂移 → 已补入 F10/§5；#2 `rect_px_to_norm` 零调用 → 已补入 §2.4（可复用为迁移工具）；#3 `docs/架构设计文档.md:384-393` legacy `crop` px 示例 → 已补入 F09/§2.4 并指定归属（W3 dev-1）；#4 CR-12/#12 事实陈旧 → 已由 §0 P1/P7 + F10 勘误覆盖；#5 口径差（27 卡/132 处 except）→ 属文档口径，**未纳入本轮**（建议 DELIVERY-R22 备注）；#6 `resources/dcp/manifest.json` DCP×6 未逐项核验 → 已并入 F10 #3（D7）；#7 `films/README.md:44` 表格串行 → 文档瑕疵，**未纳入**；#8 `calib_out` 系数地位 → 已由 §0.1① 备选路径承接。
- **#25 `build/lib/pixo/**` 漂移**：QA 已实测确认（见 §1 F-新增-4）。原 design **完全未提**，本轮已补 F10 处置行 + §5 风险行；**是否本轮清理仍需队长裁决**（§9-A4）。
- 残余未纳入项（2 条文档级）已在 §9 备查，不算阻塞。

---

## 7. 修订 diff 摘要（对 `design-r22.md` 的 21 项修订点 / 20 次定点编辑；D15+D16 同属 §4 表的一次替换）

| # | 位置 | 原句（摘要） | 新句（摘要） | 依据 |
|---|------|--------------|--------------|------|
| D1 | §0 P2 证据列 | `app.py:292-314` 两个 styles 端点；`client.ts:138-147`、`useAppStore.ts:389`、`StyleAiPanel.tsx:20` | `app.py:338`/`:352`；`client.ts:138-149`、`useAppStore.ts:391`、`StyleAiPanel.tsx:16-26`（原稿 292-314 实为 auto-loop/timeline/decide 端点，已更正） | 探针 1/3 |
| D2 | §0 P8 证据+处置 | 「6 条全部用 `files[]`」 | 「`files` 键 6/6 命中，但**仅 1 条有路径、5 条 `files: []`**；`vision_models.json` 用 `path_or_source`」；处置加「须同时要求声明有仓内文件的条目非空」「另定环境变量解析规则」 | 探针 1/3 |
| D3 | §0 表后 | （无） | **新增 §0.1**：三项裁决的证伪条件 + 若用户不同意时的备选路径 | 清单 3 |
| D4 | §1 F01 备注 | `metrics.py:76-89` 展平；无适配面 | `metrics.py:78-89`；**规则适用口径 = 全幅**，闭环只吃 preview（`loop.py:1322`→`:1371`），`preview_long_edge` 缺省 **1024**（`runtime.py:795`） | F-新增-1/2 |
| D5 | §1 F04 备注 | 白名单 + 目录栅栏 | 白名单须由 `param_schema` **派生**；`lut_path` 一律 400；既有 `PIXO_STYLE_CARDS`/`enable_style_cards` 保持关闭 | 新发现 |
| D6 | §1 F09 备注 | 「约 10 处测试同步」 | 精确清单（`test_gate_compose.py:81/92/118/135/149`、`test_decide_region_wiring.py:488/491/514`、`test_loop_e2e.py:69`、`test_region_masks_channel.py:142/651`）+ 语义中性项 + docs 更正 | 探针 4 |
| D7 | §1 F10 备注 | #3（无 DCP×6）、#7/#10/#12 | #3 加 **DCP×6 再分发核验**；#10 影响面（`:134` 起 +1 至 `:333`）；新增 **#25 登记处置** | CR 原文 :123 |
| D8 | §2.1 | 「门禁与 A/B **一律**用导出全幅」 | 收窄为「适用范围 = 噪声/细节类指标」；新增「色彩 ΔE 沿用 512，不得据此宣布 F07 证据无效」+ 闭环 preview 段落 | 清单 3/5 |
| D9 | §2.2 | A/B 单行口径 | 新增「重建前备份旧 DLL」；A/B 改「**同图、同 tier（全幅）、仅开关差异**」+ **严格串行单进程** + 记 EV | 清单 5 |
| D10 | §2.3 | 白名单 + 目录栅栏 | 白名单派生；`lut_path` 不在白名单 ⇒ 一律 400；与既有决定卡源划界；场景预设同组件 | 清单 5 |
| D11 | §2.4 | `adopt_crop`（`loop.py:1635`）、`compute_crop_rect`（`compose.py:222`）；测试约 10 处 | `adopt_crop` 段 `loop.py:1612-1652`（写回 `:1633-1640`）、`compute_crop_rect`（`compose.py:63`）；新增**默认路径零变化证据**段；翻转断言「**不得**简化为掩码不相等」；gate case baseline 首次生成 | 探针 1/2 |
| D12 | §3 W2 dev-3 | `scene_apply.py`（如存在）… `docs/`（新能力用户说明） | `scene_apply.py`（实测存在 `apply_scene_preset:47`）；`docs/` 收窄为「仅新增 F04/F05 说明，不含 changelog/tech_debt/R21_CHANGE_REQUESTS」 | 清单 4 |
| D13 | §3 W3 dev-1 | loop.py（`rect_norm_to_px`/`adopt_crop` 段） | 加 `rect_px_to_norm`、加 `docs/架构设计文档.md`（仅 F09 更正段） | 清单 6 |
| D14 | §3 串行约定 | 2 条 | 6 条（补 refine.py/reshape.py/session.py 跨波次序 + loop.py 独占 + gate_cases→tester）+ 「W1/W2 内无同文件交叠」 | 清单 4 |
| D15 | §4 门禁表 | 金样本 1 行；无 F01/F05/F07/F08 | 金样本拆两行（既有 21 features / 新 case 首次生成须队长授权）；新增 F01/F05/F07/F08 四行；安全/台账行改写 | 清单 5/7 |
| D16 | §4 台账行 | 「改查 `files[]` 后能被破坏性测试证伪」 | 加「**且要求声明有仓内文件的条目非空（否则 5/6 条仍空转）**」+ `path_or_source` 解析规则 + DCP×6 处置 | 探针 1 |
| D17 | §5 风险表 | 5 行 | 10 行（补：裁决③ 误读风险、白名单过严、build/lib 漂移、A/B 时间内存；F09 行补「生产缺省逐位不变已证」） | 清单 3/5/6 |
| D18 | §7 | 「队长裁决 P1/P2/P3 已在上文 §0 记录」 | 加「证伪条件与备选路径见 §0.1；用户不同意时按备选路径改范围后由 QA 重审」 | 清单 3 |
| D19 | §0 P3 处置 | 「唯一口径」 | 加「（限噪声/细节类指标，见 §2.1）」 | 防误读 |
| D20 | §4 F07 行 | `grep -r apply_rp_ccm src/pixo/render` = 0 | 措辞更正为「`src/` 命中仅 `rp_ccm.py` 自身（定义/`__all__`/docstring），渲染链 0 调用点」 | F-新增-3 |
| D21 | §1 F10 备注 | 「核对 R21 续排 #20/#21」 | 「核对 `qa-report-r21.md §7.2` 的 **#20~#27**」 | 探针 7 |

**修订原则**：只补事实/口径/归属，不改 F-ID 划分、不改三波结构、不改非目标（§6 未动）、不新增功能范围。

---

## 8. 复核结论

- 修订后**逐项复核通过**（重读全文 132 行 + 探针复验）：§0 前提 8/8 成立、§0.1 三条备选路径齐备、§1 的 F-ID 与 CR 映射无遗漏（含 DCP×6）、§2 四处关键约定可判定（A/B 同图同 tier、翻转断言为相对量、白名单派生、默认路径零变化有证据）、§3 文件域同波次无交叠且跨波次均有序、§4 覆盖 F01~F10 且每条均可用 pytest/脚本复跑判定、§5 风险含新增 5 类、§7 与 §0.1 联动。
- **未通过项：0**；**阻塞项：0**。
- 需队长裁决/确认 **7 项**（见 §9），其中 **A2/A5/A6 建议在卡点②与用户一并确认**（涉及门禁授权、白名单强度、F01 规则适用面）。
- 门禁：`.design_ok` 已落盘（**不含用户确认**）。按工作流第 5 阶段，`.design_ok` + 卡点②用户确认齐备后方可开工第 6 阶段。
- **一句话结论**：**修复后通过** —— 前提 8/8 独立复核成立（P3 已完全复现、P2 行号/P8 台账覆盖面两处证据经修订更正），CR 覆盖仅 CR-15 #3 的 DCP×6 一处丢失已补齐，三项裁决均补上证伪条件与备选路径，§4 补全 F01/F05/F07/F08 判据并把金样本判据与 F09 新增 case 拆开，无阻塞项。

---

## 9. 需队长裁决清单（架构级 / 范围级 / 口径级）

| # | 级别 | 事项 | QA 建议 | 影响 |
|---|------|------|---------|------|
| **A1** | 口径级 | 裁决③ 适用范围收窄为「噪声/细节类指标」，色彩 ΔE A/B 沿用 512（否则 F07 的否决证据被自身口径废除） | 接受修订（否则须用全幅重跑 RP-CCM A/B，属新增工作量） | 影响 F07 结论合法性 |
| **A2** | 流程级（**卡点②一并确认**） | F09 新增 compose gate case ⇒ 金样本 baseline **首次生成**须队长书面授权（谁执行、落盘位置、留证方式） | 由 tester 生成、队长授权并存 `.artifacts/` 证据；既有 21 features 走 `--check` 零漂移 | 门禁授权链 |
| **A3** | 范围级 | CR-15 #3 的 **DCP×6 再分发**是否纳入本轮（`resources/dcp/manifest.json` 尚未逐项核验，`THIRD_PARTY_NOTICES.md:161-162/232` 记「未核验」） | 纳入 F10（读一次 manifest + 给结论），或明确登记为 R23 | 发布前必收项 |
| **A4** | 范围级 | #25 `build/lib/pixo/**` 旧副本漂移（实测旧 OKLab 常数 + `loop.py` 旧实体）处置口径：本轮清理 / 明确排除 / 登记 R23 | 建议本轮至少**明确排除**（.gitignore/打包配置说明），避免打包误取 | 打包正确性 |
| **A5** | 口径级（**卡点②建议确认**） | `update_params` 白名单强度：严格「未知键 400」可能影响既有 PUT `/params` 调用方（前端调整面板、agent suggestion、`adopt_crop` 内部写） | 白名单由 `param_schema` 派生 + 仅对**敏感面**（路径类/新 stage）严格，保留既有键；正向用例覆盖既有参数可写 | 回归/前端功能 |
| **A6** | 口径级（**卡点②建议确认**） | F01 噪声规则「适用面 = 全幅、闭环内不生效（默认关）」是否接受；若要求闭环内可触发，须新增 preview 阈值专项标定（范围+工作量） | 接受「本轮不承担闭环触发职责」 | 范围与工作量 |
| **A7** | 进度级 | 降噪 A/B 全幅串行总时长 ≈ 32 张 × 2 轮 × 73s ≈ **78 min**（不含预热与算子对比）；须与 pytest 严格错峰 | 接受；A/B 输出落 `.artifacts/`，报告记 EV | 测试排期 |

**备查（未纳入本轮，属文档级）**：① `configs/styles/films/README.md:44` 表格单元格串行；② `task-brief.md:35` 语料计数 3428 vs 实测 765、brief「131 处 except」vs 实测 132、「25 张卡」vs 目录 27 个 JSON —— 建议 DELIVERY-R22 备注口径。

---

## 10. 附：独立核验证据（命令 → 输出落盘）

| 证据 | 命令 | 输出 |
|------|------|------|
| 资产/端点/台账/断言/行号 | `python .agent-team/tmp-r22-qa-probe.py` | `.agent-team/tmp-r22-qa-probe.txt`（228 行） |
| 关键落点上下文（loop/runtime/presets/rules/reshape/lut/store/panel） | `python .agent-team/tmp-r22-qa-probe2.py` | `.agent-team/tmp-r22-qa-probe2.txt`（160 行） |
| app.py 端点实况 / scene_apply / tone_clarity / measure / runtime payload / A/B 报告 tail / abi.cpp / 许可台账逐条 | `python .agent-team/tmp-r22-qa-probe3.py` | `.agent-team/tmp-r22-qa-probe3.txt`（321 行） |
| 闭环 decide 口径 / enable_style_cards / 测试 free px 硬编码 / docs legacy crop | `python .agent-team/tmp-r22-qa-probe4.py` | `.agent-team/tmp-r22-qa-probe4.txt`（285 行） |
| **P3 独立复现**（四档 tier + 单调性） | `python .agent-team/tmp-r22-qa-probe5.py` | `.agent-team/tmp-r22-qa-probe5.txt`（27 行，数值与 exploration §2.3 逐位一致） |
| `apply_rp_ccm` 调用点 / R21 续排 #20~#27 | pwsh Select-String + `qa-report-r21.md` 读取 | `.agent-team/tmp-r22-qa-probe6.txt` |
| **#25 漂移实测**（build/lib vs src 常数） | pwsh Select-String 两文件 | `.agent-team/tmp-r22-qa-probe7.txt` |
| A/B 报告对拍 | pwsh `Get-Content` 两份报告首尾 | `.agent-team/tmp-r22-qa-p1.txt` |

> 说明：以上探针脚本/输出均落 `.agent-team/`，仓库源码/测试/前端/配置/文档零改动（可用 `git status` 复核）。
