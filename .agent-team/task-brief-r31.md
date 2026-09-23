# 任务书 · R31 RAW 打开色彩对齐 DNG 渲染（Prism delivery 团队）

日期：2026-09-22 ｜ 队长：主会话 ｜ 团队：Prism delivery（适配裁剪见花名册）

## 1. 目标

**RAW 打开的色彩与 Adobe DNG 默认渲染对齐**（北极星：打开照片 ≈ DNG/Adobe 系观感）：

1. 建成 **DNG 参照发生器**（Adobe DNG SDK 1.7 的 dng_validate 默认渲染，本机编译）；
2. NEF→DNG 批量转换（Adobe DNG Converter 18.6，winget）；
3. n=48 首批**三臂**对照：pixo 默认打开（default_look）/ **RawTherapee-cli 渲染**
   / DNG 默认渲染，逐片 ΔL/Δa/Δb 分布（Lab 8 位标度，p10/p50/p90/IQR）
   ——RT 臂兼任"是否换核/搬哪块算法"的选型依据（用户裁决 2026-09-22）；
4. **矫正裁决（预授权）**：判据 = 中位 |ΔL| > ~5（≈2 JND，8 位标度）或残差有
   结构（与 wb_B/场景相关）→ 直接重拟合 default_look（fit_tone_curve.py 管线
   换目标至 DNG 渲染参照），全量回归 + 落档；未超阈 → 判达标，出分布证据收工；
5. 需要时（达标存疑/用户要求）后台扩全量 4053 张。

## 2. 范围与非目标

**做**：参照发生器编译/批转/测量/矫正（限 `configs/styles/default_look.json`
与标定数据）/回归/落档（R31 报告 + changelog）。

**不做**（明确非目标）：
- 分割模型进渲染引擎（单列下一轮，用户裁决）；
- auto-loop / decide 侧任何改动；
- 前端改动；Compositor 移植/集成；
- 引擎各 Stage `default_params` 改动（R23 中性纪律不破）。

## 3. 约束

- 工具链：本机免费（SDK 已下载 `K:/work/project/dngsdk/dng_sdk_1_7`；MSVC
  BuildTools cl 14.44；winget `Adobe.DNGConverter` 18.6）；
- jxl 已处置：`qDNGSupportJXL=0` + vcxproj 摘除 jxl 三引用（待重编验证）；
- 观感改动仅限数据文件（default_look.json / 标定 json），不改引擎默认；
- 判据先行（本节 1.4），改动必须过全量 pytest（0 failed 基线）+ gate 金样本零漂移；
- 参照口径如实记录：dng_validate 默认渲染参数（as-shot WB / 嵌入 profile 选择 /
  输出空间）写进报告，可复现。

## 4. 完成标准

- [ ] dng_validate.exe 编译成功并渲染出首张 DNG 参照图；
- [ ] NEF→DNG 批转链路打通（子样本）；
- [ ] n=48 对照分布报告（分位数表 + 逐片散布 + 口径记录）；
- [ ] 裁决落地：矫正（重拟合 + 全量回归绿 + 报告）或判达标（分布证据）；
- [ ] R31 报告 + changelog + 提交推送；
- [ ] 全量 pytest 0 failed；金样本零漂移。

## 5. 现状与材料

- SDK zip 已解压；MSBuild 可用；xmp/jpeg 依赖首轮已编译通过；**唯一卡点是
  jxl 的 ClangCL 工具集（已摘，待重编）**；
- pixo 侧：default_look.json 已接为默认打开（R30）、fit_tone_curve.py 拟合
  管线在仓（R24）、f01_batch 度量台架、语料 K:/data/photo 4053 张 NEF；
- 已有参照证据：R29 LR 双锚点（色度已锚定）、R30 三轴分解（病灶=亮度轴）。

## 6. 优先级与风险

- **P0** 参照发生器编译（硬前提；风险：残余编译错误 → 备选最小 main 自写渲染壳）；
- **P1** 批转 + 测量（风险：DNG Converter 静默安装失败 → GUI 装或缩子样本；
  dng_validate 渲染速度未知 → 用小尺寸渲染选项）；
- **P2** 矫正 + 回归（判据已预授权，风险低）。

## 修订记录（卡点①讨论追加，用户 2026-09-22 批准）

- 测量升级为**三臂**（+RawTherapee-cli 参照臂）；
- 新增前置任务：pixo 正式定 **GPLv3** 许可证（补 LICENSE + 改 pyproject
  `Proprietary` 残留）——为后续按需移植 RT GPL 算法铺路；
- 方向裁决：不换 RT 核心（闭环架构保留），走"搬算法不搬核心"路线。

## 复述确认记录

- 2026-09-22 用户答问定案：①规模=先 n=48 定方向、需要时再全量；②矫正=预授权
  直接改（判据先行）；③分割进引擎=单列下一轮，本轮只做主线。
- 目标/约束/完成标准源自本会话用户指令（"raw打开 色彩要和dng渲染差不多"
  "先不说 loop""把模型放进渲染引擎"〔次线〕）。
- 卡点①批准：2026-09-22 用户回复「可以」（含三臂+GPLv3 修订）。
