# stream-3 (dev-3 · M1 流) 交接黑板

## F12 region_adjust stage —— 完成 (2026-09-07)

### 做了什么
- **新 Stage** `src/pixo/render/modules/region_adjust.py`：`@register_stage("region_adjust", order=57, domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)`（56-59 槽位空闲已复核：skin=55/stylize=60）。
  - param_schema：`enabled`(bool, default **False**) + `regions`(dict: prompt→{exposure EV[-2,2], saturation[-1,1]}，键缺省=0；允许键白名单 {exposure, saturation})。
  - **曝光实现选型 = 路线 a（gamma 域增益近似）**：`gain = 2^(ev/2.2)`，线性域等效 ≈ 2^ev。中间调（gamma 0.3..0.6，EV=±1）线性增益相对误差 <4%（单测钉死）；深阴影偏差增大（sRGB 分段幂 2.4 段 vs 纯幂 2.2）、高光 clip 兜底——设计 §2 倾向 a（意图级软区域），弃 b（线性化往返，全图两次幂运算）。
  - 饱和度 = HSV S 缩放（首版 hsv 内核，oklch 演进留下轮）：S'=clip(S*(1+sat),0,1)，中性像素 S=0 严格不受影响。
  - 掩码消费：`ctx.state["region_masks"]`（dict prompt→float 0-1 软掩码，**只消费不生产**，生产归 super-dev F13）；接受 HxW/HxWx1、分辨率不一致自动双线性缩放。
  - 羽化纪律：应用前高斯羽化 `sigma=clip(长边/512, 1, 8)`——相对过渡带宽度与分辨率无关（preview/export 同语义，F13 tier 口径差教训）；F13 的 masks_cache 二值 0/255 转浮点后经此保证无硬边（单测钉死二值阶跃掩码无 1px 全幅跳变）。
  - 多区域按 regions 声明序顺序软合成 `out = out*(1-m) + adjusted*m`（skin_smooth 同款线性混合纪律）；同区域先曝光后饱和。
  - wants 门控：enabled=False / regions 缺失空 / state 无 region_masks（非 dict 或空）/ 无任一「掩码存在+参数非全零」区域 → False（静默）；区域级掩码缺失在 process 内静默跳过。
  - 零效果守卫：exposure=saturation=0 或掩码全零 → 不 set_image（"未写即未变"，run 后验允许恒等直通）。
  - 指标：`result.metrics["regions_applied"]` + `result.metrics["mask_coverage"]`（F14 decide 闭环验证观测位；直接调 process 无 results 时静默略过）。
- **进链**：`presets.py` DEFAULT_STAGES 在 skin 后 stylize 前插 `"region_adjust"`（14→15 段）；`params.py` STAGE_CLASSES 登记（PARAM_SCHEMAS/DEFAULT_PARAMS 自动派生）；`modules/__init__.py` 加 import+导出（**必要注册线**：build_default_pipeline 靠 `from pixo.render import modules` 触发装饰器注册，缺此行未 import params.py 的链路会 KeyError——见「范围外改动」节）。
- **默认零影响**：沿 dehaze t108 先例（先读 reshape.py 确认口径：默认 enabled=False + wants 门控 + 进链给点分参数执行位）。链级证据=单测 `test_default_off_full_chain_bit_identical`：默认链 ±region_adjust 输出逐位一致。

### 改了哪些文件
| 文件 | 改动 |
|----|----|
| `src/pixo/render/modules/region_adjust.py` | **新增**（stage 主体） |
| `src/pixo/render/pipeline/presets.py` | DEFAULT_STAGES 插入 region_adjust（skin 后 stylize 前）+注释 |
| `src/pixo/render/params.py` | import + STAGE_CLASSES 登记 |
| `src/pixo/render/modules/__init__.py` | 加 `from . import region_adjust` + `RegionAdjustStage` 导出（注册触发，见下） |
| `tests/unit/test_region_adjust.py` | **新增**（30 用例） |
| `tests/unit/test_phase1_chain.py` | DEFAULT_STAGES 钉死断言 14→15 段同步（原断言与新链互斥，机械修订） |
| `tests/unit/test_pipeline.py` | 同上（test_default_stages_contains_huesat 列表同步） |

### 范围外改动（报告，待 qa/队长追认）
1. **`modules/__init__.py`** 不在文件域清单内，但属注册机制必要一环：进链的完成标准要求「stage 注册全链冒烟」，而默认管线注册触发点就是 `import pixo.render.modules`；不加此行，凡未经 `render.params` 的路径（如 patch_protocol L37、loop L326）region_adjust 不在 STAGE_REGISTRY → `build_default_pipeline` 直接 KeyError。改动仅 import+__all__ 导出两行。
2. **两个既有测试的钉死断言修订**（test_phase1_chain.py / test_pipeline.py）：DEFAULT_STAGES 精确列表断言与任务书强制的进链互斥，按仓库惯例（F07/F10 缺省断言随缺省变化修订）同步，仅列表与计数，未动其他断言。

### 如何验证（命令+输出摘要）
```
python -m pytest tests/unit/test_region_adjust.py -q
  → 30 passed in 0.74s
python -m pytest tests/unit/test_phase1_chain.py tests/unit/test_pipeline.py \
  tests/unit/test_pipeline_config.py tests/unit/test_colorcal_direction.py -q
  → 55 passed in 0.91s
python -m pytest tests/unit/test_skin.py tests/unit/test_hsl.py tests/unit/test_split_tone.py \
  tests/unit/test_patch_protocol.py tests/unit/test_film_cards.py tests/unit/test_enhance.py \
  tests/unit/test_exposure.py tests/unit/test_refine.py -q
  → 126 passed in 1.78s
python -m pytest tests/unit/test_loop_param_mapping.py tests/unit/test_loop_replay.py \
  tests/unit/test_renderer_adjust.py tests/unit/test_scene_presets.py tests/unit/test_intents.py \
  tests/unit/test_render_public_adapters.py tests/unit/test_film_cards_oklch.py -q
  → 102 passed in 1.95s
python -m pytest tests/unit/test_loop_aesthetic.py tests/unit/test_loop_termination.py \
  tests/unit/test_pipeline_runner.py tests/unit/test_phase_e.py tests/unit/test_gate_golden_tool.py \
  tests/unit/test_tech_debt_invariants.py -q
  → 30 passed in 1.90s
```
定向合计 **343 passed / 0 failed**（全量回归留队长统一执行）。

30 个新用例覆盖设计完成标准四件套：
- 合成掩码数值断言：EV∈{-2,-1,-0.3,0.3,1,2} 逐像素精确 `0.5*2^(ev/2.2)`；线性域等效增益 <4%；单调+高光 clip；sat 方向/clip/中性不变；m=0.5 线性混合钉死；掩码外逐位不变
- enabled=False 零影响：默认参数全链 ±region_adjust 逐位一致（t108 口径）+ wants False
- wants 门控：enabled/regions 缺失/掩码 state 缺失/prompt 无掩码/零效果参数，共 7 用例
- 注册全链冒烟：order=57+域契约+56-59 空槽+params 三表登记+DEFAULT_STAGES 位置+非法参数 ValueError（未知键/非 dict/非数值/EV 与 sat 越界）

### 遗留问题
1. **F13 依赖（对 super-dev）**：契约键 `ctx.state["region_masks"]` = dict prompt→float 0-1 软掩码已按本实现消费；HxW/HxWx1、任意分辨率均可（自动缩放+羽化）。preview/export 掩码分辨率不一致时羽化 sigma 按长边相对缩放，两侧过渡带宽度一致——建议 F13 侧掩码上采样口径与此对齐验证。
2. **F14 接线注意（对 dev-3 自己/下任务）**：`regions` 已在 param_schema（type:"dict"，graph 校验器不支持嵌套 dict，结构校验在 stage `_regions()`，非法 ValueError）；`region.<prompt>.<param>` 双点分键不合 patch_protocol 单点分形态，F14 需走 `_apply_decide_params` 特例（design F14 已预判）。enabled=True 联动沿 dehaze 模式。
3. **深阴影近似偏差**（路线 a 已知取舍，非缺陷）：gamma<0.25 区域 EV 线性等效误差 >5%（实测 0.15 处 ≈11%）；如后续验收在意，可按区域加阴影保护或切路线 b，本轮不动。
4. gate case（enabled=True+合成掩码快照）在 F15（gate_cases.py 现归 dev-2/F08 禁碰窗口）；render/README.md 模块清单同步也在 F15 清单。
5. 本轮未 commit（提交策略归队长按依赖序分批）。

---

## F14 decide region.* 接线 —— 完成 (2026-09-07)

### 做了什么
- **键映射特例**（`src/pixo/pipeline/loop.py`，注册表/联动区，未碰掩码区）：`_DOTTED_PARAM_REGISTRY` 的 `("stage","param")` 二元组装不下 `region_adjust.regions[prompt][param]` 两级嵌套，按 design §2 F14 预判在 `_apply_decide_params` 加 `region.<prompt>.<param>` 前缀特例分支：
  - 嵌套写入 `region_adjust.regions[prompt][param]` + **enabled=True 联动**（沿 :567-570 dehaze 同区同款模式）；
  - **越界值映射侧钳制**（exposure [-2,2] / saturation [-1,1]，与 stage param_schema 同域）——stage `_regions()` 对越界 raise ValueError，渲染链不能因规则输出越界而炸；
  - 畸形键（段数≠2 / 空 prompt / 未知参数名如 hue）不吞：走既有"无执行位 informational 顶层保留+warning"路径；桶链被占非 dict 退回扁平键（t51 同款）；
  - 大小写统一（沿既有 `low=str(key).lower()` 口径）。
- **指标键宇宙补缺**（decide/engine.py `register_metric_keys` :449 的生产侧首次接线）：`SinglePhotoLoop.__init__` 注册完整生产 flatten 宇宙——`_metrics_for_decide` 全部固定键（mean_luminance/highlight_clip_ratio/shadow_clip_ratio/contrast/preview_highlight_clip_estimate/preview_overflow_ratio/haze_proxy/colorfulness_proxy/tonal_range）+ loop 上下文键（crop_suggestion_applicable）+ 按 `self.prompts` 的区域四键（`<prompt>_{luminance,area_ratio,highlight_clip_ratio,reliable}`）。
  - **关键教训（全量 unit 跑出）**：键宇宙一旦非空 load_rules 全进程走 strict lint（t59/t40 守卫设计如此），**只注册 region 键会让默认规则包加载即炸**（tone_clarity 的 condition.all 引 haze_proxy/tonal_range，test_tone_clarity_rules 14 errors）——首次实现犯了这个错，改为注册完整宇宙后归零，并加了回归钉死测试（`test_default_rules_still_lint_after_loop_construction`）。
- **首版规则 YAML 2 条**（`src/pixo/decide/rules/region_rules.yaml`，`configs/rules/` 按镜像惯例存同内容副本）：
  - `region_sky_exposure_001`：sky_luminance > 150 → `region.sky.exposure` 比例负补偿（`-0.5*(current/150)`，clamp [-2,0] 只压不升）；
  - `region_plant_exposure_002`：plant_luminance < 70 → `region.plant.exposure` 比例正提亮（`0.4*((70-current)/70)`，clamp [0,2] 只升不降）；
  - 均为 mode=set 确定性语义（多轮不累积）；公式只引 `current`（runtime 变量，lint 天然通过）。**未加入 DEFAULT_RULES**（基座默认行为不变的保守选择，入默认包留 qa/门禁批准）。
- **F12 尾巴清偿**：`tests/unit/test_build_project_graph.py::test_real_repo_graph_invariants` 的 DEFAULT_STAGES 钉死断言补 region_adjust（14→15 段，与 test_phase1_chain/test_pipeline 同款机械修订）。

### 设计陷阱确认（hard-problems.md §降维交接）
- **post-compose 坐标系**：decide 写的 region.* 只落 params dict，不碰掩码数组——掩码坐标适配完全在 super-dev 的三注入点/适配器内，本改动零接触；
- **缓存指纹**：`regions` 映射产物是纯 float 标量嵌套 dict，JSON 可序列化（有测试钉死 `json.dumps` 往返）——ndarray 只走 `ctx.state["region_masks"]` 通道，永不进 params，`_param_fingerprint` 不受影响。

### 改了哪些文件（F14 增量）
| 文件 | 改动 |
|----|----|
| `src/pixo/pipeline/loop.py` | `_REGION_*` 常量 + `_apply_decide_params` region 分支 + `__init__` 指标键注册（注册表/联动区；掩码区未动） |
| `src/pixo/decide/rules/region_rules.yaml` | **新增** 2 条规则 |
| `configs/rules/region_rules.yaml` | **新增** 镜像副本（逐字一致有断言） |
| `tests/unit/test_decide_region_wiring.py` | **新增** 17 用例 |
| `tests/unit/test_build_project_graph.py` | F12 尾巴：DEFAULT_STAGES 断言补 region_adjust |

### 如何验证（命令+输出摘要）
```
python -m pytest tests/unit/test_decide_region_wiring.py -q
  → 17 passed（含 e2e 闭环 2 条）
python -m pytest tests/unit -q -m "not e2e"
  → 1276 passed / 3 skipped / 1 xfailed / 0 errors（89s）
python -m pytest tests/unit/test_loop_param_mapping.py tests/unit/test_loop_termination.py \
  tests/unit/test_loop_aesthetic.py tests/unit/test_loop_replay.py tests/unit/test_decide.py \
  tests/unit/test_decide_formula_guard.py tests/unit/test_tone_clarity_rules.py \
  tests/unit/test_build_project_graph.py tests/unit/test_region_adjust.py \
  tests/unit/test_region_masks_channel.py tests/unit/test_phase1_chain.py \
  tests/unit/test_pipeline.py tests/unit/test_pipeline_config.py tests/unit/test_patch_protocol.py \
  tests/integration/test_export.py -q
  → 236 passed（loop/decide/F12/F13/export 邻域全绿）
```
**e2e 闭环证明**（`test_e2e_region_rule_closed_loop`，真 SinglePhotoLoop.run + 真 decide + 真映射 + 真 region_adjust 消费）：
1. decide 事件 rule_ids 含 region_sky_exposure_001；2. `result.params["region_adjust"]={enabled:True, regions:{sky:{exposure:<0}}}`；3. 施加区域调整后的测量 sky 亮度较首轮下降 >5（掩码→测量→决策→渲染→测量全环）。像素级局部性用例另证：掩码核心区变暗、远离羽化带地面行逐位不变。

17 用例覆盖：映射 8（嵌套+联动/多区域共存/钳制/畸形不吞/桶占退扁/覆盖语义/JSON 序列化）+ 指标键 3（注册/公式 lint 放行/默认包 strict 回归）+ YAML 4（双源一致/触发方向/阈值不触发/方向钳制）+ e2e 2（闭环/像素局部性）。

### 遗留问题
1. **region_rules 未入 DEFAULT_RULES**：保守选择，基座行为零变化；入默认包（任何带掩码渲染的默认 decide 都会开始写 region 键）属行为默认变更，建议队长/qa 门禁裁决。
2. **exposure 限流器波及 region.exposure 键**（既有语义非本次引入）：decide 引擎 `_is_exposure_param` 按 `"exposure" in param` 判定，`region.sky.exposure` 命中——preview 溢出率 ≥2.5% 时该键正向提亮会被压回（负向不受限）。对天空压暗场景无影响；若未来需要"溢出下仍允许区域提亮"需 decide 侧特判，本轮不动。
3. **region 键的 delta 累加基线恒 0**（v1 已知）：decide `_current_param` 读不到嵌套 `regions[prompt][param]` 现值，delta 模式每轮从 0 起算；首版两条规则用 mode=set 语义规避。若后续规则需要 delta 累加，需 decide 侧 `_current_param` 加嵌套路径解析（届时连 `_flatten_decide_params` 的 region_adjust 桶透传一起改）。
4. F15 待办不变：gate case（gate_cases.py 仍禁碰）、harness samples.py regions 展开、render/README.md 模块清单。
5. 本轮未 commit（提交策略归队长）。

---

## F15 M1 验收资产 —— 完成 (2026-09-07)

### 做了什么
1. **gate case**（`tests/regression/goldens/gate_cases.py`，F08 已解禁）：
   - `FEATURES` 追加 `"region_adjust"`（19→20）；
   - `_run_full_pipeline` 加可选参 `region_masks`（缺省 None，既有 default_dispatch/card_portra_400 两 case 行为逐位不变）——注入 `ctx.state["region_masks"]`，即 F12/F13 消费契约的唯一注入面；
   - 新增 `_region_soft_mask()`：顶部 50% 全 1 → 12.5% 高度 smoothstep 过渡到 0（F13 契约同款 float32 0..1 软掩码，禁硬边，确定性纯函数）；
   - `compute("region_adjust")`：enabled=True + sky 区域 exposure=-0.6（gamma 域增益 2^(-0.6/2.2)）+ saturation=-0.15（HSV S 缩放）经真实 DEFAULT_STAGES 链序（skin 后 stylize 前）快照。**负向选型避开两处 clip 分量**（V≤1 与 S≤1 饱和段会让"参数→像素"映射变平，削弱对内核常数的敏感度）。契约：内核常数/羽化宽度/enabled 耦合任一漂移即翻红。
   - 基线生成：`_entry_for` 同款工具写 `region_adjust.npy`（64×64×3 float32，sha256 `afbd7ebe…73c8`），compute 两次逐位一致（确定性自检）+ 效果健全性（掩码区 -0.169 vs 零参基线）。
   - **manifest 外科式插入**（沿 F08 先例）：只在 `card_portra_400` 后追加 region_adjust 条目，**既有 19 条目与 reviewer 字段一字未动**；`generate_gate_goldens.py --check` → `CHECK: OK（20 features 与现有 manifest 一致）`。
   - **已知现象（记录，非缺陷）**：链级快照中远离掩码的地面行与零参基线不逐位相等（~1e-5 量级）——region_adjust(57) 之后的 refine(70) 空间滤波把羽化带微差外溢；stage 级"掩码外逐位不变"已由 F12 单测钉死，链级快照的确定性（金样本的全部要求）不受影响。
2. **gate 断言同步**（`tests/regression/test_gate_golden.py`）：`len(features) == 19` → `20` + 注释补 F15 行。
3. **harness samples.py regions 适配**（`src/pixo/harness/goldens/samples.py`）：`compute_expected_metrics` 的区域键展开补 `regions.<name>.highlight_clip_ratio`（face/sky/plant）——与 decide 键宇宙的 `<name>_highlight_clip_ratio`（loop flatten 键，region.* 规则族引用面）对齐。**向后兼容**：compare 只遍历 manifest 声明的期望键，既有 `data/golden/reference/harness/golden_manifest.json` 缺新键不受影响，下次重生成 manifest 时自然带上。
4. **render/README.md 模块清单**：modules 计数 16→18（18 个文件）+ 清单补 `region_adjust.py`（skin 后 stylize 前）。

### 改了哪些文件（F15 增量）
| 文件 | 改动 |
|----|----|
| `tests/regression/goldens/gate_cases.py` | FEATURES + `_region_soft_mask` + `_run_full_pipeline` 可选 masks 参 + compute region_adjust 分支 |
| `tests/regression/goldens/gate/region_adjust.npy` | **新增** 基线 |
| `tests/regression/goldens/gate/manifest.json` | 外科式追加 1 条目（reviewer/既有条目未动） |
| `tests/regression/test_gate_golden.py` | 断言 19→20 + 注释 |
| `src/pixo/harness/goldens/samples.py` | regions 键展开补 highlight_clip_ratio |
| `src/pixo/render/README.md` | 模块清单加 region_adjust + 计数修正 |

### 如何验证（命令+输出摘要）
```
python -m pytest tests/regression -q -m "gate and not gate_e2e"
  → 64 passed（gate 全层 L0/L1/L2 绿; 含 test_gate_golden 4 用例 =
    manifest schema/20 守卫 + 文件 sha256 一致 + --check 零漂移 + 逐 feature 快照比对）
python tests/regression/goldens/generate_gate_goldens.py --check
  → [gate_goldens] CHECK: OK（20 features 与现有 manifest 一致）
python -m pytest tests/regression/test_goldens_v0.py tests/unit/test_gate_golden_tool.py -q
  → 16 passed（harness 金样本基础设施 + RAW gate 工具）
python -m pytest tests/unit/test_region_adjust.py tests/unit/test_decide_region_wiring.py \
  tests/unit/test_phase1_chain.py tests/unit/test_pipeline.py tests/unit/test_loop_param_mapping.py \
  tests/unit/test_loop_termination.py tests/unit/test_build_project_graph.py \
  tests/regression/test_gate_compose.py -q
  → 131 passed（F12/F14/链序邻域回归）
```

### 遗留问题
1. **基线 reviewer 复核**：region_adjust 基线由 dev-3 生成（沿 F08 先例的未提交外科式新增），manifest.reviewer 保持原文未动——按门禁惯例由 reviewer/qa 复核基线后随批次合入。
2. **harness golden manifest 重生成**：`regions.<name>.highlight_clip_ratio` 新键将在下次 `generate_manifest.py` 重生成时进入基线（本轮不重生成，避免批次外基线变更）。
3. dev-3 流（F12→F14→F15）至此全线完成；M1 剩余面（gate_e2e 层若需 region 闭环、decide 闭环的 L3 观测）不在本轮 F15 范围。

---

## M1 评审修复批 —— 完成 (2026-09-07)

> 对应 `.agent-team/reviews/m1-review.md`（阻断 0 / 重要 4 / 建议 8）。必修 4 项全修、小修 3 项全修、记债 1 项落账；建议项 S-4/S-6/S-7/S-8 按裁决留遗留（不在本批）。

### 逐项处置与验证证据

| 编号 | 处置 | 落点 | 验证 |
|----|----|----|----|
| I-3 NaN 穿透 | **已修** | `region_adjust.py`：`_prepare_mask` 加 `np.isfinite(m).all()` 守卫，非有限值抛新 `MaskContentError(ValueError)`；`process` 捕获链**先** `MaskContentError`（warn+跳过该区域，与降级声明一致）**后** ValueError（形态违约仍显式 raise，语义二分不清） | `test_nan_mask_degrades_to_skip_without_pollution`：单点 NaN 掩码 → 输出 `np.isfinite().all()` 为真、ok 区域增益正常、坏区域无作用（修复前 NaN 污染整帧，reviewer 探针复现） |
| I-4 顺序合成未钉死 | **已修** | `test_region_adjust.py::test_overlapping_regions_sequential_semantics`（重写替换原 test_overlapping_regions_deterministic） | 三重断言：(a) 两次运行逐位一致；(b) regions 声明序反转 → 结果不同（`not array_equal`）；(c) 公式级：仅 A 区 = `clip(img*gA)`、重叠内区 = `sat(A 输出, -0.6)`——B 施加于 A 的输出而非原图 |
| I-1 掩码构图变化不失效 | **已修（保守版）** | `loop.py`：`_compose_fingerprint()`（compose 参数规范 JSON，空=“”）+ `_sync_region_masks()`（指纹变化→清空 `_region_masks_soft` + warn-once）+ 三个注入点（迭代渲染 :1248 / box 即时同步 :956 经 `_build_crop_suggestion` 新增 params 参透传 / FINAL_QC :1651）统一经同步；掩码清空后 region_adjust wants 静默直通。重分割/坐标重映射留 v2 | `test_sync_region_masks_invalidates_on_compose_change`（首轮建基线不清不警；变化→清空+warn 一次；warn-once 门闩）+ `test_e2e_crop_adoption_drops_region_masks`（真 SinglePhotoLoop + monkeypatch suggest_crop + 采纳规则：crop 采纳后次轮渲染 state_extras **无 region_masks**——区域效果消失而非作用错区域） |
| S-5 规则可靠性门控 | **已修** | `region_rules.yaml` 两镜像：condition 改 `all` 型，AND `sky_reliable==true` / `plant_reliable==true` | `test_unreliable_region_blocks_rule`（reliable 缺失/False → 规则不触发，亮度超阈亦然）+ 既有触发用例补 reliable:true 全绿 |
| S-2 resize 核不一致 | **已修** | `_prepare_mask`：下采样 INTER_AREA / 上采样 INTER_LINEAR（与 F13 适配器同语义同判据） | 既有 `test_mask_resolution_mismatch_resized`（上采样路径）绿；gate 基线零漂（同分辨率掩码不走该分支，`--check` OK） |
| S-3 限幅常量双份 | **已修** | `region_adjust.py` 新公开 `REGION_PARAM_LIMITS`（单源）；`loop.py` 删 `_REGION_PARAM_LIMITS`，region 分支内懒 import 复用（沿 loop 对 render 子模块惰性导入惯例） | `test_region_key_out_of_range_clamped` 绿（钳制行为不变，常量同源） |
| S-1 sigma 声明修正 | **已修（声明）** | `region_adjust.py` 模块 docstring + `_FEATHER_REF` 注释：限定“相对过渡带分辨率无关”仅在长边 512..4096 近似成立，clamp 两端理由（<512 亚像素羽化无意义、>4096 核成本平衡）；顺手改测试文件头注 “<6%”→“<4%” 与断言一致 | 文档/注释变更，行为断言不动 |
| 组合路径单测（评审建议补） | **已补** | `test_exposure_then_saturation_combined_path`：公式级钉死“增益（不经中间 clip）→ HSV S 缩放 → 区域末尾一次 clip”的现实现语义 | `atol=1e-6` 全图通过 |
| I-2 px-rect 跨分辨率失配 | **记债** | `docs/tech_debt.md` **条目 17**：根因（compose free 像素矩形）+ 掩码通道放大效应（落点错位可达 10%+ 画幅宽）+ F13“两线一致”论断限定 ratio/full-frame 路径 + 升级 hard-problems §6.1 优先级 + I-1 时间性防线交叉引用；`test_region_masks_channel.py::test_free_px_rect_cross_resolution_geometry_mismatch_recorded` 钉现状（两线掩码逐位相同 × 相对裁剪窗 50% vs 25% 失配；断言文案注明清偿时须有意翻转重写） | 23 passed（22 旧 + 1 新） |

### 修复批验证（命令 + 输出摘要）
```
python -m pytest tests/unit/test_region_adjust.py -q                  → 32 passed
python -m pytest tests/unit/test_decide_region_wiring.py -q           → 21 passed
python -m pytest tests/unit/test_region_masks_channel.py -q           → 23 passed
python -m pytest <loop/decide/链序 邻域 13 文件> -q                    → 221 passed
python -m pytest tests/regression -q -m "gate and not gate_e2e"       → 64 passed
python tests/regression/goldens/generate_gate_goldens.py --check      → CHECK: OK（20 features 一致，region_adjust.npy 基线零漂）
python -m pytest tests/unit -q -m "not e2e"                           → 1286 passed / 3 skipped / 1 xfailed / 0 errors
```
新增测试 **+7**（region_adjust +2：NaN 降级探针、组合路径；wiring +4：指纹、同步失效、S-5 门控、crop 采纳 e2e；masks_channel +1：px-rect 钉现状）；gate 基线与 manifest 未动。

### 遗留（按裁决记债/留后，未修）
- S-4 限流器波及 region.* 曝光键：region_rules.yaml 已留注释痕（未入默认包无生产影响），引擎豁免随规则激活决策一起定；
- S-6 export 线全图工作集内存（bbox 裁剪优化留 v2）；S-7 stage 缓存命中时 metrics 丢失（观测性）；S-8 preview_overflow_ratio 双键别名（既有命名统一）；
- I-1 v2：compose 变化后重分割/坐标重映射（本轮保守清空直通）；I-2 主体：compose px→相对坐标归一化（独立战役）。
