# dev1 R32-T5 报告 · 直方图后端增强（RT 直方图对照吸收）

日期：2026-09-23 ｜ 角色：dev-1 ｜ 分支：render-core-integration（未 commit）
执行引擎：宿主原生（R32 设计 §4 兜底条款）。

**一句话：吸收 2 项代码落地（①Lab L\* luma 模式 `luma="lab_l"` → 新键 `lum_lstar`，RT 面板 Luma 同口径，既有 lum/r/g/b 逐位不变；②曲线编辑器联动数据面契约定型——pre-curve 帧 + `bins=256` + `counts.lum` 即编辑器背景数据形状，函数层已可对任意帧计算、管线级截帧待曲线 UI）+ 1 项裁决"已具备"（parade 非独立数据模式，r/g/b 键即数据面）；联动接口形态 = `/histogram` 端点 `luma=lab_l`（已透传，缺省输出键集不变）。**

---

## 1. RT 侧侦察（improccoordinator.cc + improcfun.cc + histogrampanel.h/cc @ 6c4cb59）

| 数据面 | RT 口径（逐处核实） |
| :--- | :--- |
| 面板 RGB 直方图（histRed/Green/Blue，各 256 桶） | `updateLRGBHistograms`：**处理全链完成后**的 8-bit gamma 工作图（workimg Image8）逐像素计数 |
| 面板 Luma（histLuma，256 桶） | **LabImage 的 L\* 通道**（`nprevl->L / 128`，L\*∈[0,100] 线性映射 256 桶）——**不是 BT.709 Y**；CIE L\* 感知均匀 |
| Chroma（histChroma） | Lab a/b 的 √(a²+b²)/188 → 256 桶 |
| **曲线编辑器联动**（histToneCurve，256 桶） | `firstAnalysis`：**一切处理前**的工作空间 Y 通道直方图（**65536 桶** master，`y = wprof[1]·rgb`，工作空间亮度行系数），经 CurveFactory 压缩为 256 桶做曲线编辑器背景；同一 master 喂 `getAutoExp` 做**曝光/对比曲线自动匹配**（匹配曲线联动的数据源头） |
| RAW 直方图（histRedRaw 等） | `imgsrc->getRAWHistogram`（WB 前 raw 通道分布） |
| **RGB parade** | **非独立数据模式**——`drawParade` 仅把同一组 rwave/gwave/bwave（RGB 波形，非直方图）渲染为三窗并列布局〔检视勘误 2026-09-24：底层数据是波形非 histRed/Green/Blue〕（竖/横两种排布类） |
| 下采样/性能 | 全部算在**预览级图像**（pW/pH，非 1:1 raw）；firstAnalysis 按 `W·H/histogram.getSize()` 定 OpenMP 线程数；updateLRGBHistograms 用 `omp parallel sections`（chroma/luma/rgb 三段并行）；监听器一次 `histogramChanged` 推送全部 scope 数据（曲线编辑器背景随预览实时刷新即走此通道） |

## 2. 我方现状与差集（对照表）

| 项 | RT | pixo R25 | 裁决 |
| :--- | :--- | :--- | :--- |
| 域 | RGB=8bit gamma 工作图；Luma=**Lab L\*** | 输入即显示域（gamma sRGB），lum=**BT.709 加权（gamma 域）** | lum 保持；**L\* 口径缺口 → 吸收 A1** |
| parade | 渲染布局（同数据三窗） | r/g/b 键已具备同数据 | **已具备，无 diff**（前端布局语义记入联动契约） |
| 曲线编辑器联动 | firstAnalysis 预处理 Y master + histToneCurve 推送 | 函数可对任意帧算直方图，但管线无 pre-curve 截帧、端点无 stage 参数 | **数据面契约定型（A2）**；管线截帧待曲线 UI 落地（见 §4） |
| 匹配曲线联动 | getAutoExp(vhist16) → 曝光/对比自动匹配 | 无（T7 曝光六项校准的姊妹能力） | 不在本棒（T7 域，登记） |
| 下采样 | 预览级 + OpenMP sections | 调用方帧（long_edge 控制尺寸）+ numpy 向量化 | 等价，不动 |
| bins | 固定 256/65536 | 2..1024 可调 | 我方更灵活，保持 |

## 3. 吸收集落地（diff 清单）

| 文件 | 改动 |
| :--- | :--- |
| `src/pixo/vision/measure.py` | `compute_histogram` 新增 `luma: str = "bt709"` 参数：`"lab_l"` 追加 `lum_lstar` 键（gamma sRGB → EOTF 逆 → 线性 BT.709 Y → CIE L\* 分段式 → ×2.55 分桶域；工作空间原色差为二阶近似，docstring 如实记录）；新增 `_lstar_255` 助手；非法 luma raise；**既有 lum/r/g/b 键与语义逐位不变**（bt709 路径零改动） |
| `src/pixo/service/runtime.py` | `histogram_session` 加 `luma="bt709"` 透传 |
| `src/pixo/service/app.py` | `/histogram` 端点加 `luma` query 参数；ValueError → 400 |
| `tests/unit/test_f04_param_fence.py` | **reviewer 遗留补齐**：栅栏 mode 断言 ×3（合法五值全过 / 非法值拒且含原因 / Stage._curve_dict_check 抛 ValueError） |
| `tests/unit/test_proxy_metrics.py` | 新增 4 用例：lab_l 追加键 + 缺省键集逐位不变 / 中灰 118 → L\*≈49.6 → 126 桶（±2）/ 黑白端点 + 灰阶 L\* 单调 / 非法 luma raise |

## 4. 曲线编辑器联动数据面（契约，供 T-后续曲线 UI 落地）

RT 形态 = "两时点直方图 + 一次推送"：编辑器背景 = **pre-curve** 工作空间 luma（256 桶显示压缩），面板 = post 处理直方图。我方对齐契约：

- **背景数据形状**：`compute_histogram(pre_curve_gamma_frame, bins=256)` 的 `counts.lum` —— 在 user_curve 施加前的帧上调用即得（函数已可对任意帧计算，本棒无需 diff）；
- **待落地（管线级，非本棒）**：session 渲染管线在 tone stage 前截帧（与 RT `orig_prev` 同位），端点加 `stage=final|pre_tone` 参数后即可成对推送；
- **显式开启**：`luma=lab_l` 供编辑器 y 轴感知口径（默认关）。

## 5. 门禁证据

- 定向：test_proxy_metrics（14 passed 1 skipped）+ test_f04_param_fence（50 passed，含新增 3）+ test_user_curve 28；
- 全量回归（最终代码态）：见文末回填；
- 未 commit；未动 master。

（回归结果回填处）**全量回归（最终代码态）：`1753 passed, 12 skipped, 1 xfailed, 0 failed`（198s）**。
