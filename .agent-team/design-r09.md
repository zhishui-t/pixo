# 设计文档（design.md）— Pixo 第九轮战役

> 队长执笔 2026-09-07；输入=三份侦察报告（oklch 链路 / M1 接线点 / 清债调用点）+ `.artifacts/oklch_default_eval.md`（t52）+ `.artifacts/hsm_oklch_eval.md`（t64）。qa 审核修订后盖 `.design_ok`。

## 1. 功能清单与开发流

| 流 | 角色 | F-ID |
|----|------|------|
| stream-1 清债流 | dev-1 | F03 → F04 → F05 |
| stream-2 oklch 流 | dev-2 | F07 → F08 → F09 → F10 → F11 |
| stream-3 M1 流 | dev-3 | F12 → F14 → F15 |
| 攻坚 | super-dev | F13（+ warm_sat native spike，F05 决策输入） |
| 门禁 | qa | F02、F06、设计审核、专项门禁、总审 |
| 测试 | tester | M1 测试、F10 回归、全量执行 |
| 调研 | researcher | F18、F16 素材、F19 提案（可选） |
| 文档 | writer | F01、F17、F20 |
| 评审 | reviewer | M1 代码独立评审 |

## 2. 各功能设计

### F03 FairFace 彻底移除（dev-1）
删除面（侦察确认，唯一运行时下游是 health 聚合，无业务依赖）：
- 删整文件 `src/pixo/vision/person.py`（FairFaceAge/PIXO_FAIRFACE_MODEL/get_fairface_age/fairface_health_info）
- `src/pixo/vision/health.py`：去 L15 import + L168/187/188/195 的 fairface/fairface_age 键
- `src/pixo/vision/__init__.py`：去 L47 导出 + L66-68 `__all__` 三符号
- `src/pixo/manifests/vision_models.json`：删 fairface-onnx 条目（L30-41）
- 测试：`tests/unit/test_vision_extras.py`（L16/29/58-60/68-71 相关断言删）、`test_vision_router_semantics.py`（L252-287 懒加载/单例三用例删）、`test_vision_manifests.py`（L19 断言改为 not in）
- 文档：`docs/LEARNED_BACKEND_GOVERNANCE.md` L27 env 示例去 PIXO_FAIRFACE_MODEL（换现存示例）
- **历史评审文档（PIXO_LICENSE_REVIEW.md 等）不改写历史**，仅在 tech_debt 台账记录移除事实
- 完成标准：`grep -ri fairface src/ tests/ configs/` 零命中；定向测试绿（vision 域）

### F04 gsam 彻底移除（dev-1，F03 后）
- 删整文件 `src/pixo/vision/segmenters/grounded_sam.py`
- `multi_router.py` 兜底语义重设计：`DEFAULT_ROUTE="gsam"`（L42-43）与 `_get()` gsam 分支（L141-143）删除；**未知/未命中 prompt → zeros_mask 零掩码降级 + warn-once**（守 exceptions.py 降级契约，与禁用后端同语义）；`routed_backend_names()` docstring、warmup（L249 已跳 disabled，删 gsam 分支）相应更新
- `model_licenses.json` 删 grounding-dino-tiny+sam-vit-base 条目（L56-64）
- `resources/models/models_reference.json` L7 描述更新
- `pyproject.toml`：`pixo-vision-models` extras（torch/transformers）**保留不删**——qa 抽查实测其非 gsam 专用：`segformer_scenes.py:47-48` / `uniface_face.py:40-41` / `sapiens_body.py:171-172` 均直接懒 import torch+transformers，`aesthetic.py:148-150`（CLIP 评分器）同样依赖；rfdetr 走 rfdetr pip 包（自带 torch 链）。F04 仅清理安装说明/文档中把该 extras 描述为 gsam 专属的措辞（如有），依赖归属证据记入 stream-1.md
- 测试重写（非删除）：`test_multimodel_segmenter.py` L74-107 禁用降级用例改为「gsam 不存在时未知 prompt 零掩码+warn」语义；`test_vision_router_semantics.py` L290-298 默认关断言改不存在断言；`test_sapiens_body.py` L81-82 引用清理
- 文档惯例引用更新：LEARNED_BACKEND_GOVERNANCE.md 的 PIXO_GSAM_ENABLED 示例（换 PIXO_SEGMENTER 等）
- 完成标准：`grep -ri "gsam\|grounded_sam" src/ tests/` 零命中；multi 路由 4 后端测试绿

### F05 lr_baseline 处置（dev-1，F04 后；调查+建议，队长裁决执行）
- 调查启用面：`resources/dcp/manifest.json` default_lr_preset → `configs/styles/lr_baseline.json` 的实际加载路径（哪些渲染/什么条件命中）；`refine` stage `apply_warm_sat_gamma` u8 HSV 往返 0.57-0.90 ΔE（W4 实测）
- 三选一给证据：a) float 化（沿 colorcal float 模式）b) native 化（借 LUT 内核模式，super-dev spike 输入）c) 记技术债（若启用面窄/影响小）
- 产出：streams/stream-1.md 内处置建议节；若结论=记债，同步 docs/tech_debt.md 新条目
- 完成标准：调查报告含启用面证据+决策建议，队长裁决后落地或入台账

### F06 RAW 金样本重验（qa，F10 前）
- 命令：`python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512`
- 期望：4 features（wb_as_shot_default/exposure_auto_default/compose_param/clarity_default）× 6 样本全 PASS（u8 max|Δ|≤1/255；compare 先做基线 sha256 校验）
- 产出：`.agent-team/golden-reverify.md`（逐 case 结果+sha256 校验+结论+manifest reviewer 字段更新建议：`t108-auto-verified (主代理复核, 待用户终审)` → `qa-reverified 2026-09-07`）
- FAIL 处置：区分样本缺失（FAIL 缺失）vs 真漂移（FAIL 阈值）——真漂移即阻断 F10，报告队长
- 完成标准：报告落盘+manifest 更新（或更新建议留队长执行）

### F07 存量卡钉 hsv（dev-2）——oklch 前置修补 a
- **卡 JSON 直接补域**（数据层显式，弃加载层注入）：23 张存量卡（`configs/styles/films/*.json`，排除 2 张 oklch_demo）中凡带 hsl 键的 12 张补 `hsl.color_domain:"hsv"`；带 split_tone 键的 12 张补 `split_tone.color_domain:"hsv"`；带 skin 键的 22 张补 `skin.color_domain:"hsv"`（qa 实测：22 张带 skin 键、其中 17 张 enabled=true——钉域口径统一为「凡带键即钉」，不变量无特例且未来启用即已受保护；t52 §3.2 的 18=same 口径在 f4a51db 后为 17，仅计 enabled 不敷使用）；带 colorcal 键的 23 张补 `colorcal.color_domain:"hsv"`（计数均 qa 2026-09-07 实测）
- `tests/unit/test_film_cards_oklch.py` 不变量改写：`test_legacy_cards_untouched_no_domain_keys`（L93）→ 新不变量「全部存量卡凡带涉域 stage 键即显式钉 hsv」（含逐卡断言）
- 完成标准：新不变量绿；**渲染逐位不变**（改卡前后各渲染 1 张金样本路径对比，或断言 graph.py 参数合并后 default_params 键值等价——dev-2 选实现，留验证证据）

### F08 gate 缺省分派 case（dev-2）——oklch 前置修补 b
- `tests/regression/goldens/gate_cases.py` 新增 case：
  1. **缺省分派 case**：合成图（沿 gate 现有种子随机图 `default_rng(20260820)` :69 模式）走 Stage 缺省（不显式传 color_domain）全管线快照——堵「翻转 default_params 后 gate 零敏感性」盲区（17→18）
  2. **存量卡全管线 golden**：kodak_portra_400（或同批代表卡）全管线渲染快照——卡级 A1 在金样本层可观测（18→19）
- 新增 case 的初代基线由 dev-2 生成（generate），qa 复核；`test_gate_golden.py` 断言数同步（35 行附近）
- 完成标准：gate 断言 19 features 全绿；两新 case 基线入 `tests/regression/goldens/gate/`
- **文件域**：gate_cases.py dev-2 期间 dev-3 禁碰（DAG 时序互斥）

### F09 patch_protocol 同源化（dev-2）——oklch 前置修补 d
- `src/pixo/agent/patch_protocol.py`（注意路径在 agent/ 非 pipeline/）L118 `band.get("domain", "hsv")`：无 domain 键 band 的硬编码 "hsv" 归属 → 与 Stage 缺省同源（从对应 Stage 类读 default_params()/常量，禁复制字面量；L104-117 为该函数 docstring/入口区）
- `src/pixo/render/web/session.py` L443 canonical 参数面：确认 color_domain 已透出（若未透出补上）；前端类型确认（如 canonical schema 有变化）
- 完成标准：单测钉死「patch 校验归属 == 运行时分派归属」；切换 F10 后该测试仍同源成立

### F10 oklch 第一批切换：hsl+split_tone（dev-2，F06/F08/F09 后）——最高危
- 落点仅两行：`modules/hsl.py:34` 与 `modules/split_tone.py:38-43` 的 default_params `color_domain:"hsv"→"oklch"`
- 同步修订缺省断言：t52 §3.4 的 5 项缺省断言是**四阶段全翻**口径，本批只翻 hsl+split_tone，预期红且需修订的仅其相关 4 项（test_hsl_oklch / test_split_tone_oklab 各 2 项）；skin 那 1 项（test_skin stage domain）不翻不红不动。行为级 6 项预期被 F7 卡锚定 + skin/colorcal 不翻消除——若仍有行为级 fail 逐项分析报队长
- 验证链（qa 专项门禁）：
  a) 全量测试绿（修订后）
  b) 存量卡渲染逐位不变（F8 的卡 golden 在切换前后输出一致——A1 证明）
  c) RAW 金样本复跑绿（默认路径不涉 hsl/split_tone 非零参数，预期零漂移）
  d) 缺省分派 case 基线 v2 重生成（**队长单点执行**，留 v1→v2 对比证据——这正是该 case 的观测目的）
- rollback：单 commit `git revert` 即恢复逐位现状
- 完成标准：上述 4 项证据齐 + qa 专项门禁落 `.f10_ok`

### F11 skin+colorcal 意图级 A/B（dev-2，不切换）
- 口径：沿 ab_intent_report.md「不劣于」意图级 A/B（非像素 diff）；对象：skin 掩码域（cv2-Lab 椭圆 vs OKLab 椭圆——现仅拟合证据）+ colorcal float Python 路径（oklch 下 native 旁路）
- 语料：金样本 6 张 + 合成代表图（成本可控；54 张全量视时长选做）
- 产出：`.artifacts/skin_colorcal_oklch_ab.md`（决策数据，供下轮 go/no-go）
- 完成标准：报告落盘，明确「不劣于/劣于」结论 per 维度

### F12 region_adjust stage（dev-3）——M1 主体
- 新文件 `src/pixo/render/modules/region_adjust.py`：`@register_stage("region_adjust", order=57, domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)`
- param_schema：`enabled`(bool, default **False**) + `regions`（dict: prompt → {`exposure`: float EV[-2,2], `saturation`: float[-1,1]}）；无 regions 时 wants=False
- process：读 `ctx.state["region_masks"]`（dict prompt→float 0-1 软掩码，F13 通道）；逐区域：曝光=gamma 域增益近似（`gain = 2^ev` 的 sRGB gamma 域等效缩放）、饱和度=HSV S 缩放（**首版 hsv 内核**；oklch 域演进留下轮，避免与 stream-2 战场重叠）；掩码羽化沿 skin stage 掩码纪律（平滑作用区，禁硬边）
- **曝光实现二选一**（dev-3 探索既有 kernel 后定，验收=数值合理性+单测钉死）：a) gamma 域近似缩放（快）b) 线性化往返（精确，成本高）；design 倾向 a（意图级调整，soft 区域）
- 进链：`presets.py` DEFAULT_STAGES 在 skin 后 stylize 前插 "region_adjust"；`params.py` STAGE_CLASSES 登记；**默认 enabled=False → 现有金样本/gate 零影响**（沿 dehaze t108 先例确认）
- ctx.state 掩码缺失时 wants=False 静默跳过（无掩码=无区域效果，不报错）
- 完成标准：单元测试（合成掩码数值断言+enabled=False 零影响+wants 门控）；stage 注册全链冒烟

### F13 掩码通道 preview/export 双线注入（super-dev）
- **spike 先行**（1-2 文件，回答「export 线掩码注入可行路径」）：
  - 现状：preview 走 state_extras（loop.py:336-338 合成 / :397-399 raw → session.py:321-322 → ctx.state）；**render_full（loop.py:403-407 → web/export.py:_render_full_quality:30）无 state_extras——preview 有区域效果、导出没有**
  - 方案方向：masks_cache（loop.py:1066，二值 0/255）→ 转 float 0-1 软掩码 → 下/上采样到目标分辨率 → preview 走现有 state_extras 通道扩键 `region_masks`；export 线增传（export API 增参或 session 状态携带）
- 一致性要求：preview 与 export 同掩码同语义（tier EV 口径差历史教训——W3 发现的 decode 家族 0.22EV 残差在掩码通道不允许复现）
- 缓存：掩码进 ctx.state 自动入指纹（session.py:346 state_fp，ndarray 走 _ndarray_digest）——验证掩码变化缓存失效
- **文件域**：loop.py 仅动 backend/state_extras 区；`_DOTTED_PARAM_REGISTRY`/`_apply_decide_params` 区归 dev-3
- 完成标准：spike 结论（可行/不可行+证据）→ 最终实现 + e2e 断言 preview/export 区域效果方向一致 + 缓存失效测试；spike 产物不污染主代码

### F14 decide region.* 接线（dev-3，F12+F13 后）
- `_DOTTED_PARAM_REGISTRY`（loop.py:66-72）加 region 键——嵌套 regions 结构需映射特例：`region.<prompt>.<param>` → `("region_adjust", "regions.<prompt>.<param>")` 或在 `_apply_decide_params`（:531-568）加 region 特例（沿 dehaze 联动 :553-556 同区实现）；**写 region.* 键时 enabled=True 联动**（沿 dehaze 模式）
- 指标键：`register_metric_keys`（**src/pixo/decide/engine.py**:449，仓内另有一份 render/decide/engine.py 勿混淆）确认 region 指标键（`<name>_luminance` 等 flatten 键 loop.py:450-480 已有）注册情况，补缺
- 首版规则 YAML 1-2 条（`decide/rules/`，沿 exposure_rule_001.yaml 格式）：如 `region_sky_exposure_001`（sky_luminance 超阈 → region.sky.exposure 负补偿）
- 完成标准：合成 e2e：mock 掩码+measure → decide 写 region 键 → 下轮渲染像素变化断言（闭环证明）

### F15 M1 验收资产（dev-3+tester，F14 后；gate_cases.py 在 F08 后解禁）
- gate_cases.py 加 region_adjust case（enabled=True+合成掩码快照）
- `src/pixo/harness/goldens/samples.py`（:168-171 regions 键展开）适配
- `src/pixo/render/README.md` 模块清单更新
- tester：测试计划（M1 全 F-ID + F10 回归）+ 执行 + test-report.md（运行证据）
- 完成标准：gate 断言 20 features 绿；tester 报告全 F-ID 有证据

### F16/F17 合规包（researcher 素材 + writer 成文，F04 后）
- researcher：`research/license-inventory.md`——全部第三方依赖清单（requirements/pyproject/manual 懒 import）× 许可 × 来源 URL（逐项可溯源）
- writer：仓库根 `THIRD_PARTY_NOTICES.md`（沿 inventory 成文，tech_debt #3 销账）+ 依赖声明：**PyYAML 移入 requirements.txt 必装**（qa 已复核确认：`src/pixo/decide/engine.py:255-261` YAML 规则加载 PyYAML 缺失即 DecideError 无回退，且默认规则包 5 个全 YAML——硬依赖成立）、**scipy 声明可选**（懒 import+numpy 网格回退，color.py:471-487，安装说明注明性能影响；qa 已复核现状 requirements.txt 两者均未列）
- 完成标准：NOTICES 落盘；`test_model_license_registry_paths_resolve` 等既有断言不红

### F18 DNG SDK clean-room 复审评估（researcher，独立）
- 范围：全仓 DNG SDK 痕迹清单（注释引用/算法同构性可疑点，如 huesat DCP 基准路径豁免逻辑）+ clean-room 法律标准考察（web 检索）+ 风险分级
- 产出 `research/dng-sdk-review.md`：现状证据 + 处置选项（确认 clean / 重写 / 隔离声明）+ 建议（**不做决策，决策留用户**）
- 完成标准：报告落盘，tech_debt #2 附评估结论指针

### F19 感知门禁提案（researcher，可选——时间不够降级记债）
- 基于 `scripts/ab_vs_camera_thumb.py` 现状 + tech_debt #7：出「ΔE/美学阈值纳入 gate」方案提案（口径/阈值/成本/风险）
- 产出：`research/perceptual-gate-proposal.md`；不实施

### F01/F20 changelog（writer）
- F01：`git log --since=2026-08-27` 全部 commit（08-27 约 20 + 09-04/09-05 9 条）按 docs/changelog.md 惯例成文（`## YYYY-MM-DD — 批次名`+bullet+「验收：」行；验收计数从提交信息/.artifacts 报告取，**不编造**）；可按日分多条
- F20：本轮批次（qa-final 后，含各专项门禁证据与测试计数）
- 完成标准：changelog 覆盖至最新 commit；qa 抽查事实准确性

## 3. 接口约定
- **文件域**：见 team-manifest.md「文件域仲裁」（gate_cases.py 时序互斥 / loop.py 分区 / vision↔styles↔region 三域）
- **黑板交接**：streams/stream-N.md 统一格式——做了什么/改了哪些文件/如何验证（命令+输出摘要）/遗留问题；文件落盘=交接完成
- **门禁文件**：`.{gate}_ok` 统一含审核人/覆盖 F-ID/ISO 时间戳/结论
- **提交策略**：各专项门禁过后队长按依赖序分批 commit（沿 10-commit 依赖序惯例）；F10 独立成 commit（保 revert 单点）

## 4. 疑难任务定义（super-dev 攻关题）
1. **F13 掩码双线注入**（主攻）：export 线 state_extras 缺口 + preview/export 语义一致性 + 缓存指纹失效；spike→实现的完整链
2. **warm_sat native 化 spike**（次攻，F05 决策输入）：借 4388f37 LUT native 内核模式评估 refine warm HSV native 化可行性（成本/收益/逐位对齐路径）

## 5. 风险登记
| 风险 | 等级 | 缓解 |
|------|------|------|
| F10 切默认破 A1（守卫盲区） | 高 | F8 金样本先行；卡 golden 前后对比；revert 单点 |
| F13 export 线注入牵动导出主链 | 高 | spike 先行；preview/export 一致性 e2e；tier 口径教训 |
| F04 gsam 测试道具重写量大 | 中 | 语义改写清单已在设计；tester 复核 |
| F04 未知 prompt 语义变化：现「纯未知 prompt 请求」经 gsam 禁用→SegmenterUnavailable→manual_review 升级，移除后改零掩码+warn-once | 中 | 语义变化已在 F04 设计明示（路由未命中≠模型错误，escalation 路径保留给真实后端故障）；测试改写钉死新语义 + loop 侧 manual_review 路径回归确认 |
| reviewer Flash 档评审深度 | 中 | qa 总审兜底 |
| 额度耗尽 | 中 | dev 定向测试纪律；全量队长统一执行 |

## 6. 用户确认记录（卡点②）
- 2026-09-07：用户批准组队 plan（ExitPlanMode 通过）并选择「全自主推进」——本次批准即预授权本设计；卡点②呈报留档于此。后续用户若有修正意见，修订后重走 qa 审核。
