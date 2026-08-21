# pixo.render Native 模块设计文档

> **历史迁移说明**：`rawlab` 已删除。本文档中的 `rawlab/*` 路径仅作历史迁移记录，当前实现/测试/工具均在 `render/` 下。

> **⚠ 历史文档（v0.1，队长代写）**：本文档已被以下三份架构师文档取代，内容仅作历史留档：
> - `PIXO_RENDER_NATIVE_ARCHITECTURE.md`（架构与软件设计）
> - `PIXO_RENDER_NATIVE_SPECIFICATION.md`（接口/ABI/LUT/构建规格）
> - `PIXO_RENDER_NATIVE_TEST_PLAN.md`（测试与数值等价验收）

> 版本：v0.1  
> 状态：已由架构师文档替代  
> 作者：队长（代架构师，agents service 恢复后由 architect 复核）  
> 需求来源：`rawlab/docs/PIXO_RENDER_PERFORMANCE_REQUIREMENTS.md`

---

## 1. 目标

把 pixo.render 三个性能热点（huesat / colorcal / refine）的核心计算下沉到 C++20，
通过 CMake + MinGW-w64 构建，Python 侧用 ctypes 加载。目标 half_size 真实 NEF
总耗时从 ~8s 降至 ~3~4s，并探索 1s 可行性。

## 2. 目录结构

```
render/native/
  CMakeLists.txt
  build.bat
  README.md
  src/
    hsv.h / hsv.cpp            # RGB<->HSV 内核（已完成）
    warm_sat.h / warm_sat.cpp  # M1 apply_local_warm_sat 整段
    colorcal.h / colorcal.cpp  # M2
    refine.h / refine.cpp      # M3
    native_exports.cpp         # C ABI 汇总导出
  tests/
    test_hsv.cpp
    test_warm_sat.cpp
render/_native/
  __init__.py                  # ctypes 包装 + fallback
  pixo_render_native.dll            # 构建生成，不入库
```

## 3. C ABI 设计

原则：
- 导出函数参数 **≤ 5 个**；参数多时用 `struct` 打包传指针。
- 只传裸指针 + 尺寸，不依赖 Python.h。
- 每个内核提供 float32 / float64 版本（如适用）。

示例：

```cpp
struct WarmSatParams {
    float satScale;
    float spotSatScale;
    float hueCenter;
    float hueHalfwidth;
    float satMin;
    float valMin;
    float coverageMax;
    float contrastSigmaFrac;
    float contrastThr;
    float contrastSoft;
};

// 5 个参数：rgb, out, width, height, params
extern "C" void PixoRenderApplyLocalWarmSat(
    const float* rgb, float* out, int width, int height, const WarmSatParams* params);
```

## 4. 内核设计

### 4.1 M1 huesat / apply_local_warm_sat

- 输入：线性 sRGB float32 (H,W,3)
- 流程：
  1. sRGB -> ProPhoto（矩阵乘）
  2. RGB -> HSV
  3. 计算 hue/sat/val 平滑权重
  4. 计算覆盖率，选择 broad/spot 分支
  5. spot 分支：GaussianBlur + detail 权重
  6. 修改 S，HSV -> RGB
  7. ProPhoto -> sRGB
- C++ 优化：单遍融合、避免中间数组、OpenMP 按行并行。
- 后续可选：固定参数 3D LUT。

### 4.2 M2 colorcal

- 输入：gamma RGB uint8/float32
- 流程：Lab 转换、scene_hue 旋转、skin_mask、饱和度/自然饱和度、gamut soft。
- C++ 优化：skin_mask 只算一次；scene_hue 用矩阵/降采样；整体可 LUT 化。

### 4.3 M3 refine

- 输入：gamma RGB float32
- 流程：sharpen / chroma_denoise / highlight_desat / warm_sat_gamma。
- C++ 优化：GaussianBlur 自实现 separable；降采样色度；OpenMP。

## 5. LUT 策略（可选进阶）

- 对固定参数的颜色变换（colorcal / warm_sat），预计算 33³ 或 65³ 3D LUT。
- Python 侧参数变化时重建 LUT；像素应用走三线性插值。
- 验收：A/B 视觉差异 + 数值误差报告。

## 6. 构建与集成

- `render/native/build.bat` 使用 MinGW-w64 + CMake。
- 产物复制到 `render/_native/pixo_render_native.dll`。
- Python 侧 `render/_native/__init__.py` 检测 DLL，缺失时回退纯 Python。
- 所有调用点通过 `available()` 或 try/except 回退。

## 7. 编码规范

- C++20，行宽 ≤120，K&R，中文注释。
- 常量 `constexpr`，不加 k 前缀。
- 全局变量 `g_` 前缀，慎用。
- 成员变量 `m_` 前缀，构造初始化列表。
- 函数参数 ≤5 个。

## 8. 验收

1. 单内核数值等价：float64 diff=0，float32 ≤1e-6。
2. `bench_pipeline.py` 输出每 stage 耗时。
3. 全量 pytest、ablation、render_dcp 通过。
4. half_size 真实 NEF 总耗时 ≤4s（探索 1s）。

---
