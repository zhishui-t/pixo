# huesat A 轨（HSV 移植链）删除评估 —— GPL 血缘釜底抽薪路径证据件

- 日期：2026-09-07 · 任务：供用户拍板「删除 A 轨 vs clean-room 重写」，**本报告不做删除决策**
- 上游：F18 高危 H1——`src/pixo/render/core/huesat.py:5-6` 自述「Adobe 参考实现 (dng_render.cpp / dng_color_spec.cpp) 经 RawTherapee rtengine/dcp.cc 移植」（RawTherapee 为 GPL-3.0）
- 方法：全文实读 huesat.py(525 行)/huesat_oklch.py(226)/modules/huesat.py(235)/convert_hsm_to_oklch.py(182)/base.py/api.py/presets.py + 全部调用方 grep + 全部 35 个风格配置 huesat 参数遍历 + gate manifest 解析

---

## 0. 结论（前置）

1. **判定：有条件可行**。「A 轨」不是整个 huesat.py 文件，而是一条可精确界定的**HSV 查表应用链**（约 150 行）+ 一条**测试专属的 DNG 复刻分支**；删除后 B 轨（oklch 自研）+ 共享基础设施 + local warm sat（自研）完整保留，**生产默认渲染零变化**（全部 35 个风格配置 huesat 均 `enabled:false`，逐一遍历实证）。
2. **最大风险点（回退链断裂，任务预判成立）**：oklch 点云缺失时 stage 回退 hsv 链 = A 轨（`modules/huesat.py:154-156,182-183`）。全仓只有 **1 个 DCP**（Nikon Z 5 2 RawLab LR Adobe Standard Baseline）有点云，`resources/dcp/` 共 6 个 DCP——删除后其余 5 个 DCP 若启用 huesat 将**无处回退**。条件 c：先为其余 5 个 DCP 补点云（脚本现成，见 §2.4）或显式接受「no-op + 告警」语义变更。
3. **语义损失有界且已被路线图背书**：A↔B 两域分歧 median 10.890 ΔE2000（≈4.73 JND，`hsm_oklch_eval.md:12`）意味着 B 轨渲染 ≠ A 轨渲染；但按 t64 验收口径（`hsm_oklch_eval.md:88`），A↔R/B↔R 只是 look 偏离基线「不作好坏判据」，t64 的验收主读数是接线保真度而非等价闸门——B 轨作为独立合法 look 与路线图「阶段二起用 OKLCh 连续形变**替代** DCP HSM」的既定意图（`huesat_oklch.py:3`、`docs/changelog.md:41-45`）自洽。
4. **F18 高危项清零范围**：本删除可清零 H1/H2/H3/H9（RT 移植声明、BuildHueSatMapEncodingTable 逐项一致、dng_render 包装注释、use_dng 复刻分支）；**H4-H8（color.py 的 D50_xy_coord 等 SDK 源码级注释）不在本删除范围，须另案**——color.py 的相机矩阵链仍被 `pipeline/base.py:99` 的底座渲染使用（§3.4）。
5. **工作量：2.5-3.5 人日（中等档）**，对比 clean-room 重写（F18 选项 B）显著更低，因为 B 轨与等价验证基建均已就位。

---

## 1. 双轨现状：代码边界（函数级）

### 1.1 三条执行分支（`modules/huesat.py:170-214` process 分派）

| 分支 | 触发条件 | 调用 | 生产状态 |
|---|---|---|---|
| DNG 复刻分支（:184-203） | `ctx.state["use_dng_huesat_path"]=True` 且有 cam_raw+ForwardMatrix | `apply_hue_sat_map_prophoto`/`apply_look_table_prophoto` + `exposure_ramp`/`apply_rgb_tone`（core.tone，clean-room） | **生产无触发点**：全仓 grep `use_dng_huesat_path` 仅 modules/huesat.py 读取 + `test_huesat.py:351` 一处设置——纯测试状态 |
| oklch 分支（:204-211，B 轨） | `color_domain=oklch` 且点云命中 | `core.huesat_oklch.apply_oklch_deform` | 缺省 color_domain=hsv，需显式指定 |
| hsv 分支（:212-214，**A 轨主体**） | enabled 且无上述两分支 | `core.huesat.apply_hue_sat_map` + `apply_look_table`（HSV float64 链） | 全部配置 enabled=false → **生产零执行** |
| 局部暖高光（:215-222） | `warm_highlight_sat>1.0`（不受 enabled 门控，`wants()` :142-144） | `apply_local_warm_sat` | **lr_baseline / lr_camera_standard_baseline 两配置在用**（3.3/2.2，实测遍历）——自研功能，**保留** |

### 1.2 `core/huesat.py` 函数级归属

**删除对象（A 轨 HSV 查表应用链，携 RT/Adobe 血缘声明）：**

| 函数/行 | 内容 | 血缘证据 |
|---|---|---|
| 模块 docstring :1-38 | 「经 RawTherapee rtengine/dcp.cc 移植」（:5-6）、解码约定 7 条 | **F18 H1** |
| `apply_table_to_hsv` :238-300 | HSV 三线性查表核心（H 环绕、encoding=1 V 轴 gamma 域缩放） | :286-289「encode/decode 表与 dng_render.BuildHueSatMapEncodingTable(subSample=false) **逐项一致**」——**F18 H2** |
| `apply_hue_sat_map` :322-331 / `apply_look_table` :354-359 / `_apply_table_linear` :374-386 / `_apply_table_prophoto` :362-371 | 线性 sRGB → ProPhoto → HSV 查表应用入口 | 「兼容旧路径」（:355） |
| `use_dng_huesat_path` 分支（modules/huesat.py:184-203） | SDK 顺序复刻「HueSatMap → ExposureRamp → LookTable → RGBTone → final」（:187） | **F18 H9** |

**改写后保留（共享数据访问/原语/自研工具）：**

| 函数/行 | 内容 | 保留理由 |
|---|---|---|
| `_resolve_dims` :93-101 / `decode_table` :104-119 / `get_hue_sat_table` :303-308 / `get_look_table` :311-319 | DCP 表解码（DNG 规范 tag 格式解析） | B 转译脚本、stage `wants()`/metrics、点云补齐都依赖；:107 布局注释引 RT/Adobe 需**改写为规范引证**（布局本身是 0xC6F9/0xC726 tag 定义的公开格式） |
| `_rgb_to_hsv` :54-72 / `_hsv_to_rgb` :75-90 | 通用 6 扇区 HSV 数学（非 RT 特有） | 被 `apply_local_warm_sat`（:478,521）、`tests/unit/test_native_hsv.py:12`（**C++ 内核 hsv.cpp 等价测试的 Python 参考**）、`tests/unit/test_hsl.py:14`、`scripts/ab_intent_compare.py:66`、转译脚本 :34 依赖 |
| `_srgb_encode_v` :122-125 / `_srgb_decode_v` :128-132 / `_smoothstep` :135-138 / `_sat_rolloff` :141-150 / `_tri_index` :229-235 | 数值工具 | local warm sat（:479,487）、make_hue_sat_map、转译脚本 :35 依赖；:123「与参考实现 gammatab_srgb1 一致」注释需改写 |
| `_identity_table` :153-159 / `_flatten_dcp` :162-164 / `make_hue_sat_map` :167-226 | T5 品红带拟合表构造（自研 band-drift 方案 b，:170） | 自研拟合工具；:181「对齐 apply_table_to_hsv / Adobe 参考实现」坐标语义注释需改写 |
| `apply_hue_sat_map_prophoto` :334-343 / `apply_look_table_prophoto` :346-351 | **薄包装**：取表 → 委托 `tone.apply_hue_sat_map`（导入名 `_apply_hue_sat_map_table`，:43-47） | **底座依赖**：`pipeline/base.py:18,101,104` 的 `render_dcp_linear` 直接调用；实际应用数学在 `core/tone.py`——**M1 clean-room 版**（tone.py:1「依据 (只使用公开材料, 不参考任何 SDK 实现源码)」，oracle 为黑盒 dump）。:337「走 dng_render.apply_hue_sat_map」注释——**F18 H3**，改写 docstring 即清 |
| `apply_local_warm_sat` :398-523（含 native 内核调用） | 局部暖高光饱和（A1/B5 自研，coverage/contrast 门控） | 自研算法 + C++ 内核（native/src/warm_sat.cpp）；lr_* 两配置在用；gate golden `huesat` feature 锁的就是它 |

### 1.3 B 轨运行时（`core/huesat_oklch.py`，226 行）

自研实现：Oklab/OKLCh 转换（`core/oklab.py`）+ 高斯核栅格化（:79-128，弃用 K 近邻 IDW 的记录在 docstring）+ 三线性插值（:176-196）+ 软限幅（复用 `hsl_oklch._soft_limit_chroma`）。与 A 轨的关系仅为**注释级引用**：:9「与 core.huesat 的 HSV 三线性同风格」、:15「语义同 apply_table_to_hsv」、:214——无代码复制；A 删除后这两处注释需改写（避免引用已删符号）。

---

## 2. B 轨血缘与语义损失评估

### 2.1 B 轨自身血缘：干净（数据转译，非代码衍生）

`scripts/convert_hsm_to_oklch.py`（点云生产脚本）的输入-变换-输出全链：
- **读入**：DCP 表数据（经 `core.huesat.get_hue_sat_table/get_look_table` 解码——tag 格式解析）+ `core.calibration.load_dcp`；
- **变换**：`_rgb_to_hsv/_hsv_to_rgb`（通用数学）、`_srgb_encode_v/_srgb_decode_v`、`core.color.linear_srgb_to_linear_prophoto`（**ROMM 标准矩阵**，color.py:677-684「ProPhoto RGB (ROMM 标准矩阵)」，非 SDK 相机矩阵链）、`core.oklab`（自研）、`core.tone.srgb_encode`（clean-room）；
- **输出**：纯数值 JSON 点云（每点 6 个 float）。

判定：点云是「DCP 表格数据 × 公开规范语义 × 公开域转换」的**数据→数据转译**，JSON 内不含任何代码；转译语义（encoding=1 的 gamma 域 V 缩放、布局 ((v·H)+h)·S+s、strength 混合）均为 DNG 1.4 规范定义的公开语义（huesat.py:24-31 亦按规范陈述）。脚本注释 :4「与运行时 apply_hue_sat_map_prophoto 完全同构」、:94「DNG RefBaselineHueSatMap 语义」——前者引用运行时符号（删除后改写），后者为规范语言。**结论：B 轨数据资产不继承 A 轨的 GPL 代码血缘**；但点云内容源自 RawLab DCP（数据再分发条款未核验，F16 §5 遗留项）——数据许可是另一条线，与本 GPL 代码线独立。
- 佐证：A↔B 分歧 median 10.890（§2.3）——若 B 是 A 的代码级复刻，分歧应趋 0；该分歧恰来自 B 的独立近似链（IDW 栅格化 + 两级插值 + tanh 软限幅，`huesat_oklch.py:27-31`）。

### 2.2 覆盖度：B 轨对 A 轨意图的覆盖与缺口

| 维度 | A 轨 | B 轨 | 缺口 |
|---|---|---|---|
| HSM/LookTable 作用量（dh/c_gain/l_gain） | 运行时 HSV 三线性 | 点云控制点（转译自同一张表） | 两级插值近似（点密处 <1% 增益差，`huesat_oklch.py:29-30`） |
| encoding 语义 | 运行时分支（:292-297） | **烘焙进点云**（转译脚本 :93-95） | 无运行时缺口 |
| strength 语义 | 线性混合（:284-285） | 线性混合（:215-217，同语义） | 无 |
| 域 | 线性 ProPhoto HSV（float64） | gamma sRGB → OKLCh（float64 内部） | 域本身不同（OKLCh 替代即路线图目标） |
| **采样覆盖** | 全 H/S/V 空间 | **l<0.40 深阴影与 c>0.357 色域角未覆盖**（:30-31，钳边界行） | 深阴影/高色域角形变近似放大 |
| **DCP 覆盖** | 任意有表的 DCP | **仅 1 个 DCP 有点云**（configs/color/ 实测仅 `hsm_oklch_nikon_z_5_2_rawlab_lr_adobe_standard_baseline.json`） | **关键缺口 → 见 2.4 回退链** |
| LookTable 单独应用 | `apply_look_table` 支持 | 点云为 HSM/LookTable 合并转译（本机 DCP 的 90×16×16 表在联合标签 0xC726，转译脚本 :50-52「auto: 真 HSM 优先, 缺席回退 LookTable」） | 语义上等价（本机 DCP 族只有一张表） |

### 2.3 「B ≠ A 但都合法」的口径核对（t64）

- t64 验收（`docs/changelog.md:39-45`）：主读数 = A↔B 两域分歧 median 10.890 / p95 16.070（≈4.73 JND）作「**接线保真度**」记录；**未设 A↔B 等价闸门**；
- 口径依据（`hsm_oklch_eval.md:88`）：「DCP HSM/Look 是 Adobe Camera 观感而非相机机内链路（huesat Stage 默认关闭的依据），A↔R/B↔R 只作 look 偏离基线，**不作好坏判据**」；
- 结论：在该口径下，A 与 B 是**两个合法的 look 实现**，B 不以复刻 A 为验收目标；删除 A 后 B 的输出合法性不因「与 A 不同」而受损。用户可感知的差异即 10.89 ΔE2000 量级（仅在启用 huesat 且命中点云的 DCP 上）。
- 语义损失的真实边界：①非命中点云的 DCP 失去 HSM 能力（见 2.4）；②深阴影/色域角近似带（§2.2）；③若未来需要「逐位复刻 Adobe HSM」的用途（如 base 底座对齐验证），prophoto 包装 + tone.py clean-room 实现仍保留，**不随 A 删除**。

### 2.4 回退链断裂点（关键风险，任务预判成立）

现状链：`color_domain=oklch` 启用 → `_resolve_oklch_spec` 按 **DCP 名 token 子序列**匹配 `configs/color/hsm_oklch_*.json`（modules/huesat.py:149-153；转译脚本 slug 规则 :151）→ **缺失则回退 hsv 链（A 轨）**（:154-156「点云缺失: 回退 hsv 链 —— 不能在此返回 False, 否则整个 stage 被跳过连 hsv 都不应用」；:182-183 同语义）。
- 实测：`resources/dcp/` 有 6 个 DCP，点云仅覆盖 1 个 → **其余 5 个 DCP 的 huesat 回退全部落在 A 轨**；
- 删除后该回退无目标：可选语义 = ①no-op + 一次性告警（跳过该 stage，`wants()` 改为 spec 缺失即 False）；②先补齐 5 个 DCP 的点云（`python scripts/convert_hsm_to_oklch.py --dcp <path>` 逐个生成，脚本现成、无 A 轨被删部分依赖——其依赖的 get_*_table/HSV 原语均保留）；
- **条件 c 的两条路径成本**：补 5 个点云 ≈ 0.5 人日（含逐 DCP 载入验证）；接受 no-op 语义 ≈ 0（但属行为变更，需在 changelog/文档声明）。

---

## 3. 删除面清单

### 3.1 代码

| 文件 | 动作 | 明细 |
|---|---|---|
| `core/huesat.py` | 删 ~150 行 + docstring 重写 | 删 `apply_table_to_hsv`/`apply_hue_sat_map`/`apply_look_table`/`_apply_table_linear`/`_apply_table_prophoto` + 模块 docstring RT 声明；改写 :15/:107/:123/:181/:286-289 处 RT/SDK 注释（保留部分注释改为规范引证）；`__all__` 收缩（:525） |
| `modules/huesat.py` | 删 ~60 行 + 重构 | 删 use_dng 分支（:184-203）与 hsv 分支（:212-214）；`wants()`（:141-158）与 `process()`（:170-235）按「oklch or no-op」重写；metrics（:229-235）去掉 hsv 域标记或改 oklch-only；模块 docstring（:1-40，含「DNG SDK 基准复刻」「Adobe look」表述）重写；`_oklch_domain`（:160-168）去掉 use_dng 例外 |
| `pipeline/base.py` | **不动** | :18,101,104 的 prophoto 包装（改写后 docstring）+ tone.py clean-room 应用继续服务底座渲染 |
| `core/tone.py` | **不动** | M1 clean-room，4096 表应用（`apply_hue_sat_map`）为 prophoto 路径的实际数学 |
| `core/huesat_oklch.py` | 注释微改 | :9/:15/:214 引用已删符号的注释改写 |
| `scripts/convert_hsm_to_oklch.py` | 注释微改 | :4「与运行时 apply_hue_sat_map_prophoto 完全同构」等表述更新；功能不动（其依赖全部保留） |
| `scripts/ab_intent_compare.py` / `hsm_oklch_eval.py` / `test_hsl.py` / `test_native_hsv.py` | **不动** | 依赖 `_rgb_to_hsv`/`_hsv_to_rgb`/`_resolve_oklch_spec`，均保留 |

### 3.2 测试

| 文件 | 动作 | 明细 |
|---|---|---|
| `tests/unit/test_huesat.py`（362 行） | 删 5 区段 + 改 1 区段 | 区段 1 decode_table 布局（:74-95）**保留**（数据访问）；区段 2 apply_table_to_hsv（:97-160，5 test）**删**；区段 3 apply_hue_sat_map/look_table 直通（:162-204，4 test）**删**；区段 4 门控（:206-243）**改**（wants 新语义 + make_hue_sat_map 保留）；区段 5 local warm sat（:245-311）**保留**；区段 6 use_dng 路径（:313-362）**删** |
| `tests/unit/test_huesat_domain.py`（307 行） | 大部删/改 | 区段 1 ProPhoto 转换精度（:93-151）保留（color.py 通用函数）；区段 2 恒等表往返（:152-199，A 核心验收）**删**；区段 3 单调性（:201-227）**删**；区段 4 Stage 注册 order=25<tone=30 默认关（:229-307）**改**（order/默认不变，分派语义改） |
| `tests/unit/test_huesat_oklch.py`（275 行） | **保留** | B 轨全覆盖（no-op/touch/数值对照/分派） |
| `tests/regression/test_gate_huesat.py`（53 行） | **保留** | local warm sat + native 等价 |
| `tests/regression/test_gate_e2e_ab.py` 等 RAW_PATH 层 | 不动 | 不触 huesat 应用 |

### 3.3 金样本与配置

| 项 | 影响判定 | 证据 |
|---|---|---|
| gate golden `huesat` feature | **零影响** | `gate_cases.py:170-174`——该 case 锁的是 `apply_local_warm_sat`（保留函数），非 HSM 应用 |
| gate golden `default_dispatch` / `card_portra_400`（F08） | **零影响（预期）** | 经 `build_default_pipeline` 全链，但 huesat 缺省 disabled → `wants()` False（modules/huesat.py:145-146，enabled=false 早退，不触 HSM）→ 不进金样本位型；删 A 后位型不变。**落地时用 `generate_gate_goldens.py --check` 实证零漂移**（本报告静态推断，标注：待执行验证） |
| `huesat_oklch` gate case | **不存在**（manifest 20 features 实测无此 case） | B 轨由单测覆盖、无 L2 金样本——删除 A 后 B 轨无 golden 锁属既有状态，非本删除引入；可作为后续补强项（非本任务条件） |
| 35 个风格配置 | **零改动** | 全部 huesat `enabled:false`（逐一遍历：8 个根预设 + films/ 26 卡）；lr_baseline/lr_camera_standard_baseline 的 warm_highlight_sat 走保留路径 |
| `configs/color/hsm_oklch_*.json` | 保留 | B 轨数据资产 |
| `docs/FUNCTION_GATE_SPEC.md §5.12`（huesat 门禁行） | 需同步修订 | 「HueSatMap/LookTable + 局部暖高光饱和」职责收缩为后者 + oklch（spec :262 起） |
| `docs/tech_debt.md` #2 / changelog / F18 报告 | 需同步注记 | H1/H2/H3/H9 状态更新；H4-H8 另案留痕 |

### 3.4 F18 高危项清零核查（删除后）

| F18 项 | 位置 | 本删除是否清零 |
|---|---|---|
| H1 RT 移植声明 | huesat.py:5-6 | **是**（docstring 重写） |
| H2 BuildHueSatMapEncodingTable 逐项一致 | huesat.py:286-289 | **是**（函数删除） |
| H3 dng_render 包装注释 | huesat.py:335-338,347 | **是**（docstring 改写，函数保留） |
| H9 use_dng 基准复刻路径 | modules/huesat.py:18,168,176,184-203 | **是**（分支删除） |
| H4-H8 color.py（D50_xy_coord :587、dng_render.cpp 公式 :576、SetMatrixToPCS :598、fRGBtoFinal :612、CameraWhite :557） | core/color.py:557-613 | **否——另案**。使用方：`pipeline/base.py:99`（cam_wb_to_prophoto，底座渲染在用）、`modules/huesat.py` use_dng 分支（随本删除消失一处调用点，但 base.py 仍在）。处置属 F18 选项 B/C 的 color.py 部分 |
| H12 io.py BuildStage3Image 对齐 | core/io.py:334-336 | **否——另案**（解码链，与本删除无关） |
| M1-M6/M10-M11（calibration/white_balance/OWN_PIPELINE 表格/native CMake guanlan/DCP 数据） | 各处 | **否——另案**（中风险层，F18 §1） |

---

## 4. 结论：有条件可行 + 工作量

**判定：有条件可行。** 删除对象是精确可界的「HSV 查表应用链 + DNG 复刻分支」（约 210 行含测试），生产默认渲染零影响（全配置 enabled=false 实证）、底座 prophoto 路径由 clean-room tone.py 承接不受影响、B 轨血缘干净且语义损失已由 t64 口径与路线图意图背书。GPL 血缘的最重证据（H1/H2/H3/H9）全部落在删除面内。

**前置条件（缺一则不可行/需降级）**：
- **条件 a（回退链）**：决定无点云 DCP 的行为——补齐 5 个 DCP 点云（推荐，0.5 人日）或显式接受 no-op+告警语义变更；
- **条件 b（保留边界纪律）**：删除严格限定在 §1.2 删除对象清单，共享原语/数据访问/local warm sat/T5 工具不得误删（native 内核等价测试与两个 lr_* 配置在其上）；
- **条件 c（验证闭环）**：`generate_gate_goldens.py --check` 实证金样本零漂移 + 全量回归绿 + 删除前后 oklch 轨输出逐位一致（B 轨代码未动，应天然成立，跑一次对齐实证）；
- **条件 d（披露同步）**：NOTICES/F18/tech_debt #2/changelog 同步——并明确告知用户：**本删除只解决 huesat 的 GPL 线，color.py 的 F18 H4-H8 与 io.py H12 仍在，需另案**（若用户目标是「全部 SDK 痕迹清零」，本删除只是第一步）。

**工作量估算（粗粒度 ±50%）**：

| 项 | 内容 | 估算 |
|---|---|---|
| 代码删改 | huesat.py ~150 行 + modules/huesat.py 重构 + 三处脚本注释 | 0.5-1 人日 |
| 条件 a | 5 个 DCP 点云生成 + 载入验证（或 no-op 语义决策落地） | 0.5 人日 |
| 测试删改 | test_huesat 两区段删除 + 区段 4 改写 + test_huesat_domain 重构 + 新增「oklch-or-no-op」分派测试 | 0.5-1 人日 |
| 验证 | --check 零漂移实证 + 全量回归（基线 1360 passed 量级）+ B 轨逐位对照 | 0.5 人日 |
| 文档 | FUNCTION_GATE_SPEC §5.12、tech_debt #2 注记、changelog、F18 状态更新、NOTICES 口径 | 0.5 人日 |
| **合计** | | **2.5-3.5 人日（中等档）** |

对照：F18 选项 B（A 轨 clean-room 重写）≈ 仅比本方案多「按规范重写 HSV 查表应用」本身，但因 B 轨已定位为替代品、重写出的应用链将无人调用，**删除路径的证据与基建成本优势明确**。

---

## 来源清单

**代码（文件:行，本会话实读）**：`src/pixo/render/core/huesat.py`（全文 525 行）；`src/pixo/render/core/huesat_oklch.py`（全文 226 行）；`src/pixo/render/modules/huesat.py:18,141-235`；`scripts/convert_hsm_to_oklch.py`（全文 182 行）；`src/pixo/render/pipeline/base.py:18,80-109`；`src/pixo/render/api.py:15,40-130,195-208`；`src/pixo/render/pipeline/presets.py:14-31`；`src/pixo/render/core/color.py:675-685`；`src/pixo/render/core/tone.py:1-20`（F18 已读）；调用方 grep（use_dng_huesat_path 全仓 5 命中 = 模块读取×3 + 测试×2；huesat 符号导入方 8 文件）。

**测试/金样本**：`tests/unit/test_huesat.py`（区段结构 :47-362）；`tests/unit/test_huesat_domain.py`（:93-307）；`tests/unit/test_huesat_oklch.py`；`tests/regression/test_gate_huesat.py`；`tests/regression/goldens/gate_cases.py:26-40,170-174`；`goldens/gate/manifest.json`（20 features 程序化解析，无 huesat_oklch case）。

**配置（程序化遍历）**：`configs/styles/*.json` 8 根预设 + `films/` 26 卡 huesat 参数（全部 enabled:false；lr_baseline/lr_camera_standard_baseline 带 warm_highlight_sat 3.3/2.2）；`configs/styles/preview_fast.json`（enabled:false）；`configs/color/`（点云仅 1 个）；`resources/dcp/`（6 DCP）。

**评估数据/文档**：`.artifacts/hsm_oklch_eval.md:8-16,88`（A↔B 10.890/4.73 JND、口径注记）；`docs/changelog.md:39-45`（t64 验收与「点云缺失回退 hsv 链」记录）；`docs/PIXO_RENDER_OWN_PIPELINE.md:30,76`（HueSatMap「DNG 参照★阶段一」与 huesat 行迁移意图）；`.artifacts/oklch_default_eval.md`（分派/守卫盲区口径）；F18 报告（`.agent-team/research/dng-sdk-review.md`，H1-H12 编号沿用）。

**明确标注的推测**：F08 金样本零漂移为静态推断（disabled stage 不执行 → 位型不变），落地时须 `--check` 实证（条件 c，置信度中高）；guanlan/convert 脚本对已删符号注释的改写不影响点云数据本身（数据是静态 JSON，置信度高）；「5 个无点云 DCP 补点云后 B 轨可用」未逐 DCP 实测（转译脚本 auto 模式依赖各 DCP 有表，本机 DCP 族预期同构，置信度中）。
