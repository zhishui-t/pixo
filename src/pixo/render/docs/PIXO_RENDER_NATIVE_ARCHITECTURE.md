# pixo.render Native 模块架构与软件设计文档

> 版本：v1.0  
> 状态：待审核  
> 作者：架构师（长安小队）  
> 需求来源：`render/docs/PIXO_RENDER_PERFORMANCE_REQUIREMENTS.md` v0.1  
> 配套文档：`PIXO_RENDER_NATIVE_SPECIFICATION.md`（规格）、`PIXO_RENDER_NATIVE_TEST_PLAN.md`（测试）  
> 历史文档：`PIXO_RENDER_NATIVE_DESIGN.md` v0.1（已被本文档替代）

---

## 1. 目标与范围

把 pixo.render 三个热点模块（huesat / colorcal / refine）的核心计算下沉到 C++20，
通过 CMake + MinGW-w64 构建单一共享库 `pixo_render_native.dll`，Python 侧用 `ctypes`
加载；half_size 真实 NEF 总耗时从约 8s 降至 **≤ 4s**（探索目标 1s 由任务 t8 单独论证）。

| 模块 | 当前耗时（half_size 真实 NEF） | 目标 |
|---|---:|---:|
| huesat（`apply_local_warm_sat`） | 1.7~3.0s | ≤ 0.6s |
| colorcal（`scene_hue`/`skin_mask`/Lab 路径） | 2.5~2.7s | ≤ 0.8s |
| refine（sharpen/chroma_denoise/highlight_desat/warm_sat_gamma） | 1.7s | ≤ 0.7s |
| 总耗时 | ~8s | ≤ 4s |

不纳入：decode/rawpy、DCP 解析、GPU 加速、算法语义变更。

---

## 2. 现状基线与性能瓶颈定性

对 `render/core/huesat.py`、`render/modules/color_cal.py`、`render/modules/refine.py`
的逐行审阅结论：

- 热点不是单一的数学库调用，而是 **6MP float32 全图上的多遍 NumPy 广播**：
  多次 `a = 128 + (a-128)*gain`、`np.exp`、`np.stack`、`np.take` 等，每遍都产生
  中间数组，受内存带宽限制。
- `cv2.cvtColor` / `cv2.GaussianBlur` / `cv2.resize` 本身已是 C 实现，不是主要热点；
  主要热点是包围这些调用的 **NumPy 逐元素运算和中间数组分配**。
- colorcal 当前在 `saturation` 与 `skin_trim` 两条路径中重复计算 `skin_mask`
  （两次 `cv2.cvtColor(RGB2LAB)` + 椭圆距离），M2 要求至少合并为一次。
- refine 已做过一次“共享 gray/sat_protect”优化，但 sharpen/chroma/highlight 仍是
  三组独立全图广播，可再融合。

---

## 3. 架构总览

```
Python 层
  render/modules/*.py          # 管线 stage：参数解析、WB 窗口查表、分支决策
        │
        │  （try/except + available() 自动回退）
        ▼
  render/_native/__init__.py   # ctypes 包装：结构体、argtypes、shape/dtype 检查、LUT 缓存
        │
        │  C ABI（extern "C" __declspec(dllexport)，只传裸指针 + 尺寸/参数结构体）
        ▼
  pixo_render_native.dll (C++20)
    common   # 标量数学、状态码、1D LUT、separable 滤波（备选）
    hsv      # RGB<->HSV（已实现）
    warm_sat # M1 整段内核（broad 已实现，spot 待补齐）
    colorcal # M2 Lab 域内核
    refine   # M3 灰空间/色度内核
    lut3d    # 通用三线性 3D LUT 应用
```

### 3.1 关键架构决策（AD）

| 编号 | 决策 | 理由 |
|---|---|---|
| AD-1 | 单 DLL、单 ABI 版本号，C++20 | 少一次加载；`ctypes` 一次装载全部内核 |
| AD-2 | 跨边界只用 C ABI，异常不逃逸 | 与 MinGW/CPython 版本解耦，不依赖 Python.h |
| AD-3 | 内存全部由 Python 分配，C++ 只读/写调用方缓冲 | 无跨堆释放问题；`out` 可与 `in` 不同缓冲（别名仅在明确标注的 in-place API 中允许） |
| AD-4 | 按“整段 stage 内核”划分 C ABI，不做几百个小函数 | 减少跨边界次数与中间数组；单函数融合多遍广播直接省内存带宽 |
| AD-5 | cv2 原语（RGB↔Lab/HSV、GaussianBlur、resize）留在 Python；C++ 接管 NumPy 广播；等价/性能不达标时再迁入 | cv2 迁移以穷举/海量随机对拍为门禁 |
| AD-6 | 每个内核提供 float32 路径；float64 仅保留在纯数学内核（HSV 转换等） | 现有渲染主链是 float32，float64 用于验收“逐位一致”基准 |
| AD-7 | C ABI 函数参数 ≤ 5；多参数用 `struct` 传指针；指针字段在 spec 中明确可空语义 | 遵守用户补充规范 |
| AD-8 | 无全局可变状态；固定 LUT 用函数局部 `static const std::array` 惰性构造；OpenMP 只并行像素间无依赖循环 | 线程安全 + 可复现 |
| AD-9 | 原生失败不改变管线语义：每个调用点 `available()` 检测或 `try/except` 回退纯 Python | 满足 FR6 |
| AD-10 | LUT 由 **Python 用现有 NumPy 参考实现构建**，C++ 只负责三线性应用 | 格点值与参考实现天然一致，避免在 C++ 里重复实现算法 |

---

## 4. 目录结构与文件职责

```
render/native/
  CMakeLists.txt              # 共享库 + 可选测试目标；POST_BUILD 拷贝 DLL
  build.bat                   # 一键构建（MinGW Release），失败即退
  run_tests.bat               # 构建 + 运行 render/native/tests（建议）
  README.md                   # 快速上手
  src/
    abi.h                     # 导出宏、版本号、状态码、公共 C 结构声明（C ABI 唯一真源）
    common.h / common.cpp     # clamp/smoothstep/srgb LUT/矩阵乘/边界检查
    hsv.h / hsv.cpp           # RGB<->HSV f32/f64（已实现，保持导出）
    warm_sat.h / warm_sat.cpp # M1 apply_local_warm_sat 整段（broad 已实现）
    colorcal.h / colorcal.cpp # M2 Lab 域内核 + 中性快速路径辅助内核
    refine.h / refine.cpp     # M3 灰空间融合内核 + warm_sat_gamma 内核
    lut3d.h / lut3d.cpp       # 通用 3D LUT 三线性应用
  tests/
    test_main.cpp             # 零依赖测试入口（宏断言，不引入 gtest，保证离线可建）
    test_hsv.cpp
    test_warm_sat.cpp
    test_colorcal.cpp
    test_refine.cpp
    test_lut3d.cpp
  build/                      # CMake 产物（不入库）
render/_native/
  __init__.py                 # ctypes 包装：加载、版本检查、shape/dtype 检查、LUT 缓存
  pixo_render_native.dll           # 构建生成（不入库）
render/tools/
  bench_pipeline.py           # M4：stage 级中位耗时 + 基线 JSON（任务 T5 实现）
src/render/tests/
  test_native_*.py            # Python 侧内核/回退/数值等价测试（任务 T5 实现）
```

`render/docs/PIXO_RENDER_NATIVE_SPECIFICATION.md` 是接口的唯一规范来源；`render/native/README.md`
只保留构建说明并链接回本文档，不重复定义 ABI。

---

## 5. C++ 模块设计

### 5.1 common：标量数学与 ABI 支撑

- `Clamp` / `SmoothStep` / `SmoothStepPow6`：与 `huesat.py` 语义逐位对齐。
- `SrgbEncodeLut` / `SrgbDecodeLut`：函数局部 `static const std::array<float, 4096>`
  惰性构建，线性插值查表；替代逐像素 `std::pow`（warm_sat 热点之一）。
- `Multiply3`：3×3 行主序矩阵乘（sRGB↔ProPhoto）。
- `CheckDims`：width/height 正整数、乘积不溢出 int32。
- 3×3 常量以 `constexpr float` 数组定义（**不加 k 前缀**，见 §12）。

### 5.2 hsv（已实现）

`RgbToHsv` / `HsvToRgb` 及 f32 版本保持现状；后续只做 ABI 统一（版本函数）与性能微调。
已通过随机等价测试（见测试计划 §6.2）。

### 5.3 warm_sat（M1）

现状：broad 分支已在 C++ 内完成 sRGB→ProPhoto→HSV→权重→HSV→ProPhoto→sRGB 单遍融合；
coverage 超阈值时返回 1 由 Python 走 spot/Gaussian 分支。

M1 完成态：
1. 在 C++ 内实现 spot 分支所需的 separable GaussianBlur（sigma 与 cv2 一致，
   border=reflect101/默认）。先在 C++ 单测中与 `cv2.GaussianBlur` 对拍；
   对拍不通过就保留 Python 的 `cv2.GaussianBlur` 供 C++ 使用（AD-5 的降级路径），
   其余权重计算仍在 C++。
2. 用 `SrgbEncodeLut` 替换逐像素 `std::pow`。
3. 固定参数时可走通用 3D LUT（§7），命中 ≤ 0.6s 后不再优化。

### 5.4 colorcal（M2）

按 AD-5 拆分：Python 继续用 `cv2.cvtColor(RGB2LAB/LAB2RGB)`，C++ 接管 Lab 平面上的
全部 NumPy 广播。拆分后的调用序（`ColorCalStage.process` 改造后）：

```
u8 = quantize(img)                       # NumPy
lab = cv2.cvtColor(u8, RGB2LAB)          # 保留 cv2（已 C）
PixoRenderColorCalApplyLab(lab, labOut, params)   # 一次 C++：中性校正+skin 偏移+hue+sat/vib+skin 保护
lab8 = np.clip(labOut,0,255).astype(u8)  # 或由 C++ 直接输出 uint8
out = cv2.cvtColor(lab8, LAB2RGB)        # 保留 cv2
PixoRenderGamutSoft(out, ...)                # C++ 色域软压缩
```

关键点：
- C++ 内核一次算出 `skinMask`（Lab 椭圆，常量与 `core/skin.py` 完全一致），
  同时供 `skin_trim` 与 `saturation` 保护使用，**消除当前 Python 的双重计算**。
- `scene_hue` / `scene_trim` / `scene_skin_trim` 的 WB 窗口查表仍留在 Python
  （参数解析逻辑，不是热点）；最终换算成标量 `hueDeg / skinTrimA / skinTrimB` 传入。
- 中性快速路径同样拆分：`cv2.resize` + `cv2.cvtColor` 保留在 Python；
  `PixoRenderAdaptiveNeutralCurves`（小图统计）与 `PixoRenderColorCalNeutralApply`
  （全图加权叠加）为 C++ 内核。

### 5.5 refine（M3）

Python 保留 `cv2.GaussianBlur` / `cv2.resize`，C++ 提供一次融合内核：

```
PixoRenderRefineApply(rgb, out, w, h, params)
  params: sharpen / chromaDenoise / highlightDesat
          gray, satProtect          # Python 已算（共享一次）
          grayBlur                  # sharpen 输入
          blurUp, grayBlurUp        # chroma 输入（在 sharpen 之后的图上由 Python cv2 计算）
```

C++ 按 Python 现有顺序完成 sharpen → chroma_denoise → highlight_desat 的算术部分，
只写一次 `out`。`warm_sat_gamma` 用独立 in-place 内核 `PixoRenderWarmSatGammaU8`：
Python 做 `cv2.cvtColor(RGB2HSV/HSV2RGB)`，C++ 按与 `refine.py` 相同的 256 级权重
LUT 修改 H/S 平面；coverage 统计留在 Python（一次向量化 `mean()`，廉价）。

### 5.6 lut3d（LUT 方案）

通用三线性 3D LUT 应用器，输入任意 float32 RGB `(H,W,3)`，表由 Python 构建并缓存。
细节见 §7 与规格文档。

---

## 6. C ABI / ctypes 接口设计原则

1. 导出宏统一放 `abi.h`：
   ```cpp
   #ifdef _WIN32
   #define PIXO_RENDER_NATIVE_API extern "C" __declspec(dllexport)
   #else
   #define PIXO_RENDER_NATIVE_API extern "C" __attribute__((visibility("default")))
   #endif
   ```
2. 所有导出函数名以 `pixo.render` 开头，返回 `int` 状态码：
   `0` 成功、`1` 请求 Python 回退、负数错误（-1 非法参数、-2 不支持、-3 内部异常）。
3. 全部指针语义为“调用方持有”；C++ 不 `new/delete` 跨边界内存、不保存传入指针。
4. 每个 ABI 包装函数必须 `try/catch(...)`，异常转为 `PixoRenderInternalError`，
   不允许 C++ 异常穿过 DLL 边界。
5. 参数超过 5 个一律打包进 `pixo.render*Params` 结构体指针。结构体只含
   `float/int32/const float*` 字段，ctypes `Structure._fields_` 与 C 定义逐字段同名。
6. 数组布局统一为 **C 连续、行主序、通道最末**：`HxW` 或 `HxWx3`。
   Python 包装器负责 `np.ascontiguousarray` 与 dtype/shape 校验。
7. ABI 版本检查：`PixoRenderVersion(PixoRenderVersion*)` 返回 `major/minor/patch`；
   Python 加载后校验 `major == 1`，不匹配按不可用处理并回退 Python。

M1 现有导出（`PixoRenderRgbToHsv` 等 5 个函数）保持不变，避免破坏已联调代码；
新内核全部遵循上述约定。完整的结构体与签名以规格文档 §4 为准。

---

## 7. LUT 方案

### 7.1 1D LUT（数值无近似要求，默认启用）

| LUT | 域 | 表长 | 用途 |
|---|---|---|---|
| sRGB encode | [0, 2] | 4096，线性插值 | warm_sat 的 `_srgb_encode_v` |
| sRGB decode | [0, 1] | 4096，线性插值 | 备用（encoding=1 路径） |
| warm_sat H 权重 | 0..255 | 256，直接索引 | refine `warm_sat_gamma`（与 Python `_WARM_H_LUT` 逐位一致） |
| warm_sat S/V 权重 | 0..255 | 256，直接索引 | 同上 |

1D LUT 是“查表”而非“近似”：表值用 float64 构造，插值误差计入 float32 容差
（≤ 1e-6）；H/S/V 权重表要求与 Python 逐位一致（两者都是 float32 表）。

### 7.2 3D LUT（近似路径，默认关闭，按参数缓存）

- 场景：colorcal 固定参数的全链颜色变换、M1 broad 分支固定参数（可选）。
- 格点：默认 33³；高质量档 65³；每个格点 3 通道 float32，通道最末排列
  `table[(b*grid + g)*grid + r][ch]`。
- 构建：**Python 用现有 NumPy 参考函数在格点上求值**，再把表传入 C++；
  C++ 只做三线性插值。格点值与参考实现严格一致，误差只来自格间插值。
- 缓存键：`sha256(grid + domain + 参数规范序列化 + 参考实现版本)`；
  `render/_native` 提供 `LutCache`（字典，进程级）。参数变化自动重建，无手动失效。
- 应用：`PixoRenderApplyLut3D`；域外值钳到 `[domainMin, domainMax]`。
- 门禁：LUT 路径必须通过 §测试计划 6.4 的 A/B 验收（图像 max|Δ| ≤ 2/255、
  提供视觉差异说明），未通过不得成为默认路径。默认仍走解析内核。

---

## 8. 构建流程

### 8.1 工具链与产物

- 编译器：MinGW-w64 g++（`D:\code\mingw64\bin\g++.exe`）
- CMake：`D:\code\cmake-3.31.6-windows-x86_64\bin\cmake.exe`，Generator `MinGW Makefiles`
- 标准：C++20，Release
- 产物：`pixo_render_native.dll`，POST_BUILD 自动复制到 `render/_native/`
- 依赖运行时：`-static-libgcc -static-libstdc++` 静态链接，DLL 不依赖
  libgcc/libstdc++ 动态库；OpenMP 若启用，`libgomp` 静态链接或由
  `build.bat` 校验拷贝，最终以 `available() == True` 验收。

### 8.2 命令

```bat
cd native
build.bat
```

```bat
cd native
run_tests.bat     REM 构建 pixo_render_native_tests 并运行
```

```powershell
python -c "from render import _native; print(_native.available(), _native.version())"
```

### 8.3 CMake 约定

- `PIXO_RENDER_NATIVE_BUILD_TESTS`：OFF 默认；run_tests 置 ON。
- `PIXO_RENDER_NATIVE_OPENMP`：OFF 默认（先保证数值等价与可复现）；M1/M3 若未达
  FR2 目标再由 T2/T4 开启，开启后重跑全部数值等价测试。
- 编译告警：`-Wall -Wextra`；MSVC 分支保留现有 `/utf-8 /W4`（本机用 MinGW，不展开）。
- `.gitignore` 必须覆盖：`render/native/build/`、`render/_native/*.dll`、`*.pyd`、`*.so`。

---

## 9. Python 包装器设计（`render/_native/__init__.py`）

- 启动逻辑保持“DLL 缺失/加载失败模块仍可导入”：`_lib=None` + `_load_error`。
- 加载成功后调用 `PixoRenderVersion`，major 不匹配则置 `_lib=None` 并记录原因。
- 每个内核包装函数：
  1. `available()` 为 False → 抛 `RuntimeError(load_error)`；
  2. `np.ascontiguousarray` 强制 C 连续；
  3. 校验 ndim/shape/dtype，错误信息含实际 shape；
  4. `ctypes.data_as` 传指针，返回 ndarray 或 `(out, handled)`。
- 调用点纪律：`try/except Exception` 或先查 `available()`；任何原生异常都回退
  现有纯 Python 代码，不向上抛。
- LUT 缓存类 `LutCache` 暴露 `get(key, builder)`；builder 只在 miss 时执行。

---

## 10. 性能设计要点

1. **融合多遍为一遍**：M1 已实现（1.8s 基线）；M2/M3 各一个融合内核。
2. **少分配**：C++ 内核只在内部复用调用方输出缓冲；Python 侧预分配中间平面
   （gray/satProtect/blurUp）一次。
3. **查表替代超越函数**：`std::pow` → 1D LUT；smoothstep 幂用连乘。
4. **可选 OpenMP**：仅用于像素间无依赖循环；开启必须重跑等价测试并记录
   前后图像 diff（应为 0，因为只改变调度顺序）。
5. **预算表**（验收红线，任一 stage 超预算需在对应任务内优化）：

   | stage | 预算 | 备注 |
   |---|---:|---|
   | decode | ≤ 0.9s | 不纳入优化，但计入总量 |
   | huesat | ≤ 0.6s | |
   | colorcal | ≤ 0.8s | |
   | refine | ≤ 0.7s | |
   | 其余 stage + 开销 | ≤ 1.0s | |
   | 合计 | ≤ 4.0s | |

6. **1s 探索**：本文档预留 LUT 化 + OpenMP 的演进位；但要达到 half_size 1s，
   必须动 decode 或改预览档，属任务 t8 范围，不做承诺。

---

## 11. 数值等价策略（架构级）

三层防线：

1. **构造级**：C++ 与 Python 共享同一组常量（矩阵、椭圆参数、权重表），
   常量由 Python 生成、固化进 C++ 头文件并在测试中做常数对拍。
2. **内核级**：随机/边界输入，native vs 强制 Python 回退，按规格容差验收
   （float64 max|Δ|=0，float32 ≤ 1e-6，LUT ≤ 2/255 并附视觉说明）。
3. **管线级**：全量 pytest、`dng_stage3_ablation.py`（5 张 full engine_mae ≤ 5e-5）、
   `render_dcp.py` A/B、`bench_pipeline.py` 基线对比。

具体测试用例、数据生成与判定脚本见 `PIXO_RENDER_NATIVE_TEST_PLAN.md`。

---

## 12. 编码规范（guanlan + 用户补充）

C++ 侧强制：

- C++20；行宽 ≤ 120；K&R 括号（函数体左括号换行，控制语句左括号同行）；
  中文注释；namespace 全小写（`pixo_render_native`）。
- 常量用 `constexpr`，**不加 k 前缀**。
- 全局变量 `g_` 前缀且**慎用**；本模块禁止新增可变全局，固定 LUT 用函数局部
  `static const`。
- 成员变量 `m_` 前缀，且必须经构造初始化列表初始化。
- 函数参数 ≤ 5 个；超限用 `Params` 结构体。
- 头文件 `#pragma once`；导出宏只在 `abi.h` 定义。
- 循环索引 `std::int64_t` 或 `int`（与 ABI 尺寸一致），禁止裸 `new/delete`
  （用 `std::vector`/`std::array`）。

规范示例（新增代码按此风格）：

```cpp
// 示例：成员变量 m_ 前缀 + 初始化列表；常量不加 k 前缀。
class SeparableBlur {
public:
    explicit SeparableBlur(float sigma, int radius = 0)
        : m_sigma(sigma), m_radius(radius)
    {
    }

private:
    float m_sigma;
    int m_radius;
};
```

Python 侧遵循仓库既有风格：中文 docstring、类型标注、私有名 `_` 前缀、
每阶段小步验证（先等价测试后性能调优）。

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| cv2 原语与 C++ 重实现不一致 | 数值回退/视觉差异 | AD-5：cv2 先留 Python；迁入前必须穷举/海量随机对拍 |
| MinGW ABI / 运行时依赖 | DLL 加载失败 | 静态链接 libgcc/libstdc++；ABI 版本校验；加载失败自动回退 |
| OpenMP 改变浮点结果 | 回归难定位 | 默认关闭；开启重跑等价测试并比对 diff=0 |
| 3D LUT 插值误差 | 用户可见色差 | 默认关闭；33³/65³ 双档；A/B 数据 + 视觉说明门禁 |
| 融合内核语义漂移 | 与原 Python 分支不一致 | 每个内核先写“伪代码→Python 参考”对拍表，再写 C++ |
| 性能不达预算 | FR2 验收失败 | 预留 OpenMP、1D/3D LUT、cv2 迁入三级升级路径 |

---

## 14. 任务拆分与依赖（T2~T6）

| 任务 | 交付物 | 依赖本文档章节 |
|---|---|---|
| T2 M1 | warm_sat spot 分支 + sRGB LUT + OpenMP 评估 | §5.3、§7.1、规格 §4.3 |
| T3 M2 | colorcal Lab 内核 + 中性快速内核 + LUT 门禁 | §5.4、§7.2、规格 §4.4~4.6 |
| T4 M3 | refine 融合内核 + warm_sat_gamma 内核 | §5.5、规格 §4.7~4.9 |
| T5 M4 | `bench_pipeline.py`、基线 JSON、native pytest、C++ 测试补全 | 测试计划全文 |
| T6 审核 | 代码/文档/性能审核，最多 2 轮 | 本文档 + 规格 + 测试计划 |

---

## 15. 验收速查

1. `render/native/build.bat` 成功，`render/_native/pixo_render_native.dll` 存在。
2. `render._native.available() == True`，`version().major == 1`。
3. 内核等价测试全绿（规格容差）。
4. half_size 真实 NEF 总耗时 ≤ 4s（bench 中位数）。
5. `pytest src/render/tests -q -m 'not e2e'` 全绿；ablation 5 张 full engine_mae ≤ 5e-5。
6. 删除/改名 DLL 后全量 pytest 仍通过（纯 Python 回退路径）。

---
