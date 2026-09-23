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
