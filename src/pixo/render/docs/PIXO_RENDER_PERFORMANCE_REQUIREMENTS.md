# pixo.render 性能优化功能需求文档

> 版本：v0.1  
> 状态：待架构师设计  
> 编写：队长（用户意图整理）  
> 关联：`render/docs/PIXO_RENDER_PERFORMANCE_REVIEW.md`、`render/native/`

---

## 1. 背景

pixo.render 当前真实 NEF 渲染（half_size 2020×3032）总耗时约 7.7~8.9s，主要热点：

| 模块 | 耗时 | 说明 |
|---|---:|---|
| huesat | 1.7~3.0s | `apply_local_warm_sat` 全图 HSV/ProPhoto 运算 |
| colorcal | 2.5~2.7s | Lab 全图 + scene_hue + 两次 skin_mask |
| refine | 1.7s | sharpen / chroma_denoise / highlight_desat |
| decode | ~0.9s | rawpy 解码（已 C++，暂不纳入） |

用户已确认使用 **C/C++ 实现热点内核**，工具链为 **MinGW-w64 + CMake**，并通过 **ctypes** 接入 Python。

## 2. 目标

1. 将 huesat / colorcal / refine 三个热点模块的核心算法下沉到 C++（`render/native/`）。
2. 在保持现有视觉结果基本一致的前提下，将 half_size 真实 NEF 总耗时从约 8s 降至 **4s 以内**（目标 3~4s）。
3. 建立可复现的基准与回归体系，保证后续优化可量化、可验证。

## 3. 范围

### 3.1 纳入范围

- `render/core/huesat.py` 的 `apply_local_warm_sat`
- `render/modules/color_cal.py` 的 `scene_hue`、`skin_mask`、Lab 全量路径
- `render/modules/refine.py` 的 sharpen / chroma_denoise / highlight_desat / warm_sat_gamma
- C++ 原生模块构建体系：`render/native/CMakeLists.txt`、`render/native/build.bat`
- Python ctypes 包装器：`render/_native/__init__.py`
- 性能基准脚本：`render/tools/bench_pipeline.py`

### 3.2 不纳入范围

- decode / rawpy 解码
- DCP 解析
- GPU 加速（留作后续）
- 改变现有算法语义 / 用户可感知的渲染结果

## 4. 功能需求

### FR1 原生加速模块

- 使用 C++20，位于 `render/native/` 目录，通过 CMake 构建共享库。
- 提供 C ABI 导出，供 Python `ctypes` 加载。
- 每个热点提供 float32 / float64 两套入口（如适用）。
- Python 侧保留纯 NumPy 实现作为 fallback，原生库不可用时自动回退。

### FR2 性能指标

| 场景 | 当前 | 目标 |
|---|---:|---:|
| huesat（真实 NEF half_size） | 1.7~3.0s | ≤ 0.6s |
| colorcal（真实 NEF half_size） | 2.5~2.7s | ≤ 0.8s |
| refine（真实 NEF half_size） | 1.7s | ≤ 0.7s |
| 总耗时（half_size 真实 NEF） | ~8s | ≤ 4s |

### FR3 数值等价

- float64 路径：与当前 NumPy 实现 **逐位一致或 max|Δ| = 0**。
- float32 路径：与当前 NumPy 实现 **max|Δ| ≤ 1e-6**。
- 若采用 LUT/近似算法，必须提供 A/B 对比数据，并给出视觉差异说明。

### FR4 构建与集成

- 使用 CMake + MinGW-w64。
- `render/native/build.bat` 一键构建，产物输出到 `render/_native/`。
- `render/native/build/`、`render/_native/*.dll` 不入库。
- 构建不破坏现有 Python 包导入。

### FR5 编码规范

遵循 guanlan 编码规范及用户补充约定：

- C++20，行宽 ≤ 120，K&R 括号，中文注释。
- 常量 `constexpr`，**不加 k 前缀**。
- 全局变量 `g_` 前缀，慎用。
- 成员变量 `m_` 前缀，构造初始化列表。
- 函数参数 ≤ 5 个。
- 目录结构清晰：`render/native/src/`、`render/native/tests/`、`render/native/build/`。

### FR6 兼容与回退

- 原生库加载失败时，`render/_native` 保持可导入。
- 所有调用点必须 `try/except` 或检测 `available()` 后回退纯 Python。
- 现有 pytest 全量回归不能因原生模块缺失而失败。

## 5. 模块拆分

### M1 huesat 原生化

- 将 `apply_local_warm_sat` 整段移植到 C++。
- 可选优化：HSV 转换 + ProPhoto 往返合并为单遍循环，减少中间数组。
- 可选进阶：固定参数时用 3D LUT 加速。

### M2 colorcal 原生化

- 将 `scene_hue`、`skin_mask`、Lab 全量路径移植到 C++。
- 至少修复当前 Python 侧 `skin_mask` 重复计算问题。
- 可选进阶：整条 colorcal 用 3D LUT 替代。

### M3 refine 原生化

- 将 sharpen / chroma_denoise / highlight_desat / warm_sat_gamma 移植到 C++。
- 保持现有降采样策略，可进一步用 OpenMP 并行。

### M4 基准与回归

- 新增 `render/tools/bench_pipeline.py`，输出每 stage 中位耗时与总耗时。
- 保存基线 JSON，供后续对比。
- 回归命令：
  - `pytest src/render/tests -q -m 'not e2e'`
  - `python render/tools/dng_stage3_ablation.py`
  - `python render/tools/render_dcp.py ...`

## 6. 验收标准

1. `render/native/build.bat` 构建成功，生成 `pixo_render_native.dll`。
2. `render/_native` 可加载，`available() == True`。
3. 单内核数值等价测试通过（float64 diff=0，float32 diff≤1e-6）。
4. 真实 NEF half_size 总耗时 ≤ 4s。
5. 全量 pytest 通过，ablation 5 张 full engine_mae ≤ 5e-5。
6. 原生库缺失时纯 Python 回退正常，测试仍通过。

## 6.1 探索性目标：总耗时压缩到 1s 左右

用户提出“看看能不能压缩到 1s 左右”。当前 half_size 真实 NEF 总耗时约 8s，其中 decode 约 0.9s、huesat 约 1.8s、colorcal 约 2.5s、refine 约 1.7s。

**1s 目标可行性初步判断：**
- 仅靠当前 CPU + C++ 整段移植很难达到 1s：decode 已占 ~0.9s，剩余全部 stage 只有 ~0.1s 预算。
- 要接近 1s，必须组合以下手段：
  1. decode 加速：rawpy 参数优化、更低预览分辨率、或自研 C++ 解码/重采样；
  2. 全部 stage 3D LUT 化 + SIMD/OpenMP，单 stage 压到 0.05~0.15s；
  3. 或引入 GPU（OpenCL/CUDA）做逐像素运算；
  4. 或将“1s”限定为预览档（如 1/4 或 1/8 分辨率）而不是 half_size 全质量。

**结论：** 1s 作为探索性目标成立，但需要架构师单独出可行性方案（见任务 t8），并明确是“全质量 half_size 1s”还是“预览档 1s”。t8 结论见 `PIXO_RENDER_1S_FEASIBILITY.md`。

## 7. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 数值不完全等价 | 视觉差异 | 先 float64 逐位；float32/LUT 做 A/B |
| MinGW ABI 问题 | 加载失败 | 使用 ctypes + C ABI，避免 Python.h |
| 构建环境差异 | 无法编译 | 提供 build.bat + README，依赖固定路径 |
| 优化后质量回退 | 用户不认可 | 保留 fallback，按模块开关 |

## 8. 任务拆分建议（供架构师细化）

| 任务 | 内容 | 负责角色 |
|---|---|---|
| T1 | 架构设计：native 模块接口、数据结构、LUT 方案、构建流程 | 架构师 |
| T2 | M1 huesat C++ 整段移植 | 开发 |
| T3 | M2 colorcal C++/LUT 移植 | 开发 |
| T4 | M3 refine C++ 移植 | 开发 |
| T5 | M4 基准脚本 + 回归 | 测试 |
| T6 | 代码/文档/性能审核，最多 2 轮，改不好亲自改 | 审核者 |

---
