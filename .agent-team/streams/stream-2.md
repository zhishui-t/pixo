# stream-2 交接（dev-2 · oklch 流）

## F07 存量卡显式钉 hsv（oklch 前置修补 a）——完成

### 做了什么
1. **23 张存量卡 JSON 显式钉域**（口径 = 凡带键即钉，qa 修订版）：
   `configs/styles/films/` 下全部非 oklch_demo 卡，凡 params 带
   hsl / split_tone / skin / colorcal 键的 stage 一律补
   `"color_domain": "hsv"`。逐卡清单（卡名 → 钉了哪些 stage）：

   | 卡 | 钉域 stage |
   |---|---|
   | agfa_vista_200 | hsl, split_tone, skin, colorcal |
   | cinestill_50d | hsl, split_tone, skin, colorcal |
   | film_pro_400h | colorcal（本卡无 skin 键，即 qa 计 22 非 23 的唯一特例） |
   | fujifilm_acros_100 | skin, colorcal |
   | fujifilm_astia | skin, colorcal |
   | fujifilm_classic_chrome | skin, colorcal |
   | fujifilm_community_lab_scan | skin, colorcal |
   | fujifilm_pro_neg_hia | skin, colorcal |
   | fujifilm_pro_neg_std | skin, colorcal |
   | fujifilm_provia_100f | skin, colorcal |
   | fujifilm_provia_400x | skin, colorcal |
   | fujifilm_reala_100 | skin, colorcal |
   | fujifilm_velvia_50 | skin, colorcal |
   | kodak_colorplus_200 | hsl, split_tone, skin, colorcal |
   | kodak_e100 | hsl, split_tone, skin, colorcal |
   | kodak_ektar_100 | hsl, split_tone, skin, colorcal |
   | kodak_gold_200 | hsl, split_tone, skin, colorcal |
   | kodak_portra_160 | hsl, split_tone, skin, colorcal |
   | kodak_portra_160nc | hsl, split_tone, skin, colorcal |
   | kodak_portra_400 | hsl, split_tone, skin, colorcal |
   | kodak_portra_400nc | hsl, split_tone, skin, colorcal |
   | kodak_portra_800 | hsl, split_tone, skin, colorcal |
   | kodak_ultramax_400 | hsl, split_tone, skin, colorcal |

   计数：**hsl 12 / split_tone 12 / skin 22 / colorcal 23**（共 69 个钉域
   条目），与 qa 2026-09-07 实测口径逐一吻合（skin enabled=true 17 张照钉，
   不变量无特例）。oklch_demo×2 未动；键序沿 demo 卡约定（hsl 的
   color_domain 在 bands 前，其余追加末尾）；diff 为纯键插入
   （126 insertions / 57 deletions，删行均系追加键的逗号改行），
   6 张原缺末尾换行的卡保留原状态。

2. **测试不变量改写** `tests/unit/test_film_cards_oklch.py`：
   - `test_legacy_cards_untouched_no_domain_keys`（旧 A1 口径「无 domain 键」）
     → `test_legacy_cards_pin_hsv_domain_explicitly`：逐卡断言凡带涉域
     stage 键必钉 `color_domain=="hsv"` + 逐 stage 计数钉死
     {hsl:12, split_tone:12, skin:22, colorcal:23} + 保留「hsl bands 无
     band 级 domain 键」断言（schema v2 仍是 demo 专用形态，域语义单点在
     Stage 级，禁双源）。
   - 新增 `test_legacy_domain_pin_merge_equivalent_to_defaults`：按设计
     完成标准的实现 b，在 graph.py 参数合并层（`Stage.__init__` 的
     `{**default_params(), **卡参数}`）断言钉域前后合并结果逐键相等 ——
     永久守卫「钉域当前是语义 no-op」；F10 翻缺省后卡参数显式 "hsv"
     恒覆盖新缺省（运行时取值由卡锚定）。
   - 模块 docstring 相应更新。

### 改了哪些文件
- `configs/styles/films/*.json`：23 张存量卡（oklch_demo_warm_portrait /
  oklch_demo_cool_landscape 未动）
- `tests/unit/test_film_cards_oklch.py`：不变量改写 + 新增合并等价测试
- 证据（.artifacts/ 被 gitignore，本地留档）：
  - `.artifacts/_f07_pin_hsv_cards.py`（批量钉域脚本，可复现逐卡清单）
  - `.artifacts/_f07_pin_hsv_render_check.py`（渲染逐位对比脚本）
  - `.artifacts/f07_render_hashes_before.json` / `f07_render_hashes_after.json`

### 如何验证（命令 + 输出摘要）
1. **渲染逐位不变（设计完成标准，实现 a——比合并层断言更强）**：
   - 路径：`build_default_pipeline(params=卡参数)`（api.py:103/169 的真实
     卡集成路径；非卡 JSON stages 列表——那是信息性字段，域转换依赖
     DEFAULT_STAGES 内建顺序）+ 仓库内置 DCP + duck-typed raw（固定
     camera_whitebalance）+ 固定种子合成图（肤色块/彩色渐变，保证 4 个
     涉域 stage 全部 wants 通过且像素非零贡献）。
   - 脚本先经确定性双跑验证（两次 before manifest 23/23 逐字节一致）。
   - `PYTHONPATH=src python .artifacts/_f07_pin_hsv_render_check.py <out>`
     改卡前/后各跑一次：
     - 诊断：4 stage 独立贡献 max|delta| = hsl 0.0107 / split_tone 0.2088 /
       skin 0.0201 / colorcal 0.2314（证明对比路径真实敏感，非恒等直通）
     - **改前后对比：23/23 卡 float32 字节级 sha256 全部一致**（u8 更不在话下）
2. **语义 diff 校验**：对 git HEAD 逐卡逐 stage 比对解析后 JSON ——
   唯一变化 = 涉域 stage 新增 `color_domain:"hsv"`，其余键零增删改。
3. **定向测试绿（film cards 域）**：
   - `python -m pytest tests/unit/test_film_cards_oklch.py -q` → **8 passed**
     （旧 7 项 = 现 8 项：-1 旧不变量 +2 新不变量/合并等价）
   - `python -m pytest tests/unit/test_film_cards_oklch.py tests/unit/test_film_cards.py -q`
     → 14 passed
   - 相邻域：`tests/unit/test_pipeline_config.py test_pipeline.py test_hsl_oklch.py
     test_split_tone_oklab.py test_hsl.py test_skin.py test_native_colorcal.py`
     → 122 passed
   - 卡库引用面全扫：`tests/integration/test_oklch_preview_e2e.py test_know.py
     test_film_cards.py test_film_cards_oklch.py` → 28 passed
   - 全仓无其他「存量卡无 domain 键」旧口径残留（grep 仅 huesat 测试的
     无关同名措辞）

### 遗留问题（记录不顺手修）
1. **卡 JSON `stages` 列表与真实链序不一致**（范围外）：卡内 stages 顺序
   （如 huesat 在 hsl 后）按 pipeline_from_config 直组链会因域不匹配报错；
   真实集成走 DEFAULT_STAGES + 卡参数注入，卡 stages 字段实为信息性。
   建议后续在卡 schema 文档注明，或统一删减该字段——超出 F07 范围未动。
2. **whitebalance as_shot 依赖 ctx.raw.camera_whitebalance**（范围外观察）：
   无 RAW 的合成渲染需 duck-typed raw 才能走通，测试基建如需无 RAW 全链
   渲染可参考 `_f07_pin_hsv_render_check.py` 的做法。
3. **patch_protocol band 归属硬编码 "hsv"**：F09 范围，未动。
4. `.artifacts/` 证据文件被 gitignore，不入库；如需入库存证由队长决定
   （脚本身可复现全部证据）。

### 给 F08/F10 的接口提示
- F08 存量卡全管线 golden 可直接复用 `_f07_pin_hsv_render_check.py` 的
  渲染路径（build_default_pipeline + 内置 DCP + duck raw + 合成图），
  kodak_portra_400 已验证 4 涉域 stage 全执行。
- F10 切换后复验命令：重跑渲染对比脚本（before manifest 已留档），预期
  23/23 仍逐位一致（卡级锚定的 A1 证明）。

---

## F08 gate 缺省分派 case + 存量卡全管线 golden（oklch 前置修补 b）——完成

### 做了什么
`tests/regression/goldens/gate_cases.py` 新增 2 case（FEATURES 17→19），
复用 F07 验证过的全管线渲染路径（`build_default_pipeline` DEFAULT_STAGES
真实链序 + 仓库内置 DCP + 最小 raw 桩 + 种子合成图）：

1. **`default_dispatch`（缺省分派 case，观测点）**：hsl/split_tone/skin/
   colorcal 四 stage 带非零典型参数但 **全部不传 color_domain**（Stage 级
   无、band 级亦无——bands 无 domain 键，分组归属完全落在
   `hsl.py:73 band.get("domain", default_domain)`），域分派完全由
   `default_params()` 决定。skin 不传 enabled（缺省 True，skin.py:67），
   未来 skin 缺省翻转同样被观测。**双重用途注释已写明**：F10 落地后本
   case 输出**必须变化**（切换在金样本层的可观测证据）；基线 v2 届时由
   **队长单点重生成**，留 v1→v2 对比证据；F10 后本 case 不变 = 分派切换
   未生效，阻断。
2. **`card_portra_400`（存量卡全管线 golden，A1 证明）**：kodak_portra_400
   全管线快照。参数单一直接来源 = 卡 JSON（运行时读
   `configs/styles/films/kodak_portra_400.json`，不复制参数——卡被误改
   同样在金样本层可观测）。**双重用途注释已写明**：F10 前后本 case
   **必须逐位不变**（F07 卡级锚定 → A1「存量卡零迁移、逐位不变」在
   金样本层的可观测证明，补 t52 §3.2「没有任何存量卡渲染快照级金样本」
   缺口）；F10 后漂移 = A1 被破坏，阻断切换。

输入合成：`_fullpipe_input()` = 种子随机图（独立种子 20260907，沿
`_random_small` 模式，与其他 case 输入解耦）+ 大块经典肤色补丁（gate
skin case 同款 (210,155,130) float 归一）——保证 skin wants 的掩码占比
过阈，磨皮段真实执行；`ctx.state["scene"]="portrait"` 显式钉死（不依赖
analyze 步骤，纯函数式确定）。

### 改了哪些文件
- `tests/regression/goldens/gate_cases.py`：FEATURES 17→19 + 两 compute
  分支（含双重用途注释）+ `_fullpipe_input`/`_run_full_pipeline`/
  `_FullPipeRaw`/`_DISPATCH_BANDS` helpers
- `tests/regression/goldens/gate/default_dispatch.npy`、
  `card_portra_400.npy`：新基线（各 64×64×3 float32）
- `tests/regression/goldens/gate/manifest.json`：外科手术式增 2 条目
  （**未走整库 generate**——那会重写 17 个旧 .npy 并把 reviewer 清成
  pending；旧 17 条目与 reviewer 字段自检逐字节未动）
- `tests/regression/test_gate_golden.py`：断言 17→19 + 注释更新（19 的
  构成 = 15 前置 + 2 cal_auto + 2 F08）
- 证据脚本（.artifacts/，gitignore）：`_f08_case_property_check.py`、
  `_f08_add_baselines.py`

### 如何验证（命令 + 输出摘要）
1. **关键性质（新增 case 的存在意义，进程内翻转实验验证）**
   （`PYTHONPATH=src python .artifacts/_f08_case_property_check.py`）：
   - 逐 stage 像素贡献非零（对比路径真实敏感）：hsl 0.0097 /
     split_tone 0.168 / skin 0.0766 / colorcal 0.0265
   - 进程内翻转 hsl+split_tone default_params→oklch：
     case1 **输出变化**（F10 观测点有效——堵「翻转后 gate 零敏感性」
     盲区的性质成立）；case2 **逐位不变**（F07 卡级锚定在金样本层生效）
   - 确定性双跑：两 case sha256 跨进程一致
     （default_dispatch fbd5d50c… / card_portra_400 94bdd613…）
2. **基线外科手术自检**：`_f08_add_baselines.py` 输出
   `OK: added 2; total features = 19; reviewer preserved; 17 old entries
   byte-equal`；`git status` 仅 manifest.json 修改 + 2 个新 .npy。
3. **生成器 --check 无漂移**：`python tests/regression/goldens/generate_gate_goldens.py
   --check` → `CHECK: OK（19 features 与现有 manifest 一致）`
4. **定向测试**：
   - `python -m pytest tests/regression/test_gate_golden.py -m "gate and not gate_e2e" -q`
     → **4 passed**
   - `tests/unit/test_gate_golden_tool.py` → 4 passed（RAW 工具侧无涟漪）
   - `tests/regression/test_gate_coverage.py tests/regression/test_goldens_v0.py`
     → 18 passed；`tests/unit/test_film_cards_oklch.py` → 8 passed（F07 不回归）
   - harness/regression.py 的 FEATURES 来自 `pixo.render.tools.gate_golden`
     （RAW 金样本另一套），与本 case 无关，未受影响

### 遗留问题（记录不顺手修）
1. **manifest.reviewer 仍是 t38 旧文案**：本批 2 case 未经 reviewer 复核
   （初代基线由 dev-2 按任务书生成，qa 复核）。qa 复核后应更新 reviewer
   字段追加本批复核记录（沿 t38 先例：复核说明写在 reviewer 文案里）。
2. **case1 的 wb_B=0.960 触发 warmth 标定域外警告**（stderr 提示，非
   错误）：全管线 case 的 raw 桩 wb 系数取近中性值，落在正式 warmth 曲线
   适用域外，走端点垫片近似——确定性不受影响；若 qa 认为该警告碍眼，可
   把桩系数调进 [1.758, 2.398]（会改基线，需走重生成流程，不建议本轮动）。
3. 卡 JSON `stages` 列表信息性字段问题同 F07 遗留 #1（未动）。

### 给 F10 的接口提示
- 切换后验证链：① `--check` 应报 case1 sha256 漂移（预期红）+ 其余 18
  case 零漂移；② case1 基线 v2 由队长重生成；③ case2（card_portra_400）
  逐位不变 = A1 金样本证明，漂移即阻断。
- RAW gate 工具（render/tools/gate_golden.py + harness/regression.py）的
  FEATURES 是另一套 4 features，本任务未触碰（F06/F10 边界）。

---

## F09 patch_protocol 同源化 + canonical 透出确认（oklch 前置修补 d）——完成

### 做了什么
1. **band 归属同源化**（`src/pixo/agent/patch_protocol.py`）：
   - 根因：`_oklch_band_issues` 对无 domain 键 band 硬编码
     `band.get("domain", "hsv")`（原 :120）归属校验域；运行时
     `hsl.py:73 _split_bands_by_domain` 却按 Stage 缺省 color_domain
     分派——F10 翻缺省后两者静默分叉（t52 §3.3「agent 补丁校验背离」：
     hsv 量纲 band 被当 oklch 执行，却按 hsv 语义放行）。
   - 修法：新增 `_stage_default_color_domain(stage)`——从
     `STAGE_REGISTRY[stage]().default_params()["color_domain"]` 读归属域
     （运行时链同源：graph.py:46-48 把 default_params 合入实例参数，
     hsl.py:51 `p(ctx,"color_domain","hsv")` 的缺省字面量因
     default_params 恒含该键而不可达），**零字面量复制**；防御路径
     （stage 未注册/实例化失败，正常不可达）返回空串→band 不属 oklch
     量纲仅走通用拒绝。
   - 调用链：`_bands_reject_reason(raw, stage)` 增参；调用点
     `_validate_one` 就地派生 `param.split(".",1)[0]`（该处早于统一
     stage 拆分）；模块/函数 docstring 同步。
2. **canonical 透出核查**（`src/pixo/render/web/session.py` canonical_params，
   只核查未改）：
   - **现状已透出**：canonical = 各 stage `default_params()` 深拷贝 +
     用户覆盖合并，四涉域 stage 的 color_domain 天然在 canonical 中
     （本任务零 src 改动）。
   - 消费面确认：canonical 只被 export 全质量线消费
     （export.py:175/179 `build_default_pipeline(params=canonical)`）；
     **前端不消费 canonical**（无端点回传；UI 的 ParamsState 类型面
     `frontend/src/types.ts` 已有 hsl:221/split_tone:241 的
     `color_domain?: ColorDomain`（DomainToggle 域开关用），skin/colorcal
     的 UI 类型无此字段——UI 不做这两域的切域编辑，非缺口）。
   - 补确认测试钉死（见下）。

### 改了哪些文件
- `src/pixo/agent/patch_protocol.py`：`_stage_default_color_domain` 新增 +
  `_oklch_band_issues(bands, default_domain)` / `_bands_reject_reason(raw,
  stage)` 增参 + docstring 三处同步
- `tests/unit/test_patch_protocol.py`：+3 测试（同源翻转自证 / patch↔运行时
  逐 band parity / 归属域来源单一性）+ `_flip_hsl_default_domain` 辅助
- `tests/integration/test_preview_session.py`：+1 测试（canonical 透出确认）
- session.py / 卡 JSON / gate_cases / loop.py：未动（canonical 现状已透出，
  只补确认测试；边界遵守）

### 如何验证（命令 + 输出摘要）
1. **同源翻转自证**（`test_no_domain_band_attribution_follows_stage_default`，
   设计完成标准的可测证明）：进程内 monkeypatch 翻转
   `HslStage.default_params` color_domain→"oklch"（等价 F10 切默认、零代码
   改动）→ 同一 hue_center=9999 无 domain 键 band：翻转前不检（缺省 hsv
   语义），翻转后被 oklch 量纲硬拒命名——patch 校验归属**自动跟随**
   Stage 缺省；若残留字面量 "hsv" 本测试红。
2. **patch↔运行时 parity**（`test_patch_attribution_equals_runtime_dispatch`）：
   三种 band 形态（无 domain/显式 hsv/显式 oklch）× 两种缺省（hsv/翻转
   oklch）下，patch 侧被 oklch 检查的 band 集合 == 运行时
   `_split_bands_by_domain` oklch 分组，逐 band 一致——期望值读同源，
   **F10 切换后自动成立无需修订**。
3. **canonical 确认**（`test_canonical_params_expose_color_domain`）：四
   stage canonical 均含 color_domain 且 == default_params 值（读同源，F10
   后自动跟随）；用户覆盖优先；Enabled 覆盖正常合并。
4. **定向测试绿**：
   - `python -m pytest tests/unit/test_patch_protocol.py -q` → **29 passed**
     （26 旧 + 3 新；旧 `test_bands_string_hsv_domain_not_checked` 钉的是
     当前缺省语义，F10 后该语义随缺省翻转属预期，届时该测试随缺省断言
     批次同步修订——设计 §F10 已预留）
   - `tests/integration/test_preview_session.py -q` → **21 passed**
     （20 旧 + 1 新）
   - F09 域联合：patch_protocol + preview_session + export +
     service_runtime_fixes + loop_param_mapping → **78 passed**
   - agent 域无涟漪：test_agent + test_agent_suggest + test_llm_shadow
     → **37 passed**
   - F07/F08 无回归：test_film_cards_oklch 8 passed + test_gate_golden
     （gate and not gate_e2e）4 passed

### 遗留问题（记录不顺手修）
1. `test_bands_string_hsv_domain_not_checked`（旧测试）钉当前缺省语义：
   F10 后无 domain 键 band 将被 oklch 检查（正确新语义），该测试届时需
   随缺省断言批次修订（design §F10 的 4 项缺省断言修订清单可并入）——
   非本任务范围。
2. hsl.py:51 `p(ctx, "color_domain", "hsv")` 的缺省字面量在运行时不可达
   （default_params 恒含该键），属无害冗余；如要彻底单一来源可后续把
   p() 缺省改为读 default_params——超出 F09 范围未动。
3. 前端 skin/colorcal 的 ParamsState 类型无 color_domain 字段：UI 不做
   这两域切域编辑（DomainToggle 只覆盖 hsl+split_tone，design §1.2 第一批
   口径），非缺口；F11 观察期后若扩 UI 再补。

### 给 F10 的接口提示
- 三道前置修补（F07 卡级锚定 / F08 金样本观测点+A1 golden / F09 校验同源）
  已齐。F10 切换后：F09 的 parity 测试与 canonical 确认测试**预期零修订
  自动绿**；需修订的缺省断言以 design §F10 清单为准（4 项 hsl/split_tone
  + 顺带旧 hsv-domain 语义测试 1 项）。

---

## F10 oklch 第一批切换：hsl+split_tone 缺省翻 oklch（最高危）——完成，待队长 case1 v2 重生成

### 做了什么（落点仅两处，除断言修订外零行为改动）
1. `src/pixo/render/modules/hsl.py` default_params:
   `"color_domain": "hsv"` → `"color_domain": "oklch"`（连带 schema 注释
   语义更新：A1 现由 F07 卡级钉域兑现）
2. `src/pixo/render/modules/split_tone.py` default_params: 同上
   （模块 docstring + schema 注释同步）

### 断言修订清单（实际 7 项，超出预估 5 项的部分逐项说明）
翻转后跑定向全域枚举实际红名单 = 9 项，其中 2 项 gate 为设计内过渡态
（case1 等队长 v2，非断言修订），断言修订 7 项（均为「翻转期望」非删除）：

| # | 测试 | 修订语义 |
|---|---|---|
| 1 | test_hsl_oklch::test_stage_default_hsv_bitwise_identical_to_old_kernel | design §F10 预期：缺省输出参照内核 hsl_adjust_rgb→oklch_adjust_rgb；hsv 路径由存量卡钉域锁定 |
| 2 | test_hsl_oklch::test_stage_color_domain_oklch_dispatch | design §F10 预期：hsv 对照组改显式 color_domain="hsv"（原依赖缺省，指针显式化）|
| 3 | test_split_tone_oklab::test_stage_default_hsv_bitwise_identical_to_old_kernel | 同 #1（split_tone 版）|
| 4 | test_split_tone_oklab::test_stage_color_domain_oklch_dispatch | 同 #2（split_tone 版）|
| 5 | test_split_tone_oklab::test_stage_default_params_preserved | t52 §3.4 口径内第 3 项（design「各 2-3 项」上沿）：default_params 期望表 color_domain 翻 "oklch" |
| 6 | test_patch_protocol::test_bands_string_hsv_domain_not_checked → 更名 test_bands_no_domain_checked_as_oklch_by_default | 自报第 5 项：无 domain 键 band 现按缺省 oklch 检查（hue_center=9999 硬拒）；显式 hsv 戳恒不检（新增断言，翻转无关）|
| 7 | test_film_cards_oklch::test_legacy_domain_pin_merge_equivalent_to_defaults | F07 测试 docstring 预告过的转型：合并层「钉域=no-op」→「钉域=实义覆盖」——钉域是唯一差异键且恒为 "hsv"，其余键逐键相等，无钉基线读同源 |

**F09 测试的透明说明（对「零修订自动绿」预期的偏差）**：核心同源测试
`test_patch_attribution_equals_runtime_dispatch` 函数体**零改动**自动绿
（git diff ce92c73 逐行验证，见验证 a）——同源承诺成立。但 F09 另两枚
测试原形态钉了「当前缺省=hsv」字面量（`== "hsv"` / 先验「缺省→不检」），
逻辑上不可能在缺省翻转后存活（它们断言的就是旧缺省值本身），属缺省值
相邻断言而非同源断言；已改为**翻转无关形态**（source 等式 / 读当前缺省
再翻转对照），同源证明力不降反升。共享辅助 `_flip_hsl_default_domain`
同步一处机械修正（旧实现条件覆盖 `if=="hsv"`，F10 后无法翻回 hsv，改
无条件覆盖）。若队长判定此处理应停下报备，以上即报备内容。

### 四项验证证据
**a) F09 同源/parity 测试**：
- `git diff ce92c73 -- tests/unit/test_patch_protocol.py` awk 校验：
  parity 函数体 0 条增删行（唯一 hunk 只动其上方的共享辅助）
- `pytest tests/unit/test_patch_protocol.py::test_patch_attribution_equals_runtime_dispatch`
  → PASSED（零修订）
- 定向：patch_protocol 29 passed

**b) gate --check**：
- `python tests/regression/goldens/generate_gate_goldens.py --check` →
  `检测到 1 处漂移: default_dispatch.sha256: fb733245… → b3352650…`
- **恰 1 处** = case1（缺省分派观测点按设计触发：hsl bands 改道 oklch
  内核 + split_tone 改道 oklab）；**card_portra_400（case2）与其余 18 条
  零漂移** —— A1 未破线
- gate golden 测试态：manifest_schema/baseline_sha256 2 passed；
  no_drift/current_output 2 FAILED **仅因 case1**，队长单点重生成 v2 后
  自愈（设计内过渡态，不属断言修订）
- case1 v1→v2 对比数据（供队长留证）：
  v1 sha256=fb7332458295…（hsv 分派）/ v2 现算=b3352650fc0a…（oklch 分派）

**c) 存量卡渲染逐位不变**：
- `PYTHONPATH=src python .artifacts/_f07_pin_hsv_render_check.py
  .artifacts/f10_render_hashes_after.json` → cards=23
- vs `f07_render_hashes_before.json`（缺省hsv+无钉）: **23/23 float32
  字节级全等**
- vs `f07_render_hashes_after.json`（F07 钉hsv 版）: **23/23 全等**
  （两基线本就全等——钉域在旧缺省下为 no-op；F10 后仍全等=卡级锚定
  对缺省翻转完全免疫，A1 端到端证明）

**d) RAW 金样本复跑**：
- `python src/pixo/render/tools/gate_golden.py compare --samples
  D:/tmp/pixo_t108/samples.json --out
  data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512`
- **24 case（4 features × 6 samples）全 PASS，max|Δ|=0**（逐 case 输出
  0 0 PASS），`RESULT: PASS` —— 默认路径不涉 hsl/split_tone 非零参数，
  零漂移符合预期

### 定向测试汇总（全量归队长/qa）
- tests/unit 全量：**1273 passed, 3 skipped, 1 xfailed, 0 failed**
- tests/integration（not e2e）：**112 passed, 0 failed**
- tests/regression/test_gate_golden（gate and not gate_e2e）：2 passed +
  2 FAILED（仅 case1，待 v2）

### 遗留 / 给队长的下一步
1. **case1 基线 v2 重生成（队长单点）**：因 manifest reviewer 复核纪律，
   dev-2 不动 gate 基线。建议流程：跑
   `.artifacts/_f08_add_baselines.py` 同款外科手术思路更新
   default_dispatch 单条目（或整库 generate 后回填 reviewer 旧文案+追加
   本批记录），v1→v2 sha256 对比数据已在验证 b 留证
   （fb733245…→b3352650…）。重生成后 `--check` 应 OK（19 features）。
2. F10 提交建议独立成 commit（保 `git revert` 单点回退；rollback 面=
   两行 default_params + 7 项断言修订，金样本/卡库零回滚成本）。
3. F11（skin+colorcal 意图级 A/B）等队长指令。

---

## F11 skin+colorcal 意图级 A/B 证据（不切缺省）——完成

### 做了什么
沿 ab_intent_report.md「不劣于」口径对 oklch 第二批候选（skin 掩码域 /
colorcal 双轨）出意图级决策数据。**零代码/基线/配置改动**（评估脚本与
报告均落 .artifacts/，gitignore 范围）：
- 脚本 `.artifacts/_f11_skin_colorcal_ab.py`：金样本 6（samples.json
  RAW→基座 512px 中性参数）+ 合成人像 2（带真值肤区，确定性种子）+
  ab 语料扩展 64 = **72 张**（54 张全量选做已超额完成；主 44s / 扩展 392s）
- 报告 `.artifacts/skin_colorcal_oklch_ab.md`（+ 同名 .json 机读版）

### 关键数据
**skin（cv2-Lab 椭圆 vs OKLab 椭圆）**：双非肤误伤 0.0/0.0 → **不劣于(小值)**；
磨皮强度双肤区 B/A 0.935（入对齐带）；真值精检/召回合成图两轨≈1.0。
风险面=足迹域几何差异：7%（5/72）图 B 覆盖腰斩、2.8%（2/72）图触发 3%
门控分叉（B 直通=欠磨皮方向，非误磨）→ **总评不劣于**。

**colorcal（native+Lab 掩码 vs 纯 Python float+OKLab 掩码）**：算术差
median/max = 0.000/0.000（native↔Python 逐式等价）→ 复合差 100% 来自掩码域；
复合差 median 0.000 / p95 0.034~0.088；非肤区逐位等价；肤区校正残留
B/A 1.106（card 口径，恰在闸门线上，记观察项）/ 1.063（strong，达标）。
**性能劣于 ≈15×**（8.5ms→131ms @512px；外推 4096px export ≈8.4s/图，
auto 闭环逐轮放大）→ **总评：输出不劣于 / 性能劣于，go/no-go 卡性能预算**
（若切需 native 内核 OKLab 化或接受成本）。

### 如何验证（复现命令）
```
python .artifacts/_f11_skin_colorcal_ab.py            # 主语料 (~45s)
python .artifacts/_f11_skin_colorcal_ab.py --extend   # +64 张 (~7min)
```
固定种子（合成 20260907 / 抽样 20260904）→ 指标逐位可复现（计时列除外）。

### 遗留问题
1. colorcal 肤区残留 B/A 1.106（card 口径）恰在 1.1 线上——单指标边缘，
   结合复合差 median 0.000 判「边缘观察项」而非「劣于」，qa-final 可复核。
2. 计时为 512px 口径；更大分辨率的实测未做（外推已注明线性假设）。

### stream-2 全程收尾
F07（23 卡钉 hsv + 不变量改写）→ F08（gate 17→19 双 case）→ F09
（patch 同源化 + canonical 确认）→ F10（hsl+split_tone 切 oklch，.f10_ok）
→ F11（本节）—— stream-2 oklch 流五个 F-ID 全部交付。
