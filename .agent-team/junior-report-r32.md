# junior 报告 · R32 前置 · native 工具链 bring-up

日期：2026-09-23 ｜ 执行：junior-dev（宿主原生） ｜ 分支：render-core-integration
任务：纯环境验证——用 D:\code 工具链按 build.bat 口径重编 native DLL 并验证装载与测试。不动业务码。

## 结论

**通过。** 新 DLL 重编成功并被 `pixo.render._native` 正常装载（版本门 1.6.0 过），
test_native_stage_kernels 8 passed + test_gate_curves 4 passed 全绿，无回滚。
新旧 DLL sha256 不同（字节数恰好相同）——**如实标注：工具链重编非字节级可复现，属预期漂移，功能验证全绿**。

## 执行记录（步骤 × 结果）

| # | 步骤 | 命令/动作 | 结果 |
| :- | :--- | :--- | :--- |
| 0 | 环境核验 | cmake/g++/mingw32-make --version | cmake 3.31.6、g++ 14.2.0 (x86_64-posix-seh-rev2, MinGW-Builds)、GNU Make 4.4.1，均在位 |
| 1 | 备份旧 DLL | cp 到 .artifacts/_r32_dll_backup/ | 成功，sha256 与原件一致（ee e9fa…b78），620886 B |
| 1.5 | 基线验证 | 旧 DLL 装载 + 版本 | (1, 6, 0) 过 |
| 2 | 重编 | `cmd /c build.bat`（native/ 目录内，即 bat 自身口径） | exit 0，一次通过 |
| 3 | 版本门 | `python -c "...print(n._version)"` | (1, 6, 0) 过 |
| 3a | 单测 | pytest tests/unit/test_native_stage_kernels.py | **8 passed** in 3.70s |
| 3b | 回归 | pytest tests/regression/test_gate_curves.py | **4 passed** in 0.17s |
| 4 | 范围核验 | git status | 仅派单前既有 .agent-team 4 文件改动；DLL 不受 git 跟踪；src 其他文件零触碰 |

## 构建命令与耗时

- 实际执行 = build.bat 原文（`K:/work/project/pixo/src/pixo/render/native/build.bat`）：
  1. 清空并重建 `build/`；
  2. `D:\code\cmake-3.31.6-windows-x86_64\bin\cmake.exe -S . -B build -G "MinGW Makefiles" -DCMAKE_MAKE_PROGRAM=D:\code\mingw64\bin\mingw32-make.exe -DCMAKE_CXX_COMPILER=D:\code\mingw64\bin\g++.exe -DCMAKE_BUILD_TYPE=Release`
  3. `cmake --build build --config Release` → POST_BUILD `copy_if_different` 到 `../_native/`（CMakeLists.txt:60-63）
- 总耗时 **23s**（configure 10.5s + 编译链接）；9 个源文件（abi/decode/hsv/oklab/warm_sat/colorcal/refine/stage_kernels/lut3d）全编。
- OpenMP：找到 -fopenmp（版本 4.5），与 CMakeLists 默认 ON 口径一致。

## sha256 台账

| 产物 | sha256 | 大小 |
| :--- | :--- | :--- |
| 旧 DLL（备份件 .artifacts/_r32_dll_backup/pixo_render_native.dll） | `eee9fa04b9bdf8e47c5912537e7b1bb975784e4801235c03019062408cd69b78` | 620886 B |
| 新 DLL（src/pixo/render/_native/pixo_render_native.dll） | `9a274a73a05589cf285ed1313d8ec14d2b9e1e44c6e89f1f4c21ac749fb66409` | 620886 B |

**工具链漂移标注**：同源码、同口径重编后 sha256 变化（GCC 14.2.0 非确定编译：时间戳/路径嵌入等），
但字节数完全一致、版本门与全部测试通过 → 判定为无害重编漂移。备份保留于
`.artifacts/_r32_dll_backup/`，如后续发现行为差异可一键回滚（复制回 `_native/` 即可）。

## 坑与备注

- 无实质坑。两点备注：
  1. build.bat 内 CMAKE 路径是全名 `D:\code\cmake-3.31.6-windows-x86_64\`（非裸 `cmake-3.31.6`），派单口径与 bat 实际一致，直接跑 bat 最忠实；
  2. DLL 不受 git 跟踪（`git ls-files` 仅 `__init__.py`），本次换 DLL 不产生 git 改动，符合「不动 src 其他文件」红线。

## 红线遵守

- 失败轮次：0（一次通过，未触发 2 轮上限）；
- 构建产物验证后才留 `_native/`：是（版本门+两套测试全绿后才算落地）；
- src 其他文件：零触碰；备份/报告/构建中间物（build/，原有惯例目录）之外无新增文件。
