# color.py DNG SDK 痕迹函数级定性精查（F18 H4-H8 细化，重写流作战地图）

- 日期：2026-09-07 · 任务：R12 · 上游：`.agent-team/research/dng-sdk-review.md`（F18）、`.agent-team/research/arail-removal-eval.md`（A 轨已删，color.py 另案前置）
- 方法：color.py 全文 713 行逐函数实读 + native/src 19 文件 grep + tone.py 上下文核对 + 公开标准（ICC/IEC/ISO/CIE）常数比对
- 边界：只读代码，未改任何文件；**不做重写决策**
- 重要声明：DNG 1.4 规范 PDF 本会话两次直取失败（Adobe 站点跳转 404/HTML），规范章节引证基于已知文献写入并逐条标注「重写时核对原文」（见 §2.3 与来源清单）——不影响 a/b/c 定性本身

---

## 0. 结论（前置）

1. **定性分布：a) SDK 衍生实现 2 处 / b) 规范实现 6 处 / c) 纯注释引用 2 处 / clean（审计确认无 SDK 主张）约 20 个函数与常量**。F18 的 5 个高危项（H4-H8）细化后：**H4、H7 从"重写级"降级为"改注释级"**——其牵涉常数均为公开标准值（H4 的 4 位 D50 = ICC PCS 白点；H7 的 4 位 sRGB/ROMM 矩阵 = IEC 61966-2-1 / ISO 22028-2 公开值），真正的 a) 类收敛为 **2 个函数、约 55 行**（camera_white、cam_to_prophoto_matrix）。
2. **重写量级：轻档，1-1.5 人日**（含 b/c 类注释改写与等价验证）。两个 a) 函数的公式均为**约束唯一解**（"场景白 → PCS 白"的线性映射 + 显式数值护栏），按约束重构 + 钉死公开常数可达成**逐位等价**（gate 金样本 `exposure_cal_auto`/`warmth_cal_auto` 触达 cam→sRGB 链路，等价即零重生成）。
3. **最大风险：重写时的常数选择漂移**——若重写者以 7 位 Lindbloom 常数替换 ICC 4 位公开值（更"精确"但非现行为），输出漂移 ~7e-5（color.py:589 自注），将击穿金样本与底座等价测试。缓解：重写规格书明确 pin 4 位 ICC 值 + `--check` 实证。
4. **native/ 同步扫描：零 SDK 痕迹**（grep `dng|adobe|sdk|rt_|rawtherapee` 于 native/src 19 文件零命中）——colorcal/oklab/hsv 等内核不承袭 color.py 血缘，重写不涉及 native。
5. 附带发现：`tone.py`（clean-room 模块）注释中的「SDK 影调表 dump」为**黑盒 oracle 引用**（dump 是输出数据非源码），属 clean-room 纪律允许的对照测试，非本次痕迹面；color.py 重写时应沿用该 oracle 模式。

---

## 1. 函数级定性表

### 1.1 a) SDK 衍生实现（2 处，需按规范重写实现描述并钉常数）

| # | 函数:行 | F18 号 | 现状引文 | SDK 衍生点 | 定性依据 |
|---|---|---|---|---|---|
| A1 | `camera_white` :556-570 | H8 | 「DNG SDK 的 CameraWhite 向量…对齐 dng_color_spec::CameraWhite: fColorMatrix(AB*CC*CM) × XYZ(scene white)，按最大通道归一化后 pin 到 [0.001, 1]」（:557-559） | max 通道归一化 + 下界 pin 0.001 是 SDK 内部数值护栏选择（规范无此二细节）；fColorMatrix(AB·CC·CM) 内部命名结构 | 公式本体平凡：插值色彩矩阵作用于场景白 XYZ 后做归一/护栏。数学无创作性表达；护栏是通用数值稳健性手段 |
| A2 | `cam_to_prophoto_matrix` :573-608 | H5+H6 | 「对齐 dng_render.cpp: CameraToPCS = FM × inv(diag(inv(CC)×CameraWhite)) × inv(CC)…」（:576-578）；「dng_space_ProPhoto::SetMatrixToPCS: …最后 MatrixFromPCS = Invert(S*M)。不能直接 invert 原始 M」（:598-599）；「注意 DNG 源码用 D50_xy_coord()=(0.3457,0.3585) 四位小数…差值会把 CameraToPCS 带偏 ~7e-5」（:587-589，H4） | 组合配方（FM/CC/CameraWhite 的复合次序与 diag 白点归一）转写自 dng_render.cpp；SetMatrixToPCS 白点缩放叙述引 SDK 内部函数名 | **组合公式是约束唯一解**：定义"WB 后相机 RGB → 线性 ProPhoto(D50)"且"场景白映到 PCS 白"的线性映射，其解被 FM/CC 的规范语义唯一确定——重写按约束重构即收敛到同一公式。:587-589 的 4 位常数本身是 **ICC PCS D50 公开值**（见 B5 依据），唯注释以"DNG 源码"表述（H4 据此降级） |

### 1.2 b) 规范实现（6 处，零代码改动，仅注释出处改写）

| # | 函数:行 | F18 号 | 现状引文 | 规范/公开依据（改写目标出处） |
|---|---|---|---|---|
| B1 | `illuminant_cct` :83-109 | 新发现（F18 M4 关联） | 「对齐 dng_camera_profile::IlluminantToTemperature」（:84） | EXIF/DNG LightSource 枚举为公开标签定义；各 CCT 值为 CIE 标准照明体定义值（StdA=2856K≈2850、D55/D65/D75 等）。改引：DNG 规范 tag 表 + CIE 标准照明体表 |
| B2 | `bradford_adapt` :135-150 | — | 「对齐 dng_color_spec.cpp 的 MapWhiteMatrix (Mb / A / Mb^-1 结构)」（:138） | Bradford 锥响应矩阵 Mb（:140-142）为 Lam(1985) 公开发表标准矩阵；MapWhiteMatrix 式白点映射（Mb/A/Mb⁻¹）为标准 von Kries 型 CAT 构造（Lindbloom「Chromatic Adaptation」公开文献）。改引文献 |
| B3 | `_find_matrices` :316-317 | 新发现 | 「DNG SDK 口径: 先分别插值 CameraCalibration 与 ColorMatrix, 再复合 (矩阵插值与复合不可交换…)」 | 复合次序由 CM/CC 的**规范语义**定义（CC: 参考相机→个体相机，CM: XYZ→参考相机，故 camera→XYZ = inv(CC@CM)）——次序是语义推论非 SDK 私有。改引 DNG 规范「Camera Colorimetric Characterization」节 |
| B4 | `_neutral_to_xy` :324-339 / `neutral_to_xy` :357-384 | — | 「不动点迭代, DNG 色彩标定方法」（:325）、「对齐 dng_color_spec::NeutralToXY」（:360）、「两值振荡: 取均值 (对齐 SDK)」（:383） | 白点 xy 的不动点迭代过程在 DNG 规范相机色彩表征节有公开描述（**待核对原文，置信度中高**）；振荡取均值是通用数值护栏（非 SDK 特有）。改引规范节 + 护栏措辞中性化 |
| B5 | `prophoto_to_linear_srgb_matrix` :611-626（含 :617-623 常数） | H7 | 「dng_render fRGBtoFinal = sRGB_Linear.MatrixFromPCS * ProPhoto.MatrixToPCS」（:612） | 4 位 ProPhoto 矩阵（:618-620）= ROMM RGB（ISO 22028-2 / Kodak ROMM 公开发表）4 位形；4 位 sRGB 矩阵（:621-623）= IEC 61966-2-1 派生公开值；「白点缩放使 device white 精确落 PCS」是 ICC 公开技术（Lindbloom 有文档）；fRGBtoFinal 仅为 SDK 内部命名。改引 ICC/IEC/ISO + 弃用 SDK 命名 |
| B6 | 模块头 :3-5、:15、:44-45、:672-674 | — | 「权威依据…Adobe DNG SDK: dng_color_spec.cpp / dng_camera_profile.cpp / dng_tag_codes.h」（:3-5）、「(Adobe FindXYZtoCamera)」（:15）、「Adobe DNG SDK 在线性 ProPhoto(D50)、影调曲线之前应用 HueSatMap/LookTable」（:44-45、:672-674） | HueSatMap/LookTable 在线性 ProPhoto、tone 前应用**是 DNG 规范记载的应用域**（profile encoding 章节）；矩阵链定义同规范。权威依据整段改为「DNG 1.4 规范（相机色彩表征节）+ CIE/ICC/IEC 公开标准」，删除 SDK 源文件名与 FindXYZtoCamera 函数名 |

### 1.3 c) 纯注释引用（2 处，改措辞）

| # | 函数:行 | 现状引文 | 处置 |
|---|---|---|---|
| C1 | `linear_prophoto_to_srgb` :629-630 | 「DNG SDK 的线性 ProPhoto → 线性 sRGB (final space 矩阵 + Pin[0,1])」 | 措辞中性化（实现=矩阵乘+clip，平凡） |
| C2 | `cam_wb_to_prophoto` :637-644 | 「DNG SDK 线性 ProPhoto (含 CameraWhite 裁剪 + [0,1] 钳位)」（:638） | 「CameraWhite 裁剪」语义与 A1 联动，实现平凡（min+matmul+clip）；措辞改为「按相机白裁剪后映射」 |

### 1.4 clean 确认（本审计无 SDK 主张，列出防误伤）

`_mat3`、`xy_to_cct`（McCamy 1992，:112-118）、`xyz_to_xy`/`xy_to_xyz`、`_interp_1_over_t`（:153-166，:287 已引规范）、`_calibration_temperatures`、`interpolate_color_matrices`、`interpolate_forward_matrix`、**色温插值 M3 节全体**（`_xy_to_uv`/`_ensure_planckian_curve`/`temperature_from_xy`/`temp_to_xy`，:218-277——模块自声明「基于公开 CIE 色度学…与任何第三方专有常量表无关, 独立实现」，Kim et al. 2002/CIE 1960 UCS/Robertson，**此节即重写的范本写法**）、`temp_tint_to_xy`/`temp_tint_to_wb`/`wb_to_temp_tint`（:400-405 自我声明「Adobe 的映射是每机私有标定, 此处用 DCP ColorMatrix 反推」= 明确独立）、`cam_to_xyz_matrix`（:513-541，纯规范矩阵语义无 SDK 提及）、`_diag_inv_wb`、`cam_to_linear_srgb_matrix`、`cam_to_xyz`、`xyz_to_linear_srgb`、`linear_srgb_to_linear_prophoto`/`linear_prophoto_to_linear_srgb`（:677+，ROMM 标准矩阵+Bradford）、常量 `D50_XY`(7 位 ASTM)/`D65_XY`/`PROPHOTO_RGB_TO_XYZ_D50`(7 位 Lindbloom, :47 自注「ICC / Bruce Lindbloom」)。

**相邻文件备注**：`core/tone.py`（prophoto 路径的实际应用数学，M1 clean-room 版）注释「SDK 影调表 dump」「与 SDK dump 数值一致」（tone.py:14-15,43,183,203）为 **oracle（黑盒输出 dump）引用**——clean-room 纪律允许的黑盒对照，非源码引用，不属痕迹面；`tests/unit/test_color_math.py:129,135` 的「DNG SDK 口径」注释随 B3 改写（断言本身测的是数学性质，保留）。

---

## 2. a) 类重写建议

### 2.1 A1 `camera_white`（:556-570，8 行核心）

- **数学来源**：场景白 XYZ（= `_neutral_to_xy` 输出经 `xy_to_xyz`）经插值色彩矩阵（inv(CC@CM) 或按现实现的方向约定）得到相机对场景白的响应向量；相机白=该响应按最大通道归一（使白成为各通道裁剪上界）。
- **重写要点**：①公式由「白点定义 + 色彩矩阵语义」直接导出；②max 归一化与 [0.001,1] pin 作为**显式文档化的数值护栏**写入 docstring（护栏选择独立于任何 SDK 出处——任何实现都需要防退化输入）；③保持 float64 与现运算次序。
- **逐位等价预判：★★★★★**。同一输入下 max/clip/pin 均为确定性初等运算，常数保持即逐位一致。pin 0.001 仅在病态输入（场景白响应 ≤0）生效，正常 DCP 上不绑定。

### 2.2 A2 `cam_to_prophoto_matrix`（:573-608，约 35 行核心）

- **数学来源**：约束求解式重写——目标映射 M 须满足：①M @ (WB 后场景白) = PCS D50 白 XYZ（ICC PCS 定义）；②M 的色彩几何由 FM（WB 相机→XYZ D50 的规范 look 矩阵）与 CC（个体→参考相机）语义确定；③per-channel 归一项 diag(1/(inv(CC)@camera_white)) 是使约束①对任意 WB 成立的唯一修正项。满足①-③的线性映射唯一 → 重写实现与现公式收敛。
- **常数钉死（最大风险控制点）**：PCS D50 = **ICC 公开 4 位值 (0.3457, 0.3585)**；ROMM 4 位矩阵与 sRGB 4 位矩阵 = ISO 22028-2 / IEC 61966-2-1 公开值——重写规格书必须**显式规定沿用 4 位 ICC 常数**（不得"改进"为 7 位，否则输出漂移 ~7e-5，:589 现注释即此差异的量化）。
- **逐位等价预判：★★★★☆**。线性代数确定性 + 常数一致 → 逐位等价可达；风险仅在重写者若选择不同常数/复合次序（次序由语义强制，实际自由度只有常数）。验证手段现成：`tests/unit/test_color_math.py`（含「先插值后复合」口径断言）、gate `exposure_cal_auto`/`warmth_cal_auto`（触达 cam→sRGB 真链路，`gate_calibration_coverage.md:21`）、`--check` 金样本零漂移。
- **规范引证核对清单（重写时执行，本次未完成——PDF 直取失败）**：①DNG 规范「Camera Colorimetric Characterization」节：白点 xy 迭代过程的原文表述（B4 引证，置信度中高）；②同节 1/CCT 插值权重原文（置信度高）；③ForwardMatrix 定义句（置信度高）。核对后把 §1.2 表中「待核对」标注替换为具体节号。

### 2.3 B/C 类改写（8 处，纯注释）

统一模板：SDK 出处 → ①规范（DNG 1.4 相机色彩表征 / tag 定义）②公开标准（ICC/IEC 61966-2-1/ISO 22028-2）③公开文献（Lam 1985 Bradford、Kim 2002、McCamy 1992、Lindbloom）。参照范本 = color.py:221-224 M3 节的既有写法（「与任何第三方专有常量表无关, 独立实现」）与 tone.py:9-15 的 oracle 声明写法。注意：`huesat_oklch.py`/`convert_hsm_to_oklch.py` 若有「对齐 color.py xxx」措辞不受本次影响（它们引用的是保留符号）。

---

## 3. native/ 同步扫描结果

- `native/src/`（abi/colorcal/decode/hsv/lut3d/oklab/refine/refine_sat_lut/stage_kernels/warm_sat，19 文件）+ CMakeLists：grep `dng|adobe|sdk|rt_|rawtherapee` **零命中**；
- color 相关内核（`colorcal.cpp/h` 的 PixoRenderColorCalApplyLab*/ApplyGamutSoft、`oklab.cpp`、`hsv.cpp`）实现的是 colorcal stage 的 Lab/OKLCh 调整与通用 HSV 数学——**不承袭 color.py 的 DCP 矩阵链**，native 侧无重写面；
- `native/CMakeLists.txt:14`「与 guanlan dng_engine 一致: 静态运行时」为构建选项表述（F18 M10），属 guanlan 惯例提及非 SDK 代码血缘，随 NOTICES 的 guanlan 项一并披露即可。

---

## 4. 汇总：工作量与风险分级

### 4.1 工作量（粗粒度 ±50%）

| 项 | 内容 | 估算 |
|---|---|---|
| A1+A2 重写 | 约束式重写（55 行）+ 重写规格书（常数 pin + 护栏文档化） | 0.5-1 人日 |
| B6+C2 注释改写 | 8 处出处替换（模板化） | 0.25 人日 |
| 验证 | test_color_math + gate --check 零漂移 + 全量回归 + 规范原文核对（§2.2 清单） | 0.25-0.5 人日 |
| 文档 | F18 报告状态更新（含本报告的 H4/H7 降级修正）、NOTICES 口径 | 0.25 人日 |
| **合计** | | **1-1.5 人日（轻档）** |

### 4.2 风险分级

| 级 | 项 | 说明 |
|---|---|---|
| 高（唯一） | A2 常数漂移 | 重写者换用 7 位常数 → ~7e-5 漂移 → 金样本/底座等价击穿。缓解：规格书 pin ICC 4 位值 + --check 实证 |
| 中 | 规范引证未核对原文 | 白点迭代过程的规范原文表述（B4）本会话未核对成功（PDF 404）；若核对发现规范未详述迭代，则 B4 降半档为「规范方法 + 自研数值细节」——不影响定性主结论（迭代本身是公开色彩学方法） |
| 低 | A1 护栏语义 | 0.001 pin/max 归一属通用护栏，重写文档化即可；位等价无虞 |
| 备注 | clean-room 叙事 | 注释改写后**发布文本无 SDK 源引用**；但 git 历史仍含旧注释（F18 已述"读过源码"文字证据在案）——对内是整改记录，对外以发布快照为准（该定位属 F18 处置选项 C 的范畴，决策归队长/用户） |

---

## 来源清单

**代码（文件:行，本会话全文实读）**：`src/pixo/render/core/color.py`（全文 713 行：头部 :1-63、原语 :64-167、DCP 矩阵 :169-216、色温 M3 :218-277、_find_matrices/_neutral_to_xy :280-339、WB :343-394、temp/tint :397-506、主链路 :509-667、ProPhoto 域转换 :669-713）；`src/pixo/render/core/tone.py:1-20,40-43,183,203`；`native/src/` 19 文件 grep 零命中；`tests/unit/test_color_math.py:129,135`。

**内部证据（既有档案）**：`.agent-team/research/dng-sdk-review.md`（F18 H1-H12 定级与本报告的 H4/H7 修正对照）；`.artifacts/gate_calibration_coverage.md:21`（exposure_cal_auto 触达真 cam→sRGB 链路）；`.agent-team/research/arail-removal-eval.md`（A 轨删除范围与 color.py 另案边界）。

**公开标准/文献（定性依据，常数比对）**：ICC PCS D50 (0.3457, 0.3585) 与白点缩放技术——ICC 规范/Lindbloom「Chromatic Adaptation」；ROMM RGB = ISO 22028-2（4 位矩阵公开形）；sRGB 4 位色彩矩阵 = IEC 61966-2-1 派生；Bradford = Lam(1985)；CCT = McCamy(1992)/Kim et al.(2002)/CIE 1960 UCS——均为色科学公开文献（color.py 内 :47,:112-118,:221-224,:408 已自引）。DNG 1.4 规范「Camera Colorimetric Characterization」节——**本会话未取到原文**（helpx/adobe.com PDF 直取均跳转/404，检索超时），引证标注「重写时核对」；备选核对路径：规范 PDF 镜像或 dcpTool/make-model 等公开工具对规范的转述。

**明确标注的推测**：①白点迭代过程在规范原文中的详细程度（置信度中高——B4 定性不依赖其详略）；②「组合公式约束唯一」的数学论断（置信度高——约束①②③给定后线性映射唯一，可由等价测试实证）；③gate 金样本零漂移（置信度高——常数保持 + float64 确定性，落地以 --check 实证）。
