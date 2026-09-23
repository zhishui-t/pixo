# 设计审核报告（design-review）— Pixo 第九轮战役

> 审核人：qa（2026-09-07）。被审对象：`.agent-team/design.md`（队长 2026-09-07 执笔）。
> 方法：六固定维度逐项过 + 代码抽查验证设计的删除面/接线点/计数是否与实际代码一致
> （抽查文件清单见 §8）。发现问题直接修订 design.md 并复验，修复三要素见 §7。

## 1. 需求覆盖（task-brief F01~F20 逐项对照）

| F-ID | design 落点 | 结论 |
|------|-------------|------|
| F01 | §2 F01/F20 changelog（历史批） | 覆盖，格式/不编造纪律明确 |
| F02 | §1 门禁流（qa） | 覆盖（执行型任务，无 §2 小节必要；Wave1 含 F02） |
| F03 | §2 F03 | 覆盖，删除面经抽查逐行核实（§8） |
| F04 | §2 F04 | 覆盖；pyproject 前提有事实错误已修（§7 修复 1） |
| F05 | §2 F05 | 覆盖，三选一决策路径+裁决人明确 |
| F06 | §2 F06 | 覆盖；命令与工具 docstring 多样本 compare 用法逐字一致 |
| F07 | §2 F07 | 覆盖；skin 计数口径不一致已修（§7 修复 4） |
| F08 | §2 F08 | 覆盖，17→18→19 增量与时序互斥明确 |
| F09 | §2 F09 | 覆盖；文件路径错误已修（§7 修复 2） |
| F10 | §2 F10 | 覆盖，4 项验证链+revert 单点；缺省断言计数口径已精化（§7 修复 5） |
| F11 | §2 F11 | 覆盖，只出证据不切换（合任务书非目标） |
| F12 | §2 F12 | 覆盖；order 56-59 槽位空闲已实测（skin=55/stylize=60） |
| F13 | §2 F13 | 覆盖，spike 先行+双线一致+缓存失效 |
| F14 | §2 F14 | 覆盖；engine 路径已消歧（§7 修复 7） |
| F15 | §2 F15 | 覆盖；samples.py 路径错误已修（§7 修复 3） |
| F16/F17 | §2 F16/F17 | 覆盖；PyYAML 硬依赖建议 qa 已代复核确认（§7 修复 8） |
| F18 | §2 F18 | 覆盖，不做决策留用户 |
| F19 | §2 F19 | 覆盖（可选，降级路径明示） |
| F20 | §2 F01/F20（本轮批） | 覆盖，时序 qa-final 后 |

结论：**F01~F20 全覆盖**，非目标（skin/colorcal 切换、#7 实施、#2 重写、#13.3/13.4、LLM e2e）均未被越界纳入。

## 2. 可测性

每个 F 节均带「完成标准」，抽查关键项：
- F03/F04：grep 零命中 + 定向测试绿（可执行判定）✓
- F06：compare 命令 + 逐 case 结果落盘 ✓
- F07：新不变量 + 渲染逐位不变两路验证（dev-2 选实现留证）✓
- F10：4 项验证链（全量/卡 golden 前后一致/RAW 复跑/缺省分派基线 v2）✓
- F12：合成掩码数值断言 + enabled=False 零影响 + wants 门控 ✓
- F14：mock 掩码→decide 写键→像素变化闭环断言 ✓
结论：**通过**。F05 为调查型任务，完成标准=证据+建议+裁决，符合任务书「应有」定位。

## 3. 边界与异常

- F04：未知/未命中 prompt → 零掩码+warn-once；「全部组后端不可用→上抛 manual_review」
  escalation 路径保留给真实后端故障——语义边界清晰，且审核补充了该语义变化的风险登记（§7 修复 9）。
- F06：样本缺失 vs 真漂移两类 FAIL 区分处置、真漂移阻断 F10 ✓
- F10：revert 单点回滚 + 行为级 fail 逐项分析上报出口 ✓
- F12：掩码缺失 wants=False 静默跳过、无 regions wants=False ✓
- F13：spike 可行/不可行两分支 + tier 口径教训显式引用 ✓
结论：**通过**（F04 语义变化经补强后充分）。

## 4. 接口与文件域

- design §3 与 team-manifest「文件域仲裁」交叉核对：gate_cases.py 时序互斥（F08 先/F15 后）、
  loop.py 分区（super-dev backend/state_extras vs dev-3 registry/_apply 区）、三域
  （vision/styles+modules/region）全部一致 ✓
- F12 接线点实测核对：DEFAULT_STAGES `[..., "split_tone", "skin", "stylize", "refine"]`
  「skin 后 stylize 前插」成立；params.py STAGE_CLASSES 存在（dehaze 先例 :35）；
  dehaze enabled=False 先例 = reshape.py DehazeStage `default {"enabled": False,...}` ✓
- F13 接线点实测核对：loop.py:336-338（合成注入）/ :397-399（raw preview 传
  state_extras）/ :403-407（render_full **确无** state_extras → export.py:30
  _render_full_quality）缺口描述准确；session.py:321-322 注入点、:345-346 state_fp+
  _ndarray_digest 缓存指纹描述准确 ✓
- F14 接线点实测核对：_DOTTED_PARAM_REGISTRY=loop.py:66-72、_apply_decide_params=:531-568、
  dehaze enabled 联动=:553-556、flatten 键=:450-480 全部命中 ✓
结论：**通过**。观察项（不阻断）：manifest 文件域表未列 src/pixo/agent/**（F09）与
src/pixo/decide/**（F14 规则），本轮各仅单一 owner 触碰无冲突，如并发需队长补域。

## 5. 风险登记

原 5 项风险均有等级+缓解；审核补 1 项（F04 未知 prompt 语义变化，见 §7 修复 9）。
额度纪律、reviewer 深度兜底、F10/F13 双高危缓解链（金样本先行/revert 单点/spike 先行）充分。

## 6. 与评估报告（t52 oklch_default_eval）一致性

- 三道前置修补忠实映射：a→F07（卡级锚定）、b→F08（分派级守卫+卡 golden）、
  d→F09（patch_protocol 同源+canonical 透出）；c→F10（第一批 hsl+split_tone）+F11（skin/colorcal 先 A/B 不切换）✓
- F10 前置时序（F06/F08/F09 后）合 t52 §5 顺序 ✓
- 「金样本 0 张需重生成=守卫盲区」的诊断与 F08 补 case 的对策对齐 ✓
- 两处与 t52 数字的关系已在校订中理清：t52 §3.2 计数是 24 卡/f4a51db 前口径（design 已按
  23 卡实测更新并注明口径）；t52 §3.4 的 5 项缺省断言是四阶段全翻口径（F10 只翻两个
  stage，实际红 4 项——design 已精化，防 dev-2 误改不红的 skin 断言）✓

## 7. 修复记录（改了什么 / 为什么 / 怎么验证）

1. **F04 pyproject 前提纠错（重要）**
   - 改了什么：design.md F04 pyproject 条目由「核实是否 gsam 专用——rfdetr/segformer/sapiens/uniface 均走 onnxruntime；若专用则删除该 extras」改为「保留不删」+逐文件实测证据。
   - 为什么：原前提与代码事实相反——grep 实测 torch/transformers 直接懒 import 于 segformer_scenes.py:47-48 / uniface_face.py:40-41 / sapiens_body.py:171-172，aesthetic.py:148-150（CLIP）亦依赖；rfdetr 走 rfdetr pip 包（自带 torch 链）。照原文执行会误删仍被四个后端依赖的 extras。
   - 怎么验证的：`grep -rn "import torch|from transformers" src/` 全列 + 逐文件 Read 确认为真实懒 import（非注释）；rfdetr_person.py Read 确认 `from rfdetr import RFDETRSeg2XLarge`。
2. **F09 文件路径纠错（重要）**
   - 改了什么：`src/pixo/pipeline/patch_protocol.py` L105-111 → `src/pixo/agent/patch_protocol.py` L118（`band.get("domain","hsv")` 硬编码行；L104-117 为 docstring/入口）。
   - 为什么：原路径文件不存在（pipeline/ 下无此文件），dev-2 照路径会找错模块；硬编码实际在 :118 非 :105-111。
   - 怎么验证的：`find src -name patch_protocol.py` 命中 agent/；Read :100-135 确认 `str(band.get("domain", "hsv"))` 在 :118。
3. **F15 文件路径纠错（重要）**
   - 改了什么：`harness/goldens/samples.py`（:170-171）→ `src/pixo/harness/goldens/samples.py`（:168-171）。
   - 为什么：仓库根 harness/ 不存在该文件；真实路径在 src/pixo/harness/ 下。
   - 怎么验证的：`find . -name samples.py` 唯一命中 src/pixo/harness/goldens/samples.py；Read :168-171 确认 regions 键展开在此。
4. **F07 skin 计数口径统一（重要）**
   - 改了什么：「带 skin 参数的 17 张」→「带 skin 键的 22 张（实测 22 张带键、其中 17 张 enabled=true），钉域口径统一为凡带键即钉」；不变量表述同步（L92→L93 顺带校准）。
   - 为什么：原句式「凡带 X 参数的」与 17 这个数自相矛盾（实测带 skin 键=22、enabled=true=17）；按「凡带键即钉」口径不变量测试无特例、未来启用 skin 的卡即时受保护，且与 hsl/split_tone/colorcal 三键口径一致。
   - 怎么验证的：python 脚本全量解析 25 张卡 JSON 实测：legacy 23 张、hsl 12、split_tone 12、skin 键 22（enabled=true 17）、colorcal 23；f4a51db（git show 确认退役 film_portra_400.json）后 24→23 与 t52 口径衔接成立。
5. **F10 缺省断言计数精化（建议）**
   - 改了什么：「同步修订 t52 §3.4 实测的 5 项缺省断言」→ 明确 5 项是四阶段全翻口径、本批预期红仅 hsl/split_tone 相关 4 项，skin 1 项不翻不红不动。
   - 为什么：防 dev-2 照单全改把不失败的 skin 断言也改掉（引入无据变更）。
   - 怎么验证的：t52 §3.4 明细 1(skin)+2-3(hsl)+2-3(split_tone)=5 逐项归类核对。
6. **F08 种子行号校准（建议）**
   - 改了什么：「种子随机图输入 :23-38 模式」→「`default_rng(20260820)` :69 模式」。
   - 为什么：:23-38 实为 FEATURES 表+_DCP_PATH；种子随机图实现在 :69。
   - 怎么验证的：grep gate_cases.py 种子命中 :69（`default_rng(20260820).random((64,64,3))`）。
7. **F14 engine 路径消歧（建议）**
   - 改了什么：「engine.py:449」→「**src/pixo/decide/engine.py**:449（仓内另有一份 render/decide/engine.py 勿混淆）」。
   - 为什么：仓内两份 engine.py，register_metric_keys 只在 decide/ 那份（:449）。
   - 怎么验证的：grep register_metric_keys 双文件对比，仅 src/pixo/decide/engine.py:449 命中定义。
8. **F16 PyYAML 建议 qa 代复核（建议，design 原文要求「此建议 qa 复核」）**
   - 改了什么：在 F16 条目内补 qa 复核结论（engine.py:255-261 YAML 规则加载 PyYAML 缺失即 DecideError 无回退；默认规则包 5 个全 YAML；requirements.txt 现状两者均未列）。
   - 为什么：design 自带待办，本轮直接闭合，writer 拿到即是无歧义指令。
   - 怎么验证的：Read decide/engine.py load_rules :245-275（ImportError→DecideError 无回退分支）；ls decide/rules/ 5 个 YAML；Read requirements.txt。
9. **风险表补 F04 语义变化行（建议）**
   - 改了什么：风险登记新增「F04 未知 prompt 语义变化（原纯未知 prompt 请求经 gsam 禁用→SegmenterUnavailable→manual_review 升级，移除后改零掩码+warn-once）| 中 | 设计已明示语义+测试改写钉死+manual_review 路径回归确认」。
   - 为什么：这是用户可见行为变化：现状 grounded_sam.py:61-62 禁用即抛 SegmenterUnavailable，multi_router.py:198-204 全组不可用即上抛升级；移除 gsam 后该类请求不再升级。属应登记的语义边界而非静默细节。
   - 怎么验证的：Read grounded_sam.py :60-62 + multi_router.py :198-204 链路推演确认现状行为。

全部修复均已复验：对修订后的 design.md 逐条 grep 确认九处修订落位（design.md :37/:56/:62/:69/:75/:110/:116/:123/:156）。

## 8. 代码抽查清单（验证设计事实性）

multi_router.py（DEFAULT_ROUTE/_get/warmup/routed_backend_names）、graph.py（Stage.p 回退链/
register_stage）、reshape.py（dehaze enabled=False 先例）、presets.py（DEFAULT_STAGES）、
params.py（STAGE_CLASSES）、hsl.py:30-36 与 split_tone.py:35-43（F10 落点）、
loop.py（:66-72/:336-338/:397-407/:450-480/:531-568/:1063-1066）、session.py（:321-322/:345-346/
:440-446）、export.py:30、agent/patch_protocol.py:118、decide/engine.py:449/:255-261、
decide/rules/、vision/{person,health,__init__}.py、manifests/vision_models.json、
model_licenses.json、resources/models/models_reference.json、pyproject.toml、
requirements.txt、color.py:471-487、grounded_sam.py、segmenters 四后端 import 面、
configs/styles/films/ 全 25 卡、tests/{test_vision_extras,test_vision_router_semantics,
test_vision_manifests,test_multimodel_segmenter,test_sapiens_body,
test_film_cards_oklch}.py、gate_cases.py、test_gate_golden.py、
src/pixo/harness/goldens/samples.py、render/tools/gate_golden.py（CLI 用法）、
D:\tmp\pixo_t108\samples.json 与 data/golden/.../gate_defaults（存在性）。

## 9. 升级项（报队长）

**无。** 未发现架构级/需求级问题；全部发现均为设计文档事实性精度问题，已在 design.md
就地修复并复验。两条不阻断观察项供队长知悉：
1. model_licenses.json gsam 条目内「torch/transformers 限 grounded_sam.py 内懒 import」
   的注记已过时（多个后端直接依赖）——该条目随 F04 删除自然消失，但若 F04 执行中文档
   其它处复述此说法，按修订后的 F04 设计（extras 保留）为准。
2. manifest 文件域表未覆盖 src/pixo/agent/** 与 src/pixo/decide/**（本轮各单一 owner
   触碰，无冲突风险）；若本轮中途有第二流需触碰，报队长补域后再动。

## 10. 结论

设计覆盖 F01~F20 全部功能、各项可测、边界异常识别充分（含 F04 语义边界补强）、接口与
文件域划分同 manifest 一致且经代码实测核对、风险登记 6 项含缓解、与 t52 评估结论
（三道前置修补+分批纪律）忠实一致。九处修订已落位复验。**审核通过，签发 .design_ok。**

---

# R31 设计审核意见（2026-09-22 · reviewer · WorkBuddy 独立评审）

> 轮次：R31 ｜ 审核人：reviewer（delivery 质量门禁，独立视角）
> 独立评审引擎：WorkBuddy 会话 `wbdy-651119f0-3ba`（model=deepseek-v4.1-flash，effort=max，任务 job-6fba0b63b1fb，全程只读未改任何仓内文件）
> 被审对象：`.agent-team/design.md`（F0-F5）；审核基准：`.agent-team/task-brief.md`（卡点①已批）
> **结论：有条件通过 —— BLOCKER 6 项，本轮不签发 `.design_ok`**；整改落实后由 reviewer 复检修订点，通过再签门禁

（以下为 WorkBuddy 引擎独立评审报告原文，未删改）

独立评审对象：`.agent-team/design.md`（R31，F0–F5）。基准：`.agent-team/task-brief.md`（卡点①已批）。全程只读，未修改任何文件（含 design.md）；所有事实性声明均已实际核实（见 §三）。联网核实了 RawTherapee `main-cli.cc` 帮助文本与 DNG SDK 源码；本机跑了只读的 gate 金样本 `--check`。

---

## 一、逐项审核

**1. 需求覆盖**：F0–F5 对上了任务书 §1 的主体（F1 参照发生器、F2 批转、F3 三臂 n=48、F4 预授权矫正、F5 回归），§3 约束面基本覆盖（数据-only 改动、判据先行、pytest+金样本、口径记录），F0 对应修订记录里的 GPLv3。**漏项**：任务书 §1.5"需要时扩全量 4053 张"在 design 零落点；§4 的"changelog + 提交推送"未进 design（`.agent-team/team-manifest.md` 阶段 9 已派给 junior-dev，但 design 自称唯一真相源，两份文件脱节）；§4"逐片散布"未写进 F3 交付物定义；RT 臂作为"搬哪块算法"选型依据只被要求输出 Δ 数字，未要求算法级文字结论（需求级）。

**2. 测量口径公平性（本轮核心）**：逐臂"默认打开语义"的原则正确、RT 不入判据正确。但发现三处实质偏差：(a) **RT 臂实际会跑成 neutral 而非"RT 默认"**——RT CLI 在无 `-p/-d/-s` 时"以中性值新建处理参数"，要吃到 Preferences 的默认 Profile 必须加 `-d`，与 §2"无 pp3 = RT 全默认"矛盾（B2）；(b) **几何归一的算法不唯一**：若按字面"512 像素中心裁"实现，DNG/RT 全分辨率图裁的是帧中心 ~9% 视场、pixo 1024 预览裁的是 ~50% 视场，三臂视场不一致（B1）；(c) 朝向：pixo（api.py:21-38/163/187）与 dng_validate（dng_validate.cpp:581 `finalImage->Rotate(Orientation)`）已从代码级确认按 EXIF 转正，RT 未核实；居中方形裁剪下 90° 旋转对"逐片中位数"几乎无影响（像素多重集不变），真正的风险是裁切区域定义而非朝向本身，但朝向不一致会让"四角 dhash sanity"误报跳片。色彩空间/位深：DNG 默认 8-bit sRGB（`ttByte`+`-cs1`）、pixo 8-bit、RT 默认 16-bit TIFF——可直比但 u16→u8 换算未定；"辅 ΔE76(Lab/255→0-100)"表述不准（仓内既有换算只有 L×100/255、a/b−128，见 fit_tone_curve.py:106-111）；阈值 ≤5/≤3 与 R30 读数同为 OpenCV 8 位标度，这一点是自洽的。RT 防误读：design §3 有"不入判据"字样，但报告/JSON 无结构化隔离，建议加固。

**3. 判据可执行性**：`median|ΔL|` 存在两解（median(|ΔL|) vs |median(ΔL)|），分布 p10/p50/p90 未说算在哪一量上——n=48 下两解可翻转"达标/矫正"裁决（B1）；`|Spearman(ΔL, wb_B)|` 的 wb_B 没有任何来源定义、无产出方（B3）；矫正后目标 `|Δa|/|Δb| ≤ 2` 按字面是"比值判据"，且全节没有判定角色、没有"三候选均不达标"的失败路径（B4）；任务书里的"残差结构（与 wb_B/**场景**相关）"只被操作化为 wb_B，场景项被静默丢弃。

**4. 风险预案完备性**：五条预案中，"装失败→GUI"可执行但缺"装后验证 exe/CLI 真可用"（本机已有半装残留证据）；"编译错→修 props/最小壳"需要区分两类失败（最小壳兜不住 SDK 核心编译失败），且真正的 P0 前置"vcxproj jxl 三引用摘除"根本没进 design（实际也还没做，B5）；"渲染慢→小尺寸选项"引用的 435-450 行是 `-dng` 预览路径，对 `-t` 输出不适用：`-max` 不影响 `-t` 渲染，`-min` 会把参照降级为 Stage3 预览渲染（建议-1）；"RT 色彩空间"与 §2 自相矛盾；"几何/朝向"缺"某臂失败时该片如何处置"的一致规则。另漏登记：DNG Converter CLI 调用细节与半装残留、RT portable zip 版本口径、jxl 重编仍败的第二层兜底、48 片各臂成败不一的样本集规则（建议-2/3）。

**5. 边界与异常**：坏文件处理——"已知 LibRaw 坏文件"在仓内**无台账**（仅历史报告提过 1/24、2/798），跳片是否三臂一致未定义，默认实现"各臂各自跳过"会引入幸存者偏差（建议-3）。样本可比性——design 称"与 R30 三轴探针同一 pick() n=48"，但 R30 探针脚本不在仓（`.artifacts` 无 `_r30_*`、git 历史无、无人入库过任何 `_` 前缀产物），该声明不可核实；好在存活的 R25/R27/R28 探针用同款等步长 pick，我已验算：同语料下 n=48 的集合（步长 84）是 n=24 集合（步长 168）的超集（`168k, k≤23` 全在 `84·2k` 序列内 ✓）——但这必须写进 design 才算数。回归面——default_look 单测实际只有 2 个（tests/unit/test_service_runtime_fixes.py:204/230），且只硬断言 `tone.profile_curve is True` 与 `whitebalance.mode == "as_shot"`，不校验数值；gate 金样本**不吃** default_look.json（gate_cases 只读 warmth_curve.json 与 kodak_portra_400.json；我在当前工作树实跑 `generate_gate_goldens.py --check` = "21 features 与现有 manifest 一致"），recipe_tone_curve.json 改动也不触 gate（无用例走 eotf=recipe，单测均 monkeypatch/temp）→ design §4.4"预期零漂移"成立，但"数据文件改动需过 default_look 单测"的实际约束含义应写明（见 B4）。

**6. 接口约定**：F1 入参只有"dng 路径→出 TIFF 路径"，与花名册要求的"WB/profile/输出空间参数化"不符；F2 manifest 三元组 OK 但缺版本/成败/口径字段；F3 的 `_r31_three_arm.json` 只写了"逐片+分布"，字段级定义缺失（wb_B、|Δ|、判据块、口径常量）；**F4 输入不闭合**——fit_tone_curve.py 现在是"内部自采样（session 配额随机，seed 20260919）+ 目标=相机 thumb"，没有"传入 48 片清单/换目标图"的入口（建议-6）；F5 的 `.qa_ok` 路径符合项目惯例（`.agent-team/.qa_ok` 已存在），但"抽片复现"无程序/无容差（建议-7）。

---

## 二、意见清单

### BLOCKER（6 项）

- **BLOCKER-1**：[design §2 度量段 + §3 达标行] 核心判据的数学定义不唯一、几何归一算法未定。① `median|ΔL|` 两解（先取绝对值再跨片取中位 vs 跨片有符号中位后取绝对值），分布 `p10/p50/p90/IQR` 未说对哪个量；②"统一长边 512 中心裁齐"未给唯一算法（先缩放再裁还是裁原生 512 像素、方形还是长边、重采样方法）——若按"裁原生 512 像素"实现，三臂视场完全不同（DNG/RT 全分辨率 vs pixo 1024），测量不公；③"辅 ΔE76(Lab/255→0-100 标度换算记录)"与仓内既有换算不符（fit_tone_curve.py:106-111：只有 L×100/255，a/b 减 128 去偏；若把 a/b 也除 255 会得到另一套数）；④RT 16-bit TIFF→Lab 前的 u16→u8 换算未定。另：a/b 在 8 位标度上量化步长=1，"矫正后 ≤2"=2 个量化步，建议全程在 float 上算避免二次量化。**修法（纯文档，1 小时内）**：在 §2 写死公式与伪代码（逐片 `ΔL = median_crop(L_pixo) − median_crop(L_dng)`；`|ΔL|` 后跨片取中位；分布定义在"逐片有符号 Δ"或"逐片 |Δ|"上二选一写明）；几何写"各臂先长边→512（INTER_AREA）再取中心 min(h,w) 方形"；u16→u8 与 ΔE76 换算各写一行公式。

- **BLOCKER-2**：[design §2 表 RT 行 + §5 风险行 4] RT 臂口径错误，测的不是"用户打开照片的 RT 样子"。RT 官方 CLI 帮助文本明示：不传 `-p/-d/-s` 时"a new processing profile is created using **neutral values**"；要用默认观感必须加 `-d`（Preferences > Image Processing > Default Processing Profile）——所以"无 pp3 = RT 全默认"不成立，且与风险行 4"用 pp3 指定输出 sRGB"互相打架（用了 pp3 就不是"全默认"）。后果：RT 臂无 Auto-Matched 曲线等默认处理，Δ(RT−DNG)/Δ(RT−pixo) 会系统性偏暗，作为"搬哪块算法"的选型依据失真。**修法**：命令固定为 `rawtherapee-cli -o <dir> -t -Y -d [-p 输出profile.pp3] -c <file>`（`-c` 必须最后，此项 design 写法正确；`-t` 默认即 16-bit TIFF，符合 design 预设），或明确声明"RT 臂 = neutral 口径"并给理由；版本/实际输出 profile 从装后 `--help` 与输出文件元数据取录。标「队长处理」（口径裁决）。

- **BLOCKER-3**：[design §3 + §6 F3 交付物] 判据变量 wb_B 悬空：`|Spearman(ΔL, wb_B)|` 没写 wb_B 是哪个臂的什么量、由谁产出、是否进 `_r31_three_arm.json`。仓内唯一现存口径在未入库的探针里（`.artifacts/_r28_recipe_generalization.py:55-63`：rawpy `camera_whitebalance[2]/[1]`，B/G）。**修法**：§3 定义 `wb_B := 相机 as-shot WB 的 B/G（rawpy camera_whitebalance，源 NEF）`（并说明 DNG 转换不改变相机 WB，报告里以 1 例对照佐证）；§6 把 F3 JSON 字段写全：逐片 `{file, wb_B, ΔL, Δa, Δb, |ΔL|, |Δa|, |Δb|}` + 分布块 + 判据判定块（含所用阈值的字面常量）。

- **BLOCKER-4**：[design §3 矫正后目标 + §4.3] ①`|Δa|/|Δb| ≤ 2` 按字面是比值判据（|Δa|=4,|Δb|=3 会被判过），应写"median|Δa| ≤ 2 **且** median|Δb| ≤ 2"；②"胜者（判据指标最优）写入 default_look.json"没有失败路径：三候选都不达矫正后目标时怎么办、谁判、留痕/是否再迭代均未写；③写盘约束未写明——`tests/unit/test_service_runtime_fixes.py:211-212` 硬断言 `tone.profile_curve is True` 且 `whitebalance.mode=="as_shot"`，若胜者是 `eotf=recipe` 形态，必须保留 `profile_curve: true` 键（该键在 recipe 分支惰性无害）或显式改单测。**修法**：补"判定人=dev-2 出数、reviewer 复核、tester 抽片复现"；补失败路径（均不过 → 不写盘、保留现状、报告+上报队长仲裁，援引 R18"失败路径合法"先例）；补两条硬约束。标「队长处理」（判据闭环为需求级）。

- **BLOCKER-5**：[F1 / `K:/work/project/dngsdk/dng_sdk_1_7/dng_sdk/projects/win/dng_validate/dng_validate.vcxproj:255,337,400` + `dng_validate.sln:16,22,24`] 任务书称"vcxproj 摘除 jxl 三引用（待重编验证）"，**实际三处引用仍在**（ClCompile dng_jxl.cpp / ClInclude dng_jxl.h / ProjectReference jxl.vcxproj），sln 还挂着 jxl/brotli/highway 三个工程——现在编译仍会触达 libjxl 的 ClangCL 卡点，P0 会原样重蹈。已在源码侧核实的只有 `dng_flags.h:480-481` 的 `qDNGSupportJXL (0)`（注释自带"R31"）。**修法**：F1 显式增加工作项"摘除 ProjectReference（必要）+ 两个文件引用（建议）并重编验证"；sln 同步或只编 vcxproj 并在报告记录。

- **BLOCKER-6**：[design §1/§6 + 完成标准] 测量/拟合 harness 被 `.gitignore:85`（`.artifacts/_*`）排除，且全仓从无 `_` 前缀产物入库先例（`git ls-files .artifacts/ | grep '/_'` = 0）——"报告可复现"与任务书 §1.5"需要时扩全量 4053"都依赖这些脚本长期存活。该风险已在本轮现形：R30 探针脚本丢失，导致 design"与 R30 同一 pick()"无法核实（见 §一.5）。**修法**：最小要求——把最终版 pick/度量/拟合脚本入库（如去 `_` 前缀为 `.artifacts/r31_three_arm.py` 等随报告同批提交），报告附脚本 sha256；即便队长裁定脚本保持机器本地，报告也必须内嵌**48 张完整清单 + 口径常量 + R30 的 24 张交集核对行**，使测量可复算。

### 建议（9 项）

- **建议-1**：[design §5 风险行 3 + F1] 小尺寸渲染勘误与量化。已核实：`-max` 只改 host 尺寸（dng_host.cpp:110-137），`dng_render` 的 `fMaximumSize` 不继承 host（构造处置 0），`-t` 输出仅在传 `-min` 时被 `render.SetMaximumSize(Max(stage3.v,h))` 夹到 Stage3 尺寸（dng_validate.cpp:559-566）——即 `-min` 会把"默认渲染参照"降级为**预览级渲染**，不可用；435-450 行的 256/1024 属于 `-dng` 预览路径（:440-448）。可执行方案三选一并记录：(a) 全分辨率渲染（慢但最忠实，`-t` 默认 ttByte/sRGB 已是参照口径）；(b) 在 `-t` 路径加一行 `render.SetMaximumSize(...)` 重编；(c) 最小壳里限尺。另补量化验收："渲染慢"=单片/总时长阈值由 dev-1 实测后回填；"最小渲染壳"验收=同参数下与 `dng_validate -tif` 输出一致（8-bit 逐位或 ≤1 LSB），否则只作过渡并在报告标注。

- **建议-2**：[design §5 风险行 1/2] 风险登记补漏：(a) DNG Converter 实为**半装残留**——本机 `C:\Program Files\Adobe\Adobe DNG Converter\` 仅有 `adobe_c2pa.dll`，`winget list` 里无该包（已核实）；安装后必须验证 exe 存在且 CLI 可跑（DNG Converter 的 CLI 调用形式/输出目录/覆盖行为 design 完全没写），并在 §5 加"装后验证 + 半装残留清理"；(b) RT 若走 portable zip，冻结下载版本号+sha256 并记录（现在只写"官网 portable zip"，无版本口径）；(c) jxl 重编仍失败要分两层兜底：dng_validate.cpp 编译错→最小壳；SDK 核心/工具集错→最小壳同源码同 cl 也兜不住，需决策点"降 SDK/换 toolset/裁剪源集"上报队长。

- **建议-3**：[design §5 风险行 5 + §1] 样本集一致性规则：定义"有效片集=三臂齐备；任一臂失败即整片移出**所有**分布统计"，另表留痕（文件名/失败臂/异常类型）；LibRaw 坏文件与 dng_validate/RT 失败分类记录；报告给出"48 计划 / N 有效 + 剔除清单"。禁止各臂各自跳过（幸存者偏差），RT 选型段与判据段共用同一有效片集。

- **建议-4**：[design §3 + §2] 判据与 RT 隔离加固：`_r31_three_arm.json` 加结构化字段（`criteria.arms=["pixo","dng"]`、`reference.arm="dng"`、`rt.role="selection_only"`）；报告把"判据段（pixo vs DNG + 阈值判定）"与"选型参考段（RT）"物理分节、RT 数字旁标注"不参与达标判定"。另：任务书的"场景相关"结构项被静默丢弃，建议要么补一个替代检验（如按 ISO/光源分组看组间 ΔL 差），要么在 §3 明写"本轮不做场景结构检验"并给理由。

- **建议-5**：[F0 / pyproject.toml:11] GPLv3 落地细化：选定并写明 SPDX 变体（`GPL-3.0-only` vs `-or-later`，与 RT 代码血缘的兼容方向要一句说明）；LICENSE 全文来源、`pyproject` license 写法（SPDX 字符串或 text）；同步 `docs/PIXO_LICENSE_REVIEW.md`/`THIRD_PARTY_NOTICES.md` 的项目自身许可口径，避免许可台账与 pyproject 脱节（该两份文档现存且引用了 RT GPL 与分发阻断面）。

- **建议-6**：[design §4 / §6 F4] F4 输入接口闭合：给出实现形态二选一并写进 design——(a) 新增 `_r31_refit.py`，import `fit_tone_curve` 的 `fit_curve/fit_gains/apply_kcurve/decode_ch`，输入=F3 的 48 片清单 + DNG 渲染图（u8 sRGB），用同 seed+shuffle 规则复现 train/holdout；(b) 给 fit_tone_curve.py 加 `--files/--target-dir` 入口。输出 JSON 的 provenance 记 48 片清单 sha256 与切分。注意拟合域是中性链线性（`Renderer(dcp)` 无 params），候选对比才叠加 default_look 域——别混。

- **建议-7**：[design §6 F5] 抽片复现可执行化：定义抽片数（建议 5 片，覆盖横/竖/日光/钨丝）、复现判据（同口径重算逐片 ΔL/Δa/Δb 与报告值一致，容差写死，如 ≤0.5 Lab 或逐位）、执行人（tester-whitebox）、失败处置（回 dev-2）。

- **建议-8**：[design §1 + §6] 覆盖率补丁：任务书 §1.5 全量扩展加落点（触发条件=判达标存疑/用户要求、责任=dev-2、复用脚本与产物路径）；"changelog + 提交推送"在 design 交叉引用 `.agent-team/team-manifest.md` 阶段 9（责任 junior-dev）或直接立 F6；F3 交付物补"分位数表 + 逐片散布（CSV/图）+ 口径记录"清单。标「队长处理」。

- **建议-9**：[process · 轮次编号，队长处理] `.artifacts/R31_enabled_wiring.md`（2026-09-21）+ 未提交工作树（18 文件 +360/−114，含 `src/pixo/render/modules/*`、`src/pixo/service/runtime.py`）与本轮共用 R31 编号；design 称"引擎代码零改动"，但入口基线本身含上一轮未提交的引擎改动，F5/金样本将在该基线上跑。建议：design 增"基线声明"（HEAD=9a7443b + 在途 R31 enabled-wiring diff，pytest 基线数字由 dev 实测回填）；"提交推送"时明确两轮提交切分与 changelog 区分（避免两条 R31 混淆）；本报告命名建议与 `R31_enabled_wiring.md` 并列时加轮次后缀。

---

## 三、事实性核验记录

核实=已亲自读文件/代码/联网/实跑；每条附位置与结论。

1. **default_look 已接默认打开**：`src/pixo/service/runtime.py:354-387`（`_load_default_look`，deepcopy 缓存、env off、缺失回中性）、`:511-525`（会话工厂注入）；`configs/styles/default_look.json` 现有 params（profile_curve=true/eotf=srgb/exposure baseline/wb as_shot）。✓
2. **R30 三轴 n=24**：`.artifacts/R30_dng_replica_retirement.md:45`"（n=24 vs 相机内嵌 JPEG）"；ΔL −83.5/lr观感 −40.5 等。design"同一 pick() n=48"**不可直接核实**——`.artifacts` 无 `_r30_*`，git 历史亦无（`git log --all --name-only -- "*_r30*"` 空）。若 R30 用存活的等步长 pick（_r25/_r27/_r28/_f01 同为 `step=len//n; out[::step][:n]`），我验算 sel(48) ⊇ sel(24)：4053//48=84、4053//24=168，168k（k≤23，max 3864）全部落在 84·2k（≤3948）内。✓（有条件）
3. **fit_tone_curve.py**：共享曲线+gains、目标=相机内嵌 thumb、分布级（无几何对齐）、train/holdout（seed 20260919，`sample()` 为 session 配额随机——与 R31 的等步长 pick **不同款**）、`--n/--seed/--holdout-frac`，无 `--files`/换目标入口（:46-83、:196-214、:256-289）。✓（并暴露 F4 接口缺口）
4. **recipe 数据文件**：`src/pixo/render/recipe_tone_curve.json` 存在（version 4、target=camera_thumb），消费点 `tone_map.py:62/113/396-418`（仅 eotf=lrfit/recipe 分支）。✓
5. **default_look 单测**：`tests/unit/test_service_runtime_fixes.py:204-227`（加载/env off/非法文件）、`:230-250`（工厂注入）；硬断言 `tone.profile_curve is True`、`whitebalance.mode=="as_shot"`。除这 2 个文件外，tests/ 无 default_look 引用（grep ✓）。
6. **gate 金样本机制**：`tests/regression/test_gate_golden.py`（manifest 21 features、reviewer 非空、sha256、--check 与逐 feature 复算 ≤1e-6）；`goldens/generate_gate_goldens.py`（合成 golden，写盘/check 两模式）；`goldens/gate_cases.py` 只读 `configs/calibration/warmth_curve.json`（≈:310）与 `configs/styles/films/kodak_portra_400.json`（≈:348），**不读 default_look.json**；用例中无 eotf=recipe。**实跑** `python tests/regression/goldens/generate_gate_goldens.py --check` → "CHECK: OK（21 features 与现有 manifest 一致）"（当前工作树、含未提交改动）。✓ design §4.4"预期零漂移"成立。
7. **dng_validate 事实**（dng_validate.cpp，1161 行）：`-tif <file>`=TIFF 输出（usage :712 附近）；TIFF 渲染全尺寸（:540-624），仅 `host.MinimumSize()`（即 `-min`）时 `render.SetMaximumSize(Max(stage3.v,h))`（:559-566）；`-dng` 预览路径的 256/1024 在 :440-448（design 引用的"435-450 行"属于此路径）；`finalImage->Rotate(negative->Orientation())`（:581）→ 像素按 EXIF 转正；默认位深 `ttByte`（:75）、默认色空间 sRGB（`-cs1`）；`-max` 经 host 只影响尺寸裁整（dng_host.cpp:110-137），`dng_render` 的 fMaximumSize 默认 0 且不继承 host（dng_render.cpp:2112-2128）。✓（并更正 design 风险行 3）
8. **pixo 朝向**：`src/pixo/render/api.py:21-38`（`_apply_orientation`/`_orientation_from_exif`）、`:163`/`:187`（render 链两处施加）。✓
9. **SDK 编译现状**：`dng_flags.h:480-481` `qDNGSupportJXL (0)`（含 R31 注释）**已设**；但 `dng_validate.vcxproj:255/337/400` 三处 jxl 引用**仍在**，`dng_validate.sln:16/22/24` 挂着 jxl/brotli/highway；SDK 树内无任何 .exe（未编译出产物）。✗（与任务书"已摘"不符）
10. **语料**：`K:/data/photo` 实测 4053 张 NEF（2026春节 256 / 厦门 2407 / 西安 1390，剔 AppleDouble）。✓
11. **本机环境**：winget v1.29.290；`winget list` 无 Adobe DNG Converter / RawTherapee（仅 Lightroom Classic 15.0.1、Photoshop 2026）；`C:\Program Files\Adobe\Adobe DNG Converter\` 仅 `adobe_c2pa.dll`（半装残留）。✓
12. **RT CLI（联网核，RawTherapee dev 分支 `rtgui/main-cli.cc` 帮助文本）**：`-t[z]`=TIFF（默认 16-bit；`-b8/16/16f/32` 可改）、`-Y`=overwrite、`-c` 必须最后、`-o` 输出目录；**无 `-p/-d/-s` 时"a new processing profile is created using neutral values"**，`-d`=用 Preferences 默认 Profile。✗（推翻 design §2"无 pp3=RT 全默认"）
13. **许可证现状**：`pyproject.toml:11` `license = {text = "Proprietary"}`（仅此一处 license 字段，无 classifiers）；仓库根**无** LICENSE；`THIRD_PARTY_NOTICES.md`/`docs/PIXO_LICENSE_REVIEW.md` 存在并涉 RT GPL 血缘。✓
14. **gitignore/入库惯例**：`.gitignore:85` `.artifacts/_*`；`git ls-files .artifacts/ | grep '/_'` = **0** → 探针脚本从无一入库；`.artifacts/*.md` 不在忽略列表（报告可入库）。✓（支撑 BLOCKER-6）
15. **在途工作与轮次**：HEAD=`9a7443b`（R30 B2）；`git status` 18 文件已改（含 render 引擎模块、service/runtime、多个测试）+360/−114；`.artifacts/R31_enabled_wiring.md` 及 `_r31_*` 一批为未跟踪/被忽略（上一轮 R31 未提交）。`docs/changelog.md` 最新条目为第三十轮（R29/R30 已入）。✓
16. **wb_B 口径**：仓内唯一现存实现 `.artifacts/_r28_recipe_generalization.py:55-63`（rawpy `camera_whitebalance[2]/[1]`）；未入库为契约。✓
17. **"f01_batch"标识**：全仓 grep 无 `f01_batch`（只有 `.artifacts/_f01_*.py` 一次性探针与 `skin.py` 内部函数名 `_smooth_rgb_f01`）。design §2 引用此名无实据。✗（建议改引存活探针）
18. **recipe 真实文件的测试面**：`tests/unit/test_calibration_store.py:231-259`、`tests/unit/test_tone_sixkey.py:222-236` 均用 temp 文件/monkeypatch，**不读真实 recipe_tone_curve.json**（grep "recipe" tests/ 仅此两处文件）。✓ → F4 改数据不会因它们翻红。
19. **.qa_ok 惯例**：`.agent-team/.qa_ok`（+历史 `.rNN_ok`）存在，签章要素见 `.agent-team/qa-plan-r22.md:51`。✓
20. **花名册对齐**：`.agent-team/team-manifest.md`（2026-09-22）角色/F 分配与 design 一致；阶段 3 判定="无 blocker"；阶段 9="R31 报告+changelog+push（junior-dev）"；dev-1 契约要求"WB/profile/输出空间参数化"（design F1 未写）。✓

---

## 四、结论

**有条件通过**——方向与结构（F0–F5、预授权判据、RT 选型臂定位）成立，不需要重设计；但按 `team-manifest.md` 阶段 3"无 blocker"口径，**本轮不签发 `.design_ok`**，需先完成下述整改并经 reviewer 复检（仅复检修订点）：

| 整改项 | 责任 | 类型 |
|---|---|---|
| B1 度量/判据公式与几何算法写死 | 队长（design 修订） | 文档 |
| B2 RT 臂口径裁决（`-d` 默认 vs neutral 声明） | 队长 | 口径裁决 |
| B3 wb_B 定义 + F3 JSON 字段表 | 队长 + dev-2 | 文档/接口 |
| B4 矫正后目标改写 + 失败路径 + 写盘约束 | 队长 | 判据闭环 |
| B5 摘除 vcxproj/.sln jxl 引用并重编 | dev-1（F1 工作项） | 前置/编译 |
| B6 harness 入库（或报告内嵌清单+常量+sha256） | dev-2 + 队长 | 可复现性 |
| 建议 1–9 | 队长/dev-1/dev-2/junior-dev 按项 | 完善 |

**BLOCKER 计数：6 项**（其中 B2、B4 含需求/口径级裁决，已标注「队长处理」；建议-8、建议-9 同为需求/流程级）。复检通过后即签 `.design_ok`，随后按 `team-manifest.md` 阶段 4a/4b/4c 并行开工。

---

# R31 设计复检意见（2026-09-22 · reviewer · WorkBuddy 独立复检 · design v2）

> 轮次：R31 复检（v2 整改回传）｜ 审核人：reviewer ｜ 复用会话 `wbdy-651119f0-3ba`（任务 job-a7b4c04b4485，model=deepseek-v4.1-flash，effort=max，全程只读）
> 被审对象：`.agent-team/design.md` v2；**结论：有条件通过 —— 5/6 消解、B2 部分消解（1 处一行级 gating），本轮未签发 `.design_ok`**；残留-1~3 修订落位后复核这三处即签，无需全文重审。

（以下为 WorkBuddy 引擎独立复检报告原文，未删改）

复检对象：`.agent-team/design.md` v2（已全文重读，行号以现行文为准）。全程只读，未修改任何文件（含 design.md）。不信申报、只信文件与磁盘证据：本轮本机实证了 cv2 float/uint8 Lab 标度对照、u16 换算链、几何顺序 A/B、**pristine zip 全树字节比对（3809 条目）**、vcxproj/sln/dng_flags.h 现状、`git check-ignore`，并联网抓取 RawTherapee 官方源码帮助文本核对 `-d` 语义。仓内工作树自首轮以来无变化（同 18 M + 4 ??），首轮 pytest/gate 结论继续有效。

## 一、六项 BLOCKER 逐项复检

| # | 队长申报处置 | 复检 verdict |
|---|---|---|
| B1 | 公式写死（float 管线/几何/换算） | **消解** |
| B2 | RT 臂改 `-d`、删错误表述 | **部分消解**（语义对，命令语法错，一行修） |
| B3 | wb_B 定义 + F3 JSON 全字段 | **消解** |
| B4 | "且"语义/失败路径/判定链/写盘约束 | **消解** |
| B5 | jxl 物理清偿 | **消解**（字节级实证，本轮最强证据） |
| B6 | 脚本入库 + 清单内嵌 | **消解** |

**B1 消解** — design.md:36-49 公式链完整（u16→u8f→rgb01→float Lab→8 位标度→几何→逐片 Δ→主判据量→分布→ΔE76）。本机实测（cv2 5.0.0）：
- float→8 位标度（L×2.55、a/b+128）与 uint8 路径逐像素吻合：随机全色域图 max|Δ|≤1.08 LSB、均值 0.30；6 个纯色残差=取整级；且 float 路径实测输出标准 sRGB Lab（红=53.24/80.09/67.20）→"OpenCV float Lab"陈述与换算均属实；
- `u16→u8f→rgb01 ≡ u16/65535`（allclose True）→ 端到端无二次量化；
- ΔE76 行与 fit_tone_curve.py:106-111 一致（/2.55 与 ×100/255 恒等、a/b−128 逐字对上）；
- 附注（不构成整改）：几何与色彩处理先后未写死，实测两序中位数差 ≤0.16 标度单位（n=1 照片，A-B=[-0.001,-0.032,0.158]）→ 无实质影响。

**B2 部分消解** — 语义修正正确且已与官方帮助对齐："不传 -d 走 neutral 起新档"属实（帮助原文 "1- A new processing profile is created using neutral values"）。但 design.md:33 命令 `-d <Default.pp3>` **语法错误**：RT 官方源码（dev 分支）帮助文本明示 `-d` 为**无参 flag**（synopsis `[-d]`，帮助原文 "Use the default raw or non-raw processing profile as set in Preferences > Image Processing > Default Processing Profile"；handler `case 'd': useDefault = true; break;`）——`<Default.pp3>` 会成为游离参数/被当作输入文件处理。必改一行：`rawtherapee-cli -o <dir> -t -Y -d -c <file>`（若确需文件语义应换 `-p <file.pp3>`，但那改变口径）。另："fresh 安装即 Neutral"未独立证实（rawpedia 抓取受阻），设计自带"装后 --help/元数据核录"步骤可兜住，但措辞宜改"预期 Neutral，装后核录"。

**B3 消解** — design.md:53-55 定义 `wb_B := rawpy.camera_whitebalance[2]/[1]`（源 NEF，B/G），与仓内唯一实现（`.artifacts/_r28_recipe_generalization.py:55-63`）一致；§6:99-101 F3 JSON 逐片 `{file,wb_B,dL,da,db,abs_*}`+分布块+判据块（含阈值字面常量与 verdict）齐全。建议级残：§3:57 Spearman 入参"逐片ΔL"未注明有符号/绝对值（两解 ρ 可不同）。

**B4 消解** — :59"且"语义、:60-61 失败路径（不写盘+上报队长）、:62 判定链、:63-65 写盘硬约束齐全；引用的 `tests/unit/test_service_runtime_fixes.py:211-212` 实测无误（`profile_curve is True` / `wb mode=="as_shot"` 两条硬断言）；§4:75 明示"受 §3 判据/写盘/失败路径约束"→ F4 引用闭环。R18 先例实质可查（changelog:214 第十八轮 2026-09-08"数据性关闭"；"R18 先例"字样见 changelog:56），"失败路径合法"为转述措辞、非原文，无碍。建议级残：矫正后目标（:59）未含 Spearman 条款、§4 候选"胜出排序"未写死。

**B5 消解（磁盘实核，勿信申报——已全面复核）**：
- vcxproj：`jxl` 匹配 **0 行**；`ProjectReference Include` **0**；`<ProjectReference />` 空占位 4 处——经 zip diff 证实为 **pristine 原有**（diff 中为上下文行）；
- **全树字节比对**（`K:/work/project/dngsdk/dng_sdk.zip`，3809 条目）：**0 缺失；仅 2 个文件差异**＝恰好 vcxproj + dng_flags.h，其余 3807 文件逐字节一致；
- vcxproj diff = **REMOVED 11 / ADDED 0**（dng_jxl.cpp、dng_jxl.h、brotli/highway/jxl 三条 ProjectReference；原 ItemGroup 包壳留存为空组）→"仅删不加"属实；XML 良构（ElementTree 解析通过）；mtime 2026-09-22 10:53 与申报吻合；
- dng_flags.h diff = `(1)`→`(0)`+R31 注释，位于 **:481**（#ifndef 在 :480）；
- sln diff = **0/0**（逐字节未动）→"只编 vcxproj、不编 sln 并记录"与现状一致（sln:16/22/24 仍挂 jxl/brotli/highway）；
- 树内 175 个"多余文件"全部在 `xmp/` 下（XMP 构建残留，mtime 2026-09-19 23:49=zip 下载当夜），dng_sdk 子树零杂项 → SDK 源码零漂移。
- 剩余闭环：重编验证已排入 F1（design.md:85，含"仍败→最小壳"兜底）。

**B6 消解** — design.md:102-105；`.gitignore:85` 仅忽略 `_*`；实测 `git check-ignore`：`.artifacts/r31_three_arm.py`、`.artifacts/R31_dng_alignment.md` **不命中任何忽略规则（可入库）**，`_r31_*.py` 被忽略 → 入库路径可行。建议级残：§1:18 措辞未随 §6 降级（见残留-4）。

## 二、专项核验

**(1) §2 公式闭合性：通过。** 端到端 float 无二次量化（恒等实测）、u16→u8f 与 L×2.55/a+128 数学正确且与 OpenCV float Lab 语义一致（数值实测）、ΔE76 对齐属实——见 B1。

**(2) §3 判据无歧义 + F4 闭环：通过。** 每个量唯一可复算：Δ 定义（:45）、主判据量（:46"先逐片绝对值再跨片中位"）、分布总体（:47 有符号 Δ）、wb_B（:53）均唯一；阈值 5/3/3 与 R30 读数同为 OpenCV 8 位标度（自洽）；§4:75 引用 §3 闭环。余留两处建议级注记（B3/B4 尾部）。

**(3) 全文一致性互查——发现 2 处 v2 引入/遗留矛盾 + 2 处措辞不一致：**
- **矛盾 A**：§5:88 旧行"用其小尺寸渲染选项（预览 256/1024 路径在源码 435-450 行可见）"与 §5:86 新行"**禁用 -min/预览级渲染路径**（会降级为预览管线）"直接冲突（435-450 属 `-dng` 预览路径，对 `-t` 不适用，上轮已勘误）；§2:34"渲染尺寸选项按速度定并记录"同源过时。
- **矛盾 B**：§8 声明"`.artifacts/_r31_*` 为无关残留……下游以本声明为准"，而 §1:20/§0:10/§6:95 本轮脚本与交付物命名恰为 `_r31_*.py`——同 glob 自相矛盾（磁盘现存 `_r31_enabled_wiring_probe*.py`、`_r31_ruler_selfcheck.py`、`_r31_*.xml/log` 确为该声明对象，但本轮新建 `_r31_dng_render.py`/`_r31_three_arm.py`/`_r31_three_arm.json`/`_r31_refs/` 会命中同一 glob），下游可能误弃本轮产物。
- **不一致 C**：§1:18"与 R30 同一 pick() n=48"未随 §6:104"R30 探针已丢失⇒同 pick 算法重建"降级。
- **不一致 D**：§5:89（RT pp3 表述似无条件）与 §2:33（仅非 sRGB 时补，且记口径偏离）未对齐。
- 其余互查（§3↔§4、§6 交接物、§7 非目标、§9 修订记录）未见新矛盾；v2 未在数学/口径上引入新错误。

## 三、残留项（分级 + 最小修法）

- **残留-1【必改·BLOCKER 级残·一行】** design.md:33 `-d <Default.pp3>` → `-d`（无参）。证据：RT 官方帮助+handler。责任：队长。
- **残留-2【须修·中】** 删 design.md:88 全行（重复且矛盾的风险行）；design.md:34"渲染尺寸选项按速度定并记录"→"全分辨率渲染（见 §5：禁 -min/预览级路径）；尺寸选项记录"。
- **残留-3【须修·中】** §8 限定残留范围：列明"开工前既有" `_r31_*` 文件（或加时间限定），并声明本轮新建 `_r31_dng_render.py`/`_r31_three_arm.py`/`_r31_three_arm.json`/`_r31_refs/` 不在其列。
- **残留-4【建议】** design.md:18 加"（R30 探针已丢，按同 pick 算法重建，见 §6）"。
- **残留-5【建议】** design.md:89 与 :33 对齐条件性；"fresh 安装即 Neutral"改"预期 Neutral，装后核录"；补 RT portable zip 版本+sha256 口径（:84）。
- **残留-6【建议】** design.md:57 注明"逐片**有符号** ΔL"；:59/:75 各一句话写死"矫正后是否复检 Spearman"与"候选胜出排序规则"。
- （非阻塞备忘）上轮建议未采纳项可随报告批注：F4 拟合输入接口（建议-6）、F5 抽片复现量化（建议-7）、RT 结构化隔离（建议-4）、GPLv3 SPDX/台账同步（建议-5）、全量 4053 扩展落点（建议-8）。

## 四、复检结论

**有条件通过。** 存量 6 项 BLOCKER：**5 消解 + 1 部分消解（B2）**，未消解 0，新 BLOCKER 0；B2 的语法残留为 1 项 gating（一行修）。残留合计：必改 1 + 须修 2 + 建议 3，全部为文档级、合计 <10 行。

**条件**：完成残留-1~3 修订（分钟级），经 reviewer 复核这三处 → **即可签发 `.design_ok`，无需全文重审**；建议-4~6 与备忘项不阻塞签发。另请注意：F1 开工第一件事即"只编 vcxproj"重编验证（B5 物理前置已清净，重编是 B5 风险的最后闭环）。

---

# R31 复核签发记录（2026-09-22 · reviewer · design v2.1）

队长回传残留-1~3 + 建议三条已落实（design.md v2.1，§9:128 修订记录行在案）。reviewer 逐处 grep 复核（引擎复检已预授权"三处落位即签，无需重审"）：

- **残留-1 落位** ✓ design.md:32：`rawtherapee-cli -o <dir> -t -Y -d -c <file>`（注明"`-d` 为无参 flag"），`<Default.pp3>` 已除；
- **残留-2 落位** ✓ §5「小尺寸渲染选项 435-450 行」矛盾行整行删除（现表仅存 :85 禁 -min 行）；DNG 臂 :33 改"全分辨率渲染（见 §5：禁 -min/预览级路径），实际输出尺寸记录"；
- **残留-3 落位** ✓ §8:113-118：开工前既有时间限定 + 残留枚举 + 本轮新建产物白名单（`_r31_dng_render.py`/`_r31_three_arm.py`/`_r31_three_arm.json`/`_r31_refs/` + 入库物），glob 碰撞消解；
- **建议三条**：§1:18 可比性措辞 ✓、§3:56 Spearman 有符号 ΔL ✓；§5:87 pp3 行未逐字对齐（仍无条件表述）——建议级不阻塞，以 §2:32 条件口径为准，如实记入门禁非阻塞项；
- §2 公式块（:35-48）与 §3/§4/§6 相对 v2 零漂移。

**签发**：`.agent-team/.design_ok`（R31 签章，2026-09-22T11:11:41+0800，覆盖 F0-F5；R22 旧签章归档 `.design_ok.r22`）。下游 dev/junior/tester 可按 `team-manifest.md` 阶段 4 开工；F1 第一件事=只编 vcxproj 重编验证。
