# streams/r17-hard-problems.md — super-dev 攻坚流 (r17)

> 椭圆常数参数化 —— tech_debt #18 清偿 (r10 立债: colorcal.cpp 硬编码
> 副本 vs core/skin.py 单源, "下次椭圆变更前必须参数化"; dev-1 已重拟合过
> 一次并触发过失同步 3 红, 且 F10 第二批已把 color_domain 缺省翻成 oklch
> —— 本债升级为现役缺省路径的单点风险, 清偿时机成熟)。
> 执笔 2026-09-07。

## 1. 改动清单

| 文件 | 改动 |
|---|---|
| `native/src/colorcal.h` | 新增内部 `SkinOklabEllipse` (7 字段, 字段级对齐纪律注释) + C ABI `PixoRenderSkinOklabEllipse`; `ApplyColorCalLabF32Oklch`/导出签名增 ellipse 参 |
| `native/src/colorcal.cpp` | **`SkinOklab*` 七个 constexpr 副本删除** (双源消除); `SkinMaskOklab(e, r,g,b)` 改读椭圆参数; 内核/ABI 导出串参; ABI 空指针护栏 |
| `native/src/abi.cpp` | **1.5.0 → 1.6.0** (changelog 注明签名变化与不兼容语义) |
| `render/_native/__init__.py` | 新结构体 ctypes 定义 + 符号 argtypes 增第 7 参; `skin_oklab_ellipse()` —— **单源 core/skin.py → 内核常数的唯一入口** (缓存; 变换纪律: 中心 np.float32 舍入展宽 / cos·sin 为 np 产物 / 软带 f32); `colorcal_apply_lab_f32_oklch(..., ellipse=None)` 增可覆盖参 + **version ≥ 1.6.0 调用门** (1.5.x 旧 6 参符号存在但签名不兼容, 版本门防静默错用 → 旧 DLL 自动回退纯 Python) |
| `modules/color_cal.py` | 接线注释更新 (常数单源流入/版本门); 调用面不变 (ellipse 缺省) |
| `tests/unit/test_native_colorcal_oklch.py` | 版本门 1.5.0→1.6.0 (fixture+gate 测试); 新增 `test_ellipse_parameterized_single_source` (字段==单源变换 + 半轴→0 掩码全零 = 参数实时生效, 编译期残留不可能通过); 模块 docstring 补参数化口径 |

**未碰**: core/skin.py 常数定义 (它就是单源)、hsv/u8 内核、CMakeLists。

## 2. 数值纪律 (对齐语义随参数携带, 防止参数化引入精度自由度)

| 字段 | Python 侧变换 | native 接收 |
|---|---|---|
| centerA/B | `float(np.float32(SKIN_OKLAB_A/B))` —— f32 舍入后展宽 (十进制 f32 非精确, da/db 减法须用舍入后值) | f64 直收 |
| cosAngle/sinAngle | `float(np.cos/sin(SKIN_OKLAB_ANGLE))` —— np 产物 f64 直传 | f64 直收 (内核不调 libm cos/sin, 跨实现 1 ULP 消除) |
| major/minor | Python float (f64) 直传 | f64 |
| softBand | `float(np.float32(SKIN_OKLAB_SOFT_BAND))` | **f32** (smoothstep 除法按 f32 = NEP50 语义) |

## 3. 验证证据

- **逐位零漂移 (核心验收)**: 改造前 (DLL 1.5.0 编译期常数) 固定语料
  (2 图 × 3 参数组 = 6 内核输出) 快照 → 改造后 (1.6.0 参数化) 对拍:
  `[check] DLL (1, 6, 0): PASS — 逐位零漂移`
  (`.agent-team/spike/_r17_kernel_snapshot.py save/check`)。
- `test_native_colorcal_oklch` **7/7 绿**: 原 bitwise/容差/回退全套
  (掩码隔离路径仍与 skin_mask_oklab 逐位) + 版本门 (1.6.0) + 新参数化
  生效测试。
- native 回归 (`test_native_colorcal + test_native_oklab + test_native_abi +
  test_native_fallback`) → **29 passed**。
- gate `--check` → **21 features 零漂移** (oklch 已是缺省域, 即现役金样本
  路径零漂)。
- 全量 `pytest tests/` → **1533 passed, 5 skipped, 1 xfailed**。
- 性能无损: 内核 11.96 vs 11.8 ms @512² (噪声内, 结构体传参不伤热路径)。
- DLL 重编: build.bat 1.6.0 落 `render/_native/` (构建期 pixo.service 进程
  持锁旧 DLL → rename 热换, 服务不断)。

## 4. 台账

- **tech_debt #18 → ✅ 关闭** (终章注记: 参数化结构/单源入口/逐位实证/
  性能无损/SkinStage native 化仍为独立机会项)。
- 顺带观察: dev-2 的 F10 第二批 (color_domain 缺省翻 oklch) 已在树 ——
  本次参数化后其单点常数风险即消 (此前金样本基线按 v1.5.0 常数生成,
  零漂实证 = 基线无需再动)。
- spike 产物: `_r17_kernel_snapshot.py` + `_r17_kernel_ref.npz` (零漂对拍
  证据, 保留至 R17 验收复核后可删)。
- 现场遗留: `render/_native/pixo_render_native.dll.v15-locked` (pixo.service
  运行中持锁, 进程退出后可删)。

**一句话结论**: 参数化落地 (DLL 1.6.0, 椭圆 7 常数经
PixoRenderSkinOklabEllipse 从单源 core/skin.py 流入, constexpr 副本删除) ——
v1.5.0↔v1.6.0 同语料快照对拍**逐位零漂移**, oklch 测试 **7/7** + native
回归 **29** 全绿 + gate 21 features 零漂 + 全量 **1533 passed**, 性能无损,
**tech_debt #18 关闭**。
