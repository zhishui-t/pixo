# pixo.render Native

pixo.render 性能热点内核的 C++ 实现，使用 CMake + MinGW-w64 构建，通过 ctypes 被 Python 侧加载。

## 目录结构

```
native/
  CMakeLists.txt   # CMake 构建脚本
  build.bat        # Windows 一键构建（MinGW）
  run_tests.bat    # 构建并运行 C++ 单元测试
  src/             # C++ 源码（遵循 guanlan/AGENTS.md 编码规范）
  tests/           # C++ 测试
  build/           # CMake 构建产物（不入库）
render/_native/    # Python ctypes 包装器 + 生成的 DLL（DLL 不入库）
```

## 构建

```bat
cd native
build.bat
```

构建成功后会把 `pixo_render_native.dll` 复制到 `render/_native/`。

```bat
cd native
run_tests.bat
```

## 已实现内核

- `RgbToHsv` / `HsvToRgb`（float64）
- `RgbToHsvF32` / `HsvToRgbF32`（float32，用于 `apply_local_warm_sat`）
- `PixoRenderApplyLocalWarmSat`（M1 broad/spot）
- `PixoRenderColorCalApplyLab` / `PixoRenderGamutSoft`（M2）
- `PixoRenderRefine*` / `PixoRenderWarmSatGammaU8`（M3）
- `PixoRenderDecodeCfaHalf`（P1 CFA 2×2 分箱快速解码）

## 数值约束

- float32 路径与 NumPy 原实现最大误差 ≤ 1e-6
- float64 路径与 NumPy 原实现逐位一致（max diff = 0）
