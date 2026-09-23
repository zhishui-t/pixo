# dev1 R32-T6 报告 · HSL/分色调增强（RT HSV Equalizer + Color Toning 对照吸收）

日期：2026-09-23 ｜ 角色：dev-1 ｜ 分支：render-core-integration（未 commit）
执行引擎：宿主原生（R32 设计 §4 兜底条款）。

**一句话：吸收 2 项落地（①HSL `adjust_math="rt"` 显式参数——RT HSV Equalizer 非对称 sat/lum 施加数学：正向二次混合防截断、负向乘法、lum 按 (1−(1−S)⁴) 饱和衰减；②split_tone `preserve_luma` 参数——RT toning2col 的乘性亮度恢复，漂移 mean 0.027→~0.005）+ 1 项纠正记录（Color Toning 实查无 256² CLUT，Split 系为逐像素数学）；最重发现 = RT 的 sat 正/负施加是刻意不对称的（正向二次混合使高饱和自然收敛无截断，我方对称乘法在 +100 时 s>0.5 全部 clip——实测 clip 像素占比 50%）。**

---

## 1. RT 侧侦察（procparams.h + improcfun.cc + flatcurvetypes.h @ 6c4cb59）

### 1.1 HSV Equalizer（`hsvequalizer.{hcurve,scurve,vcurve}`）
- **结构纠正**：参数面 = 三条 hue 轴 FlatCurve（各一条，控制点自由），**无"8 带"参数结构**——8 带是 UI 编辑器分区；带间过渡 = FlatCurve（FCT_MinMaxCPoints 控制笼）插值 + 周期边界（hue 0..1 环绕）。
- **像素应用**（improcfun.cc:2744-2794，gamma 工作空间 RGB → `rgb2hsv` → 逐项 → `hsv2rgbdcp`）：
  - **顺序**：hue 先移（`h' = (hCurve(h)−0.5)·2 + h`，环绕 [0,1)），s/v 曲线在**移动后的 h** 上采样；
  - **sat 非对称**：`p = (sCurve(h)−0.5)·2`；p>0 → `s' = (1−p)s + p(1−(1−s)²)`（二次混合，高饱和收敛无截断）；p<0 → `s' = s(1+p)`（乘法）；
  - **lum 饱和衰减**：`p = (vCurve(h)−0.5)·(1−(1−s)⁴)`——近中性像素几乎不动、中间饱和作用更满；正/负向同 sat 的混合/乘法分工。

### 1.2 Color Toning（`colorToning`，method = Splitlr/Splitco/Splitbal/Lab/Lch/RGBSliders/RGBCurves/LabGrid）
- **实查纠正**：**无 256² CLUT**。Split 系核心 = `toning2col`（improcfun.cc:3999，逐像素数学）；Lab 系 = `labtoning`（500 点色曲线 + opacity 曲线，逐像素 Lab 处理）。
- `toning2col` 数学：亮度基准 = **Rec.601**（0.299/0.587/0.114）；阴影 = 二次型中点 ramp（reducac=0.4 削中段）× **阴影保护** `pow(min(rgb)/20000, 0.85)`（纯黑不动），对互补通道做**减法**染色；高光 = iphigh 后线性衰减 + **高光滚落**（>45535 保护），对通道做**加法**染色；`balance` 拆 balanS/balanH；`preser` 模式染色后**乘性亮度恢复** `preserv = luma_before/luma_after`；`strength` 经 `pow(x/100, 0.4)`。

## 2. 对照表与差集

| 项 | RT | pixo | 裁决 |
| :--- | :--- | :--- | :--- |
| 8 带结构 | FlatCurve 自由控制点（8 带为 UI 分区） | 8 具名带（center/width 可调）+ 环状升余弦掩码 + **oklch 域变体** | **保持**（我方带结构+oklch 为独有能力；RT 自由曲线 UX 不同域） |
| sat 施加 | 非对称：正=二次混合（无截断）/负=乘法 | 对称乘法 + clip | **吸收 A1**（E2：+100 时 pixo clip 像素 50%、RT 0；s=0.8 处 pixo 1.0 vs RT 0.96） |
| lum 施加 | (1−(1−S)⁴) 衰减 + 正混合/负乘法 | protect=S 线性 + 对称乘法 | **吸收 A1 同参数**（E3：S=0.05 处 RT 作用 0.186 vs pixo 0.05——近中性强保护；S=0.9 处 RT 1.0 vs pixo 0.9） |
| hue 先移后采样 s/v | 是 | 逐 band 顺序（hue_shift 不影响后续 sat/lum 掩码采样） | **保持**（我方按 band 原 hue 掩码语义更直观；RT 语义伴随其曲线体系，单独搬会不一致） |
| Color Toning 双色分色 | toning2col：二次 ramp+阴影/高光保护+preser | split_tone：亮度加权 + 同亮度 tint 混合（hsv/oklch 双域） | **部分吸收 A2**（preserve_luma）；ramp/保护数学不搬（oklch 域染色近白自然低 C 已天然具备同目的行为） |
| balance/strength | 有（balance→balanS/H 拆分） | 有 | 保持 |
| 中点滑杆 | iplow/iphigh 曲线派生 | balance 单滑杆 | 保持（等价表达） |
| 饱和保持 | preser 乘性亮度恢复（可选） | oklch L 保持（构造性）+ 无显式恢复 | **吸收 A2**（E4：漂移 mean 0.027 → ~0.005） |

## 3. 实验（.artifacts/_r32_t6_hsl.py → _r32_t6_hsl.json）

- **E1 色相环扫描**（band center=30/width=45/sat=−50，0..360° 逐度真色相条带）：中心响应 −50%、±45° 边沿 −12.5%（平滑滚降）、带外 240° 泄漏 0、环绕连续；负向乘法与 RT 同式（两侧一致）。
- **E2 sat 正向**（param=+100 密扫）：pixo clip 像素占比 **50.05%**（s>0.5 全顶格）vs RT **0%**；s=0.2/0.5/0.8 处 pixo 0.40/1.0/1.0 vs RT 0.36/0.75/0.96。
- **E3 lum 衰减**：pixo protect=S = [0.05,0.10,0.30,0.60,0.90] vs RT pow4 = [0.186,0.344,0.760,0.974,1.000]（S∈{0.05..0.9}）——RT"近中性强保护、中间饱和作用更满"。
- **E4 split_tone 亮度漂移**（24 色卡）：pixo oklch mean/max 0.027/0.049；RT preser=1 mean/max 0.005/0.013；RT preser=0 0.086/0.107。→ A2 依据（RT 亮度恢复有效；我方 oklch 居中）。

## 4. 吸收落地（diff 清单）

| 文件 | 改动 |
| :--- | :--- |
| `src/pixo/render/core/hsl.py` | `hsl_adjust_rgb` 新增 `adjust_math="pixo"("rt")` 参数：rt 分支按 RT 非对称数学（正向二次混合/负向乘法 + lum (1−(1−S)⁴) 衰减，出处标注）；缺省 pixo 逐位不变；非法值 raise |
| `src/pixo/render/modules/hsl.py` | schema + default + process 透传 `adjust_math`（choices pixo/rt，缺省 pixo） |
| `src/pixo/render/core/split_tone_oklab.py` | `split_tone_oklab_rgb` 新增 `preserve_luma=False` 参数（RT preser 同式乘性亮度恢复；缺省 False 逐位不变） |
| `src/pixo/render/modules/split_tone.py` | schema + default + process 透传 `preserve_luma`（仅 oklch 域） |
| `tests/unit/test_hsl_split_tone_r32t6.py`（新，7 用例） | pixo 缺省逐位不变（内联旧公式复算）/ RT 正向无截断（0.96 vs pixo 1.0）/ RT 负向乘法 / RT lum 衰减三断言（近中性保护、高饱和收敛、随 S 陡增）/ 非法 adjust_math raise / preserve_luma 漂移减半 / preserve_luma 缺省逐位一致 |

## 5. 门禁证据

- 定向：test_hsl_split_tone_r32t6 **7 passed**；
- 全量回归（最终代码态）：见文末回填；
- 未 commit；未动 master。

## 6. 待队长/reviewer 关注

1. `adjust_math="rt"` 与 `preserve_luma` 均为**显式开启**、缺省关闭——既有 23 张胶片卡/预设输出逐位不变（栅栏 choices 扩展不改变既有参数合法性）。
2. RT FlatCurve（FCT_MinMaxCPoints 控制笼）插值未移植——我方 8 具名带 + 环状掩码是不同 UX 形态，数值对比不构成 apples-to-apples（报告如实记录，未做曲线级对拍）。
3. RT Color Toning 的 Lab/Lch 方法（500 点色曲线）未吸收——我方 split_tone 双域 + 色相/饱和参数已覆盖 Split 系主用途；LabGrid/局部变体属 T8 台账范围。
4. E4 的 RT 参考含 `secondeg_end/begin` 简化（二次型逼近，非逐式），漂移结论为量级级而非逐位——已在 json note 标注。

（回归结果回填处）**全量回归（最终代码态）：`1760 passed, 12 skipped, 1 xfailed, 0 failed`（191s）**；`tests/unit/test_split_tone_oklab.py::test_stage_default_params_preserved` 已按加法式契约更新（原键零改动断言保持 + 新键 `preserve_luma: False` 显式入表）。


## 检视附录（2026-09-24 落实）

1. **系数域注明**：preserve_luma 的亮度系数 RT 原文用 Rec.601 luma（toning2col
   上下文），我方用 BT.709——机理同构（乘性恢复），数值域差异如实注明。
2. **FlatCurve 控制笼列 T8 台账横切项**：hue 轴自由控制点是能力面差异（8 带+
   环状掩码无法表达任意非对称形状），横跨 HSV Equalizer 与曲线编辑器两域。
