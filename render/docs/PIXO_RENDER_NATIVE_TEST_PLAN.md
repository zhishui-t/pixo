# pixo.render Native 模块测试文档（测试计划与数值等价验收方案）

> 版本：v1.0  
> 状态：待审核  
> 作者：架构师（长安小队）  
> 需求来源：`render/docs/PIXO_RENDER_PERFORMANCE_REQUIREMENTS.md` v0.1  
> 被测对象：`render/native/`（C++）、`render/_native/`（ctypes 包装）、huesat/colorcal/refine 调用点  
> 配套文档：`PIXO_RENDER_NATIVE_ARCHITECTURE.md`、`PIXO_RENDER_NATIVE_SPECIFICATION.md`

---

## 1. 测试目标

1. 证明每个 C ABI 内核与 Python 参考实现数值等价（容差见 §6）。
2. 证明原生缺失/损坏时纯 Python 回退可用，全量测试不退化。
3. 证明构建流程可复现，DLL 可加载且 ABI 版本正确。
4. 证明 half_size 真实 NEF 性能达标（huesat ≤ 0.6s / colorcal ≤ 0.8s /
   refine ≤ 0.7s / 总耗时 ≤ 4s）。
5. 为 LUT 近似路径建立 A/B 数据与视觉差异门禁。

---

## 2. 测试环境

| 项 | 要求 |
|---|---|
| OS | Windows（x86_64） |
| Python | 3.12（仓库当前环境） |
| C++ | g++ MinGW-w64（`D:\code\mingw64`），C++20 |
| 构建 | CMake 3.31 + MinGW Makefiles，Release |
| Python 依赖 | numpy、opencv-python（cv2）、pytest 9.x |
| 数据 | `render/tests/goldens/`（生成物）、真实 NEF 语料（本机路径由 `bench_pipeline.py` 配置项固化） |

测试均不联网；C++ 测试使用零依赖断言宏（`render/native/tests/test_main.cpp`），
不引入 GoogleTest/Catch2，保证离线构建。

---

## 3. 测试分层与执行顺序

```
L1 render/native/tests        C++ 内核单元测试（构建 pixo_render_native_tests.exe）
L2 render/tests        Python ctypes 包装 / 内核等价 / 调用点回退测试
L3 集成                stage 级 A/B、DCP 渲染、ablation
L4 性能                bench_pipeline.py 中位数 + 基线 JSON
L5 验收                FR1~FR6 全部门槛（§8）
```

执行命令（L1→L5）：

```bat
cd native
run_tests.bat
```

```powershell
pytest render/tests -q -m 'not e2e'
pytest render/tests/test_native_abi.py render/tests/test_native_hsv.py `
       render/tests/test_native_warm_sat.py render/tests/test_native_colorcal.py `
       render/tests/test_native_refine.py render/tests/test_native_lut3d.py `
       render/tests/test_native_fallback.py -q
python render/tools/bench_pipeline.py --baseline render/bench/native_baseline_v1.json
python render/tools/dng_stage3_ablation.py
python render/tools/render_dcp.py --check-config 2>nul || python render/tools/render_dcp.py --help
```

最后一行按 T5 固化的 `render_dcp.py` 实际参数执行（此处只要求该工具可运行且
输出图与基线无肉眼差异）。

---

## 4. C++ 单元测试（L1）

文件：`render/native/tests/test_*.cpp`，入口 `test_main.cpp`。

### 4.1 断言宏约定

```cpp
#define TEST_CASE(name) ...
#define CHECK(expr) ...      // 失败打印文件/行号并累计失败数
#define CHECK_NEAR(a, b, eps) ...
#define CHECK_ARRAY_EQ(actual, expected, n) ...   // 逐位比较
```

测试进程返回失败用例数（0=通过）；`run_tests.bat` 对非零 `errorlevel` 失败。

### 4.2 用例矩阵

| 测试文件 | 覆盖点 | 关键输入 |
|---|---|---|
| `test_hsv.cpp` | RGB↔HSV f32/f64 | 全 0/全 1/全 >1、灰轴（R=G=B）、六扇区边界 H=0/60/…/300、±0.0、10⁵ 随机（固定种子） |
| `test_warm_sat.cpp` | broad 分支 | 恒等（scale=1 应原样输出，diff=0）、低覆盖/高覆盖、`satMin/valMin/hueHalfwidth` 边界、out≠in |
| `test_warm_sat.cpp` | spot 分支（v1.1） | 人工小亮斑 + 均匀背景，coverage 超阈值；结果与 Python 参考对拍；GaussianBlur 与 cv2 对拍（若保留 cv2 则跳过本项） |
| `test_colorcal.cpp` | Lab 内核 | 每项参数单独非零、全组合、curve 端点/中间点、skinMask 椭圆内/边界/外、hue=±15、vibrance 溢出钳位 |
| `test_colorcal.cpp` | adaptive 测量 | 构造 7 带已知 median 的 Lab 小图，断言 `-damping*median`；样本不足带输出 0 |
| `test_colorcal.cpp` | neutral apply / gamut soft | weight=0/1、tint 越界、strength=0/>0、out=clip 边界 |
| `test_refine.cpp` | 融合内核 | sh/cd/hd 单开与全开、satProtect=0/1、越界软压缩上/下界、cd=0 时 blur 指针为 null 不解引用 |
| `test_refine.cpp` | warm_sat_gamma | gain>0、hueShift≠0、H 索引 0..255（≥180 权重为 0）、in-place 可重入 |
| `test_lut3d.cpp` | 3D LUT | grid=2/33、格点值精确复现、域外钳位、max==min 退化、非法 grid/空表返回 -1 |

### 4.3 C++ 测试通过标准

- 所有 `CHECK` 通过；无崩溃/无 ASAN 报告（本机如启用）。
- 内存：每个用例结束 `std::vector` 析构后无泄漏（手动校验工具可选）。

---

## 5. Python ctypes 包装测试（L2）

文件：`render/tests/test_native_abi.py` 等，允许在无 DLL 环境 skip
（但 CI 验收机必须有 DLL）。

### 5.1 ABI / 加载

| 用例 | 步骤 | 期望 |
|---|---|---|
| `available_true` | DLL 存在 | `available()==True`，`version().major==1` |
| `version_missing_tolerated` | monkeypatch 删除 `PixoRenderVersion` 符号 | v1.0 白名单可加载，`version() is None` |
| `missing_dll_importable` | `_DLL_PATH` 置为不存在 | import 成功、`available()==False`、`load_error()` 非空 |
| `argtypes_shape` | 传 `(...,4)` 的数组 | `ValueError`，消息含期望 shape |
| `non_contiguous` | 传 `arr[::2]` | 内部 `ascontiguousarray` 后结果与连续输入一致 |
| `status_negative_raises` | monkeypatch `_lib` 返回 -1 | 包装器抛 `RuntimeError`，调用方 try/except 回退 |

### 5.2 回退契约（FR6）

| 用例 | 步骤 | 期望 |
|---|---|---|
| `huesat_fallback` | 置 `_lib=None` 调 `apply_local_warm_sat` | 走 Python 参考，输出与原生开启 diff≤容差 |
| `colorcal_fallback` | 同上 | 走 Python 参考，含 skin_trim 重复计算旧路径 |
| `refine_fallback` | 同上 | 走 Python 参考 |
| `full_suite_no_dll` | 改名 DLL 后跑 `pytest -m 'not e2e'` | 无新增失败（允许预存在的 xfail/skip） |

### 5.3 LUT 缓存

| 用例 | 步骤 | 期望 |
|---|---|---|
| `cache_hit` | 同 key 两次 get | builder 只执行一次，返回同一 ndarray 对象 |
| `cache_miss` | 参数变更 | 重建，表内容与参考格点一致 |
| `key_stability` | 同参数不同 dict 顺序 | key 相同（规范序列化） |

---

## 6. 数值等价验收方案（核心）

### 6.1 参考实现固定

- 参考 = 当前 `render/core/huesat.py`、`render/modules/color_cal.py`、
  `render/modules/refine.py` 的 Python 代码路径。
- 原生 A/B 必须用同一进程、同一输入数组；用 monkeypatch 强制
  `render._native._lib = None`（或 `available()->False`）切换，**不得**手工复制公式
  写第二份 Python。
- 随机种子固定为 `np.random.default_rng(20260820)`；任何代码修改导致种子集
  变化必须更新基线并说明。

### 6.2 数据生成

| 数据集 | 规格 | 用途 |
|---|---|---|
| `golden_identity` | 全 0 / 全 1 / 全 0.5 的 64×64×3 | 快速恒等检查 |
| `golden_edges` | 通道值覆盖 {0, 1/255, 0.0031308, 0.04045, 0.5, 0.999, 1.0, 1.5, 2.0} 的笛卡尔子集 | 分段函数边界 |
| `golden_random_small` | 64×64×3，10 个固定种子 | 内核逐点对拍 |
| `golden_random_medium` | 256×256×3，3 个固定种子 | 中间数组/内存布局 |
| `golden_hsv_extreme` | 灰轴 + 六扇区边界 ±1e-9 | HSV 分支全覆盖 |
| `real_nef_half` | 真实 NEF half_size 输出（1~3 张，由 bench 语料提供） | stage 级 A/B 与性能 |

生成脚本由 T5 放在 `render/tests/goldens/generate_native_goldens.py`，产物
`.npy` 入库（< 20MB）；超过 20MB 的 medium 集改为运行时生成。

### 6.3 容差表

| 内核/路径 | 输入精度 | 容差 | 判定 |
|---|---|---|---|
| `rgb_to_hsv/hsv_to_rgb`（f64） | float64 | max\|Δ\| = 0（逐位） | `np.array_equal` |
| `rgb_to_hsv/hsv_to_rgb`（f32） | float32 | max\|Δ\| ≤ 1e-6 | `np.allclose(atol=1e-6, rtol=0)` |
| `apply_local_warm_sat`（f32） | float32 | max\|Δ\| ≤ 1e-6 | 同上 |
| `colorcal_apply_lab` | cv2 Lab float32 | max\|Δ\| ≤ 1e-6（uint8 输出按 1/255 换算） | 全像素 max 判定 |
| `adaptive_neutral_curves` | cv2 Lab float32 | 曲线 14 值 max\|Δ\| ≤ 1e-6 | |
| `colorcal_neutral_apply` / `gamut_soft` | float32 | max\|Δ\| ≤ 1e-6 | |
| `refine_apply` | float32 | max\|Δ\| ≤ 1e-6 | |
| `warm_sat_gamma_u8` | uint8 | 输出 uint8 与 Python 参考 max 差 ≤ 1（量化） | 不得出现结构性差异 |
| `apply_lut3d`（格点输入） | float32 | 格点处 max\|Δ\| = 0（表由 Python 构建） | |
| `apply_lut3d`（任意输入，33³） | float32 | 随机 RGB max\|Δ\| ≤ 2/255，并附 A/B 视觉说明 | FR3 的 LUT 豁免条款 |

任何内核不满足精确路径容差，**不允许**通过放宽容差交付；必须回该内核修复
或降级为状态 1 回退。

### 6.4 LUT 近似路径 A/B 验收

1. 数值：`golden_random_medium` 上解析内核 vs 33³ LUT，输出 max\|Δ\| 与
   95/99 分位写入 `render/bench/lut_ab_<module>.json`。
2. 图像：选 1 张真实 NEF half_size 渲染，用 `render/tools/diff_viewer.py`
   生成并排对照与 Δ 热图，存档到 `render/bench/lut_visual/`。
3. 人工/审核者确认：网格点 0 误差、插值误差 ≤2/255 且无边缘伪影，方可合入；
   默认路径仍为解析内核，LUT 只作为预设开关。

### 6.5 管线级等价

- `dng_stage3_ablation.py`：5 张 full engine_mae ≤ 5e-5（需求 §6.4）。
- 渲染回归：`render_dcp.py` 输出与 native 关闭时 A/B，像素级差异必须由
  上述容差表解释；无法解释的差异视为 bug。
- 全量 pytest：native 开启与关闭各跑一遍，通过集合差为空。

---

## 7. 性能测试（L4）

### 7.1 基准脚本要求（T5 交付）

`render/tools/bench_pipeline.py`：
- 合成图 2020×3032×3 默认基准 + `--nef <path>` 真实 NEF half_size 模式。
- 每 stage 计时用 `perf_counter`，预热 1 次后取 **5 次中位数**；输出
  `stage_name: median_ms`、总耗时、`native_available` 标志。
- `--baseline out.json` 保存；再跑 `--compare old.json` 输出每 stage 相对变化，
  任一 stage 慢 >20% 判失败（防性能回退）。
- 基线上传到 `render/bench/native_baseline_v1.json`（入库）。

### 7.2 性能门禁

| stage | 门禁（中位数） |
|---|---:|
| huesat | ≤ 0.6s |
| colorcal | ≤ 0.8s |
| refine | ≤ 0.7s |
| 总耗时（half_size 真实 NEF） | ≤ 4.0s |

未达标时允许的优化顺序（保持每步等价测试通过）：
1D LUT → 融合循环 → OpenMP（默认关）→ 3D LUT（门禁 §6.4）→ cv2 原语迁入
（穷举/海量随机对拍门禁）。

---

## 8. 验收清单（L5，对应需求 §6）

| # | 验收项 | 命令/判据 | 责任 |
|---|---|---|---|
| 1 | 构建成功 | `cd native && build.bat` exit 0 | T2~T4 |
| 2 | DLL 可加载 | `from render import _native as n; assert n.available()` | T5 |
| 3 | 内核数值等价 | L1+L2 全绿（§6.3 容差） | T2~T4 |
| 4 | 真实 NEF 总耗时 ≤4s | §7.2 中位数 | T5 |
| 5 | 全量 pytest 通过 | `pytest render/tests -q -m 'not e2e'` | T5 |
| 6 | ablation 5 张 engine_mae ≤ 5e-5 | `python render/tools/dng_stage3_ablation.py` | T5 |
| 7 | 回退可用 | 改名 DLL 后 §5.2 全量测试无新增失败 | T5 |
| 8 | 编码规范 | 行宽/命名/前缀/参数数人工 review + grep 检查 | T6 |
| 9 | LUT（若启用） | §6.4 A/B 数据 + 视觉说明已归档 | T3/T5 |

---

## 9. 测试文件归属

| 任务 | 新增/修改 |
|---|---|
| T2 | `render/native/tests/test_warm_sat.cpp`、`test_hsv.cpp` 补边界；`test_native_warm_sat.py` |
| T3 | `render/native/tests/test_colorcal.cpp`、`test_lut3d.cpp`；`test_native_colorcal.py`、`test_native_lut3d.py` |
| T4 | `render/native/tests/test_refine.cpp`；`test_native_refine.py` |
| T5 | `test_native_abi.py`、`test_native_fallback.py`、goldens 生成器、`bench_pipeline.py`、基线 JSON |
| T6 | 全量执行 §8，出审核结论 |

---

## 10. 缺陷处理规则

- 任何数值等价失败：禁止“调整参考实现绕过测试”；先查 C++ 语义差异表，
  再查常量/舍入/顺序，修复后全量重跑。
- 任何性能不达标：先跑 `bench_pipeline.py` 分 stage 定位，按 §7.2 优化顺序升级，
  每升一级重新过 §6。
- 任何回退路径失败：在 `render/tests/test_native_fallback.py` 中固化复现用例，
  修复 native 调用点的 try/except 或 `available()` 检测。

---
