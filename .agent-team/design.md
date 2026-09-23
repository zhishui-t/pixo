# 设计 · R32-T1 RawTherapee RCD 去马赛克移植进 native 内核

队长 2026-09-22 拟；依据 task-brief.md v2（T1）+ dev1-r32-recon.md（侦察结论）。
本设计只覆盖 T1；T2-T8 各步过门禁前另拟增补。

## 0. 定案（依侦察）

| 决策点 | 定案 | 依据 |
|---|---|---|
| 移植策略 | **整文件搬 + 薄适配**（核心 ~330 行原样拷贝） | 数值保真是 A/B 公信力前提；依赖面近自包含（recon 评级 A） |
| 算法事实 | RCD 核心 = 高通色差方向判定（V/H+P/Q 对角）+ 比率修正 + intp 加权合成，**无 census 步**；零算法可调参数（仅 DualDemosaicContrast=20 / ChunkSizeRCD=2 性能参数） | recon 事实纠正，设计不再沿用 census 表述 |
| 归一化 | **(value−black)/(white−black)**，否决 RT 固定 /65536 | Nikon 白电平 15520 场景防整体压暗（recon §4；与 decode_cfa_half 同口径） |
| 依赖面 | 随核心一并移植：rt_math 单行助手（SQR/LIM01/intp）、border_interpolate（demosaic_algos.cc:46 ~70 行）、array2D 以**薄模板垫片**替代（下标语义等价，不改数值） | recon 依赖清单 |
| 并行 | OpenMP pragma 原样保留；CMakeLists 为新文件开 `-fopenmp`（MinGW posix-seh GCC 14.2 libgomp 在位，recon 风险评估低） | 工具链实测 |

## 1. 接口设计

### 1.1 C ABI 入口（对齐 abi.h 状态码约定）

```c
// rcd_demosaic_native.cpp（新文件，native/src/）
// 输入: mosaic (H,W) float32【Python 侧已按 (v-black)/(white-black) 归一化——
//       M3 定夺: 归一化归 Python（96MB 级全分辨率 float 中间缓冲可接受，
//       换 native 纯算法、无 tile 归一化分片复杂度）；LIM01 钳位留在 native（RT 原语义）】
//       pattern: 2x2 CFA 布局码 0=R,1=G,2=B【M2 修正: rawpy raw_pattern 的值是
//       color_desc 颜色索引（两 G 共用 1，无 "3=G2"）——按 io.py:189-207 既有
//       推导取 2x2 索引后映射为布局码】
// 输出: out (H,W,3) float32 线性 RGB
int PixoRenderDemosaicRCD(const float* mosaic, float* out, int w, int h,
                          const int pattern[4]);
// 状态码: 0=OK; FallbackRequested=1（abi.h:17 既有，非新增）= 非 RGBG Bayer /
//         尺寸非法 → 调用方回落 AHD；其余 = 错误
```
- ABI 版本**不升**（1.6.0）：新函数为可选符号，装载门 `_version >= (1,6,0)`
  不受影响；Python 侧按 hasattr 可选门（既有惯例）。
- 非 Bayer（X-Trans）明确不支持 → FallbackRequested（=1，abi.h:17 既有）。

### 1.2 Python 接线（最小面）

- `_native/__init__.py`：`demosaic_rcd(mosaic, pattern) -> rgb | None`（None=回落）；
- `core/io.py`：**对齐既有参数**（M4：decode_raw 已有 `demosaic: str = "AHD"`，
  io.py:135-143）——新增取值 `"RCD"`（大写口径与现有一致），走 rawpy mosaic
  取数（raw_image_visible/raw_pattern/black/white，路径同 decode_cfa_half
  既有实现）→ 归一化 → native RCD → 线性 RGB；失败/不支持回落 AHD 并
  record_degradation；缺省 "AHD" 不变（默认链零漂移）；
- 出口线（M1 修正：**不走 params stage 键**——strict 栅栏拒未知 stage 且
  canonical 不透传）：`_render_full_quality` 加**显式 kwargs**
  `demosaic="AHD"`，ExportManager 加独立通道（照 region_masks 先例
  export.py:169-176：导出请求体独立字段 → 显式 kwargs 透传），不进
  params 白名单体系。
- 预览线不动（cfa_half 分箱是既有语义，RCD 属全分辨率选项）。

### 1.3 A/B 口径

- n≥12 全分辨率（同 R31 pick 算法子采样），臂：AHD（现默认）vs RCD；
- 质量：色彩分离边缘锐度（去马赛克伪彩指标：色度通道高频能量比）、
  ZIP/锐边区伪彩面积、缩放后 ΔE(vs 各自 512 下采样基准的保留度)；
- 耗时：单张全分辨率去马赛克墙钟（含归一化）。
- 判定：RCD 伪彩显著低于 AHD 且耗时倍率 <3x → 判值得（作为可选项保留，
  不改默认；默认切换另议）。

## 2. GPL 合规

- rcd_demosaic_native.cpp 文件头：**保留 RT 原版权块原文** +
  `// Source: RawTherapee rtengine/rcd_demosaic.cc @ 6c4cb59 (GPLv3,
  // ported for pixo (GPL-3.0-or-later); adaptation notes ...`；
- border_interpolate/rt_math 垫片同格式逐处标注；
- THIRD_PARTY_NOTICES.md §8 追加 RT 移植条目（文件清单 + commit + 日期）。

## 3. 测试面

1. 单测（合成）：渐变/棋盘/彩色边缘合成 Bayer → RCD 输出无 NaN、
   单调性（渐变保序）、彩色边缘伪彩低于双线性基线；**四种 Bayer 相位**
   （RGGB/BGGR/GRBG/GBRG）各跑一遍 + FallbackRequested/非法尺寸错误路径；
2. 等价守卫：同一合成 mosaic 的 RCD 输出金样本（确定性，锁算法不漂移）；
3. 回归：全量 pytest 0 failed + gate 金样本零漂移（默认链不动）；
4. A/B 报告数据入 R32 报告（复算口径写死，tester 复算）。

## 4. 风险

| 风险 | 处置 |
|---|---|
| MinGW OpenMP 行为差异 | 编译告警审查 + 串行化开关（#pragma 保留但 CMake 可临时 -fopenmp=libgomp 显式钉） |
| array2D 垫片语义偏差 | 垫片仅下标/边界语义，reviewer 检视逐行对照 RT 原文 |
| 全分辨率耗时超预期 | ChunkSizeRCD 调优；仍超 3x 判"不作为默认、仅选项" |
| WorkBuddy 引擎拒答（侦察期实测 refusal×3） | dev 实施棒兜底宿主原生直接执行，勿重试引擎；报告如实标注执行引擎 |

## 5. 非目标

默认链行为、预览线、master 分支、X-Trans 支持、AMaZE（T1 后续可选项）。


## 6. 修订记录

- v2 2026-09-22（reviewer 4 主要整改落实）：M1 出口通道改 ExportManager 显式
  kwargs（弃 params stage 键）；M2 pattern 口径改 color_desc 索引推导
  （io.py:189-207）；M3 定夺 float 预归一化归 Python、LIM01 留 native；
  M4 对齐既有 `demosaic="AHD"` 大写参数口径；补四相位与错误路径测试。
