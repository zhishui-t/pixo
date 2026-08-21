# pixo.render Native 模块规格文档

> 版本：v1.0  
> 状态：待审核  
> 作者：架构师（长安小队）  
> 需求来源：`render/docs/PIXO_RENDER_PERFORMANCE_REQUIREMENTS.md` v0.1  
> 架构依据：`render/docs/PIXO_RENDER_NATIVE_ARCHITECTURE.md`  
> 验证依据：`render/docs/PIXO_RENDER_NATIVE_TEST_PLAN.md`

---

## 1. 术语与约定

| 术语 | 定义 |
|---|---|
| ABI | C 导出函数/结构体/状态码/内存布局的总约定，Python 仅通过 `ctypes` 访问 |
| 内核（kernel） | 一个 C ABI 函数实现的最小可测计算单元；规格允许一个内核含多遍循环 |
| 原生路径 | `render._native.available() == True` 时走 C++；否则走纯 Python |
| 回退（fallback） | 内核返回状态 1，或 Python 捕获异常，转纯 Python 实现继续 |
| float32/float64 路径 | 同一算法两种精度入口；float32 是渲染主链，float64 用于等价基准 |
| 逐位一致 | `np.array_equal` 为 True（不含 NaN/Inf；输入限定有限值域） |

数组约定（全局）：
- C 连续、行主序、通道最末：`HxW` 或 `HxWx3`。
- 除非标注 in-place，`out` 与输入指针不得重叠（Python 侧保证分配独立 ndarray）。
- `width*height` 不得使 int32 溢出；`width, height > 0`。
- 输入值域在各内核节中声明；超值域按“未定义行为”处理，但 C++ 必须保证
  不越界写、不崩溃、不抛异常穿过 ABI。

标量类型映射：

| C ABI | ctypes |
|---|---|
| `int` | `ctypes.c_int` |
| `std::int64_t` | `ctypes.c_int64` |
| `float` | `ctypes.c_float` |
| `double` | `ctypes.c_double` |
| `uint8_t*` | `POINTER(c_uint8)` |
| `const float*` | `POINTER(c_float)` |

本机平台固定为 Windows x86_64（MinGW-w64）。结构体包含指针字段，ctypes
`Structure._fields_` 必须与 C 定义字段顺序完全一致；不做跨 32 位兼容承诺。

---

## 2. 全局 ABI 规范

### 2.1 导出宏（`render/native/src/abi.h`）

```cpp
#ifdef _WIN32
#define PIXO_RENDER_NATIVE_API extern "C" __declspec(dllexport)
#else
#define PIXO_RENDER_NATIVE_API extern "C" __attribute__((visibility("default")))
#endif
```

所有导出函数名以 `pixo.render` 开头；C++ 内部实现位于 `namespace pixo_render_native`，
导出包装函数只做参数校验、结构体拷贝与 `try/catch` 转换。

### 2.2 状态码

| 常量 | 值 | 含义 |
|---|---|---|
| `PixoRenderOk` | 0 | 成功，输出缓冲已写满 |
| `PixoRenderFallbackRequested` | 1 | 当前参数/分支未实现，调用方必须走 Python 回退 |
| `PixoRenderInvalidArgs` | -1 | 空指针、非法尺寸、非法参数（先于任何写入返回） |
| `PixoRenderUnsupported` | -2 | 已识别的参数组合但本版本不支持 |
| `PixoRenderInternalError` | -3 | C++ 内部异常（已 catch，不外溢） |

错误码为负时，输出缓冲内容未定义（调用方不得使用）。

### 2.3 版本

```cpp
struct PixoRenderVersion {
    int major;
    int minor;
    int patch;
};
PIXO_RENDER_NATIVE_API int PixoRenderVersion(PixoRenderVersion* version);
```

- 首个补全版本定为 `1.1.0`；`major==1` 为兼容版本。
- `PixoRenderVersion` 失败仅当 `version==nullptr`，返回 `PixoRenderInvalidArgs`。
- Python 加载后检查 `major==1`；不符则视为不可用并回退。

兼容期约定：当前已构建的 v1.0 DLL 无 `PixoRenderVersion` 符号。T2 合入该符号后，
`render/_native` 用 `hasattr(_lib, "PixoRenderVersion")` 判空；无符号时按 v1.0
白名单导出（现有 5 个函数）继续工作。

### 2.4 异常与内存纪律

1. 导出包装函数签名允许抛出的唯一来源是内部算法；实现必须 `try { ... }
   catch (...) { return PixoRenderInternalError; }`。
2. C++ 不释放、不保存任何跨边界指针；内部临时缓冲用 `std::vector`。
3. 内核必须可重入、无共享可变状态；同一输入多次调用输出逐位相同。

---

## 3. 公共数据结构（C ABI）

所有结构体字段为 `float/int/指针`，按声明顺序自然对齐；ctypes 侧逐一对应。

```cpp
// M1 现有结构（保持兼容）
struct PixoRenderWarmSatParams {
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

// M2 全量 Lab 内核参数；curveA/curveB 各为 7 个 float（可为 nullptr）
struct PixoRenderColorCalParams {
    float saturation;
    float vibrance;
    float hueDeg;
    float neutralA;
    float neutralB;
    float neutralSigma;
    float skinProtect;
    float skinTrimA;
    float skinTrimB;
    const float* curveA;   // nullable，7 点，对应 _NEUTRAL_CENTERS 顺序
    const float* curveB;   // nullable，7 点
};

// M2 中性快速路径的 adaptive 测量参数
struct PixoRenderAdaptiveMeasureParams {
    float damping;
};

// M2 中性快速路径的全图应用参数
struct PixoRenderNeutralApplyParams {
    const float* weight;   // HxW，0..1
    const float* tint;     // HxWx3，0..255 坐标的 RGB 色偏
};

// M3 融合内核参数；按 sharpen→chroma→highlight 顺序使用
struct PixoRenderRefineParams {
    float sharpen;
    float chromaDenoise;
    float highlightDesat;
    const float* gray;       // HxW
    const float* satProtect; // HxW
    const float* grayBlur;   // HxW，sharpen 输入；sharpen==0 时可为 nullptr
    const float* blurUp;     // HxWx3，chroma 输入；chromaDenoise==0 时可为 nullptr
    const float* grayBlurUp; // HxW，chroma 输入；chromaDenoise==0 时可为 nullptr
};

// M3 gamma 域暖色补强（in-place）
struct PixoRenderWarmGammaParams {
    float gain;
    float hueShiftDeg;
};

// 通用 3D LUT
struct PixoRenderLut3D {
    const float* table;  // grid^3 * 3，通道最末：table[(b*grid+g)*grid+r][ch]
    int grid;
    float domainMin;
    float domainMax;
};
```

字段命名沿用现有 `satScale` 风格（ctypes 同名），不改历史结构体。

---

## 4. 内核 ABI 规格

### 4.1 RGB↔HSV（已实现，保持兼容）

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderRgbToHsv(const double* rgb, double* h, double* s, double* v,
                                    std::int64_t pixelCount);   // 现状返回 void，T2 起统一返回 int（见 4.1.1）
PIXO_RENDER_NATIVE_API int PixoRenderHsvToRgb(const double* h, const double* s, const double* v,
                                    double* rgb, std::int64_t pixelCount);
PIXO_RENDER_NATIVE_API int PixoRenderRgbToHsvF32(const float* rgb, float* h, float* s, float* v,
                                       std::int64_t pixelCount);
PIXO_RENDER_NATIVE_API int PixoRenderHsvToRgbF32(const float* h, const float* s, const float* v,
                                       float* rgb, std::int64_t pixelCount);
```

语义与 `render/core/huesat.py::_rgb_to_hsv/_hsv_to_rgb` 一致：
H∈[0,360)，S/V≥0，灰像素 H=0、S=0，负数/除零处理同 Python。

#### 4.1.1 返回类型迁移

现状 4 个函数声明为 `void`。T2 统一改为返回 `int`（`PixoRenderOk`/`PixoRenderInvalidArgs`）；
`ctypes` 侧同步把 `restype` 从 `None` 改为 `c_int`，并做空指针/非法 n 前置校验。

### 4.2 M1 `PixoRenderApplyLocalWarmSat`（已实现 broad，扩展 spot）

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderApplyLocalWarmSat(
    const float* rgb, float* out, int width, int height,
    const struct PixoRenderWarmSatParams* params);
```

- 输入：线性 sRGB float32 `HxWx3`（可含 >1 高光；调用方已保证非负）。
- 语义：完整复刻 `core/huesat.py::apply_local_warm_sat` 的 broad 分支
  （sRGB→ProPhoto→HSV→权重→HSV→ProPhoto→sRGB）。
- 状态：
  - `0`：broad 路径完成，`out` 为最终结果；
  - `1`：coverage 超阈值，spot/Gaussian 分支未实现 → Python 回退（v1.0 现状）；
  - v1.1 完成 spot 分支后，spot 可处理时返回 `0`；
  - 参数非法（nullptr / 尺寸非法 / `satScale<=1` 且 `spotSatScale<=1` 视为调用方
    不应调用本函数）返回 `-1` 或 `-2`。
- v1.1 目标：spot 分支返回 `0` 的比例 ≥ 100%（所有有效参数都由 C++ 处理），
  使 M1 不再有状态 1 的回退；若 GaussianBlur 未通过 cv2 对拍，允许保留状态 1。
- 输出：非负 float32（只钳下界，不截 >1）。

### 4.3 M2 全量 Lab 内核 `PixoRenderColorCalApplyLab`

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderColorCalApplyLab(
    const float* lab, uint8_t* labOut, int width, int height,
    const PixoRenderColorCalParams* params);
```

- 输入：`cv2.cvtColor(u8, COLOR_RGB2LAB).astype(np.float32)` 的 Lab 平面，
  值域 0..255；`u8 = (clip(img,0,1)*255 + 0.5).astype(uint8)` 由 Python 量化。
- 输出：uint8 Lab（0..255），与 Python `np.clip(lab2,0,255).astype(np.uint8)`
  的截断语义一致。
- 处理顺序（必须与 `ColorCalStage.process` 全量路径一致）：
  1. 计算 `C = sqrt((a-128)^2+(b-128)^2)`；
  2. 中性轴：`w=exp(-C^2/(2*sigma^2))`；`curveA/B` 非空时按 7 点线性插值
     （节点 `_NEUTRAL_CENTERS=[8,32,72,128,184,224,248]`，`np.interp` 语义，
     端点外取端点值）：
     `a += (neutralA + aOff) * w`，`b += (neutralB + bOff) * w`；
  3. skin_trim：用 §4.4 椭圆公式计算一次 `skinMask`；
     `a += skinTrimA * skinMask`，`b += skinTrimB * skinMask`；
  4. hue：以 (a-128,b-128) 绕原点旋转 `hueDeg` 度；
  5. saturation/vibrance：
     `gain = 1+saturation + vibrance*clip(1-C/128,0,1)`；
     若 `skinProtect>0`：`gain = 1+(gain-1)*(1-skinProtect*skinMask)`；
     `a=128+(a-128)*gain`，`b=128+(b-128)*gain`；
  6. 逐元素 `clip(0,255)` 后按截断规则写 `labOut`。
- 状态：成功 `0`；nullptr/尺寸非法 `-1`；其它 `-3`。
- 注意：`gamutSoft` 不在此内核（它作用于 Lab→RGB 之后），见 §4.6。

### 4.4 肤色椭圆掩码常量（C++ 内部）

C++ 内部 `SkinMask(lab)` 必须使用与 `render/core/skin.py` 完全相同的常量：
`A=140, B=150, major=22, minor=14, angle=0.65 rad, softBand=0.25`；
软掩码 = `1 - smoothstep(clamp((d-1)/softBand,0,1))`，`d` 为椭圆马氏距离。
该函数不必导出。

### 4.5 M2 中性快速路径内核

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderAdaptiveNeutralCurves(
    const float* labSmall, int width, int height,
    const PixoRenderAdaptiveMeasureParams* params, float* curves);

PIXO_RENDER_NATIVE_API int PixoRenderColorCalNeutralApply(
    const float* rgb, float* out, int width, int height,
    const PixoRenderNeutralApplyParams* params);
```

`PixoRenderAdaptiveNeutralCurves`：
- 输入 `labSmall` 为 1/2 降采样后的 float32 Lab（Python `cv2.resize` INTER_AREA 产出）。
- 输出 `curves` 共 14 个 float：`[a0..a6, b0..b6]`。
- 语义复刻 `_adaptive_curves`：`C<=14` 为中性候选；7 个亮度带边
  `[0,16,48,96,160,208,240,256]`；`min_n = max(32, int(size*0.0005))`；
  每带 `median(A/B - 128)` 存在时输出 `-damping*median`，样本不足输出 0。

`PixoRenderColorCalNeutralApply`：
- 输入 RGB float32 `HxWx3`（0..1）；`weight` HxW；`tint` HxWx3（0..255 单位）。
- 输出 `out = clip(rgb + weight*tint/255, 0, 1)`，与 `_apply_neutral_fast`
  末尾 `out = img + w_up * tint_up / 255.0; clip(0,1)` 一致。
- 状态码同上。

### 4.6 M2 色域软压缩 `PixoRenderGamutSoft`

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderGamutSoft(
    const float* rgb, float* out, int width, int height, float strength);
```

- 输入 `cv2.cvtColor(lab8, LAB2RGB).astype(float32)/255.0` 的 RGB（0..1）。
- `strength<=0`：逐元素拷贝后 `clip(0,1)`。
- 否则：`over=max(rgb-1,0)`；`scale=1/(1+strength*sum(over,axis=-1))`；
  `out=clip(rgb*scale,0,1)`。与 `color_cal.py` 第 306~310 行一致。

### 4.7 M3 融合内核 `PixoRenderRefineApply`

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderRefineApply(
    const float* rgb, float* out, int width, int height,
    const PixoRenderRefineParams* params);
```

- 前置条件（Python 保证）：
  - `gray = img @ [0.2126,0.7152,0.0722]`（float32）；
  - `satProtect` 来自 `_sat_protection(img)`（cv2 HSV 计算）；
  - `grayBlur = cv2.GaussianBlur(gray,(0,0),1.2)`；
  - `blurUp`/`grayBlurUp` 来自当前（sharpen 之后）img 的 1/4 路径：
    `small=resize(img,(w//4,h//4),INTER_AREA)`，
    `small_blur=GaussianBlur(small,(0,0),cd)`，
    `grayBlurUp=resize(gray(small_blur), INTER_LINEAR)`，
    `blurUp=resize(small_blur, INTER_LINEAR)`。
- 语义严格按 `refine.py` 顺序：
  1. sharpen：`detail=gray-grayBlur`；
     `luma=clip(gray+sharpen*12*detail*(1-satProtect),0,1)`；
     `out0=luma3+(img-gray3)`；越界软压缩（上下界两段逻辑逐行复刻）。
  2. chroma_denoise（`chromaDenoise>0`）：在 `out0` 基础上
     `chromaOrig=out0-gray3`、`chromaBlur=blurUp-grayBlurUp3`、
     `blend=satProtect`、`out1=gray3+chromaBlur+blend*(chromaOrig-chromaBlur)`。
  3. highlight_desat（`highlightDesat>0`）：
     `wLum=smoothstep(clamp((gray-0.55)/0.30,0,1))`；
     `w=wLum*(1-satProtect)*highlightDesat`；
     `out2=out1*(1-w)+gray3*w`。
  4. `out=clip(out2,0,1)`。
- 任何子步为 0 跳过；对应可空指针在跳过的子步不得解引用。
- 状态码：成功 `0`；非法 `-1`。

### 4.8 M3 warm_sat_gamma `PixoRenderWarmSatGammaU8`

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderWarmSatGammaU8(
    uint8_t* hsv, int width, int height, const PixoRenderWarmGammaParams* params);
```

- **in-place**：`hsv` 为 `cv2.cvtColor(u8, COLOR_RGB2HSV)` 的 uint8 `HxWx3`
  （H∈0..179，S/V∈0..255），调用方随后用 `cv2.cvtColor(..., HSV2RGB)`。
- 权重 LUT 必须与 `refine.py::_build_warm_luts` 逐位一致：
  H 带宽 `(5,38)/6`，S 带 `(80)/30`，V 带 `(100)/40`，均为 smoothstep；
  H LUT 长度 256（索引 ≥180 为 0）。
- 行为：
  - `gain>0`：`s = clip(s*(1+gain*hw),0,255)`（截断写回 uint8）；
  - `hueShiftDeg!=0`：`hueW=hw*sw*vw`，`h=(h + hueShiftDeg*hueW) mod 180`；
  - 两者为 0：原样返回 `PixoRenderOk`（Python 侧不应调用）。
- 注意 Python 参考先转 `astype(np.float32)` 计算再转 uint8，C++ 以 float32
  计算后截断，误差 ≤ 0.5/255；等价测试按 §测试计划 6.3 容差执行。

### 4.9 通用 3D LUT `PixoRenderApplyLut3D`

```cpp
PIXO_RENDER_NATIVE_API int PixoRenderApplyLut3D(
    const float* rgb, float* out, int width, int height, const PixoRenderLut3D* lut);
```

- 输入 float32 RGB `HxWx3`，任值域；坐标先 `clamp` 到 `[domainMin,domainMax]`。
- 归一化坐标 `t=(x-min)/(max-min)`（max==min 时 t=0）；格点坐标
  `p=t*(grid-1)`，三线性插值，每通道独立。
- 表长度校验：`table != nullptr`、`grid>=2`、`domainMax>domainMin`，
  否则 `PixoRenderInvalidArgs`。表内存由 Python 持有，C++ 只读。
- 输出不做额外 clip（表值即最终值）。

---

## 5. 1D LUT 内部规格

| 名称 | 输入域 | 表长 | 索引 | 插值 | 等价容差 |
|---|---|---|---|---|---|
| sRGB encode | 负值按 0 处理，>1 允许 | 4096 | `x*(N-1)` 后 floor | 线性 | 对 10⁶ 随机点 max\|Δ\|≤1e-6（vs `_srgb_encode_v`） |
| sRGB decode | [0,1] 钳位 | 4096 | 同上 | 线性 | 同上 |
| warm_sat 权重 H/S/V | 整数 0..255 | 256 | 直接索引 | 无 | 与 `_build_warm_luts` 逐位一致 |

1D LUT 用函数局部 `static const std::array<float, N>` 惰性构造；构造过程无锁
（C++11 magic statics），不得定义全局可变表。

---

## 6. Python ctypes 包装器规格

### 6.1 模块状态

```python
_lib: ctypes.CDLL | None = None
_load_error: str | None = None
```

- DLL 名：Windows `pixo_render_native.dll`；路径 `Path(__file__).parent / name`。
- 加载失败（不存在 / OSError / 符号缺版本）→ 模块仍可导入，`available()==False`。
- 公共 API（目标态）：

```python
available() -> bool
load_error() -> str | None
version() -> tuple[int, int, int] | None
rgb_to_hsv(rgb) -> (h, s, v)                # float64
hsv_to_rgb(h, s, v) -> rgb                  # float64
rgb_to_hsv_f32(rgb) -> (h, s, v)            # float32
hsv_to_rgb_f32(h, s, v) -> rgb              # float32
apply_local_warm_sat_native(rgb, params) -> (out, handled)
colorcal_apply_lab(lab, params) -> lab_u8
adaptive_neutral_curves(lab_small, params) -> np.ndarray  # (14,)
colorcal_neutral_apply(rgb, weight, tint) -> out
gamut_soft(rgb, strength) -> out
refine_apply(rgb, params) -> out
warm_sat_gamma_u8(hsv, params) -> None      # in-place
apply_lut3d(rgb, lut) -> out
```

### 6.2 校验规则

1. `available()==False` → `raise RuntimeError(f"native DLL unavailable: {load_error}")`。
2. dtype 不符先 `np.ascontiguousarray(..., dtype=target)`（不复制则直接传）。
3. shape 不符 → `ValueError`，消息含期望与实际 shape。
4. 参数结构体赋值前做 `float(...)` 转换，越界交由 C++ 状态码；C++ 返回负值时
   包装器 `raise RuntimeError(f"native status {code}")`，调用方 catch 后回退。
5. 所有指针在调用期间由局部 ndarray 变量持有（防 GC）。

### 6.3 调用点改造约束

- `core/huesat.py`：沿用现有 try/except + `handled` 模式，扩展 spot 分支后删除
  “spot 由 Python 兜底”的临时注释，保留兜底代码供异常回退。
- `modules/color_cal.py`：在量化与 `cv2.cvtColor` 之后插入 native 分支；
  native 不可用/异常时逐句执行原 Python 代码（不得重构原代码语义）。
- `modules/refine.py`：native 分支复用 `gray`/`satProtect`；warm_sat_gamma
  仅在 `gain>0 或 hueShift!=0` 时调用 in-place 内核。
- 任何 native 调用失败不得写 `ctx.results` 半成品；回退后再继续 stage 流程。

### 6.4 LUT 缓存

```python
class LutCache:
    def get(self, key: str, builder) -> np.ndarray: ...
```

- 缓存键生成规则：`sha256(f"{grid}:{min}:{max}:{module}.{func}:{repr(params)}:{REFERENCE_VERSION}")`。
- 表形状 `(grid, grid, grid, 3)` float32 C 连续；由 Python 参考函数构建。
- 进程级字典；不跨进程持久化（首张图重建成本 < 0.1s）。

---

## 7. 构建规格

### 7.1 命令与产物

```bat
cd native
build.bat
```

期望产物与复制：

| 产物 | 位置 | 入库 |
|---|---|---|
| `pixo_render_native.dll` | `render/native/build/` | 否 |
| `pixo_render_native.dll`（副本） | `render/_native/` | 否 |
| `pixo_render_native_tests.exe`（run_tests.bat） | `render/native/build/` | 否 |

### 7.2 编译选项

- `-std=c++20 -O3 -DNDEBUG -Wall -Wextra`；
- 链接 `-static-libgcc -static-libstdc++`；
- CMake：`PREFIX ""`（MinGW 默认 lib 前缀必须去掉）；
- `PIXO_RENDER_NATIVE_OPENMP` 默认 OFF；开启后链接 OpenMP 运行时并保证 `available()`。

### 7.3 失败处理

`build.bat` 任一步失败 `exit /b 1`；CMake 配置与编译输出保留在 `render/native/build/`
供排查。构建成功后必须执行 §8.1 冒烟，不能只凭 `errorlevel==0` 验收。

---

## 8. 验收口径（本规格的可执行门槛）

1. 构建冒烟：
   ```powershell
   python -c "from render import _native as n; assert n.available(); print(n.version())"
   ```
2. 逐内核数值等价：见 `PIXO_RENDER_NATIVE_TEST_PLAN.md` §6 容差表。
3. 回退：临时把 `render/_native/pixo_render_native.dll` 改名后，
   `pytest render/tests -q -m 'not e2e'` 不得新增失败。
4. 性能：`python render/tools/bench_pipeline.py`（T5 交付）输出每 stage 中位
   耗时，huesat ≤ 0.6s、colorcal ≤ 0.8s、refine ≤ 0.7s、总耗时 ≤ 4s。
5. 视觉回归：`python render/tools/dng_stage3_ablation.py` 5 张 full
   engine_mae ≤ 5e-5；LUT 路径额外附 `diff_viewer.py` 对照与差异说明。

---
