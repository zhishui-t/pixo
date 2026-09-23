# 任务书 · R32 RawTherapee 组件移植战役（render-core-integration 分支，串行）

日期：2026-09-22 ｜ 队长：主会话 ｜ 分支：render-core-integration（基于 a8f7890）
来源：用户指令「任务先一个一个来 把 RawTherapee 的核心算法 dcp 胶片 这都给搬过来」。
**v2 修订（用户 2026-09-22 口头定案）**：原三线并行改为**串行**，RT 移植线先行扩为三步；
分割进引擎（S1）与 Compositor 图层模型（S2）**后置排队**（本轮非目标，队列登记）。

## 0. 串行队列（一个一个来；用户 2026-09-22 三连指令扩容：曲线/直方图/HSL 也要）

**本轮 = RT 移植六步串行**：
- T1 核心算法：去马赛克 RCD/AMaZE 进 native；
- T2 DCP 处理：RT 双光源 DCP 链对照吸收；
- T3 胶片模拟：HaldCLUT 引擎接入 + 对接 LUT 卡库；
- T4 曲线：RT 的 tone curve 体系（控制点/插值模式 linear-smooth-spline-Akima/RGB 与
  Lab 域/分通道）——**增强**我方 user_curve（我方已有控制点版，吸收 RT 插值与多域）；
- T5 直方图：RT 直方图后端（RGB parade/亮度/匹配曲线联动数据口径）——增强我方
  R25 compute_histogram（对照吸收，非整替）；
- T6 HSL 等：RT 的 HSV Equalizer（8 带 hue/sat/lum）与 Color Toning（阴影/高光分色）
  ——增强我方 hsl stage（oklch 域）与 split_tone；
- T7 曝光六项优化校准（用户 2026-09-22）：RT 曝光工具链——阴影/高光恢复算法、
  黑白点（含逐通道黑点）、Highlight compression、auto-matched 曲线——对照吸收
  **优化校准我方 T1.5 六键**（exposure + highlights/shadows/whites/blacks）。
- T8 **全模块清点收尾**（用户 2026-09-22「还有需要的都吸收进来」）：RT 全模块过一遍
  ——小波工具套件、局部调整（蒙板局部编辑器）、Retinex、色调映射、RL 锐化/小波降噪、
  色差矫正、镜头矫正（lensfun）、HDR 合成、BADPIXEL、批量引擎等——出**吸收台账**
  （我方现状 × RT 能力 × 吸收/跳过 × 理由），按台账逐个裁决，需要的全收。
后续轮（排队）：分割进引擎、Compositor 图层模型。

**T4-T6 姿态 = 对照吸收/增强**（我方已有实现，按差异清单+数据定吸收项，同 T2 口径），
非盲目整替；RT 侧为 GPL 参照实现，吸收代码逐处标注出处。

## 1. 目标（三步各设验收）

**T1 RT 核心算法——去马赛克进 native**（原 S3 前置）：RF-DETR/SegFormer multi-router（ONNX）从 vision 层接进渲染管线——
打开照片自动出语义蒙板（face/sky/plant），region_adjust 直接消费；懒加载+进程内缓存，
预览路径性能不回退（对比基线：无分割时打开耗时）。

**T2 RT DCP 处理链移植/吸收**：参照 robbietilton/Compositor（MIT）的
project-format schema 纪律，设计 pixo 图层栈数据模型 v1（图层/文件夹/混合模式/不透明度/
蒙板/调整图层/剪贴）+ 引擎侧合成内核（blend/mask/adjust-layer 应用）+ 服务 API 骨架。
**不含前端画布 UI**（下一轮）。

**T1**：RT 的 RCD（首选）/AMaZE 移植进 native 内核（GPLv3 已落地，逐处标注出处），
作为全分辨率导出的去马赛克选项；A/B 对比现 AHD 的质量与耗时。
**T3 胶片**：RT Film Simulation 的 HaldCLUT 应用引擎（rtengine 侧代码）接入 +
HaldCLUT→我方 LUT 卡库的格式适配；**CLUT 图数据本身许可异质**——只搬引擎代码，
数据包许可评审后另议入库。

## 2. 范围与非目标

**做**：T1→T2→T3 串行（前一步过门禁才开下一步）+ 各步单测/金样本/门禁 + 全量回归。
**不做**：前端画布/图层面板（S2 下一轮）；master 分支任何改动（全在 render-core-integration）；
R23 中性纪律破例（S1/S2 均为显式能力，不改默认链语义）；RT 色科学模块（S3 后续）。

## 3. 约束

- GPLv3 合规：pixo 已 GPLv3；移植代码文件头标注来源（RawTherapee 源文件路径+版本）；
- **native 工具链 = MinGW（用户 2026-09-22 指令）**：历史构建=MinGW Makefiles + g++
  （build.bat 原生路径 D:\code\mingw64 (GCC 14.2.0 posix-seh) + D:\code\cmake-3.31.6
  ——**用户指认在位，实测核验通过，零安装**）；
- RT 源码 clone 进外部目录（K:/work/project/rawtherapee，同 dngsdk 惯例，不进 pixo 仓）；
- T2 与我方 clean-room DCP 实现的关系=**对照吸收**（RT 侧为参照实现，差异落报告，
  吸收与否按数据定），不盲目整替；
- 全量 pytest 0 failed 基线；gate 金样本零漂移（三线均不得动默认链输出）。

## 4. 完成标准

- [ ] T1：RCD native 内核 + 质量测试 + n≥12 全分辨率 A/B（vs AHD）质量/耗时数据；出处标注齐。
- [ ] T2：RT DCP 链对照报告（与我方实现的差异清单+逐项数据）+ 吸收决定落档。
- [ ] T3：HaldCLUT 引擎接入 + ≥3 张胶片效果实测（对接 LUT 卡库形态）；数据包许可评审结论。
- [ ] 每步 reviewer 门禁 + 全量回归 0 failed + 分支推送；R32 报告 + changelog。
- [ ] R32 报告 + changelog。

## 5. 现状与材料

- R31 状态：测量完成（色度 PASS/亮度 13.44 FAIL），候选 c（4.453）仲裁**挂起待用户**，
  R31 的检视/回归/交付段顺延至本战役收官一并补（黑板有全链记录）；
- RT 源码：本机未 clone（T1 开工先 clone 到 K:/work/project/rawtherapee）；
- 我方现状：去马赛克=rawpy AHD（decode_raw）+ native cfa_half 分箱；DCP=calibration.py+huesat
  （clean-room，R11/R12 清偿）；LUT 卡库=lut3d + configs/styles/films（.cube）；
- native：src/pixo/render/_native/（DLL）+ native/src（源码）——构建链归属待核。

## 6. 优先级与风险

串行 T1→T2→T3，单 dev 流 + reviewer 每步门禁 + tester 每步回归；风险：native 工具链归属
（T1 前置核实）、RT 代码与 rawpy 数据结构的适配层（CFA mosaic 布局/黑电平口径）、
胶片 CLUT 数据许可异质（只搬引擎，数据另议）。

## 复述确认记录

- 2026-09-22 用户：「拉一个新分支 我们渲染核心把之前的组件接进来」→ 已执行（分支已建）；
  「都要」→ 三组件线全要；「任务先一个一个来 把 RawTherapee 的核心算法 dcp 胶片 这都给搬过来」
  → **v2 定案：串行、RT 线先行（T1 核心算法→T2 DCP→T3 胶片），分割/图层后置排队**。
