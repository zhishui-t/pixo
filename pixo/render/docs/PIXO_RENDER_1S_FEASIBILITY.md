# pixo.render 1s 渲染目标可行性预研

> 版本：v1.0  
> 状态：待审核  
> 作者：架构师（长安小队）  
> 需求来源：`render/docs/PIXO_RENDER_PERFORMANCE_REQUIREMENTS.md` §6.1  
> 架构依据：`render/docs/PIXO_RENDER_NATIVE_ARCHITECTURE.md` v1.0  
> 关联任务：t8（本文档）、t1~t7（native 4s 路线）、后续“1s 路线”专项任务

---

## 0. 结论（TL;DR）

1. **“half_size 全质量管线压缩到 1s”当前架构下不可行，不建议直接立项。**
   decode 已占 ~0.9s，且 half_size 全链有 12 个 stage；仅靠 CPU 上的
   C++/SIMD/OpenMP/LUT 优化，合理下限约 **1.5~2.5s**（含 decode）。
2. **“1s 左右”可以成立，但必须限定口径**，推荐按三个口径分档实现：
   - **P0 即时预览（0.1~0.3s）**：`rawpy.RawPy.extract_thumb()` 内嵌 JPEG/缩略图，
     只用于“看有没有拍对”，不走 pixo.render 色彩链路。
   - **P1 管线预览（0.4~1.0s，推荐先做）**：`preview_fast` 轻量链
     [exposure, whitebalance, huesat(关), tone] + **C++ 快速解码**
     （CFA 2×2 分箱 half/quarter 解码），用 native 内核跑少数活跃 stage。
   - **P2 最接近 1s 的高质量快档（1.5~2.5s，作为 4s 主线的下一跳）**：
     t1 架构的 native 内核全量合入 + OpenMP/SIMD + colorcal 3D LUT +
     低频 stage 降采样，再决定是否上 GPU。
3. **真正“half_size 全质量 1s”需同时满足 §7 的 6 个硬条件**（自研 decode +
   全部 stage render/native/LUT + GPU 或等效算力），建议作为实验分支（探索性任务），
   不作为验收承诺。

---

## 1. 目标定义与基线

| 口径 | 分辨率 | 链 | 输出 |
|---|---|---|---|
| A. 全质量 half_size | 2020×3032 | 默认 12 stage 全链 | 与当前引擎视觉一致（ablation ≤5e-5） |
| B. 高质量快档 | 2020×3032 | 默认链 + 可选 stage 精简 | 视觉接近 A，允许量化 A/B 差异 |
| C. 管线预览 | half/quarter/eighth | preview_fast 轻量链 | “快、可见、大致准” |
| D. 即时预览 | 内嵌缩略图 | 不走管线 | 相机内嵌观感，秒开 |

基线（需求文档 §2 / 性能实测 2026-08-20）：

| 环节 | 当前耗时 | t1 后目标（4s 路线） | 1s 路线预算 |
|---|---:|---:|---:|
| decode（rawpy AHD half_size） | ~0.9s | ≤0.9s（不优化） | ≤0.25s |
| huesat | 1.8~3.0s | ≤0.6s | ≤0.15s |
| colorcal | 2.5~2.7s | ≤0.8s | ≤0.20s |
| refine | 1.7s | ≤0.7s | ≤0.15s |
| 其余 stage + Python 开销 | ~1.0~1.1s | ≤1.0s | ≤0.25s |
| **合计** | **~8s** | **≤4s** | **≤1.0s** |

1s 预算说明：half_size 图约 6.1MP × 3 通道 float32 ≈ 73MB。理想带宽下
单遍读写只有 ~10ms 级，但热点耗时来自多遍广播、超越函数、分支与中间数组；
**只有每 stage 都变成“单遍 C++/LUT + 并行”才有机会**，任何一处保留 Python
广播都会击穿 1s 预算。

---

## 2. decode 加速可行性（1s 路线的关键约束）

当前 `render/core/io.py::decode_raw`：`rawpy.postprocess(output_color=raw,
output_bps=16, half_size=True, demosaic=AHD, no_auto_bright=True)`。

### 2.1 可选方案

| 方案 | 机制 | 预估耗时 | 质量影响 | 建议 |
|---|---|---:|---|---|
| D0 保持现状 | rawpy AHD half_size | ~0.9s | 无（基准） | 4s 路线默认 |
| D1 参数降档 | demosaic AHD→LINEAR、output_bps=8 | 预计 0.4~0.7s，需 bench 实测 | 拉链/摩尔纹风险，8bit 丢高光精度 | 仅 B/C 档；A 档禁用 |
| D2 内嵌缩略图 | `raw.extract_thumb()` | 0.05~0.2s | 相机机内观感，非 pixo.render 链 | D 档专用 |
| D3 half_size + 再降采样 | rawpy 无 quarter_size 参数，仅能 half 后 `cv2.resize` | 0.9s + ~0.03s | 分辨率降、色彩不变 | 不改 decode，无 1s 意义 |
| D4 自研 C++ 快速解码 | CFA 2×2 分箱 + WB + 色彩矩阵 | 0.10~0.30s（6MP；SIMD+OpenMP） | 与 AHD 有差异，需 A/B 门禁 | 先 C 档，后评估 B 档 |
| D5 GPU 解码 | CUDA/OpenCL demosaic（若平台有可用设备） | 0.05~0.15s + 传输 | 依赖 GPU 可用性与驱动 | 实验分支 |

### 2.2 关键结论

- rawpy 的 `half_size` 已是 LibRaw 的快速解码开关；**在 rawpy API 内继续压 decode
  的合法空间很小**（仅 demosaic 算法与位深，且质量风险大）。
- 1s 若要求“pixo.render 自己的色彩”，D4（CFA 2×2 分箱快速解码）是唯一现实路径；
  其质量门禁建议：预览档先上（允许视觉差异说明），高质量档必须在
  5 张真实 NEF 上通过 `dng_stage3_ablation` 口径或给出 A/B MAE 上限，否则禁用。
- 若允许“相机内嵌观感”，D2 是唯一确定性 <0.2s 的方案。

---

## 3. stage 加速组合（C++ / LUT / SIMD+OpenMP / GPU）

### 3.1 各技术适用性

| 技术 | 适用 stage | 预计增益 | 风险 |
|---|---|---|---|
| C++ 单遍融合（t1 路线） | huesat/colorcal/refine | 3~5×（已由 8s→4s 路线验证预算） | 低（有 Python 回退） |
| 1D LUT（sRGB EOTF、HSV 权重） | huesat、refine warm_sat_gamma | 10~30% 单 stage | 低（≤1e-6） |
| 3D LUT（33³/65³） | **colorcal 最理想**（uint8 输入，skin_mask/中性曲线均为逐像素函数，可完整表化） | 0.8s→0.03~0.08s | 中（A/B 视觉门禁） |
| SIMD（AVX2，编译器自动向量化优先） | 全部逐像素内核 | 1.5~2.5× | 低~中（分支型 HSV 需改 branchless） |
| OpenMP（默认关，验收后开） | 像素无依赖循环、separable 滤波行间 | 2~4×（桌面 8 核，内存带宽受限） | 中（数值可复现性按测试计划管控） |
| 降采样执行 | clarity/skin/colorcal 测量等低频 stage | 2~4× 对应环节 | 中（细节/掩码上采样伪影） |
| GPU（OpenCL/cv2.UMat） | colorcal/refine 类滤波与 LUT | 可能 3~10× | 高（跨设备传输、驱动、回退一致性） |

### 3.2 各 stage 1s 模式预估（估算，需 bench 逐项验证）

| stage | 1s 模式手段 | 预算 |
|---|---|---:|
| exposure / whitebalance | C++ 单遍（当前 NumPy 已较轻） | 0.05s |
| huesat | C++ broad+spot + 1D LUT + OpenMP；固定参数 3D LUT | 0.10~0.15s |
| tone | 1D 影调表查表（已是查表型） | 0.03s |
| clarity | 1/2 分辨率 separable blur + native | 0.05s |
| colorcal | 3D LUT（主）+ 解析内核回退 | 0.05~0.10s |
| calibration / hsl / split_tone / stylize | 合并为单遍矩阵/LUT | 0.05~0.10s |
| skin | 1/2 分辨率 guided filter（现状已有 half_res） | 0.05s |
| refine | C++ 融合 + cv2/C++ blur + 1D LUT | 0.10~0.15s |
| **stage 合计** | | **0.40~0.60s** |

注意：上表是“1s 模式的极限预算”，任一 stage 按 t1 文档的正常容差实现
（尤其 colorcal 不 LUT、refine 不融合）都会翻倍；因此 1s 全质量路线不是
t1 的自然延续，而是**一条需要专项开发的快速档产品线**。

---

## 4. 预览快速路径（推荐优先落地的 1s 口径）

现状：`render/api.py::render_preview` 已用 `presets/preview_fast.json`
（[exposure, whitebalance, huesat(disabled), tone]），half_size 默认。
由于 decode 仍占 ~0.9s，当前预览总耗时估计 **1.2~1.5s**，已接近但未达 1s。

### 4.1 预览分档设计

| 档位 | 分辨率 | decode | 链 | 目标 |
|---|---|---|---|---:|
| P0 | 内嵌缩略图（约 1~2MP） | D2 extract_thumb | 无 | 0.1~0.3s |
| P1 | quarter（约 760×1010） | D4 CFA 2×2 分箱或 D3 half+resize | preview_fast | 0.4~0.8s |
| P2 | half（2020×3032） | D1（LINEAR/8bit，预览档）或 D4 | preview_fast | 0.6~1.0s |
| P3 | half（2020×3032） | D0 AHD 16bit | preview_fast | 1.2~1.5s（基线） |

### 4.2 推荐路线

1. **先固化 P3 实测**（T5 的 `bench_pipeline.py` 增加 `--preview` 模式），
   确认 preview_fast 当前真实中位数；没有实测数字前不批准任何 decode 方案。
2. **P0 只做 UI 层**（返回缩略图 + 元数据），零算法风险，当天可用。
3. **P1 依赖 D4**：新 C++ `PixoRenderDecodeHalf/Quarter`（或独立 `render/native/decode`），
   先走预览档（允许 P1 与 P3 视觉差异说明），命中 ≤0.8s 后再评估升级高质量档。
4. 高质量快档（口径 B）在 t1~t5 的 4s 路线验收后，按 §5 逐项降档。

---

## 5. “最接近 1s 的可达方案”建议路线

### 路线 R1：确定性交付（预览 1s，全质量 4s）——推荐

- 交付物：P0 + P1 + 现有 4s 主线。
- 时间/风险：低~中；P0 即时预览几乎无风险；P1 需要 decode C++ 与 preview_fast
  集成，算法风险由“预览档允许视觉差异说明”消化。
- 预期：**预览档 ≤1s（目标 0.4~0.8s），全质量 ≤4s**。

### 路线 R2：高质量快档 1.5~2.5s（在 4s 验收后启动）

- 条件：t1~t5 全绿；`bench_pipeline.py` 基线存在。
- 动作：
  1. OpenMP/SIMD 开启并重跑等价测试（t1 文档 §10 已规定门禁）；
  2. colorcal 33³/65³ 3D LUT 上线，过测试计划 §6.4 A/B 门禁；
  3. refine/huesat 融合内核微调；
  4. 低频 stage（clarity/skin）降采样执行；
  5. decode 保持 D0，若仍 >2.5s 再评估 D4。
- 预期：总耗时 **1.5~2.5s**，视觉与全质量档 A/B 差异受控。

### 路线 R3：全质量 half_size 真 1s（实验分支，不承诺）

- 条件：§7 六个硬条件全部满足。
- 动作：D4/D5 快速解码 + 全部 stage render/native/LUT/GPU + 端到端等价体系重建。
- 预期：可能达到 1.0~1.5s，但开发与验收成本高，**若失败回退 R2**。

---

## 6. GPU 评估

- **适合**：demosaic（D5）、3D LUT 应用、GaussianBlur/resize 类滤波；
  像素间无依赖，天然并行。
- **不适合/收益存疑**：当前链有大量逐 stage 中间数组；每次 GPU 往返
  （6.1MP×3×4B≈73MB）若 stage 间来回拷贝，传输会吃掉收益。必须整链
  “一次上卡、卡内多 stage、一次下卡”才有意义，等于重写 pipeline 执行器。
- **平台事实**：本机 GPU 能力、OpenCL 驱动、双显卡切换均未验证；
  cv2.UMat 可做最小实验，但不得进入默认路径。
- **结论**：GPU 列为 R3 选项；R1/R2 不做 GPU 依赖。若用户允许“GPU 可选”，
  在 R2 验收后立项一次 UMat 试点（只试点 colorcal+refine），按 A/B 数据决策。

---

## 7. “全质量 half_size 1s”的达成条件（硬条件清单）

只有以下全部成立才允许把口径 A 的目标设为 1s：

1. **decode ≤0.25s**：D4 自研 CFA 解码通过 5 张 NEF A/B 验收，或 D5 GPU 解码可用；
2. **colorcal ≤0.10s**：3D LUT 路径通过测试计划 §6.4 视觉门禁；
3. **huesat ≤0.15s、refine ≤0.15s**：C++ 融合 + OpenMP/SIMD 全量合入；
4. **其余 8 个 stage 合计 ≤0.25s**：默认链实现 stage 精简/LUT 合并，
   或产品同意“1s 快档”自动跳过 clarity/skin/split_tone/stylize；
5. **端到端 overhead ≤0.10s**：DCP 预热、Python 编排、终端 8bit 转换全部计入；
6. **视觉验收**：与 4s 全质量输出做 A/B + 5 张 ablation（engine_mae ≤5e-5）
   或产品书面接受量化差异。

任一条件不满足 → 目标自动降级为 R2（1.5~2.5s）或 R1（预览 ≤1s）。

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 低估内存带宽墙 | OpenMP 增益远低于预期 | bench 先测单 stage 扩展性，再决定并行投入 |
| D4 解码质量回退 | 用户不接受 | 预览档先上；高质量档设 MAE 门禁，不达标禁用 |
| 3D LUT 插值伪影 | 色带/边缘误差 | 33³ 与 65³ 双测；视觉门禁不过则回退解析内核 |
| GPU 驱动/传输不可控 | 投入打水漂 | 只做 R3 实验分支；默认 CPU 路径必须可用 |
| 1s 路线挤占 4s 主线 | 两线延期 | 严格执行顺序：4s 主线验收 → 预览 1s → 高质量快档 |
| 预览档与全质量观感差异投诉 | 产品预期错位 | UI 明确标注“预览”与“完整渲染”；提供档位切换 |

---

## 9. 建议任务顺序（供队长拆解）

| 序号 | 任务 | 依赖 | 目标 |
|---|---|---|---|
| P-1 | bench 固化 + preview_fast 实测 | t5 | 拿到 P3 中位数，任何 1s 决策的唯一数据源 |
| P-2 | P0 extract_thumb 预览接口 | P-1 | 0.1~0.3s 即时预览 |
| P-3 | D4 C++ CFA 快速解码（预览档） | t1/P-1 | P1 quarter ≤0.8s |
| P-4 | OpenMP/SIMD 开启 + 重验 | t2~t4 | 4s 主线不退化，R2 起步 |
| P-5 | colorcal 3D LUT 上线 | t3 | colorcal ≤0.1s，A/B 归档 |
| P-6 | 高质量快档集成 + 验收 | P-4/P-5 | 口径 B ≤2.5s |
| P-7 | GPU 试点（可选实验） | P-6 | 决策是否立项 R3 |

---

## 10. 给队长的决策建议

- **默认采纳 R1**：把“1s”定义为“预览 ≤1s + 全质量 ≤4s”，确定性最高，
  与用户 §6.1 中“或将 1s 限定为预览档”的开放口径一致。
- **可选追加 R2 目标**：全质量 4s 验收后再报“1.5~2.5s 快档”作为下一里程碑。
- **不默认采纳 R3**：除非用户明确要求“half_size 全质量必须 1s”并接受
  GPU/自研解码的开发成本与质量门禁；此时按 §7 立项并给独立排期。

---
