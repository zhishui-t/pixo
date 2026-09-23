# R22 前期探索摸底报告（researcher, 只读）

> 生成：2026-09-10 · 阶段 2 前期探索 · 输出供队长写 `design-r22.md`
> 范围：9 条 CR（CR-06~CR-15）+ 台账 #17（+ #3/#7/#10/#12）
> 纪律：只读仓库；所有结论带 `文件:行号` 或「命令 + 输出摘要」；无法溯源处显式标 **[推测]**
> 探针脚本全部落 `%TEMP%`（见 §12 附录），仓库零改动。
> **红线遵守**：未跑真 RAW 全渲染（单次 ≈73s）；所有实测均为「EXIF 头解析 / rawpy 内嵌缩略图 / 纯函数探针」。

---

## 0. 一句话结论（给队长的最短路径）

| F-ID | 探索结论 | 与 brief 假设的差异 |
|---|---|---|
| F01/CR-06 | 要做，改动点已定位到 4 处；**但阈值必须先钉死测量分辨率** | brief 未提分辨率依赖（本次实测发现强依赖，见 §2.3） |
| F02/CR-07 | 要做；native 链改动点 8 处已列全；**高 ISO 语料足够（≥3200 有 32 张）** | — |
| F03/CR-08 | 要做；关键路径 13 处（非 132 处）；`multi_router` 已有可复用 degraded 结构 | — |
| F04/CR-09 | **口径需修正**：仓内 **0 个 `.cube`**，风格注入不是「LUT 注入」而是「卡 params → 渲染参数注入」；`/api/styles` 端点**已存在** | CR-09 原文的 `style.lut_path` 白名单**无资产可指** |
| F05/CR-10 | 要做；`scenes.json` 6 预设 `lut` 全为 `null`（纯 params 覆盖） | — |
| F06/CR-11 | 要做；软告警最小落点已定位 3 处 | — |
| F07/CR-12 | **CR-12 引用的 −7.7% 已失效**；现行系数同脚本复评为 **+19.3%（更差）** | CR-12 证据陈旧，**结论应翻转为「否决」** |
| F08/CR-13 | **已交付，勿重复造**（一致性单测 + 2 个 gate case 全在） | CR-13 属「已完成待销账」 |
| F09/#17 | 要做；**迁移面实测≈0**（仓内 0 处持久化 px 矩形）；金样本无 compose case ⇒ 不必然重生成 | brief 担心的「存量卡/参数迁移」实为空集 |
| F10/CR-15 | #3 冲突项已逐条定位（含测试未覆盖面）；**#12 前置条件已满足**（原生 `all`/`between` 已落地） | tech_debt 对 #12 的「前置未到」表述已陈旧 |

---

## 1. 降噪（F02 / CR-07）

### 1.1 现有降噪实现与参数

| 项 | 证据 | 事实 |
|---|---|---|
| 真正在跑的色度降噪 | `src/pixo/render/modules/refine.py:174` / `:182` / `:229-251` | `RefineStage.chroma_denoise`，`param_schema` 域 `[0,5]`，**默认 0.8**；实现为 **1/4 降采样** → `GaussianBlur(σ=cd)` → 上采样，再与原始色度按 `sat_protect` 混合（`_chroma_denoise_small`，`:333-366`） |
| native 色度内核 | `refine.py:238-249` | `refine_apply`（chroma+highlight 融合）或 `refine_chroma`；异常即退纯 Python（`:247-249`） |
| `DenoiseStage` 占位现状 | `src/pixo/render/modules/reshape.py:113-134` | `DenoiseStage.wants()` **恒 `False`**、`process()` 直接 `return`；`SharpenStage` 同（`:125-134`）。两者仍在 `DEFAULT_STAGES` 之外/之内？→ `presets.py:15-17` 的 `DEFAULT_STAGES` **不含** `denoise`/`sharpen`（含 `clarity`/`refine`） |
| 无亮度降噪 | 全仓 grep：`luminance` + `denoise` 无实现命中；`refine` 三子步骤只有 `highlight_desat` / `sharpen` / `chroma_denoise` | 确认「亮度降噪」为零 |

> 结论：F02 = 在 `DenoiseStage`（order=47，gamma_rgb 域，`reshape.py:113`）实现亮度降噪，**且必须把它加入 `DEFAULT_STAGES` 之外的显式执行位**——因为 `presets.py:15-17` 现有链序里没有 `denoise`。执行位二选一：(a) 加入 `DEFAULT_STAGES`（会改所有既有渲染的链序 → 金样本 21 features 里 `default_dispatch`/`card_portra_400`/`region_adjust` 三个 case 会变）；(b) 参数化注册但默认 `enabled=False`，不加入 `DEFAULT_STAGES`（`wants()` 门控为空转）→ **推荐 (b)**，与 brief「默认关」约束一致且金样本零漂移。

### 1.2 native 构建链完整步骤（实测）

```
build.bat:3   CMAKE = D:\code\cmake-3.31.6-windows-x86_64\bin\cmake.exe
build.bat:4   MINGW = D:\code\mingw64
build.bat:5-7 rd build → cmake -S . -B build -G "MinGW Makefiles"
              -DCMAKE_MAKE_PROGRAM=%MINGW%\bin\mingw32-make.exe
              -DCMAKE_CXX_COMPILER=%MINGW%\bin\g++.exe -DCMAKE_BUILD_TYPE=Release
build.bat:9   cmake --build build --config Release
CMakeLists.txt:21-31  add_library(pixo_render_native SHARED <9 个 .cpp>)
CMakeLists.txt:34     PREFIX ""（去掉 lib 前缀 → pixo_render_native.dll）
CMakeLists.txt:38-43  -static-libgcc -static-libstdc++（否则 ctypes 需 MinGW bin 在 PATH）
CMakeLists.txt:45-50  find_package(OpenMP) → 缺省链接（CMakeCache 证明 OpenMP 已找到）
CMakeLists.txt:57-64  POST_BUILD 自动 copy 到 ../_native/
```

**产物落点实测**：`src/pixo/render/_native/pixo_render_native.dll` = **620,886 B**；构建中间产物另有 `native/build/` 与 `native/build_tests/`（均已入库存在，非 clean）。

**Python 加载与版本门控位置**（实测）：

| 环节 | 位置 |
|---|---|
| DLL 搜索路径 | `_native/__init__.py:38 _add_dll_search_path()` |
| `ctypes.CDLL` + 各函数 `restype/argtypes` 声明块 | `_native/__init__.py:259-500`（单一大 `try` 块；缺符号即整体置 `_lib=None`） |
| 版本读取 | `_native/__init__.py:479-494`：调 `PixoRenderVersion`，**`major == 1` 才视为可用** |
| `version()` 公开入口 | `_native/__init__.py:511-513` |
| **版本门控范式**（新增内核照抄此行） | `_native/__init__.py:1049-1053`：`if (_version is None or _version < (1, 6, 0)): raise RuntimeError(...)`；调用方 `color_cal.py:418` 的 `except Exception: native_ok = False` 接住 → 分层回退 |
| DLL 当前版本实测 | 命令：`python -c "from pixo.render import _native; print(_native.available(), _native.version())"` → `True (1, 6, 0)`；源码 `native/src/abi.cpp:24-26` = `1.6.0`；变更历史注释 `abi.cpp:13-16` |

**新增内核需要改哪些文件（实测清单，8 项）**：

1. `native/src/abi.cpp:25` — `version->minor = 6 → 7`（**DLL 1.7.0**）；`:13-16` 补 ABI 变更注释（沿用 1.6.0 的注释范式）。
2. 内核实现：**复用** `native/src/refine.{h,cpp}`（亮度降噪与 chroma 同域同参风格，推荐）或**新建** `native/src/denoise.{h,cpp}`——若新建，须在 `CMakeLists.txt:21-31` 的 `add_library(...)` 源文件列表加一行。
3. 若内核签名带结构体参数 → `native/src/abi.h` 加 `struct`（参考 `PixoRenderSkinOklabEllipse` 的做法）。
4. 导出函数定义后缀 `PIXO_RENDER_NATIVE_API`（宏定义 `abi.h:9/11`；26 个现存导出函数的命名范式见附录 A1）。
5. `_native/__init__.py:259-500` — 在新 `try` 块内加 `_lib.PixoRenderXxx.restype/argtypes`。
6. `_native/__init__.py` — 新增 Python 包装 `def xxx(...)` + 版本门（照 `:1030-1074 colorcal_apply_lab_f32_oklch` 范式）+ 加入 `__all__`（`:1277`）。
7. `native/tests/test_main.cpp` + `native/tests/CMakeLists.txt` — 原生单测（`run_tests.bat` 一键跑，`PIXO_RENDER_NATIVE_COPY_TO_PY=OFF` 隔离构建，不污染 `_native/`）。
8. Python 侧消费者 `src/pixo/render/modules/reshape.py:113-134`（`DenoiseStage`）+ 纯 Python 等价位回退；`_native` 缺席/版本不足时 `except` 回退（范本 `reshape.py:97-105`）。

**ABI 测试兼容性**：`tests/unit/test_native_abi.py::test_version_callable` 只断言 `tuple len==3`，**版本 +1 不会翻红**（实测源码已读）。

### 1.3 可用算子与代价（本地已装依赖实测）

实测环境（命令 → 输出）：`cv2 5.0.0`（含 contrib `ximgproc`）/ `scipy 1.18.0` / `numpy 2.5.1` / `exiftool→exifread 3.5.1` / `Pillow 12.3.0`；`cv2.cuda` 设备数 = **0**（无 GPU 加速）；`cv2.getNumThreads() = 8`。

代价基线：输入 `(341, 512, 3)` RGB（= 512 长边预览 tier），预热后均值：

| 算子 | 耗时 | 备注 |
|---|---|---|
| `cv2.GaussianBlur(f32)` | **1.0 ms** | 现色度降噪用的就是它 |
| `cv2.bilateralFilter(u8, d=7)` | **4.1 ms** | f32 域 5.0 ms；保边，**推荐首选亮度降噪** |
| `cv2.ximgproc.guidedFilter(r=8)` | **6.1 ms** | 保边；`core/skin.py` 已自实现同族 `guided_filter`（`skin.py:6`, `:42-44` r=4/eps=0.01） |
| `cv2.medianBlur(3)` | 0.1 ms | 仅去脉冲噪 |
| `cv2.detailEnhance` | 65.5 ms | 太慢 |
| `cv2.edgePreservingFilter(RECURS_FILTER)` | 96.8 ms | 太慢 |
| `cv2.pyrMeanShiftFiltering(8,16)` | 278.8 ms | 不可用 |
| `cv2.fastNlMeansDenoising(gray, h=10)` | **382.6 ms** | 质量最好但 512 tier 已 0.38s；导出 6000px 不可行 |
| `cv2.fastNlMeansDenoisingColored` | **881.3 ms** | 不可用 |
| `scipy.ndimage.median_filter` / `gaussian_filter` / `scipy.signal.wiener` / `scipy.fft` | 全部可用 | 备选，同族代价不优于 cv2 |

**建议**：native 内核实现「导向滤波/双边」型的**亮度保边降噪**（O(N) 可向量化、易与 C++ 逐位对齐），Python 回退用 `cv2.bilateralFilter` 或 `core/skin.guided_filter` 复用（同 r/eps → 可做逐位对拍）。⚠️ 不要选 NLM 系：512 tier 已 0.38–0.88s，与「单次预览预算」冲突。

### 1.4 A/B 指标口径（`noise_ratio` / `detail_score` 定义与取值范围）

源码（`src/pixo/vision/measure.py:287-307`）：

```python
lap_raw       = cv2.Laplacian(gray, CV_64F).var()          # gray 来自 cv2.COLOR_RGB2GRAY(uint8 0-255)
lap_denoised  = cv2.Laplacian(cv2.medianBlur(gray,5), CV_64F).var()
noise_ratio   = clip((lap_raw - lap_denoised)/max(lap_raw,1e-6), 0, 1)   # ∈[0,1], round 4
detail_score  = round(lap_denoised, 2)                                   # 量纲 = 拉普拉斯方差, 无上界
fft_high_ratio= _fft_high_ratio(gray)                                    # ∈[0,1]
```

实测取值范围（**rawpy 内嵌相机 JPEG 全幅**，12 张高 ISO + 6 张低 ISO，命令见附录 A2）：
- 高 ISO(≥3200)：`noise_ratio` ∈ **[0.4724, 0.7473]**；`detail_score` ∈ [1.81, 3.71]
- 低 ISO(640~1600)：`noise_ratio` ∈ **[0.4137, 0.5961]**；`detail_score` ∈ [0.81, 4.13]
- 合成平坦补丁（本次探针）：`noise_ratio = 0.0`（medianBlur 几乎无耗散）

**→ `noise_ratio` 是比值型、有界 [0,1]，但 `detail_score` 无界且随分辨率 20× 变化（见 §2.3）。CR-07 的「`detail_score` 降 ≤10%」是比值判据，必须在**同一 tier、同一后缀**下比较，否则不可判定。**

### 1.5 高 ISO 语料筛选方式（实测）

- EXIF 读取路径（生产链）：`src/pixo/meta/exif.py:387-392` 定义 `_ISO_KEYS = ("EXIF ISOSpeedRatings","Image ISOSpeedRatings",...)`；`:457` 归一化为 `meta["iso"]`；底层 `:498-502` `exifread.process_file(f, details=False)`（读头不读全图，快）。
- 闭环侧入口：`pipeline/loop.py:662-666 _default_meta_extractor → pixo.meta.extract`。
- 快速筛选替代路径（本次探针用）：`rawpy.extract_thumb()` + `cv2.imdecode`（生产已有先例 `render/api.py:256-261`），只读内嵌 JPEG，**毫秒级、不触发全渲染**。

**实测 `K:\data\photo\0711\raw` ISO 分布**（765 个 NEF 全解析，0 失败，命令见附录 A2）：

```
ISO_HIST: [(100,8),(110,3),(125,202),(140,1),(160,2),(180,1),(200,102),(220,4),
           (250,6),(280,5),(320,240),(360,8),(400,4),(450,11),(500,5),(560,11),
           (640,16),(800,99),(1000,1),(1600,4),(3200,12),(5000,5),(6400,11),
           (8000,2),(12800,2)]
ISO>=3200 count = 32      ← 满足 CR-07「≥20 张高 ISO」要求（余量 12 张）
ISO>=1600 count = 36
TOP12_HIGH_ISO: DSC_5314(12800) DSC_5315(12800) DSC_5278(8000) DSC_5279(8000)
                DSC_5290~5295(6400) DSC_5309/5310(6400)
```

> **结论**：语料无需新建，直接按 ISO 降序取 `ISO>=3200` 的 **32 张**（或取 TOP20）即可满足 ≥20 张。注意 `ISO>=3200` 的子集含 DSC_5290-5295（`1/800s`、`1/640s` 快门外）→ 画面可能欠曝，A/B 需记录 EV 以免「降噪效果」被曝光差混淆。

---

## 2. 噪声指标入键宇宙（F01 / CR-06）

### 2.1 `measure_sharpness` 输出的**实际层级**（实测打印）

命令（附录 A3）→ 输出：

```
measurement top-level keys = ['detection_version','global','image_id','mask_version','regions','render_version']
global keys               = ['contrast','detail','highlight_clip_ratio','mean_luminance',
                             'preview_highlight_clip_estimate','shadow_clip_ratio']
global.detail keys        = ['haze','motion_blur','sharpness','thresholds','zone_exposure']
global.detail.sharpness   = {"laplacian_raw":1840.85,"laplacian_denoised":2063.98,
                             "noise_ratio":0.0,"fft_high_ratio":0.0014,"detail_score":2063.98}
metrics_for_decide(rep) keys = ['contrast','highlight_clip_ratio','mean_luminance',
                               'preview_highlight_clip_estimate','preview_overflow_ratio','shadow_clip_ratio']
"noise_ratio" in flat  → False
"detail_score" in flat → False
```

即层级 = **`measurement["global"]["detail"]["sharpness"][<metric>]`（4 层）**，源码 `vision/measure.py:549-553`（`measure()` 组装 `global_result["detail"]`）。

### 2.2 展平与注册的最小改动点（4 处 + 1 规则）

| # | 文件:行 | 现状 | 改动 |
|---|---|---|---|
| 1 | `src/pixo/pipeline/metrics.py:76-89` | 只读 `global` 的 6 键 + 区域键 | 增加 `sharp = ((global.get("detail") or {}).get("sharpness") or {})`，写入 `noise_ratio` / `detail_score`（建议加 `fft_high_ratio`、`laplacian_raw/denoised` 可选）。**注意缺失语义**：现有 `metrics_for_decide` 对 6 个固定键恒写（值为 `None`）；新键应保持一致风格（恒写 or 仅在存在时写——二选一需在 design 明确，因 `decide` 侧 `metric is None` 走「缺失静默不触发」`engine.py` 语义） |
| 2 | `src/pixo/pipeline/metrics.py:39-55` `METRIC_KEYS` | 10 键 frozenset | 加 `noise_ratio` / `detail_score`（**这是 `metric_universe()` 的组成常量**，`:105-123`；当前 `metric_universe()` 实测 = **22 键**） |
| 3 | `src/pixo/pipeline/loop.py:761-770` | `register_metric_keys({...})` 硬编码 10 键 | 同步加两键（该注册是**构造期全局 set 副作用**，lint 松紧取决于 `load_rules` 与 loop 构造先后，见 `metrics.py:115-117` 的告警） |
| 4 | `src/pixo/decide/rules/__init__.py:31 DEFAULT_RULES` + 新增 YAML | 现有 5 个 YAML（`color_rules` / `crop_suggest_rule_003` / `exposure_rule_001` / `highlight_protect_rule_002` / `region_rules` / `tone_clarity_rules`） | 新增噪声规则（condition 引 `noise_ratio >= 阈值`），登记进 `DEFAULT_RULES` |
| 5 | lint 机制（无需改，供设计引用） | `decide/engine.py:151 _enforce_formula_lint` / `:232 load_rules(source, metric_keys=...)` / `:446 _METRIC_KEY_REGISTRY` / `:449 register_metric_keys` | 键宇宙非空时公式标识符与 `condition.all` 指标走严格校验 |

### 2.3 ⚠️ 新发现（brief 未覆盖）：指标强分辨率依赖，阈值必须先钉 tier

命令（附录 A4）→ 同一张相机 JPEG 缩放至不同 long_edge 后测 `measure_sharpness`：

| 照片 | 512 | 1024 | 2048 | 全幅 6048 |
|---|---|---|---|---|
| DSC_5314 (ISO12800) `noise_ratio` | **0.2837** | 0.4678 | 0.8156 | 0.7416 |
| DSC_5278 (ISO8000) `noise_ratio` | 0.5512 | 0.4749 | 0.5887 | 0.6139 |
| DSC_5236 (ISO1600) `noise_ratio` | **0.6680** | 0.7110 | 0.7140 | 0.5211 |
| DSC_5241 (ISO640) `noise_ratio` | **0.1427** | 0.1887 | 0.3602 | 0.4137 |
| DSC_5314 `detail_score` | 58.69 | 15.78 | 4.70 | 2.21 |

**两个致命发现**：
1. `detail_score` 从 512→全幅**降 ~26×**（拉普拉斯方差随降采样单调变）；「降 ≤10%」必须同 tier。
2. `noise_ratio` **排序非单调**：512 tier 下 ISO12800 的 noise_ratio(0.284) **低于** ISO1600(0.668) —— 512 预览 tier 上「噪声」几乎不可判别；全幅才恢复正确排序（0.742/0.614/0.521/0.414）。

**影响**：
- CR-06 的「新增 1 条阈值锚定实测分位的噪声规则」必须**钉死 tier**（建议：规则阈值基于**导出全幅**分位；但闭环 decide 只在 preview 上循环 → 若规则要在闭环内触发，阈值必须按 `preview_long_edge` 归一化，**这是设计必须显式裁决的一个点**）。
- CR-07 的 A/B 验收（`noise_ratio` ↓≥30%、`detail_score` ↓≤10%）必须写明「在哪个 tier 上测」+「测同 tier 无降噪基线 vs 有降噪」。
- **[推测]** 真实管线在 512 是从 RAW 重采样生成（非 JPEG 缩放），噪声谱不同；但「分辨率强依赖、排序非单调」的方向性结论对真实链同样成立（`_gray_from_rgb` 转 u8 + 拉普拉斯对尺度极敏感，`measure.py:194-197`）。

---

## 3. 多轴 QC（F06 / CR-11）

### 3.1 `_qc_outcome` 现状与判定权威

| 项 | 证据 | 事实 |
|---|---|---|
| `_qc_outcome` | `pipeline/loop.py:1716-1735` | 只读 **1 个量**：`full_measurement["global"]["highlight_clip_ratio"]` → 组 `qc_context = {params, qc_overflow_ratio, qc_rollback_count, unreliable_regions, locked_params}` → 调 `qc_rollback()` |
| 判定权威 | `src/pixo/decide/engine.py:1016-1079` `qc_rollback()` | 阈值常量 `engine.py:81 _QC_OVERFLOW_THRESHOLD = 0.03`；返回 `decision ∈ {adjust_and_continue, rollback, manual_review}`；rollback = `Exposure -0.15 EV`（`:1069`）；二次超标 / Exposure 被锁 → `manual_review` |
| 谁读它 | `loop.py:1821 qc = self._qc_outcome(...)` → `:1823/1873` 分支 → `sm.transition("ACCEPTED"/"MANUAL_REVIEW")` | **最终 ACCEPT/REJECT 由 loop 的 `PhotoStateMachine` 状态机决定**，`qc_rollback` 只给建议 decision |
| 双重短路 | `engine.py:1134-1145` | `decide()` 入口对同一 `qc_overflow_ratio` 走「FINAL_QC 回退优先」短路 → 同一阈值两处生效（`loop.py:1821` 与 `decide()` 入口） |
| 回退计数 | `pixo/state/machine.py::_MAX_QC_ROLLBACKS`（`engine.py:29` import） | 上限常量单源 |

### 3.2 `targets` 现状与生产默认

| 项 | 证据 | 事实 |
|---|---|---|
| 参数入口 | `loop.py:727 targets: Mapping|None = None` → `:780 self.targets = dict(targets or {})` | 库层缺省 `{}` |
| **生产默认** | `src/pixo/service/runtime.py:951` | `SinglePhotoLoop(..., targets={}, ...)` — auto-loop 生产装配**显式传空** |
| 消费面（3 处） | `engine.py:498-531 _resolve_target()`（公式 `target` 变量，支持 dict/list 两种形态）、`engine.py:562-572`（把 targets 直接展开进公式变量表）、`engine.py:824`（另一条 targets 用法） | 公式守卫规则的 `target` 目前靠 `action.target` 或 `condition.value` 回退 |
| trace 留痕 | `loop.py:1399 _target_value(self.targets, metric_name)`、`:1420 "targets": self.targets` | 已进 trace |

### 3.3 报告/响应里加「软告警」字段的**最小侵入落点**（3 处，推荐组合 A+B）

| # | 落点 | 位置与理由 |
|---|---|---|
| **A** | `engine.py:1037-1044`（达标分支）/ `:1071-1079`（rollback 分支）的返回 dict 各加一个 `"soft_warnings": [...]` 键 | loop **只读** `decision` / `params` / `reasons`（`loop.py:1823/1825/1830/1852/1874`）→ 新增键对判定**完全惰性**，零行为风险 |
| **B** | `loop.py:1716-1735 _qc_outcome`：把 `full_measurement` 的多轴值（清晰度/噪声/色彩）放进 `qc_context`，并把 `qc["soft_warnings"]` 写进 `LoopResult.metadata`（或加 `LoopResult.qc` 字段，`loop.py:207-262`）+ 一条 `_add_trace(event_type="qc_soft_warning")` | `LoopResult.metadata` 是天然的扩展槽；trace 已有 `qc_rollback` 事件范式（`loop.py:1834-1846`） |
| **C**（服务边界，供前端/用户可见） | `service/runtime.py:963-972` `payload = {state, iteration, params, rule_ids, ...}` 加 `"soft_warnings": ...` | auto-loop 响应字段集是 R21 新增的，扩字段不动既有契约；`decide_photo` 路径的字段集合被 design 明确「不变」（`runtime.py:737`），**不要**在那里加 |

### 3.4 美学阈值分支现状（确认不得作硬门禁）

| 项 | 证据 | 事实 |
|---|---|---|
| 美学注入 | `loop.py:731-733` `aesthetic_scorer` / `aesthetic_accept_threshold` / `aesthetic_stagnation_eps`；`:785-795` 存字段，**缺省全 `None`（关闭）** | 生产 `runtime.py:954 aesthetic_scorer=None` ⇒ 美学维度**在生产闭环里不生效** |
| 生产是否传阈值 | `runtime.py:943-957` 构造参数列表**没有** `aesthetic_accept_threshold` | 缺省 `None` ⇒ 美学不作门禁（红线已满足） |
| 红线依据 | `docs/R21_CHANGE_REQUESTS.md:108` + `docs/tech_debt.md:148-153`（t98 结论：合成/低纹理域 Spearman ρ≈0.03，「不可作合成图质检硬结论」） | 硬门禁仍只 `highlight_clip_ratio` |
| 现有硬门禁全集 | `engine.py:81`（唯一阈值）+ `loop.py:1723`（唯一读点） | 确认：像素溢出是**唯一**硬门禁 |

> **F06 的最小实现** = 让 `_qc_outcome` 组装多轴 → `qc_rollback` 返回 `soft_warnings` → loop 落 metadata/trace → service payload 透出；**判定分支一行不改**（`engine.py:1037` 的 `ratio <= 0.03` 保持唯一硬门禁）。验收「回归集 QC 报告含多轴字段且不改变既有 ACCEPT/REJECT」自然成立。

---

## 4. 静默降级（F03 / CR-08）

### 4.1 总数复核（R21 说 131，现为 132）

命令：`Get-ChildItem src\pixo -Recurse -Include *.py | Select-String "except Exception" -SimpleMatch | Measure-Object` → **132**（R21 后新增 1 处）。分布 Top：`loop.py 14` / `meta/exif.py 10` / `service/runtime.py 7` / `modules/exposure.py 7` / `modules/refine.py 6` / `batch.py 5` / `render/api.py 5` / `core/io.py 5`。

### 4.2 **关键路径清单**（13 条，逐条给 file:line + 降级后果；其余 119 处属纯回退路径，维持现状）

| # | 路径 | 位置 | 现状 | 降级后果（用户可见性） |
|---|---|---|---|---|
| 1 | clarity native | `render/modules/reshape.py:97-105` | `except Exception:` → 纯 Python `_clarity` | 预览清晰度算法切换；**仅预览**路径（`:87` 分支）+ 降采样 1/2~1/4；无日志 ⇒ 用户看不到「native 没生效」 |
| 2 | refine native 导入 | `render/modules/refine.py:198-208` | `except Exception: native=False` | 整条 refine 退纯 Python（~慢数倍）；无日志 |
| 3 | refine sat_protect | `refine.py:210-217` | 局部退 Python | 单子步骤退化 |
| 4 | refine sharpen | `refine.py:219-228` | 局部退 Python | 同上 |
| 5 | refine chroma(+highlight fused) | `refine.py:238-251` | 局部退 Python `_chroma_denoise_small` | 色度降噪数值路径切换（**降噪是 F02 主战场**，此处静默会让 A/B 结论失真） |
| 6 | refine highlight | `refine.py:252-262` | 局部退 Python | 高光去饱和路径切换 |
| 7 | exposure native | `render/modules/exposure.py:457-467` | 退「vignette + 2^ev + soft_highlight_rolloff」纯 Python | 曝光链数值切换；**关键路径**（所有照片必经） |
| 8 | tone LUT1D native | `render/modules/tone_map.py:330-335` | `except Exception` → `apply_lut1d_fast` | 影调曲线插值路径切换（逐位差风险） |
| 9 | WB matrix_apply3 native | `render/modules/white_balance.py:394-399` | 退 `cam_w.reshape(-1,3) @ m_total.T` | WB 矩阵路径切换（**色彩链关键**） |
| 10 | WB warmth 标定表加载/校验 | `render/modules/white_balance.py:146-159` | `except Exception: curve, domain = None, None` → 回退内置斜率模型（`_WARM_CAL_CACHE` 缓存坏结果） | **标定表静默失效**（R20 才刚扩域，被静默吞掉危害最大）；无日志 |
| 11 | colorcal native（hsv/oklch + gamut） | `render/modules/color_cal.py:380-419` | `except Exception: native_ok = False` → 纯 Python Lab 域实现（`:421-427`） | 肤色保护/饱和路径切换；oklch 域 **DLL<1.6.0 也必须走这里**（设计如此），故不能一律告警 → 需**区分**「版本门拒绝」vs「真异常」 |
| 12 | LUT3D native | `render/core/lut3d.py:178-191` | `except Exception: pass` → numpy lookup | 风格 LUT 路径切换；**唯一一处 `pass`（连变量都不记）** |
| 13 | 解码 native CFA | `render/core/io.py:168` 调用点；接住处 `render/web/session.py:200-204` | 退 rawpy AHD half | 解码算法切换 ⇒ **像素级不同**（预览/导出一致性风险）；无日志 |

补充：`render/core/io.py:180`（decode `.npz` 缓存读失败静默 `pass`）、`render/core/huesat.py:341/355`（native hsv/点云路径）——建议归入「次要关键」，可一并纳入清单。

### 4.3 `vision/health.py` 现有结构可否承载

| 项 | 位置 | 结论 |
|---|---|---|
| 顶层返回 | `vision/health.py:129-191` | `{status, ready, available, version, segmenter, models{...}, multi_router, aesthetic, horizon}` |
| 已有 degraded 语义 | `vision/health.py:82-126 _multi_router_health_info()` → `backends` 各条 `loaded/degraded/last_error` + **`last_degraded` 列表**（`:95`, `:114`）；`detail` 里给出「N 个最近降级」（`:110-112`） | **可直接复用的结构范式** |
| 生产来源 | `vision/segmenters/multi_router.py:191-198` `_record_degrade()` + `_warn_once()`；`:239-244` detect 失败；`:259-262` warmup 失败 | segmenter 侧**已经**有结构化 degraded + warn-once，F03 不必重造 |
| 缺口 | `vision/health.py` **只覆盖 vision 模型栈**（aesthetic/horizon/segmenter），**完全不覆盖 render 侧的 native/标定/LUT 降级**（清单 13 条里 12 条在 `render/`） | ⇒ 需新增一个 render 侧承载点 |

### 4.4 建议挂点

**两层**（推荐）：
- **L1 采集层**：`render/` 内新增模块级 `render_degradations: list[dict]`（或复用 `_native` 已有的 `load_error()` 范式 `_native/__init__.py:507`），配 `record_degradation(kind, path, exc, detail)` + `warn_once` 语义（照抄 `multi_router._warn_once` 的节流协议，避免 132 处变 132 行日志）。
- **L2 暴露层**：在 `vision/health.py:170-191` 的返回 dict 加一个 `"render_degraded": [...]` 键（或独立 `render_health()` 挂到 `service/app.py` 的 `GET /api/health`，`:362-365`）；同时在 **render trace** 留痕（`LoopResult.trace_events` 已有 `event_type` 槽位）。
- **不要**把所有 `except Exception` 都改 `log.warning`（132 处全改会淹日志且触发大量既有测试的 caplog 断言）。**只改清单 13 条 + 区分「预期版本门拒绝」与「真异常」**（清单 #11 的 colorcal 是典型：DLL<1.6.0 的回退是**设计行为**，不应告警）。

**验收锚点**（CR-08 原文）：人为破坏一个标定文件 → health 暴露 degraded 条目。清单 #10（`white_balance.py:146-159` warmth 表）是最现成的靶子：删/写坏 `configs/calibration/warmth_curve.json` → 新增测试断言 `render_degraded` 含 `warmth_curve`。

---

## 5. 风格化（F04 / F05 / CR-09 / CR-10）

### 5.1 `apply_intents` 的 LUT 与场景语义（源码实测）

| 项 | 位置 | 事实 |
|---|---|---|
| `apply_intents` | `render/pipeline/intents.py:187-256` | 纯函数，`params` → 新 dict；`op=="style"` → `out["stylize"]["lut_path"] = str(value)`（`:236-238`）；`op=="scene"` → `apply_scene_preset()` 展开 params + 可选 `stylize.lut_path`（`:239-247`）；场景 id 落 `out["__meta__"]["scene"]` |
| style/scene op 白名单 | `intents.py:63 _STR_OPS`、`:45-60 _OP_TABLE`、`:87-94 EditIntent.__post_init__` | `style`/`scene` 需**字符串**值；`_RULES:303-312` 把中文词映射到 `scene ∈ {portrait,landscape,night,street,food,mono}` 与 `style ∈ {velvia,classic_neg,astia}` |
| `apply_scene_preset` | `render/pipeline/scene_apply.py:47-65` | 读 `configs/styles/scenes.json`（**进程内缓存** `:24`，`_reset_caches()` 测试钩子 `:40-44`）；未知场景 `({}, None)` + `warnings.warn` |
| `StylizeStage` | `render/modules/style.py:19-59` | `param_schema = {lut: any, lut_path: str, lut_strength: float[0,1]}`；`wants()` = LUT 可加载（`:47-48`）；`_get_lut` 走 `core.lut.load_lut_path` **共享 LRU（上限 4 表）**（`:42-45`）；`process` 用 `lut.apply_f32`（native 四面体 v1.3.0，缺席内部回退 numpy，`:55-58`） |
| `src/` 内 `apply_intents` 调用点 | R21 §1 表 + 本轮复核（`grep -r apply_intents src/pixo`）= **0** | 仍然零调用 |

### 5.2 `StyleCard.from_films_dir` 与 25 张卡字段

| 项 | 位置 | 事实 |
|---|---|---|
| 加载器 | `src/pixo/know/cards.py:89-122` | 扫 `configs/styles/films/*.json`；**要求 `data["stages"]` 非空**否则跳过（`:115-116`）；`style_id = fp.stem`；`metadata` 补缺省（`:44-52` + `:118-120`，family 缺省 `"uncategorized"`，label 缺省文件名） |
| 卡 schema（样卡实测） | `configs/styles/films/fujifilm_astia.json:1-73` | `{stages:[8~12 段], params:{exposure,whitebalance,tone,huesat,colorcal,skin,stylize:{},refine}, output:{quality}, metadata:{family,label,tags,scenes,character,year,grain_proxy}}` |
| **`stylize` 键实测** | 同上 `:45` = `"stylize": {}` **空对象** | 25 张卡**没有任何 LUT 路径** |
| 资产实况（关键） | 命令：`Get-ChildItem -Recurse -Include *.cube,*.3dl,*.look` → **0 命中**；`Get-ChildItem configs -Recurse -Include *.json | Select-String "lut_path"` → **0 命中**；无任何名字含 `lut` 的目录 | **仓内 0 个 `.cube` LUT**；`configs/styles/films` 是**参数卡**不是 LUT 卡 |
| 目录文件数 | 25 个胶片 JSON + README + 2 个 demo（`oklch_demo_*`）= **27** 个卡 JSON（R21 与 brief 说 25 张，口径差在 2 个 demo 卡） | 与 brief「25 张」一致（口径说明） |
| 说明文档自证 | `configs/styles/films/README.md:16-19`「渲染管线 `pipeline_from_config` 只读 stages/params/output，`metadata` 为未知键自然忽略」 | 卡的**预期消费方式 = 参数注入**，非 LUT |
| 外置 LUT 目录（仓外） | `THIRD_PARTY_NOTICES.md:164`「仓内无 .cube 文件，运行时 LUT 目录回退指向**仓外** `guanlan/luts`（`src/pixo/render/core/lut.py:28`）」 | **[实测确认]** 仓外依赖，分发环境不可用 |

> **F04 口径修正建议（重要）**：CR-09 原文的「service 支持 `style.lut_path`（白名单 + 路径限制在 `configs/styles/films` 内）」在本仓**无资产可指**（0 个 `.cube`；白名单目录里只有 JSON 参数卡）。
> 正确的最小改动 = **「风格卡参数注入」**：`style_id` → `StyleCard.from_films_dir()` 取卡的 `params` → **深合并进 session params**（语义等价于 `apply_scene_preset` 的做法 `scene_apply.py:64`），可选保留 `stylize.lut_path` 作为**未来** LUT 扩展位（白名单同时限 `configs/styles/films` 与 `.cube` 后缀，但当下无消费者 ⇒ 会引入「永不触达」的死代码，建议**本轮不做**，只登记）。
> 若队长坚持 CR-09 原文口径，则**必须同时产出 1 个 `.cube` 资产**（本仓自产、无第三方许可面）——这超出「只读探索」范围，属需裁决的范围变更。

### 5.3 service 侧**渲染参数装配路径**（白名单该放哪）

| 环节 | 位置 | 现状 |
|---|---|---|
| HTTP 参数入口 | `service/app.py:135-146 PUT /api/sessions/{session_id}/params` → `rt.update_params(session_id, patch, source)` | 透传 |
| service 层 | `service/runtime.py:477-489 Runtime.update_params()` → `session.update_params(dict(patch))` | 只做 generation 递增与响应组装 |
| **render 层（真正的合并点）** | `render/web/session.py:175-180 RawPreviewSession.update_params()` | `_deep_merge(self.params, dict(new_params or {}))` —— **无任何键白名单、无路径校验、无 param_schema 校验**（实测源码，全局 grep `validate_patch|unknown_param|whitelist` 在 `render/web/` 零命中） |
| 参数 → 管线 | `render/web/session.py:451-467 canonical_params()` → `build_default_pipeline(prof, params=self.params)`（`presets.py:20-30`） | 每 stage 的 `default_params()` + 用户覆盖 |
| 消费 | `StylizeStage._get_lut()`（`style.py:35-45`）→ `core.lut.load_lut_path(path)`（`core/lut.py:90`） | **任意路径会被直接打开**（若做 LUT 注入，这是真实安全/越界面） |

**白名单建议挂点**（按「策略 vs 机制」分层）：
- **机制层（必须）**：`render/web/session.py:175` 的 `update_params` 加 `stylize.lut_path` 的**路径栅栏**（解析后必须落在 `configs/styles/films` 或专门的 LUT 白名单目录内），或更干净地放在 `core/lut.py:90 load_lut_path` 入口做统一栅栏（**一处覆盖所有调用方**，含 `apply_intents` → `StylizeStage`）。
- **策略层（服务）**：`service/runtime.py:477` 新增 `style_id` 参数装配（校验白名单 = `from_films_dir()` 的 `style_id` 集合），把「风格选择」提升为一等 API 参数而不是让前端拼 params。
- **[推理]** 推荐「策略层做 style_id 校验 + 机制层做路径栅栏」双保险；只做其一都有绕面（只做策略层：前端仍可直传 `stylize.lut_path`；只做机制层：任意白名单内文件仍可被拼路径读取）。

### 5.4 前端 `StyleAiPanel` 现状（**已接样式列表，非占位**）

| 项 | 位置 | 事实 |
|---|---|---|
| 后端端点**已存在** | `service/app.py:338-350 GET /api/styles`（降载：`style_id + metadata`）、`:352-360 GET /api/styles/{style_id}`（完整卡） | **CR-09 要求的「GET /api/styles/films 列表」实质已完成**（路径名不同） |
| client | `frontend/src/api/client.ts:138-147` `listStyles()` / `getStyle(styleId)` | 已实现 |
| 类型 | `frontend/src/types.ts:308-329` `FilmCardMetadata` / `StyleSummary` / `StyleCardDetail`（含 `stages`/`params`/`output`） | 已实现 |
| store 接线 | `frontend/src/store/useAppStore.ts:389-391` — 模块加载时 `fetchStyleCards()` fire-and-forget → `setStyleCards`；`api/index.ts:227-252` 后端优先 + mock 回退 | **已接线** |
| 面板组件 | `frontend/src/components/StyleAiPanel.tsx:16-208` | 已按 `family` 分组渲染（`:42-50`）；点击 → `fetchStyleDetail` 展开「适用场景 + 渲染链段数」（`:26-39`、`:118-133`） |
| **缺什么** | 全组件 grep：**没有任何「应用」动作**；store 无 `applyStyle` / 无 `patchParam({stylize|tone|colorcal|...})` 调用来自本面板 | ⇒ 点击只是**查看**，样式不落渲染参数 |
| 可复用的写参数通路 | `store/useAppStore.ts:267-275 patchParam(patch, source)` → `api/index.ts:141-154 patchParams()` → `PUT /api/sessions/{id}/params` | **现成**；风格应用只需 `patchParam(card.params)` |
| 页面组织 | `frontend/src/App.tsx:220` `{rightTab === 'style' ? <StyleAiPanel /> : <AdjustmentsPanel />}` | 已是独立右栏 tab |
| 用户偏好冲突（需注意） | `StyleAiPanel.tsx:94/150` 用了 `linear-gradient(135deg, accentA(...), T.overlay)` 渐变卡 + `border 1px accentA` + `ChevronDown` 旋转动画（`:108`） | 与 user profile「不喜欢玻璃拟态/光斑/大量动画/列表式罗列」**相冲突**；F04 若动此面板，应**顺带简化为朴素选择器** |

### 5.5 「后端注入 + 前端简约选择器」最小改动清单

| # | 端 | 文件 | 改动 |
|---|---|---|---|
| 1 | 后端 | `service/runtime.py:477`（或新增 `apply_style(session_id, style_id)`） | `style_id` → `StyleCard.from_films_dir()` 白名单校验 → 卡的 `params` 深合并进 session params（`session.update_params`）|
| 2 | 后端 | `service/app.py:135` 附近 | 新增 `POST /api/sessions/{id}/style`（body `{style_id}`）或复用 PUT params + 服务侧 style_id 解析；**越界 style_id → 404/400** |
| 3 | 后端 | `render/pipeline/scene_apply.py` 范本 | 场景预设走同一装配函数（`apply_scene_preset` 返回 params 覆盖 → 同样深合并），6 个场景 id 白名单 = `scenes.json` 键集 |
| 4 | 前端 | `store/useAppStore.ts` | 加 `applyStyle(styleId)` / `applyScene(sceneId)` action → 调 `patchParam(...)`（复用 `:267`） |
| 5 | 前端 | `components/StyleAiPanel.tsx` | 卡片 → **简约选择器**：`Select`/`SegmentedControl` 或紧凑 chip 行（去渐变/去动画）；选中即 `applyStyle`，失败要**显式提示**（user profile：「更新失败要明确提示，不能静默无效」）|
| 6 | 前端 | 同面板 | 场景预设用同一选择器（6 项），放风格选择器上方；`StyleAiPanel.tsx:66` 目前是「本地 mock 对话」占位（明说 `本地 mock`），**不要**把它当 F04 交付面 |
| 7 | 测试 | `tests/unit/` + `tests/integration/` | ① 带 `style_id` 的请求使渲染 params 变化（trace 留痕）；② 越界 style_id 被拒；③ `apply_scene_preset` 未知场景告警路径 |

---

## 6. RP-CCM（F07 / CR-12）—— **本轮最重要的证据翻转**

### 6.1 A/B 证据原文数字与结论（两份报告，结论相反）

| 报告 | 时间 | A: DCP | B: DCP+RP-CCM | B−A | B 更优张数 |
|---|---|---|---|---|---|
| `.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md:12-16` | 2026-08-28 | median 6.151 / p95 16.732 | median **5.675** / p95 16.239 | **−0.475 (−7.7%)** / p95 −2.9% | **45/54** |
| `.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260904_235522.md:12-16, :77` | 2026-09-04 | median 5.946 / p95 15.928 | median **7.093** / p95 16.711 | **+1.147 (+19.3%)** / p95 +4.9% | **22/54** |

两份报告**同语料**（`exports/auto/full_scan` 54 张）、**同脚本**、**同 DCP**、同指标口径（CIEDE2000 D65、线性窗 [0.01,0.9]、逐照片 gain 对齐）。唯一变化是**系数表**：

- `configs/color/rp_ccm_nikon_z5_2.json` mtime = **2026-09-04 20:14**，由 commit **`3fbe56d`**（"新表入库正式 configs（阶段二终审路径1）"）替换（`git show 3fbe56d -- configs/color/rp_ccm_nikon_z5_2.json` 可见 matrix 3×6 逐值变更，matrix[0][0] 1.8133→2.3556）。
- 脚本取系数路径：`scripts/eval_rp_ccm_ab.py:73 --ccm-dir default="configs/color"`（即**生产位**），`:104 load_rp_ccm(ccm_path)`。⇒ 9/4 报告评的就是**现行生产系数**。

**第三方独立复核（同向）**：`.artifacts/ev_stress_experiment.md:13`（R18，5 臂 ×270 渲染）「RP-CCM B 轨 6.19~6.77」vs「A 轨 5.51~5.77」；`:17`「B−A 在所有臂一致为正（**+0.73~+1.45**），B 优于 A 的照片数 **19~21/54** 恒定」；`:54-55` 明确「与 2026-09-04 报告 B−A=+1.147 方向/量级一致」。

**为什么翻转**（`.artifacts/calib_run.md:142` 自己解释了）：「G-5 的 B 轨用**中性语境系数**而非联合 rp*；主优化的 rp* 在端到端语境（表 ev 进链）与 warmth/neutral **联合拟合**，拆到中性语境单独评估会**语境错配**（本轮全语料实测：联合 rp* 在 A 轨基座上 median **5.98→6.86 反而劣化**）」。⇒ 8/28 的 −7.7% 用的是**阶段一中性弱监督拟合**的旧系数；9/4 入库的是**联合优化**的新系数，在中性语境评估口径下反而劣化。

**门槛线**（`docs/OWN_PIPELINE_STAGE2_DESIGN.md:38` 文档化的转默认条件）：
> RP-CCM 转默认须**同时**满足 —— median 改善 **≥15%**、无单照片 median 回归 >1 JND、总体 p95 不劣化、**≥2 相机**复验。

现行系数的实测：median **+19.3%（方向相反）**、p95 **+4.9%（劣化）**、54 张中 32 张回归（含 DSC_5283/5284 的 +2.887/+2.785，**>1 JND**）、仅 1 台相机语料。**4 项门槛线 0 项通过**。
（对比：`.artifacts/stage2_adopt_eval_A.md:221` / `stage2_qa_verdict.md:90` 记载的是 **B 轨用 `calib_out/rp_ccm_by_group.json` 的 `rp_global_neutral`** 时的 3/4 通过 —— 那是**另一套系数**，不在生产加载链上。）

### 6.2 运行时接入点（若选「切换」）

| 项 | 位置 | 事实 |
|---|---|---|
| 设计口径 | `docs/OWN_PIPELINE_STAGE1_DESIGN.md:124-127`、`src/pixo/render/core/rp_ccm.py:28`（docstring） | `apply_rp_ccm(linear_rgb, coeff)` 作用于「**DCP 渲染后的线性 sRGB**」，出口 float32 值域 [0,1]（对齐 `linear_prophoto_to_srgb`） |
| 现行 DCP 出口 | `src/pixo/render/pipeline/base.py:96-107` `render_dcp_linear()`：`cam_wb_to_prophoto → hue_sat_map → exposure_ramp(baseline) → look_table → rgb_tone(table) → linear_prophoto_to_srgb(pp)`（`:107`） | **这是离线 `render_dcp_linear` 的出口**（非在线 Stage 链） |
| 在线 Stage 链的对应位 | `presets.py:15-17 DEFAULT_STAGES = [exposure, whitebalance, compose, huesat, tone, dehaze, clarity, colorcal, ...]` | 在线链里 DCP 在 `whitebalance`（`wb.py` 用 `cam_to_prophoto` / `matrix_apply3`）+ `huesat`；**「线性 sRGB」在在线链里没有显式落点** —— 真正的插入面是 `whitebalance` 出口（线性相机域→ProPhoto）或新增 Stage |
| gate 侧既有建议 | `.artifacts/gate_calibration_coverage.md:38` | 「建议形态：**stylize 前线性域并联点**直调 `load_rp_ccm(正式表)` + `apply_rp_ccm`，场景取 rp 特征敏感的色块图」 |
| 现状调用点 | `docs/ARCH_REVIEW2_DISPOSITION.md:51` + `.artifacts/gate_calibration_coverage.md:5,36-38` | `apply_rp_ccm`/`load_rp_ccm` 在 `src/pixo/render` **零运行时调用点**；仅 `scripts/calib/diff_core.py` 代理侧 |

> **[推理]** 在线插入点必须在 design 里**显式定死**（三个候选：① `whitebalance` Stage 出口；② 新增 `rpccm` Stage，order 介于 `whitebalance(20)` 与 `huesat(25)` 之间；③ `stylize` 前线性域）。选 ② 最干净（不改既有 Stage 数值语义、可 `wants()` 门控、可默认关）。

### 6.3 切换的回归风险面

| 面 | 证据 | 风险 |
|---|---|---|
| 金样本 | `tests/regression/goldens/gate_cases.py:25-42 FEATURES`（21 features）**无任何 rp_ccm case**；`.artifacts/gate_calibration_coverage.md:5,36-38` 明确「rp_ccm 因运行时未接线（src 零调用点）**无从触达**，按任务预案如实记录、留待接线后补 case」 | 接线后**必须先补 1 个 gate case**（否则金样本对新链零敏感 = 门禁空洞）；接线本身**不会**让现有 21 features 漂移（它们不走 rp 路径） |
| 键位/键宇宙 | RP-CCM 不产测量指标（纯像素变换）⇒ **不动 `METRIC_KEYS`** | 无风险 |
| 真实像素语义 | `rp_ccm.py:169`+`164` docstring：恒等系数走**逐位 no-op 快路径**；`tests/unit/test_rp_ccm.py:136-142` 曝光不变性 k∈{0.25,0.5,2,4} atol=1e-12 | 接线后若默认关（恒等/不注册）⇒ 既有导出像素**逐位不变** |
| 标定表敏感面 | `.artifacts/stage2_adopt_report.md:65`「金样本对四个标定表**零敏感**」；`gate_calibration_coverage.md:10`「缺口已关闭（warmth + exposure 两个运行时路径）」 | rp 是第 3 个待补的标定敏感 case |
| 语料 | 只有 **1 台相机**（nikon_z5_2）语料（`.artifacts/stage2_qa_verdict.md:90`、`rp_ccm_by_group.json` 顶层 `schema/note/created`） | 门槛线第 4 项（≥2 相机）**物理不可满足**（本机无第二台相机语料） |

### 6.4 「切换」vs「否决」两条路的代价对比

| 维度 | 路 A：切换（接入运行时） | 路 B：显式否决 + 登记结论 |
|---|---|---|
| 数据支撑 | **反对**：现行系数 median **+19.3%**、p95 +4.9%、32/54 回归、0/4 门槛线；R18 270 渲染独立复核同向 | **支持**：两份报告 + 1 份压力实验一致指向「现行（入库）系数在中性评估口径下劣化」；`.artifacts/stage1_qa_verdict.md:61`/`stage2_qa_verdict.md:102-103` 两轮 QA 都建议不切默认 |
| 需要的前置 | ① 重新推导/安装**中性语境**系数（`calib_out/rp_ccm_by_group.json` 的 `rp_global_neutral`：`.artifacts/stage2_adopt_eval_A.md:221` 报 4.777 vs 现行同基座 5.732）② 换表后重跑 `eval_rp_ccm_ab` 验证 4 项门槛 ③ 补 ≥2 相机语料（**本机不可得**）④ 定死在线插入点 + 新增 Stage ⑤ 补 1 个 gate case ⑥ 全量回归 + 金样本复核 | ① 在 `docs/tech_debt.md` #12 附近（或新增条目）+ `docs/changelog.md` 登记结论（引用两份报告 mtime + commit 3fbe56d）② 把「CR-12 引用的 −7.7% 已失效」写进 `R21_CHANGE_REQUESTS.md`/DELIVERY-R22 的更正节 ③ 保留 `calib_out/rp_ccm_by_group.json` 作为**阶段三分簇门控**输入（`stage2_qa_verdict.md:103` 已如此定位） |
| 工作量 | ≥1 个完整战役（重新拟合 + 换表 + 新 Stage + native 可选 + 门禁 + QA），且**没有可用语料满足复验门槛** | 文档级（0.5~1 人时）+ 可选 1 个「防止未来误开」的守卫测试 |
| 风险 | 若强行切换：**色彩保真倒退 19.3% median** 且无第二相机复验；换表会同时改动 `configs/color/`（发布面） | 无代码风险；唯一「代价」= 承认阶段二 rp 联合优化在中性口径下不达门槛 |
| **建议** | ❌ 本轮**不做** | ✅ **本轮做**：显式否决 + 更正 CR-12 证据 + 登记「待阶段三分簇门控 / ≥2 相机语料」的触发条件 |

> **给队长的措辞建议**：CR-12 的「二选一」应选 B，且理由不是「门槛线未达标」这么轻，而是 **「CR-12 所引用的 −7.7% 证据已被 2026-09-04 同脚本复评推翻为 +19.3%」**。这属于**必须更正的既有文档错误**（与 R21 §0 更正「阶段二新表待入库」同类），建议单独在 `docs/R21_CHANGE_REQUESTS.md` 加一节勘误。

---

## 7. skin 一致性（F08 / CR-13）—— **已交付，勿重复造**

### 7.1 `core/skin.py` 常数 ↔ `configs/color/skin_oklab.json` 字段对应关系（逐位实测）

| 源码常数（`src/pixo/render/core/skin.py:188-196`） | 值 | JSON 字段（`configs/color/skin_oklab.json`） | 值 | 一致 |
|---|---|---|---|---|
| `SKIN_OKLAB_A` | 0.015127 | `constants.SKIN_OKLAB_A`（= `new_ellipse_fit.center_a`） | 0.015127 | ✅ |
| `SKIN_OKLAB_B` | 0.061263 | `constants.SKIN_OKLAB_B`（= `new_ellipse_fit.center_b`） | 0.061263 | ✅ |
| `SKIN_OKLAB_MAJOR` | 0.049594 | `constants.SKIN_OKLAB_MAJOR`（= `new_ellipse_fit.major`） | 0.049594 | ✅ |
| `SKIN_OKLAB_MINOR` | 0.047463 | `constants.SKIN_OKLAB_MINOR`（= `new_ellipse_fit.minor`） | 0.047463 | ✅ |
| `SKIN_OKLAB_ANGLE` | 0.196323 (rad) | `constants.SKIN_OKLAB_ANGLE`；`new_ellipse_fit.angle_deg` = 11.2485 | 0.196323 | ✅（`degrees(0.196323)=11.2485`） |
| `SKIN_OKLAB_SOFT_BAND` | 0.31 | `constants.SKIN_OKLAB_SOFT_BAND` | 0.31 | ✅ |

（另有**另一族**常数 `SKIN_LAB_A/B/MAJOR/MINOR/ANGLE`（`skin.py:31-35`，值 140/150/22/14/0.65）对应 JSON 的 `baseline_ellipse.*` —— 那是 **cv2 u8 Lab 域**旧椭圆，与 OKLab 椭圆是两套域，勿混。）

**native 侧已无副本**（tech_debt #18 R17 清偿）：`colorcal.cpp` 的 constexpr 副本已删除，改为 ABI 结构体 `PixoRenderSkinOklabEllipse`（7 常数）第 7 参传入；Python 单源流入 `_native/__init__.py:1004-1026 skin_oklab_ellipse()`；门控 `_native/__init__.py:1049`（需 DLL ≥1.6.0）。**故 CR-13 的「防双源失同步」面现在只剩「`core/skin.py` ↔ JSON」一支。**

### 7.2 现有一致性测试**已经存在**（避免重复造）

| 测试 | 位置 | 断言 |
|---|---|---|
| `test_skin_oklab_constants_bitwise_locked_to_fit_json` | `tests/unit/test_skin_oklab.py:354-383` | JSON 路径常量 `_SKIN_OKLAB_JSON = parents[2]/"configs/color/skin_oklab.json"`（`:350-351`）；校验 `schema == "pixo.skin_oklab.v1"`；六常数 **IEEE754 逐位 `==`**（非 approx）；键集相等；失败消息含 `float.hex()` 位型证据 |
| `test_skin_oklab_json_angle_deg_consistent_with_constant` | `tests/unit/test_skin_oklab.py:386-396` | `degrees(SKIN_OKLAB_ANGLE)` vs `new_ellipse_fit.angle_deg`，容差 1e-3° |

⇒ **CR-13 的「增加一致性单测」= 已完成**。

### 7.3 gate case 机制如何加 1 个 case（+ **已有 skin case**）

机制（`tests/regression/goldens/gate_cases.py`）：
1. 在 `FEATURES` 元组（`:25-42`）追加 case 名；
2. 在 `build_case(feature)` 的分派链（`:255+` 一系列 `if feature == ...`）加分支，返回**确定性输入/输出数组**（禁随机：现有 case 用固定种子或纯构造）；
3. 生成器与校验测试**共享本模块**（`:1` docstring：「生成器与校验测试共享，保证输入与计算口径一致」）；
4. 金样本 baseline 由 `render/tools/gate_golden.py` 生成，`pytest tests/regression/test_gate_golden.py` 校验；`--check` 用于零漂移复验。

**已存在的 skin 相关 case**（`gate_cases.py:28` + `:255-269`）：

| case | 构造 | 作用 |
|---|---|---|
| `skin` | `skin_mask(_skin_patch())`（`:255-256`） | HSV/u8 Lab 椭圆掩码 |
| `skin_oklch` | `skin_mask_oklab(_skin_patch()/255.0)`（`:257-263`，注释「终审 G-1」） | **OKLab 椭圆几何锁定**（经典肤色锚，核内 d≈0.85） |
| `skin_oklch_softband` | `skin_mask_oklab(_skin_softband_probe())`（`:264-269`） | **软边带/半轴敏感性探针**（r12 观察窗清偿；`:79-116` 详述两射线 ×32 步色度扫描，实测软带掩码梯度 0.94→0.01） |

⇒ **CR-13 的「1 个金样本 case」= 已完成（且有 2 个，互补覆盖核内与软带）**。

> **F08 的建议处置**：本轮**不新增任何 F08 代码**；改为①复跑 `pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q` 留证；②在 `docs/tech_debt.md` / `DELIVERY-R22.md` 登记「CR-13 已于 R17+（gate case r12/G-1）交付，本轮仅复核」。若队长仍要「新增」，唯一有新价值的候选是**per-group 椭圆门控**（JSON `per_group_fit` 有 6 组，中心漂移 a∈[-0.006, 0.041]）—— 但那是**新能力**（阶段三），不在 CR-13 范围。

---

## 8. #17 几何（F09）—— free 模式像素矩形跨分辨率

### 8.1 全链路（用户参数 → compose → preview/export → 掩码适配）

```
用户参数 (PUT /api/sessions/{id}/params)
  └ render/web/session.py:175-180 update_params  ← 无校验, 原样 _deep_merge
      └ session.py:451-467 canonical_params() → build_default_pipeline(params=...)
          └ render/modules/compose.py:268-277 ComputeStage.process
              └ compose.py:63-86 compute_crop_rect(mode="free")
                   x0=round(x); cw=round(width); clip 到本画布 (h,w)  ← ★失配根源: 单位=当前画布像素
```

**adopt_crop（AI 构图建议回写）**：`pipeline/loop.py:1612-1652`
- `:1619-1621 _full_canvas_size(backend, preview_w, preview_h)` → `:1054-1063` 取后端 `full_size()`（真 RAW 全分辨率，如 6048×4032），未知才退回预览尺寸；
- `:1622-1624 rect_norm_to_px(crop_suggestion["rect"], fw, fh)` → `:278-289` 归一化→**全幅像素**；
- `:1633-1640 params["compose"] = {mode:"free", x:x0, y:y0, width:x1-x0, height:y1-y0}` → **写入的是全幅像素**。

**后果**：preview 渲染（`preview_long_edge=512`，`runtime.py:948`）用**同一像素值**在 512 画布上执行 `compute_crop_rect` ⇒ 相对取景完全不同（tech_debt #17 的 10% 画幅宽错位）。

**掩码适配**：`render/pipeline/region_masks.py:64-118 adapt_region_masks`
- `:36-62 _post_compose_shape()` **用 `compute_crop_rect` 预测 post-compose 帧**（与 `ComposeStage.process` 同源，`:41-42` 自证）—— 所以 shape 预测**是**跟随的（两线裁出同尺寸窗时 shape 相同）；
- `:107-112` 只做 `cv2.resize(arr, (tw,th), INTER_AREA/…)` —— **shape 对齐，无坐标重映射** ⇒ 掩码坐标语义不变，落点错位。

**缓存时间性防线**（`loop.py:505-519 _compose_fingerprint` + `:1025-1052 _sync_region_masks`）：compose 参数指纹变化（含 adopt_crop）即清空 `_region_masks_soft` + warn-once（`:815-817`, `:1044-1045`），"不作为"优于"错作为"。注入点 3 处：`:990-996`（preview 线）、`:1284-1286`、`:1692-1694`（FINAL_QC/导出线）。

### 8.2 归一化的候选基准（哪个 tier 作参考）

| 候选 | 含义 | 评价 |
|---|---|---|
| **B1: 全幅（full canvas / backend.full_size()）** | `x/y/width/height` 解释为**全幅归一化**；`compute_crop_rect` 内部 `*w, *h` 到当前画布 | ✅ **推荐**。adopt_crop 已按全幅算（`loop.py:1619-1624`），只需把 `rect_norm_to_px` 后的四个 px 值**除以 fw/fh**再写进 params（或换成 `rect_norm_to_px` 的归一化版本）。用户/前端语义也直观（「裁左半边」= x∈[0,0.5]）；导出与 preview 天然一致 |
| B2: preview tier 作参考 | 以 `preview_long_edge` 为基准 | ❌ 依赖运行时 tier；导出与 preview 仍不一致（只是把错位搬到导出侧）；`preview_long_edge` 是可变参数（`runtime.py:948`） |
| B3: 不改 compose，改适配器做坐标重映射 | `region_masks` 按裁剪窗差重映射掩码坐标 | ⚠️ 只解掩码错位的**表象**，不解决「同参数跨分辨率取景不同」这一**用户可感知**的主问题（tech_debt #17 第一句：「同一参数在不同渲染分辨率下相对裁剪窗不同」）。可作为**补充**而非主方案 |

**`rect_norm_to_px` / `adopt_crop` 与 `region_masks` 的耦合**：
- `rect_norm_to_px`（`loop.py:278-289`）**只被 adopt_crop 调用**（grep 命中 2 处：定义 + `:1622`）；其对称函数 `rect_px_to_norm`（`:265-276`）**当前零调用**（grep 仅定义处）—— **[推测]** 它可能正是为 #17 预留的迁移工具。
- `region_masks._post_compose_shape`（`:36-62`）→ `compute_crop_rect`：**归一化后自动跟随**（它本来就是「用同一参数预测 shape」），无需额外改动；**这是「改 compose 语义即可，掩码层零改动」的关键证据**。
- 掩码**坐标语义**（哪个像素对应哪块场景）依赖 `_post_compose_shape` 只算 shape、不算偏移 ⇒ 归一化后两线 shape 与相对偏移都一致，错位消失。

### 8.3 存量卡与用户参数里的 px 矩形有多少处（实测：≈0）

| 面 | 命令 | 结果 |
|---|---|---|
| `configs/**/*.json` 含 `"compose"` 键 | `Get-ChildItem configs -Recurse -Include *.json \| Select-String '"compose"'` | **0 命中** |
| `resources/**/*.json` 含 `"compose"` | 同上 | **0 命中** |
| 全仓（排除 node_modules/.git/build）含 `"mode": "free"` 的持久化 JSON | `Get-ChildItem . -Recurse -Include *.json` + 过滤 | **0 命中** |
| `docs/` 内示例 | 同上 | **1 处**：`docs/架构设计文档.md:384-393`（且键名是 legacy `"crop"` 不是 `compose`，值为 `x:100,y:80,w:3000,h:2000`） |
| 前端 crop UI | `frontend/src` grep `crop\|mode.*free` | **无**（只有 SVG 的 `width/height` 属性与 CSS） |
| 代码内写 free px 的位置 | grep `"mode": "free"` in `src/` | **2 处**：`compose.py:222`（`default_params`，全 0 + `mode=free` ⇒ `compute_crop_rect` 在 `width<=0` 时返回全幅，`compose.py:76-77`，**语义中性**）、`loop.py:1635`（adopt_crop） |
| 测试硬编码 free px | `tests/**`：`test_gate_compose.py:81,92,118,135,149`、`test_region_masks_channel.py:142,651`、`test_decide_region_wiring.py:488,514`、`test_loop_e2e.py:69`、`test_compose_autolevel.py:109`、`test_loop_replay.py:48` | 需**逐个按新语义重写**（`test_gate_compose.py` 5 处用的是 64×64 小图 + px 值，归一化后会变；`test_loop_e2e.py:69` 是 `compose_params` 入参） |

> **结论**：**没有存量卡、没有持久化用户参数需要迁移**（"存量卡与参数迁移" 的迁移面 ≈ 空集 + 1 处 docs 示例 + 约 10 处测试）。这大幅降低 F09 的风险与工作量——**brief 里担心的迁移成本实测不存在**。

### 8.4 现钉死用例的断言内容与「有意翻转」的正确写法

`tests/unit/test_region_masks_channel.py:637-672 test_free_px_rect_cross_resolution_geometry_mismatch_recorded`：

```python
compose = {"mode":"free","x":50.0,"y":0.0,"width":50.0,"height":50.0}
line_a = adapt_region_masks({"sky": _top_band_mask(50,100)}, (50,100), compose)   # 100×50 帧
line_b = adapt_region_masks({"sky": _top_band_mask(100,200)}, (100,200), compose) # 200×100 帧
assert line_a["sky"].shape == line_b["sky"].shape == (50,50)        # 现状: 同 px-rect 裁出同尺寸窗
assert np.array_equal(line_a["sky"], line_b["sky"])                 # ★现状钉死: 掩码逐位相同 = 失配可观测面
ra = compute_crop_rect(50,100,"free",x=50.0,y=0.0,width=50.0,height=50.0)   # → x0=50, cw=50
rb = compute_crop_rect(100,200,"free",x=50.0,y=0.0,width=50.0,height=50.0)  # → x0=50, cw=50
assert abs(ra[0]/100.0 - 0.5) < 1e-6 and abs(rb[0]/200.0 - 0.25) < 1e-6     # ★现状: 相对窗 50% vs 25%
assert rela != relb
```

**该用例的 docstring 已写明翻转契约**（`:646-647`）：「未来 compose px→相对坐标归一化或适配器坐标重映射清偿本债时，本用例应**有意翻转重写**（断言两线掩码不同/几何一致），不得静默通过」。

**「有意翻转」的正确写法（建议，B1 基准）**：
```python
# 归一化后: x=50 在 100 宽帧 = 0.5; 在 200 宽帧 = ? -> 参数语义改为归一化, 需用同一归一化参数
compose = {"mode": "free", "x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0}   # 归一化
# ① 相对裁剪窗一致（这是清偿的正面断言）
rel = [compute_crop_rect(h, w, "free", x=0.5, y=0.0, width=0.5, height=1.0)[0] / w
       for (h, w) in ((50, 100), (100, 200))]
assert rel == [0.5, 0.5]                                    # ← 翻转点 1: 由「50% vs 25%」变「两线同」
# ② 掩码适配按相对窗重映射 ⇒ 两线掩码在**相对坐标系**下一致, 但**像素坐标**(shape 不同时)不再逐位相同
#    若 shape 仍相同(两线相对窗一致) -> 逐位相同仍是正确结果, 断言应改为「相对取景一致」
```
> ⚠️ **写法要点**：翻转后不能简单把 `assert np.array_equal(...)` 改成 `assert not equal`（那是另一侧的错误钉死）。正确的不变量是 **「相对裁剪窗一致」**（`compute_crop_rect(...)[0]/w` 两线相等），掩码逐位相等只在两线 shape 相同时才成立——`brief` 完成标准 3 的措辞「同一归一化参数在不同 tier 下相对裁剪窗一致」正是这条。design 应把该断言写成**显式的相对几何不变量**。

### 8.5 风险面（会不会改变既有导出取景 → 金样本是否必然重生成）

| 风险 | 证据 | 判定 |
|---|---|---|
| 金样本必然重生成？ | `gate_cases.py:25-42 FEATURES` 21 个 case，grep `compose` 在 `gate_cases.py` = **0 命中** | ❌ **不必然**。金样本无 compose case ⇒ 归一化改动**不会**让 gate 漂移（但这也说明金样本对 compose 零覆盖 = 建议补 1 个 case） |
| 既有导出取景改变？ | 生产路：`default_params` 是 `mode=free, width=0` → `compute_crop_rect` 走 `width<=0 → (0,0,w,h)` 全幅（`compose.py:76-77`） | ✅ **默认参数下逐位不变**（全幅归一化 = 全幅）。仅当用户显式传 px 或 adopt_crop 生效时行为改变 |
| adopt_crop 生产影响 | `loop.py:1612-1651`；R21 生产装配（`runtime.py:943-957`）**未传** `crop_suggest`（缺省 `False`，`loop.py:736`） | ✅ 生产默认**不触发** adopt_crop ⇒ 归一化后默认路径零变化 |
| 前端 | 无 crop UI（§8.3） | ✅ 无前端改动 |
| session 参数兼容 | `render/web/session.py:175-180` 无 schema 校验 ⇒ 旧 px 参数**不会报错**，但会被当归一化解释（若用户/客户端真有 px 参数会**静默改变取景**） | ⚠️ **需要 legacy 开关或迁移**（brief 已提「含 legacy 开关」）——建议：`compose.coord` 显式 `"norm"|"px"`（缺省 `norm`；`px` 走旧逻辑 + 一条 deprecated 告警） |
| 测试面 | §8.3 列的 ~10 处测试 | ⚠️ 必然要改（含翻转那个钉死用例），属预计内工作量 |
| 掩码层 | `region_masks._post_compose_shape` 同源调 `compute_crop_rect`（`region_masks.py:36-62`） | ✅ 自动跟随，**零改动**（这是本方案最省的一点） |

---

## 9. 台账（F10 / CR-15）

### 9.1 `model_licenses.json` vs `vision_models.json` 冲突项逐条现状

**关键事实**：两个台账**位置不同**——`model_licenses.json` 在**仓库根**（本轮 `fast_locate` 实测：`K:\work\project\pixo\model_licenses.json`，3.4 KB，mtime 2026-09-06 17:23）；`vision_models.json` 在 `src/pixo/manifests/vision_models.json`（1,227 B，`updated: 2026-09-07`，**只有 2 条**）。

| # | 冲突项 | `model_licenses.json`（根，6 条） | `src/pixo/manifests/vision_models.json`（2 条） | 是否有测试钉死 |
|---|---|---|---|---|
| C1 | **aesthetic_scorer.pt** | `license: "MIT"`、`publishable: true`、`files: ["resources/models/aesthetic/aesthetic_scorer.pt"]`、`usage/status: redistribution_allowed_with_license_notice`（`model_licenses.json:5-15`） | `license: "**需核验**（来源 rsinema/aesthetic-scorer）"`、`publishable: **false**`、`path_or_source: "**$GUANLAN_ROOT**/models/aesthetic_scorer.pt"`、`pixo_status: adapter_in_pixo_vision_aesthetic`、notes「发布前需确认模型许可」（`vision_models.json:6-17`） | **无**。`tests/unit/test_tech_debt_invariants.py:91-101` 只校验 `model_licenses.json` 里 `path/local_path/file` 三键的存在性 → **`vision_models.json` 完全未覆盖**，其 `$GUANLAN_ROOT` 陈旧路径**不会被任何测试抓到** |
| C2 | **segformer 自相矛盾** | `publishable: false` 但 `usage: redistribution_allowed_with_license_notice` + `status: redistribution_allowed_with_license_notice`（`model_licenses.json:47-55`） | 未登记 | **无测试**（tech_debt #3 自陈「segformer 条目 publishable/status 自相矛盾同挂待核验」） |
| C3 | **条目数不一致** | 6 条（aesthetic / clip / uniface / rfdetr / segformer / sapiens） | **2 条**（aesthetic / clip）——uniface/rfdetr/segformer/sapiens **缺登记** | **无测试** |
| C4 | sapiens 许可措辞 | `"CC-BY-NC-4.0 (Sapiens2 License 口径)"`（`:59`） | 未登记 | `THIRD_PARTY_NOTICES.md:104` 记为「HF 页 tag **CC-BY-NC-4.0**；论文自述 **CC BY-NC-SA 4.0**，SA 之差——取 HF tag 并列注记」→ **三处措辞不完全一致** |
| C5 | uniface / rfdetr | `internal_development_only` / `Apache-2.0`（`:27-45`）与 NOTICES §3 M3/M4 一致 | 未登记 | — |

**测试覆盖现状（实测）**：`tests/unit/test_tech_debt_invariants.py:91-101` 只读 `_REPO_ROOT/model_licenses.json`，只查 `("path","local_path","file")` 三键；**当前 6 条都用 `files`（数组）而非这三个键** ⇒ 这个"防悬空"断言目前**实际是空转**（0 个被检查的路径）。**[发现，非推测，源码可验]**
→ F10 #3 的最小加固 = 把该测试扩展为覆盖 `files[]` 数组 + 覆盖 `src/pixo/manifests/vision_models.json`。

**DCP×6 再分发事实**：`THIRD_PARTY_NOTICES.md:161`「DCP 相机配置 ×6（`resources/dcp/`）**存疑（警示二）**：RawLab 社区来源（**推测，置信度中**）再分发条款未核验；被 pyproject data-files 打包将随 wheel 分发」；`:162` HSM→OKLCh 点云 1 个「血缘继承上述 DCP → 同挂发布前核验」；`:232` 存疑速查表「DCP ×6 再分发条款 | 未核验（RawLab 社区，推测置信度中）| 发布前核验；wheel 打包事实并陈」。`resources/dcp/manifest.json` 本轮未逐字节核验（**[推测]** 其存在与 6 项计数应从 manifest 内容确认，属 F10 执行时的一次读取）。

### 9.2 #7 感知门禁可复用的现有资产

| 资产 | 位置（实测存在） | 可复用面 |
|---|---|---|
| `scripts/ab_vs_camera_thumb.py` | 3,057 B（存在） | #7 点名的 ΔE/裁切预算工具 |
| `scripts/eval_rp_ccm_ab.py` | `:33 from pixo.pipeline.perceptual import delta_e_2000, linear_srgb_to_lab`；`:38-56` Sharma 2005 文献对 `--selftest` | ΔE2000 口径（**已抽为 src 单源**） |
| `src/pixo/pipeline/perceptual.py` | `:32 JND_DELTA_E = 2.3`；`:41 gamma_srgb_to_linear` / `:48 linear_srgb_to_lab` / `:58 delta_e_2000` / `:113 delta_e_median` / `:129 JndConvergenceTracker` | **src 内单源 ΔE2000 + JND 常数**（#7 门禁可直接消费，不必再抽） |
| `scripts/run_ab_regression.py` | `docs/ARCH_REVIEW2_DISPOSITION.md:105` 列为「全语料分层 ~40 张三层验收」 | 语料级回归框架 |
| gate 机制 | `tests/regression/goldens/gate_cases.py`（21 features）+ `render/tools/gate_golden.py`（`--check`）+ `tests/regression/test_gate_golden.py` | 门禁骨架；#7 的「ΔE/美学阈值纳入 gate」只需加 case |
| 分布标定档 | `docs/metrics/proxy_distribution.md`、`docs/metrics/scorer_distribution.md`（t98）、`docs/metrics/ab_highlight_stress.md` | 阈值锚定分位来源 |
| 待补缺口 | `.artifacts/gate_calibration_coverage.md:90`「rp_ccm 运行时接线后补第三个标定 case」 | #7 与 F07 的交集 |

### 9.3 #10 重复编号位置

`docs/tech_debt.md` 中 **`10.` 出现两次**（实测 grep `^\d+\.\s`）：
- `:129` `10. **跨包知识边须同组发布**`
- `:134` `10. **色彩规则执行位占位**`
后续编号连续到 `:333` 的 `21.`（`20.` 在 `:325`）。⇒ 重编号需把 `:134` 起的后续项整体 +1（`13.` 下有 13.1~13.4 子项，`:161-190`；`:161` 的 `13.` 引用了 `docs/OWN_PIPELINE_REVIEW_DISPOSITION.md ③④⑤⑧` —— 重编号**不要动这些外部引用编号**，只动列表序号）。**另需同步**：`qa-report-r21.md:187-188` 已记录「编号口径队长域，R21 待登记 #20/#21」，R22 若再插入新条目须一并续排。

### 9.4 #12 公式守卫前置条件现状（**已满足，tech_debt 表述陈旧**）

| 项 | 位置 | 事实 |
|---|---|---|
| tech_debt 现行表述 | `docs/tech_debt.md:24`「条目 12（公式守卫日落）：触发前置（**原生 AND/between 落地**）未到」；`:156-158`「引擎原生 AND/between 落地后，新规则改用原生 condition，存量公式守卫规则（clarity_flat 等）择机迁移」 | 声称前置未到 |
| **原生 AND** | `src/pixo/decide/engine.py:222`（`for sub in cond.get("all") or []`，条件校验）+ `:410`（`subs = condition.get("all")`，求值）→ **已落地** | 前置 ①**已满足** |
| **原生 between** | `src/pixo/decide/engine.py:384-389`（`elif op == "between": lo<=metric<=hi`）| 前置 ②**已满足** |
| 迁移先例 | `src/pixo/decide/rules/tone_clarity_rules.yaml:36-39` 注释：「护栏④日落条款**首例**（t60）：原 formula 带通守卫迁原生 all 条件」，并保留旧式注释 `formula: "0.04 if (haze_proxy < 0.22 and tonal_range <= 0.46) else 0.0"` | **已迁移 1 条**（clarity_flat 类） |
| 剩余 formula | `tone_clarity_rules.yaml:29/54/66/79`（`"0.06"`/`"0.04"`/`"0.05"`/`"-0.08"` 纯常数，**非守卫**）；`region_rules.yaml:56`（`-0.5*(sky_luminance/150.0)`）、`:86`（`0.2*((70-plant_luminance)/70.0)`）；`exposure_rule_001.yaml:9`（`2.2*log2(target/current)`——**这是真公式，需 `targets`**）；`crop_suggest_rule_003.yaml:10`（`"1"`）；`highlight_protect_rule_002.yaml:10`（`"-0.15"`） | 真正「带通守卫」型 formula 只剩注释里的历史形态；剩余 formula 多为**标量/线性增益**，不属 #12 的迁移对象 |
| 引擎侧守卫 | `engine.py:151 _enforce_formula_lint` / `:186-242`（`:191` 白名单 = `_FORMULA_FUNCS ∪ 运行时变量 ∪ 已知指标键`；`:242`「白名单外的名字直接 DecideError」） | 迁移的**安全保障已就位**（改 condition 会被 lint 拦住笔误） |

> **F10 #12 的建议处置**：结论从「前置未到、维持」改为 **「前置已满足（`engine.py:222`/`:384`），首例已迁移（`tone_clarity_rules.yaml:36`），剩余 formula 经逐条复核**不属带通守卫类**（纯标量/线性增益 + 需 targets 的 exposure 公式）⇒ 本轮判 **日落条款关闭**」**。这条是 tech_debt 中的**事实陈旧**，与 CR-12 同类，建议一并写进 R22 台账更正节。

---

## 10. 风险清单

| # | 风险 | 证据 | 影响面 | 规避 |
|---|---|---|---|---|
| R1 | **CR-12 引用证据已失效**（−7.7% → +19.3%） | `.artifacts/eval_rp_ccm_ab_..._20260904_235522.md:16,77`；commit `3fbe56d`；`ev_stress_experiment.md:13-17,54-55` | 若按 CR-12 原文「二选一」轻率选 A（切换），生产色彩保真倒退 19.3% median | 本轮选 B（否决）；**在 `R21_CHANGE_REQUESTS.md` 加勘误节**；`design-r22.md` 必须引用 9/4 报告而非 8/28 |
| R2 | **噪声指标强分辨率依赖 + 排序非单调** | §2.3 实测表（512 tier 下 ISO12800 noise_ratio 0.284 < ISO1600 0.668） | CR-06 阈值锚定与 CR-07 A/B 验收**不可判定**；若在 512 tier 判 A/B，可能得出错误结论 | design 必须**钉死 tier**：① 门禁/A-B 统一在**导出全幅**测；② 若规则需在闭环 preview 内触发，阈值按 `preview_long_edge` 单独标定并写明 |
| R3 | **CR-09 口径无资产支撑**（0 个 `.cube`，25 卡是参数卡） | §5.2 实测（`*.cube` 0 命中、`lut_path` 0 命中、`fujifilm_astia.json:45 stylize:{}`）；`THIRD_PARTY_NOTICES.md:164`（LUT 目录指向**仓外** `guanlan/luts`） | 若照 CR-09 原文实现 `style.lut_path` 白名单 → **死代码 + 无法验收**（没有 LUT 可加载） | design 把 F04 定义为**卡参数注入**；`lut_path` 仅登记为未来扩展位；验收改为「带 `style_id` 的请求使渲染 params 变化 + trace 留痕」 |
| R4 | **写参数通路零校验** | `render/web/session.py:175-180`（`_deep_merge`，无白名单/无路径校验；全 `render/web/` grep 零命中） | 任何客户端可直传 `stylize.lut_path` 指向任意路径 ⇒ 越界读文件 | 机制层在 `core/lut.py:90 load_lut_path` 加统一路径栅栏（一处覆盖所有调用方），策略层在 `service/runtime.py:477` 做 `style_id` 白名单 |
| R5 | **`DenoiseStage` 不在 `DEFAULT_STAGES`** | `presets.py:15-17` 链序无 `denoise`；`reshape.py:113-134` 占位 | 若为 F02 把 `denoise` 加进 `DEFAULT_STAGES`，会改**所有**既有渲染链序 → `default_dispatch` / `card_portra_400` / `region_adjust` 3 个金样本 case 必然漂移 | 保持不入 `DEFAULT_STAGES`；`wants()` 门控 + 显式参数开启（默认关），与 brief「默认关」一致 |
| R6 | **F08 重复造轮子** | `tests/unit/test_skin_oklab.py:354/386` + `gate_cases.py:28`（`skin_oklch`/`skin_oklch_softband`） | 浪费一轮工作量，且可能造出与既有 case 重叠的冗余金样本 | design 把 F08 标为「复核 + 销账」；如需新增，唯一有价值方向是 per-group 椭圆门控（属阶段三新能力） |
| R7 | **`model_licenses.json` 防悬空测试空转** | `tests/unit/test_tech_debt_invariants.py:91-101` 只查 `path/local_path/file` 三键；根台账 6 条**都用 `files[]`** | 台账路径失同步**不会被任何测试抓到**（tech_debt #3 的「防复发断言」名存实亡） | F10 扩该测试覆盖 `files[]` + 覆盖 `src/pixo/manifests/vision_models.json` |
| R8 | **#17 旧 px 参数静默改义** | `render/web/session.py:175-180` 无校验；§8.3 实测无持久化 px 参数 | 若任何客户端/脚本仍在传 px（仓内无，仓外未知），归一化后会**静默改变取景** | `compose.coord: "norm"|"px"` 显式开关（缺省 `norm`；`px` 走旧逻辑 + deprecated 告警）；1 处 docs 示例（`架构设计文档.md:384-393`）同步更正 |
| R9 | **测试面必改** ~10 处（含翻转钉死用例） | §8.3 测试清单；`test_region_masks_channel.py:637-672` docstring 已写翻转契约 | 改漏一处 → 全量回归翻红或「静默变正确」 | design 单列「#17 测试改造清单」；翻转写法按 §8.4 的**相对几何不变量**而非简单取反 |
| R10 | **F03 告警洪泛 / 既有 caplog 断言翻红** | 132 处 `except Exception`；`refine.py` 6 处都在热路径 | 若全量改 `log.warning`，日志淹没 + 可能有测试断言 warning 计数 | 只改 13 条关键路径 + `warn_once` 节流（复用 `multi_router._warn_once` 范式）；**区分「设计性版本门拒绝」（如 `color_cal.py:418` 收 `_native` 的 `RuntimeError`）与「真异常」** |
| R11 | **F02 A/B 与 pytest 并发 OOM** | brief 约束（单次真 RAW ≈73s，串行；并发 `ArrayMemoryError`） | A/B 脚本若并行会崩 | A/B **复用 `rawpy.extract_thumb` 做语料筛选/快速预检**（§1.5，实测毫秒级），真渲染 A/B **严格串行**、单进程；A/B 输出落 `.artifacts/` 而非仓库根 |
| R12 | **[推测] 高 ISO 子集欠曝干扰 A/B** | §1.5 TOP12 含 `1/800s`/`1/640s`（DSC_5290-5295） | 曝光差会被误读为「降噪效果」 | A/B 记录每张 EV（脚本已有 gain 对齐口径，`eval_rp_ccm_ab.py:116-123` 范式），或按 EV 分桶报告 |

---

## 11. 遗留问题（范围外发现，交队长裁决）

1. **`build/lib/pixo/**` 旧副本漂移**（qa-report-r21 §7.2 #25）：本轮实测 `build/lib/pixo/render/core/skin.py:183-191` 仍是**旧常数**（`SKIN_OKLAB_A=0.01516`、`SOFT_BAND=0.25`），而 `src/pixo/render/core/skin.py:188-196` 是 R10 重拟合后的新值。⇒ ①若打包/导入误取 `build/lib` 会用错椭圆常数；②`build/lib/pixo/pipeline/loop.py` 仍是旧实体。**属 R21 已记债（#25）未清**，本轮 F08 复核时会撞见，建议一并清或明确排除。
2. **`rect_px_to_norm`（`loop.py:265-276`）当前零调用**——**[推测]** 它是为 #17 预留的迁移工具。design 若能确证，可直接复用（省一个函数）。
3. **`docs/架构设计文档.md:384-393`** 用 legacy 键名 `"crop"`（非 `compose`）描述 free 像素矩形，与现行 schema 不符，且 F09 归一化后语义也变。属文档陈旧，建议 F09 顺带更正。
4. **`docs/R21_CHANGE_REQUESTS.md:112`（CR-12 证据）与 `docs/tech_debt.md:24/:156-158`（#12 前置）两处事实陈旧**——建议 R22 统一加「勘误节」（与 R21 §0 同类手法），否则后续轮次会继续以错误前提派单。
5. **task-brief 与实测的口径差**：R22 brief 提到「`configs/styles/films` 25 个 JSON」——实测目录含 **27 个卡 JSON**（25 胶片 + 2 个 `oklch_demo_*`）；brief「131 处 `except Exception`」——**实测 132**。均为文档口径，非功能问题。
6. **`resources/dcp/manifest.json` 的 DCP×6 计数未逐项核验**（本轮只读 NOTICES/tech_debt 层陈述）。F10 #3 落地时需读一次该 manifest 做双源对齐。
7. **`configs/styles/films/README.md:44`** 有一行表格单元格内容重复/串行（`fujifilm_provia_400x` 行尾粘连了 `fujifilm_astia` 的描述文字），属文档瑕疵。
8. **`.artifacts/stage2_adopt_eval_A.md:221` 报「仅转 RP-CCM 路径门槛线 3/4 通过」用的是 `calib_out/rp_ccm_by_group.json` 的 `rp_global_neutral`**——该系数**不在**生产加载链（`configs/color/rp_ccm_by_group.json` 只存在于 `configs/color/calib_out/`，R21 §0 已判为陈旧快照目录）。若队长考虑「切换」，**必须先裁决这些系数的地位**（重拟合 → 换表 → 重跑门槛），这是一条独立战役，不是本轮能完成的。

---

## 12. 探针附录（命令 + 关键输出；脚本落 `%TEMP%`，仓库零改动）

### A1. 环境与算子可用性

```
python -c "import exifread,cv2,scipy,numpy,PIL; print(...)"
→ exifread 3.5.1 | cv2 5.0.0 | scipy 1.18.0 | numpy 2.5.1 | pillow 12.3.0
python -c "import cv2; print(hasattr(cv2,'ximgproc'), hasattr(cv2.ximgproc,'guidedFilter'), cv2.cuda.getCudaEnabledDeviceCount(), cv2.getNumThreads())"
→ True True 0 8
```

### A2. 高 ISO 语料 + 噪声指标 + 算子代价

脚本 `%TEMP%\r22_probe_iso.py`（EXIF 头解析 765 NEF）→ 关键输出见 §1.5（`ISO>=3200 = 32`）。
脚本 `%TEMP%\r22_probe_noise.py`（rawpy 内嵌缩略图 + 18 张指标 + 11 个算子计时）→ 关键输出见 §1.3/§1.4。

### A3. 指标层级与展平（F01 核心证据）

脚本 `%TEMP%\r22_probe_metrics.py`（`VisionMeasure().measure(img, {})` + `metrics_for_decide`）→ 完整输出见 §2.1。

### A4. 指标分辨率敏感性（F01/F02 核心风险）

脚本 `%TEMP%\r22_probe_scale.py`（同一相机 JPEG 缩放至 512/1024/2048/全幅）→ 完整输出见 §2.3。

### A5. native 版本与构建链

```
python -c "from pixo.render import _native; print(_native.available(), _native.version(), _native.load_error())"
→ True (1, 6, 0) None
Get-Item src/pixo/render/_native/pixo_render_native.dll → 620886 B
src/pixo/render/native/src/abi.cpp:24-26 → major=1, minor=6, patch=0
```

### A6. 关键路径 `except Exception` 分布

```
(Get-ChildItem src\pixo -Recurse -Include *.py | Select-String "except Exception" -SimpleMatch | Measure-Object).Count
→ 132
按文件 Top: loop.py 14 / meta/exif.py 10 / service/runtime.py 7 / modules/exposure.py 7 /
            modules/refine.py 6 / pipeline/batch.py 5 / render/api.py 5 / core/io.py 5
逐文件行号: 见 §4.2 表（含 render/core/lut3d.py:186, huesat.py:341/355, io.py:120/131/180/217/324,
            modules/color_cal.py:255/272/418/501, exposure.py:95/141/211/414/427/461/528,
            white_balance.py:155/397, tone_map.py:93/334, vision/aesthetic.py:78/120/217/256,
            segmenters/multi_router.py:82/191/239/259, segmenters/common.py:71/92/117,
            render/api.py:39/147/174/187/235, web/session.py:203/219/224/463）
```

### A7. 资产存在性（F04 关键证据）

```
Get-ChildItem -Recurse -Include *.cube,*.3dl,*.look,*.cub -File   → 0 命中
Get-ChildItem -Recurse -Directory | Where Name -match "lut"       → 0 命中
Get-ChildItem configs -Recurse -Include *.json | Select-String "lut_path" → 0 命中
Get-ChildItem configs/styles/films -File → 27 个 JSON（25 胶片卡 + 2 个 oklch_demo）+ README
```

### A8. 存量 free px 矩形搜索（F09 关键证据）

```
Get-ChildItem configs -Recurse -Include *.json | Select-String '"compose"' → 0 命中
Get-ChildItem resources -Recurse -Include *.json | Select-String '"compose"' → 0 命中
全仓 JSON（排除 node_modules/.git/build）| Select-String '"mode":\s*"free"' → 0 命中
docs/ 内 → 1 处：docs/架构设计文档.md:384-393（legacy 键名 "crop"）
src/ 内 '"mode": "free"' → 2 处：compose.py:222（default，全 0=中性）、loop.py:1635（adopt_crop）
frontend/src grep crop|mode.*free → 0 命中（无裁剪 UI）
```

### A9. RP-CCM 证据对拍

```
Get-Item configs/color/rp_ccm_nikon_z5_2.json → 3385 B, 2026-09-04 20:14:15
git log --oneline -- configs/color/rp_ccm_nikon_z5_2.json
→ 3fbe56d feat(calib): 新表入库正式 configs（阶段二终审路径1）+ cal_ev_weights 修复
git show 3fbe56d -- configs/color/rp_ccm_nikon_z5_2.json → matrix 3×6 逐值变更
两份报告：.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md（−7.7%, 45/54）
          .artifacts/eval_rp_ccm_ab_nikon_z5_2_20260904_235522.md（+19.3%, 22/54）
scripts/eval_rp_ccm_ab.py:73 --ccm-dir default="configs/color"（读生产位）
```

### A10. 台账结构

```
fast_locate "model_licenses.json" → K:\work\project\pixo\model_licenses.json (3.4 KB, 2026-09-06)
src/pixo/manifests/vision_models.json → 1227 B, 2 条（aesthetic 仍 "需核验" + $GUANLAN_ROOT 旧路径）
tests/unit/test_tech_debt_invariants.py:91-101 → 只查 path/local_path/file（当前台账用 files[]）
python -c "json.load(...skin_oklab.json)" → constants.* 六值与 core/skin.py:188-196 逐位一致
grep "^\d+\.\s" docs/tech_debt.md → "10." 出现两次（:129 跨包知识边 / :134 色彩规则执行位），至 :333 的 21.
grep between|all src/pixo/decide/engine.py → :222(all) :384(between) — 原生条件已落地
```

---

## 13. 给队长的一页速览（决策点）

| 决策点 | 建议 | 依据 |
|---|---|---|
| F04 口径：`lut_path` 白名单 vs 卡参数注入 | **改为卡参数注入**；`lut_path` 登记为未来扩展位 | §5.2（0 个 `.cube`）、§5.3（写参数零校验） |
| F07 二选一 | **选 B：显式否决 + 更正 CR-12 证据** | §6.1/§6.4（−7.7% → +19.3%，0/4 门槛线，且 ≥2 相机语料本机不可得） |
| F01/F02 指标口径 | **design 必须钉死测量 tier**；建议门禁/A-B 用导出全幅，规则阈值若用于闭环则按 tier 单独标定 | §2.3（排序非单调实测） |
| F02 执行位 | **`denoise` 不入 `DEFAULT_STAGES`**，`wants()` 门控 + 默认关 | R5（否则 3 个金样本 case 必然漂移） |
| F08 工作量 | **标为「复核销账」，不新增代码** | §7.2/§7.3（一致性单测 + 2 个 gate case 已在） |
| F09 迁移面 | **实测为空集**；工作量集中在「归一化语义 + ~10 处测试 + 1 个 legacy 开关」 | §8.3（0 处持久化 px 矩形） |
| F03 范围 | **只改 13 条关键路径**（区分版本门拒绝 vs 真异常），复用 `multi_router` 的 degraded/warn-once 范式 | §4.2/§4.4（R10） |
| F10 #12 | **日落条款关闭**（前置已满足 + 首例已迁移 + 剩余 formula 非守卫类） | §9.4（`engine.py:222/384`、`tone_clarity_rules.yaml:36`） |
| F10 #3 | 加固 `test_model_license_registry_paths_resolve`（现为空转）+ 处置 C1~C4 冲突 | §9.1（R7） |
