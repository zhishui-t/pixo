# dev1 R32 侦察报告 · RCD 移植方案（T1 前置）

日期：2026-09-23 ｜ 角色：dev-1（只读侦察，零代码写入）｜ RT 源码：K:/work/project/rawtherapee @ 6c4cb59（dev）
**一句话结论：RCD 可搬性评级 A（高，近自包含）；预估移植行数 ≈600（native 内核+适配 ≈400、Python 绑定+io 接入 ≈80、测试 ≈150，核心直接拷贝部分约 330 行）。**

> 执行说明：本棒按纪律向 WorkBuddy 引擎提交三次（job-aa756a04c742 / job-69093af4d41f / job-c8c362746593，
> 两种措辞口径），均在提交时被引擎拒答（stop_reason=refusal，未产生 session id）。侦察属非代码产出且
> 红线明示「.agent-team 报告除外」，故兜底由 dev-1 直接完成。无 workbuddy 会话线，请队长知悉。

---

## 1. RT 侧精读结论

### 1.1 输入输出契约（rcd_demosaic.cc，348 行，RCD v2.3，Luis Sanz Rodriguez / Ingo Weyrich tiled 版）

| 项 | RT 侧事实 | 备注 |
| :--- | :--- | :--- |
| 输入 | `rawData`（array2D<float>，W×H），**已减黑电平**、未做 WB、未归一化，值域 [0, 65535] | RT 在 rawData 构建期减黑；demosaic 前置条件 |
| 归一化 | 逐 tile 装载时 `LIM01(rawData / 65536.f)`，域 [0,1]，`scale=65536.f` | 4×4 精度常数：`eps=1e-5`、`epssq=1e-10` |
| CFA 布局 | `FC(row,col)` 从 `ri->get_filters()` 位编码取 0=R/1=G/2=B/3=非 RGB → 收敛为 `cfarray[2][2]` | **任一位置为 3（非 RGB CFA）→ 直接 fallback igv_interpolate**，即只支持标准 Bayer 四排列 |
| G 偏移 | 通过 `fc(cfarray,row,col)&1` 逐行决定奇偶列起点，无硬编码 G 位置 | 对 RGGB/GBRG/GRBG/BGGR 天然自适应 |
| 输出 | `red/green/blue`（array2D<float> 平面），`max(0, rgb01 * scale)`，值域 [0, 65536) | 输入侧 LIM01 决定输出 ≤1.0，无高光超白 |
| 边界 | tile 内算法区留 9px；外框 9px 由 `border_interpolate(W,H,9,…)` 补（demosaic_algos.cc:46，3×3 邻域同色平均，~70 行） | 外圈 tile 也用 9（`rcdBorder=tileBorder=9`） |

### 1.2 算法核心（无 census 步——任务书里 "gradient census direction" 是 AMaZE/DCB 特征，RCD 实为「高通色差方向判定 + 比率修正估计」，报告在此纠正记录）

tile（194×194，有效区 176×176）内五步：

1. **Step 1 方向判定（V/H）**：5 抽头高通色差滤波（类拉普拉斯：`cfa[-3w]-cfa[-w]-cfa[+w]+cfa[+3w]-3(cfa[-2w]+cfa[+2w])+6cfa[0]`）平方，3 行滑动窗累计 → `VH_Dir = V_Stat/(V_Stat+H_Stat)`（行方向用同式水平版）。
2. **Step 2 低通 `lpf`**：同色 CFA 位置 `cfa + 0.5(N/S/E/W) + 0.25(对角)`，按 `indx/2` 打包存储。
3. **Step 3 G@R/B**：四方向梯度（abs 差组合 + eps）；**比率修正估计** `N_Est = cfa[-w]·2lpf/(eps+lpf+lpf[-w])`（RCD 名称由来）；V/H 梯度加权合成；`VH_Disc` 取中心值与 4 邻域均值中离 0.5 更近者（精化判向）；`rgb[1] = intp(VH_Disc, H_Est, V_Est)`。
4. **Step 4 R/B**：4.0/4.1 对角（P/Q）高通色差 → `PQ_Dir` 判向；4.2 R/B@R/B 位：对角梯度 + 对角色差 `rgb[c]-rgb[1]`，加权得 P/Q Est，`rgb[c]=rgb[1]+intp(PQ_Disc,…)`；4.3 R/B@G 位：G 梯度 N1/S1/W1/E1 + 色差，V/H 加权。
5. **写出**：`rgb[0..2] × scale` 钳非负写入全局平面；随后 border_interpolate 补外框。

`intp(a,b,c)=b+a(c-b)`；装载时 `rgb[c0][indx]=rgb[c1][indx]=cfa 值`（每行两个 CFA 色平面同点播种）。

### 1.3 依赖面清单（评级核心：意外地干净）

| RT 依赖 | 用途 | 处置 | 预估行数 |
| :--- | :--- | :--- | :--- |
| `rt_math.h`：`SQR/LIM01/intp/max` | 单行 constexpr 模板 | **内联复制进新文件**（GPL 头同文件标注） | ~15 |
| `array2D<float>`（rawData/red/green/blue） | 仅 `[row][col]` 下标 | **替代**：裸指针 + 显式 stride | 0（签名层） |
| `FC()/cfarray` | CFA 索引 | **替代**：入口传 `patternR/G0/G1/B`（rawpy 已有） | ~10 |
| `border_interpolate`（demosaic_algos.cc:46） | 9px 外框 | **整搬适配**（纯函数，仅用 FC） | ~70 |
| `igv_interpolate` | 仅 FC==3 fallback | **替代**：返回 FallbackRequested → Python 回落 AHD | 0 |
| `StopWatch`/`plistener`/`M()`/Glib | 计时/进度/i18n | **丢弃** | −20 |
| `ALIGNED16` | bufferH 对齐 | **替代**：`alignas(16)` | 1 |
| Imagefloat / LUT / 曲线 | **未使用** | 无需 | 0 |
| OpenMP（`parallel` + `for collapse(2) schedule(dynamic,chunk) nowait`） | tile 级并行 | **保留**（`_OPENMP` 守卫，可无 OMP 串行编译） | 0 |

线程安全：每线程自持 tile 缓冲（cfa+rgb[3]+VH_Dir+PQ_Dir/lpf+P/Q_CDiff_Hpf ≈ **1.3 MB/线程**），唯一共享写是进度上报（`omp critical`，丢弃）。无数据竞争。

### 1.4 调度与参数面（辅助精读结论）

- 分发点在 `rawimagesource.cc:1797 RawImageSource::demosaic()`（不在 demosaic_algos.cc）：按 `raw.bayersensor.method` 字符串 switch；`RCD → rcd_demosaic(options.chunkSizeRCD, options.measure)`；`RCDBILINEAR/RCDVNG4 → dual_demosaic_RT()`（对比度阈值混合 RCD 与 bilinear/VNG4，amaze 同型，T1 核心不做）。
- amaze_demosaic_RT.cc（1610 行）仅扫结构：依赖远重于 RCD（LUT/gamma/多 pass、`(0,0,W,H,raw,rgb…,chunkSize,measure)` 签名）；**T1 选 RCD 首选正确**。
- **pp3 参数面**：核心 RCD **零算法可调项**（eps/tile/border 全部硬编码）。RT 侧仅两项：`[RAW Bayer] Method = rcd|rcdbilinear|rcdvng4`；`DualDemosaicContrast`（默认 20，仅 dual 变体）。性能参数 `ChunkSizeRCD` 默认 2（rtgui/options.cc:526，非 pp3）。

## 2. 我方接入点现状

- **io.py:135 `decode_raw`**：rawpy postprocess（`output_bps=16, output_color=raw, user_wb=(1,1,1,1), gamma=(1,1)` R28 钉死，AHD 默认）→ float32/65535 [0,1]（高光可 >1 语义：相对白电平）。RCD 接入点：`demosaic="RCD"` 时走 native 分支。
- **io.py:165 `decode_cfa_half` 已建好 mosaic 获取全路径**（直接复用）：`raw_image_visible`（uint16 HxW）→ `raw_pattern`+`color_desc` 校验 1R+2G+1B 得 `patternR/G0/G1/B`（0..3 线性位置）→ `black_level_per_channel` 按位置 → `white_level`。
- **native C ABI 约定**（abi.h）：`PIXO_RENDER_NATIVE_API`（Win dllexport）；状态码 `PixoRenderOk=0 / FallbackRequested=1 / InvalidArgs=-1 / Unsupported=-2 / InternalError=-3`；参数=纯 C 结构体 const 指针；入口 `int PixoRenderXxx(in, out, width, height, params)`。Python 侧 `_native/__init__.py` 逐结构体 ctypes.Structure + argtypes/restype，DLL 预编译随包。
- **构建/测试**：CMake 单 SHARED `pixo_render_native`（源文件显式列举，加 rcd.cpp 即可）；tests/test_main.cpp 零依赖 CHECK 宏 harness，返回失败数。

## 3. 移植策略推荐：整文件搬 + 薄适配层（否决"按算法重写"）

理由：(a) 依赖面近乎自包含（§1.3），适配成本低于重写验证成本；(b) 数值逐位保真——A/B 结论「RT 的 RCD」才有公信力，重写则无法区分算法差异与重写误差；(c) tile/OpenMP 结构久经 RT 生产验证；(d) 出处标注清晰（同一文件可识别对应）。

## 4. C ABI 接口草案

```c
// src/pixo/render/native/src/rcd.h —— 文件头带 GPL 块（见 §7）
struct PixoRenderRcdParams {
    int patternR, patternG0, patternG1, patternB;  // 2x2 线性位置 0..3（row-major）
    float black[4];      // 按 2x2 线性位置的每位置黑电平（Python 侧换算，同 cfa_half）
    float whiteLevel;    // raw.white_level
};
// cfa: HxW uint16 C 连续（raw_image_visible）
// rgbOut: H*W*3 float32，HWC 交错，白电平相对 [0,1] 线性相机 RGB（与 decode_raw 语义一致）
PIXO_RENDER_NATIVE_API int PixoRenderDemosaicRcd(
    const uint16_t* cfa, float* rgbOut, int width, int height,
    const struct PixoRenderRcdParams* params);
```

- 状态映射：参数非法 → `InvalidArgs`；非 RGB CFA（对齐 RT 的 igv fallback）→ `FallbackRequested`（Python 回落 AHD）；其余 `Ok`。
- **归一化决策点（供设计定夺）**：RT 用固定 `/65536`（其 rawData 值域上限即 65535 无削波）；我方建议按 `(white−black_pos)` 归一（Nikon 白电平常 15520，固定 /65536 会整体压暗），raw 峰值恰映射 1.0，高光语义与 decode_raw 对齐，A/B 更公平。tile 内逐点 `LIM01((raw−black)/(white−black))` 装载，不引入全分辨率 float 中间缓冲（遵循 RT 逐 tile 装载）；border_interpolate 移植同样按此归一化读入。
- Python 路径：io.py 新增 `decode_raw_rcd()`（或 decode_raw 分支）复用 decode_cfa_half 的 rawpy 取数段 → ctypes 调用 → (H,W,3) float32；export 主线 `_render_full_quality` 加 demosaic 选项，**默认链保持 AHD 不动**（金样本零漂移红线）。

## 5. A/B 实验设计（vs AHD，n≥12 全分辨率）

- 语料：≥12 张全分辨率 RAW，混品牌/传感器/ISO 100–6400，覆盖细纹理（树叶/砖墙/织物/文字）与高反差边；可参照 R22 A/B 惯例（.agent-team/tmp-r22-f02-ab-render.py 有先例）。
- 双臂：A=现 decode_raw(AHD)；B=PixoRenderDemosaicRcd；下游链（WB→DCP→tone→sRGB）逐位同参。
- 指标：(1) **耗时**——去马赛克单步 wall clock（native 调用段 vs rawpy 段）+ 全导出耗时，mean/p95，暖机同机；(2) **细节**——Laplacian 能量比 / MTF50（斜边可测时），B/A 比值；(3) **伪彩/拉链**——中性区与边缘带高频色度离群计数；(4) **色差**——oklch 域 ΔE2000 p50/p95（无真值，记录 A↔B 差异）；(5) **稳定性门禁**——AHD 默认链金样本必须零漂移。
- 建议验收口径：无伪彩回归、细节比 ≥1.0（细纹理 crop）、去马赛克耗时 ≤ AHD×3（RCD 典型 2–3×，AMaZE 约 5×）。产物落 .artifacts/R32_rcd_ab/。

## 6. 风险清单

| # | 风险 | 评估/对策 |
| :--- | :--- | :--- |
| 1 | OpenMP 在 MinGW（GCC 14.2 posix-seh） | 支持 `-fopenmp`（winpthreads 随 posix 线程模型在位），`collapse(2)`/dynamic 均被 GCC 支持，风险低；代码 `_OPENMP` 守卫，无 OMP 自动退串行；CMake 加 flag 并在 CI 实测一次 |
| 2 | array2D 内存布局 | RCD 仅 `[row][col]` 寻址且 tile 缓冲固定 stride=194 → 换裸指针+stride 零语义差；逐 tile 装载结构保持 |
| 3 | GPL 出处标注 | 新文件头：原版权声明（Luis Sanz Rodriguez & Ingo Weyrich 2017-2020）+ "This file is part of RawTherapee" GPLv3 块原文保留 + 我方适配说明（来源 rtengine/rcd_demosaic.cc 与 demosaic_algos.cc border_interpolate，commit 6c4cb59，上游 https://github.com/LuisSR/RCD-Demosaicing）；pixo 已 GPLv3，合规路径现成 |
| 4 | 高光语义差异 | RT 输入侧 LIM01 理论封顶 1.0；按 §4 (white−black) 归一后实测无削波，A/B 报告中记录该决策 |
| 5 | 单色/非 Bayer CFA | FC==3 → FallbackRequested，Python 回落 AHD（对齐 RT fallback igv 的行为哲学） |
| 6 | 内存 | 每线程 tile 缓冲 1.3MB；输出 H×W×3 float32（24MP≈288MB，与现有 decode 同量级）——可控 |
| 7 | 数值漂移 | 移植禁"顺手重构"（不换 double、不动常量 eps=1e-5/tile=194/border=9），保证与 RT 生产版行为一致 |
| 8 | WorkBuddy 引擎拒答 | 本棒实证：两种口径均提交即拒（refusal）。后续棒次若再遇，直接由当值 agent 兜底并声明，勿反复重试浪费轮次 |

## 7. 移植工作量预估（供队长排期）

- `rcd.h/rcd.cpp`（新）：内核整搬适配 + border_interpolate + rt_math 内联 ≈ **400 行**；
- `_native/__init__.py`：ctypes 结构体+绑定 ≈ 40；`io.py`：`decode_raw` RCD 分支 ≈ 40；
- 测试：test_main.cpp（合成 Bayer 梯形/恒色场数值校验 + 错误码）≈ 80；pytest 冒烟（真 RAW 走通 + 形状/值域 + 回落路径）≈ 70；
- 合计 **≈ 600 行**（其中直接拷贝自 RT 约 330 行，全部带出处标注）。
