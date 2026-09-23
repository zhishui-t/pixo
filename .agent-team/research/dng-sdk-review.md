# DNG SDK clean-room 复审评估报告（tech_debt #2 评估材料）

- 任务：F18（Wave1，与 F16 合规包并行）
- 日期：2026-09-07
- 方法：只读代码盘点（grep src/docs/tests/configs/scripts/根文件，排除 `.graphify` 生成物）+ web 许可与法律标准调研
- 边界：本报告只提供事实与选项，**不做决策**；非法律意见

---

## 0. 结论（前置）

1. **痕迹总量**：DNG 关键词命中 286 行（排除 `.graphify` 缓存；src 217 / docs 45 / tests 19 / scripts 3 / configs 1 / 根文件 1，来源：本次 grep 实测命令输出）。其中**实质性溯源痕迹约 35 项**，覆盖 18 个文件；其余为 `.dng` 文件格式使用、本机数据路径（`K:\dsh-share\dng_verify`）、以及 graphify 之外的生成图数据，不构成许可问题。
2. **风险分布（实质性痕迹）**：高 12 项 / 中 11 项 / 低 12 项（明细见 §1 分级表）。
3. **发现高危项，且不止一类**：
   - **[最高] GPL 血缘**：`src/pixo/render/core/huesat.py:5-6` 自述实现「经 RawTherapee rtengine/dcp.cc 移植」——RawTherapee 为 **GPL-3.0**（来源：[github.com/RawTherapee/RawTherapee](https://github.com/RawTherapee/RawTherapee)）。若属实，这是比 Adobe 专有许可**更尖锐**的问题（GPL 传染性），且 `PIXO_LICENSE_REVIEW.md` 未提及此条。
   - **[高] 读源码的直接文字证据**：`src/pixo/render/core/color.py:587` 写有「注意 **DNG 源码**用 D50_xy_coord()=(0.3457,0.3585) 四位小数」——作者明知并引用 SDK 内部符号与实现细节，color.py **不构成 clean-room**（与其余模块的 clean-room 声明矛盾）。
   - **[高] 仓库自认**：`docs/架构设计文档.md:859`「当前 DCP 应用部分存在**从 DNG SDK 源码移植**的实现细节」。
4. **许可事实修正**（相对仓库既有文档的假设）：Adobe DNG SDK 许可**并不禁止**衍生作品与分发——原文明确授予 "use, reproduce, **prepare derivative works from** … distribute and sublicense the Software **for any purpose**"（来源：[ScanCode LicenseDB 原文](https://scancode-licensedb.aboutcode.org/adobe-dng-sdk.LICENSE)）。真实约束是：① 保留版权声明并随人类可读分发物携带；② 商业分发触发对 Adobe 的**赔偿义务**（§5）；③ **不可再授权**（不能以项目自身许可再发布，非开源兼容）；④ 文档（Documentation）不得修改；⑤ DNG 规范另许可（与 SDK 分离）。因此 `PIXO_LICENSE_REVIEW.md:115`「不能以 Adobe 源码直接移植进入发布产品」**在许可条款层面过严**，但在**开源发布**层面（项目方向为开源，见 `PIXO_RENDER_OWN_PIPELINE.md:171`）依然成立。
5. **clean-room 声明缺过程证据**：代码引用了 `CLEANROOM_M1..M5.md`（`src/pixo/render/docs/PIXO_RENDER_STATUS_20260820.md:21`），但全仓 `find -iname "*clean*"` 仅命中 cmake 构建产物——**过程记录文件不在仓库内**，warp/tone/resample 的 clean-room 主张目前是「无纸面证据的口头声明」，需 git 考古或补档才能坐实。
6. **旁证**：`src/pixo/render/README.md:92` 引用的 `tools/dng_stage3_ablation.py` 已不存在（`find` 无命中）——文档过期。

---

## 1. 全仓 DNG SDK 痕迹清单

### 计数口径

| 范围 | 命中行数 | 说明 |
|---|---|---|
| src/ | 217 | 含 bench JSON 数据、render/docs 子目录 |
| docs/ | 45 | 含 project_graph.json 等生成物 |
| tests/ | 19 | 多数为 `.dng` 夹具文件名 |
| scripts/ | 3 | |
| configs/ | 1 | hsm_oklch 点云 JSON |
| 根文件 | 1 | README.md |
| **合计** | **286** | 已排除 `.graphify`（src/pixo/.graphify/cache 下约 130KB 误命中） |

来源：`grep -rn -i "dng" ...` 逐目录实测（2026-09-07）。

### 分级表（实质性痕迹，高→低）

#### 高：算法同构可疑 / 有移植或读源码的直接文字证据（12 项）

| # | 文件:行 | 引文（节选） | 性质判定 |
|---|---|---|---|
| H1 | `src/pixo/render/core/huesat.py:5-6` | 「Adobe 参考实现 (dng_render.cpp / dng_color_spec.cpp) **经 RawTherapee rtengine/dcp.cc 移植**」 | **移植声明 + GPL-3.0 血缘**（RawTherapee 为 GPL-3.0）。最尖锐项 |
| H2 | `src/pixo/render/core/huesat.py:286-289` | 「encode/decode 表与 dng_render.BuildHueSatMapEncodingTable(subSample=false) **逐项一致**」 | 函数级一致声明 = 同构自认 |
| H3 | `src/pixo/render/core/huesat.py:335-338` | 「走 dng_render.apply_hue_sat_map … 与 RefBaselineHueSatMap 同语义」 | 同上，运行时路径即 SDK 复刻 |
| H4 | `src/pixo/render/core/color.py:587-589` | 「注意 **DNG 源码**用 D50_xy_coord()=(0.3457,0.3585) 四位小数」 | **读过 SDK 源码的直接证据**（内部函数名+内部常量+精度差异分析） |
| H5 | `src/pixo/render/core/color.py:574-585` | 「对齐 dng_render.cpp: CameraToPCS = FM × inv(diag(inv(CC)×CameraWhite)) × inv(CC)」 | SDK 内部公式转写 |
| H6 | `src/pixo/render/core/color.py:598-607` | 「dng_space_ProPhoto::SetMatrixToPCS: … 最后 MatrixFromPCS = Invert(S*M)。**不能直接 invert 原始 M**」 | SDK 内部实现行为的实现指引级描述 |
| H7 | `src/pixo/render/core/color.py:612-613` | 「dng_render **fRGBtoFinal** = sRGB_Linear.MatrixFromPCS * ProPhoto.MatrixToPCS」 | SDK 内部成员变量名（fRGBtoFinal）直接引用 |
| H8 | `src/pixo/render/core/color.py:557-560` | 「对齐 dng_color_spec::CameraWhite: … pin 到 [0.001, 1]」 | SDK 内部函数行为逐条对齐（含 pin 魔数） |
| H9 | `src/pixo/render/modules/huesat.py:18,168,176` | 「use_dng_huesat_path (**DNG SDK 基准复刻**) 优先级更高」 | 生产代码内保留「DNG SDK 基准复刻」执行路径开关（任务所述「DCP 基准路径豁免」：该路径豁免于 oklch 分派） |
| H10 | `docs/架构设计文档.md:859-860` | 「当前 DCP 应用部分存在**从 DNG SDK 源码移植**的实现细节」 | 仓库自认移植 |
| H11 | `docs/PIXO_LICENSE_REVIEW.md:100` | 「当前存在从 DNG SDK 源码移植/参考实现细节」 | 仓库自认移植（历史审计快照） |
| H12 | `src/pixo/render/core/io.py:334-336` | 「链路对齐 dng_negative::BuildStage3Image … dng_fast_interpolator」 | 解码链对齐 SDK 内部函数结构 |

#### 中：接口/语义沿用声明，SDK 头文件或规范之外的行为引用（11 项）

| # | 文件:行 | 引文（节选） | 性质判定 |
|---|---|---|---|
| M1 | `src/pixo/render/core/color.py:5` | 「权威依据 … Adobe DNG SDK: dng_color_spec.cpp / dng_camera_profile.cpp / dng_tag_codes.h」 | 权威依据直指 SDK 源文件（非仅规范） |
| M2 | `src/pixo/render/core/color.py:138` | 「对齐 dng_color_spec.cpp 的 MapWhiteMatrix (Mb / A / Mb^-1 结构)」 | 结构对齐声明 |
| M3 | `src/pixo/render/core/color.py:316,360` | 「DNG SDK 口径: 先分别插值…」「对齐 dng_color_spec::NeutralToXY」 | 插值次序/不动点迭代对齐声明 |
| M4 | `src/pixo/render/core/color.py:84` | 「对齐 dng_camera_profile::IlluminantToTemperature」 | 函数名级引用 |
| M5 | `src/pixo/render/core/calibration.py:12,55,66` | 「参考: Adobe DNG SDK dng_tags.h + dng_camera_profile.cpp」「0xC7A5 … 见 DNG SDK dng_tag_codes.h」 | 引 SDK 头文件作 tag 码依据（tag 码本身是规范公开事实，属表达层引用，降半档） |
| M6 | `src/pixo/render/modules/white_balance.py:3` | 「权威链路 (DNG 1.4 + **Adobe dng_color_spec.cpp**, 基座 colorimetric 路径)」 | 语义权威链路声明 |
| M7 | `tests/unit/test_color_math.py:129,135` | 「DNG SDK 口径: 先插值后复合」「DNG SDK (dng_color_spec) 先分别插值…」 | 测试注释固化 SDK 行为口径 |
| M8 | `docs/PIXO_RENDER_OWN_PIPELINE.md:29-31` | 色彩变换/HueSatMap/RGBTone 三层归属「**DNG 参照**」（★阶段一替换） | 架构层自认三层为 DNG 参照实现 |
| M9 | `scripts/convert_hsm_to_oklch.py:94,161` | 「DNG RefBaselineHueSatMap 语义…」「与 DNG SDK HSM 应用域一致」 | 标定脚本同构语义引用 |
| M10 | `src/pixo/render/native/CMakeLists.txt:14` | 「与 **guanlan dng_engine** 一致: 静态运行时…」 | 指向 guanlan 项目的 dng_engine（另一溯源线，非 Adobe 本体；native C++ 源码本身无 DNG/Adobe 引用，已实测） |
| M11 | `configs/color/hsm_oklch_nikon_z_5_2_rawlab_lr_adobe_standard_baseline.json:1` | 「source_dcp: "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp" … 与 DNG SDK HSM 应用域一致」 | DCP 数据衍生点云（23040 网格→2765 点）入库；DCP 本体的数据许可未核验（**推测**，置信度中：RawLab 社区 profile 的再分发条款未见档案） |

#### 低：clean-room 声明 / 纯提及 / 文件名与数据路径（12 组）

| # | 文件:行 | 引文（节选） | 性质判定 |
|---|---|---|---|
| L1 | `src/pixo/render/core/warp.py:3,11` | 「实现依据（**clean-room，未读取 DNG SDK 源码**）… 黑盒产物对齐验证（*.stage3.raw 作为 oracle），不复制任何 SDK 源码中的变量名、分支结构、常量表或注释」 | 明确声明 clean-room + 黑盒 oracle 协议，书面最完整；**但过程证据文件不在仓**（见 §0.5） |
| L2 | `src/pixo/render/core/tone.py:1,11-15` | 「M1 clean-room 版」「依据（只使用公开材料, 不参考任何 SDK 实现源码）」oracle=SDK 影调表 dump | 明确声明 clean-room；oracle 为输出 dump（非源码），符合黑盒惯例 |
| L3 | `src/pixo/render/core/resample.py:7,15` | 「clean-room re-implementation」「数值契约经 K:\dsh-share\dng_verify 黑盒 oracle 校准」 | 同上 |
| L4 | `docs/ENGINE_ARCHITECTURE.md:10` / `RAWLAB_MASTER_PLAN.md:17,26` / `PIXO_RENDER_STATUS_20260820.md:4,21` / `PIXO_RENDER_PACKAGE_REFACTOR.md:10` / `RAWLAB_ADJUSTMENTS_PLAN.md:59` | 「clean-room 合规：DNG SDK 只作黑盒 oracle」「DNG clean-room 未完成前不开功能」「CLEANROOM_M1..M5.md (clean-room)」 | 流程声明与计划文档；引用的 M1-M5 记录文件**缺失于仓** |
| L5 | `tests/unit/test_tech_debt_invariants.py:5` | 「DNG clean-room 复审…判定为不可机器断言」 | 本条目自身的台账记录 |
| L6 | `src/pixo/render/pipeline/base.py:35,60-69` | 「运行时无 DNG SDK 依赖; 相机/镜头参数从 dng_camera_cache.json 查表」 | 运行时零 SDK 依赖声明 + 缓存文件名 |
| L7 | `resources/camera_profiles/dng_camera_cache.json`；`src/pixo/render/README.md:46` | 文件名引用 | 数据文件命名 |
| L8 | `src/pixo/render/core/resample.py:139,149`；`tests/integration/test_render_perf_fixes.py:557` | 「dng_resample」函数名 | 符号命名（接口沿用痕迹） |
| L9 | `src/pixo/render/README.md:3,10,22,56,91-92` | 「输出与 DNG SDK 对齐的渲染结果」「公开面干净: 无 dng_* 公开符号」「DNG SDK 消融」 | 定位声明；:92 引用的 `tools/dng_stage3_ablation.py` **已不存在**（过期文档） |
| L10 | `src/pixo/render/bench/*.json`、`T24/T25 报告`、`io.py:352-358`、`tests/unit/test_native_decode.py:168` | 「K:\dsh-share\dng_verify\...」「NEF→Adobe DNG 实测 WhiteLevel=15892」 | 本机验证数据路径与转换器行为观测（事实记录，非代码衍生） |
| L11 | `docs/PIXO_ARCH_ALIGN_REVIEW.md:432`、`docs/tech_debt.md:45-46`、`docs/PROJECT_GRAPH.md:403-405` 等 | 「产品化前 clean-room 复审」 | 台账/评审记录（本任务上游） |
| L12 | 其余 `.dng` 后缀、rawpy 读取、RAW_PATH 等 | — | 文件格式使用，与 SDK 无关 |

**判定口径说明**：高=注释自认移植/同构/读源码；中=以 SDK 源文件或内部行为为权威依据，但未自认复制；低=clean-room 声明、命名、路径与流程文档。tag 码（0xC621 等）与矩阵链数学本身是 DNG 规范公开内容，不因提及而侵权；风险在于**表达层**（逐行结构、内部符号、魔数选择、注释语言习惯）是否复制自 SDK 源码。

---

## 2. clean-room 法律标准考察

### 2.1 Adobe DNG SDK 许可条款（一手原文）

来源：[ScanCode LicenseDB adobe-dng-sdk.LICENSE](https://scancode-licensedb.aboutcode.org/adobe-dng-sdk.LICENSE)（SPDX: `LicenseRef-scancode-adobe-dng-sdk`，分类 Proprietary Free；以下为逐字引文）

**许可授予（§1 Software License）**——注意与仓库内部假设的差异：
> "Adobe hereby grants you a non-exclusive, worldwide, royalty free license to use, reproduce, **prepare derivative works from**, publicly display, publicly perform, **distribute and sublicense the Software for any purpose**."

即：**衍生作品与任何目的的分发/转许可均被明确授权**。不存在「禁止移植到其他语言」条款（本轮检索未见任何一手文本支持该说法；`docs/PIXO_LICENSE_REVIEW.md:115` 的「不能以 Adobe 源码直接移植进入发布产品」是对许可的**过严解读**——但见下文 ④⑤，该结论在开源场景下仍实际成立）。

**文档许可（§1 Document License）**：可复制有限份数供开发用途，"**You may not modify the Documentation**"。

**限制与所有权（§2）**：
> "You will not remove any copyright or other notice … and you will include such notices in any copies of the Software that you distribute in human-readable format."
> "You will not copy, use, display, modify or distribute … in any manner not permitted by this Agreement. … **All rights not granted are reserved by Adobe**."

**赔偿（§5）**：
> "If you choose to distribute the Software in a commercial product, you … agree to **defend, indemnify and hold harmless Adobe** against any losses, damages and costs arising from the claims … arising out of such distribution."

**其他**：§7 违约即终止全部权利；§8 加州法管辖；末段明示 "**the DNG File Format Specification … is not included in the DNG SDK**"，规范另行许可。

**要点归纳**：
1. 直接移植/衍生**可发布**（专有/闭源形态），条件：保留声明 + 接受商业分发的赔偿义务；
2. **不可再授权**：不能把 SDK 衍生代码以 MIT/Apache/GPL 等项目许可再发布 → **开源发布即阻断**（项目方向为开源：`PIXO_RENDER_OWN_PIPELINE.md:171`「当前项目方向：开源」）；
3. SDK 许可**无专利授权**；DNG 格式实施另有单独的规范专利许可（可撤销，来源：[Adobe DNG 官方页](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html)）；
4. 非开源兼容已被社区长期实践佐证：RawTherapee/darktable 均不捆绑 DNG SDK 而走独立解析（来源：[RawTherapee issue #1982](https://github.com/Beep6581/RawTherapee/issues/1982)、[OSI 邮件列表 2012-10 讨论](https://lists.opensource.org/pipermail/license-discuss_lists.opensource.org/2012-October/018034.html)——Perens 评注文档许可不合 OSD）；
5. **冲突信息并列**：ScanCode 一手文本（可信度高，已逐字核对）vs. 本轮搜索摘要曾出现「仅限内部使用、禁止衍生」的概括（可信度低，与原文冲突，以原文为准）。

### 2.2 clean-room 实务标准

来源：[NEC v. Intel clean-room 程序评述（UIC law review 存档）](https://repository.law.uic.edu/cgi/viewcontent.cgi?article=1423&context=jitpl)、[Lexology: clean-room 方法 unpacking](https://www.lexology.com/library/detail.aspx?g=ff325ca4-8ce4-48a8-89b1-aa9db5f7f67c)、[Hexaware: clean room engineering 规则与风险](https://hexaware.com/blogs/ai-clean-room-engineering-can-you-legally-rebuild-what-you-can-see/)

法律要件（业界通行两团队协议）：
1. **团队隔离**：接触原品的规格团队只产出「黑盒功能规格」；实现团队只读规格、不接触源码；
2. **规格只含不受保护的思想/功能/接口**，不得承载原表达（结构、命名、注释、非常量取舍的编排）；
3. **过程留痕**：文档化的协议与交付记录（NEC v. Intel 中程序合规本身被法院采信为独立创作的证据）；
4. **黑盒输出对照测试是允许的**（拿对方的输出当 oracle 验证，不读其源码）。
另注（[HN 社区讨论](https://news.ycombinator.com/item?id=47259177)）：clean-room 协议本质是**简化诉讼的证据策略**而非成文法要求——一旦已知读过源码，问题转为「表达是否实质相似」的普通版权分析。

### 2.3 仓库实践对照标准

| 模块 | 自我声明 | 与标准的关系 |
|---|---|---|
| warp.py / tone.py / resample.py | clean-room + 黑盒 oracle（SDK 输出 dump） | **符合** §2.2 要件 4；要件 1/3 的过程记录缺失于仓（M1-M5 文档未入库），主张可辩护性打折扣 |
| color.py | 权威依据含 SDK 源文件，注释含 SDK 内部符号/魔数/实现告诫（H4-H8, M1-M4） | **不满足** clean-room：H4「DNG 源码用 D50_xy_coord()…」直接证明规格作者读过源码；此类注释同时是「表达层接触」的证据 |
| huesat.py | 自认「经 RawTherapee rtengine/dcp.cc 移植」+ 函数级逐项一致 | **最不符合**：若代码确从 dcp.cc 移植，则属 GPL-3.0 衍生品（RawTherapee 为 GPL-3.0，来源：[RawTherapee 仓库](https://github.com/RawTherapee/RawTherapee)）；非 GPL 发布即违约，且与 Adobe 专有链**叠加**成双重来源问题 |
| calibration.py / white_balance.py / io.py | SDK 文件级/函数级引用 | 介于两者之间：引用对象多为规范公开行为，但「权威依据=SDK 源文件」的写法削弱独立创作主张 |

---

## 3. 风险分级与处置选项（供队长/用户决策，本报告不决策）

### 3.1 风险结论

- **内部研发（不分发）**：所有路径当前均不构成许可违规（许可义务随分发触发）。**低风险，可继续现状**。
- **闭源商业发布**：若 color/huesat 确有 SDK 衍生，可行但需：保留 Adobe 声明、接受 §5 赔偿义务；**huesat 的 GPL 血缘必须先行排除**（GPL 衍生代码不能进闭源产品）。**中风险**。
- **开源发布（项目声明方向）**：SDK 衍生代码（color.py 主体、huesat.py）**不可随开源库发布**；GPL 线（若坐实）同样阻断多数开源许可组合。**高风险，发布前必清**——与 `PIXO_LICENSE_REVIEW.md` §6 的「阻断」结论一致，但阻断理由应修正为「不可再授权 + GPL 血缘」而非「许可禁止移植」。
- **专利面**：色彩矩阵/三线性插值等是公开文献方法，SDK 许可无专利条款的实际暴露**推测为低**（置信度中低，未做专利检索——明确标注：本报告未覆盖专利检索）。

### 3.2 处置选项（按模块差异化）

**选项 A：确认 clean（证据固化）**
- 对象：warp.py、tone.py、resample.py（已声明 clean-room 的 M1 类模块）。
- 动作：git 考古恢复/补写 CLEANROOM_M1..M5 过程记录入库（规格↔实现团队隔离说明、oracle dump 来源说明）；补一份「未接触 SDK 源码」的书面声明（若事实成立）。
- 成本：低。限制：color.py/huesat.py **不适用**（痕迹反证在案）。

**选项 B：重写（自规范出发）**
- 对象：color.py 矩阵链/HSM 域链、huesat.py、io.py BuildStage3Image 对齐段（H1-H12 所涉）。
- 动作：仅依 DNG 1.4 规范 + 公开色彩学文献重写；新团队不看现实现注释；保留黑盒 oracle 等价门（M1-M5 / ablation 回归已在位，验收基建成熟：`PIXO_RENDER_OWN_PIPELINE.md` §6、`docs/PIXO_LICENSE_REVIEW.md:100`）。
- 成本：高（色彩链是基座核心）；可借 `PIXO_RENDER_OWN_PIPELINE.md` 阶段一（Oklab 编辑层 + RP-CCM 替代 DCP 链）**顺路完成**，不必单独立项。
- 附带收益：顺带消除 H1 的 GPL 线。

**选项 C：隔离声明（现状保留 + 合规包装）**
- 对象：全部 SDK 衍生痕迹。
- 动作：① 在 THIRD_PARTY_NOTICES（F16 素材）登记 Adobe DNG SDK License Agreement 全文链接与保留声明义务（文本可得：[ScanCode 原文](https://scancode-licensedb.aboutcode.org/adobe-dng-sdk.LICENSE)）；② 精确登记衍生文件清单（H1-H12 文件级）；③ 接受闭源分发下的 §5 赔偿条款；④ **huesat.py 仍须单独处置 GPL 线**（核实是否真从 dcp.cc 取码：git 历史比对/重写该单文件），此项 C 方案盖不住。
- 成本：中。限制：**与开源方向不兼容**（衍生代码不能以项目许可再授权）。

**选项 D：混合（按模块拆分，证据现状下最顺势）**
- L 组（warp/tone/resample）→ A；H/M 组按发布形态在 B/C 间选：闭源商业 → C + huesat 单独重写；开源 → B（并借阶段一路线图摊薄成本）。

### 3.3 需要队长/用户拍板的问题清单

1. 发布形态最终口径：开源 or 闭源商业？（决定 B vs C 的适用面）
2. huesat.py 的 RawTherapee 血缘是「注释表述夸大」还是「真实取码」？（git 考古可判；若仅表述夸大，H1 降级为改注释即可）
3. CLEANROOM_M1..M5 过程记录是否存在于仓外（K:\dsh-share 等），可否归档入库？
4. Adobe DCP 数据衍生物（`configs/color/hsm_oklch_*.json` 点云、`resources/camera_profiles/dng_camera_cache.json`）的来源 profile 再分发条款核验（RawLab 社区 profile，未核验——推测项）。
5. `src/pixo/render/README.md:92` 等过期文档（dng_stage3_ablation.py 已删）是否随本次清理修正。

---

## 4. 来源清单

**仓库证据（文件:行）**：§1 分级表全部条目；上游输入 `docs/tech_debt.md:45-46`、`docs/PIXO_LICENSE_REVIEW.md`（§2 表 +95-100、:114-116、:157）、`docs/PIXO_RENDER_OWN_PIPELINE.md`（:29-34、:171）、`docs/架构设计文档.md:859-872`、`tests/unit/test_tech_debt_invariants.py:5`。

**web 来源**：
- Adobe DNG SDK License Agreement 原文：https://scancode-licensedb.aboutcode.org/adobe-dng-sdk.LICENSE （另见条目页 https://scancode-licensedb.aboutcode.org/adobe-dng-sdk.html ）
- DNG 规范与 SDK 许可分离/规范专利许可：https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html
- OSI 邮件列表许可讨论（2012-10）：https://lists.opensource.org/pipermail/license-discuss_lists.opensource.org/2012-October/018034.html
- RawTherapee 许可（GPL-3）：https://github.com/RawTherapee/RawTherapee
- RawTherapee 不捆绑 DNG SDK 的许可动因：https://github.com/Beep6581/RawTherapee/issues/1982
- NEC v. Intel clean-room 程序法评述：https://repository.law.uic.edu/cgi/viewcontent.cgi?article=1423&context=jitpl
- clean-room 方法综述（Lexology / Hexaware）：https://www.lexology.com/library/detail.aspx?g=ff325ca4-8ce4-48a8-89b1-aa9db5f7f67c 、 https://hexaware.com/blogs/ai-clean-room-engineering-can-you-legally-rebuild-what-you-can-see/

**明确标注的推测项**：RawLab DCP 再分发条款未核验（§3.3-4，置信度中）；专利暴露为低（§3.1，置信度中低，未检索）；「禁止移植语言」条款不存在（基于一手原文缺席 + 多轮检索未见，置信度高）。
